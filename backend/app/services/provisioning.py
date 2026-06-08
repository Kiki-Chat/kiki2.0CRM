from fastapi import HTTPException, status

from app.db.supabase_client import get_service_client
from app.schemas.provision import ProvisionRequest, ProvisionResponse
from app.services.agent_config import configure_agent

DEFAULT_AGENT_CONFIG = {
    "autonomy_level": 1,
    "proactive_ai_enabled": True,
    "kva_automation_enabled": False,
    "mandatory_fields": [],
    "appointment_categories": [],
    "scheduling": {
        "buffer_minutes": 15,
        "max_per_day": 8,
        "parallel_slots": 1,
        "lead_days": 1,
    },
}

# The 3 mandatory identification fields every newly-provisioned org receives.
# Locked + duty so the tradesperson can't delete them (they're how Kiki ties a
# caller to a customer record). Mirrors migration 0015's test-org seed minus the
# 'concern' field (the agent always captures the concern; it's not a stored field
# the way name/phone/address are). Tuple order: (field_key, label, description,
# is_locked, is_duty, identification_role, sort_order).
_DEFAULT_REQUIRED_FIELDS = [
    ("name", "Name", "Vor- und Nachname", True, True, None, 0),
    ("phone", "Telefonnummer", "Rückrufnummer", True, True, "caller_id", 1),
    ("address", "Adresse", "Anschrift des Kunden / Einsatzorts", True, True, "address", 2),
    # The customer's concern, now a (locked, reorderable, editable) required field
    # instead of a separate config — so the org controls WHERE in the ask order
    # Kiki captures the problem details. is_locked → can't be deleted, only
    # reordered + its description edited. (Migration 0052 backfills existing orgs.)
    ("problem_description", "Anliegen / Problembeschreibung", "Das Anliegen des Kunden — welche Problem-Details Kiki erfassen soll.", True, True, None, 3),
]


def _seed_required_fields(client, org_id: str) -> None:
    """Insert the default agent_required_fields for a fresh org — idempotent.

    No-op when the org already has any required fields (so a provisioning retry
    or a re-sync never duplicates them). Matches the existing insert style
    (one .insert([...]) call via the service client)."""
    existing = (
        client.table("agent_required_fields")
        .select("id")
        .eq("org_id", org_id)
        .limit(1)
        .execute()
        .data
    )
    if existing:
        return
    rows = [
        {
            "org_id": org_id,
            "field_key": field_key,
            "label": label,
            "description": description,
            "is_locked": is_locked,
            "is_duty": is_duty,
            "identification_role": identification_role,
            "sort_order": sort_order,
        }
        for (field_key, label, description, is_locked, is_duty, identification_role, sort_order)
        in _DEFAULT_REQUIRED_FIELDS
    ]
    client.table("agent_required_fields").insert(rows).execute()


def provision_org(payload: ProvisionRequest) -> ProvisionResponse:
    """Create org + admin user + default agent_config, then wire the
    ElevenLabs agent (phone fetch, hk_* tool merge, master prompt write,
    conversation-initiation webhook enable, audio assertion).

    Rejects duplicates on heykiki_org_id OR login_email (no silent overwrite).

    Step B (2026-05-27): the function now finalizes the ElevenLabs agent
    via ``agent_config.configure_agent`` after the DB rows are in place.
    Failures in that step trigger a compensating rollback of all four
    Supabase rows + the auth user, so a retry can succeed cleanly.

    Step B.6 (2026-05-27): no longer generates / persists an org_secret.
    The per-org secret was misleading (used for the post-call webhook hop,
    not per-customer auth). Lookup is via agent_id + caller phone_number.
    The ``org_secrets`` table is intentionally left in place (Agent 3's
    frontend-cleanup surface); this function simply stops writing to it.

    P0.9 — Fresh-tenant audit (2026-05-26): this function inserts the
    three DB rows listed below and configures the EL agent. NO customers /
    calls / inquiries / appointments / cost_estimates / invoices / employees
    / vehicles / tools / catalog_items / text_modules / projects / documents
    are seeded. Any pre-existing "test data" in older orgs (e.g. c4dbf596)
    came from manual verification testing, not from this provisioning path.
    Historical EL conversations are imported separately via
    ``app.services.history_import.import_agent_history``, scheduled by the
    /api/heykiki/provision and /api/super-admin/orgs routes as a
    BackgroundTask after this function returns.
    """
    client = get_service_client()

    # Duplicate checks (handover known-bug #3).
    existing_org = (
        client.table("organizations")
        .select("id")
        .eq("heykiki_org_id", payload.heykiki_org_id)
        .limit(1)
        .execute()
    )
    if existing_org.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Organization '{payload.heykiki_org_id}' already exists",
        )

    existing_user = (
        client.table("users")
        .select("id")
        .eq("email", payload.login_email)
        .limit(1)
        .execute()
    )
    if existing_user.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User '{payload.login_email}' already exists",
        )

    # Create the auth user first; we need its id for the users row.
    auth_res = client.auth.admin.create_user(
        {
            "email": payload.login_email,
            "password": payload.login_password,
            "email_confirm": True,
            "user_metadata": {"full_name": payload.admin_name or payload.org_name},
        }
    )
    auth_user = auth_res.user
    if auth_user is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create auth user",
        )
    user_id = auth_user.id

    # Inserts that may need to be undone on a later failure.
    org_id: str | None = None
    try:
        org_res = (
            client.table("organizations")
            .insert(
                {
                    "heykiki_org_id": payload.heykiki_org_id,
                    "name": payload.org_name,
                    "slug": payload.heykiki_org_id,
                    "elevenlabs_agent_id": payload.elevenlabs_agent_id,
                    "email": payload.contact_email,
                }
            )
            .execute()
        )
        org_id = org_res.data[0]["id"]

        client.table("users").insert(
            {
                "id": user_id,
                "org_id": org_id,
                "full_name": payload.admin_name or payload.org_name,
                "email": payload.login_email,
                "role": "org_admin",
            }
        ).execute()

        client.table("agent_configs").insert(
            {"org_id": org_id, **DEFAULT_AGENT_CONFIG}
        ).execute()

        # Seed the 3 mandatory identification fields so every newly-provisioned
        # org has its required-field set from day one (migration 0015 only seeded
        # the test org). Idempotent: only insert when the org has none yet.
        _seed_required_fields(client, org_id)

        # ─── Step B — finalize the ElevenLabs agent ──────────────────────────
        # Runs synchronously inside provision_org so a hard failure (e.g.
        # zero phones bound) rolls back the org as part of the same HTTP
        # request, instead of leaving a half-provisioned org behind.
        configure_agent(
            org_id=org_id,
            agent_id=payload.elevenlabs_agent_id,
            org_name=payload.org_name,
        )
    except Exception:
        # Compensating rollback: undo DB rows so a retry can succeed.
        if org_id:
            try:
                # organizations CASCADEs to users + agent_configs + org_secrets
                # via ON DELETE CASCADE in 0001_init_schema.sql.
                client.table("organizations").delete().eq("id", org_id).execute()
            except Exception:
                pass
        # And the auth user, since users.id has no FK back to auth.users.
        try:
            client.auth.admin.delete_user(user_id)
        except Exception:
            pass
        raise

    return ProvisionResponse(
        org_id=org_id,
        user_id=user_id,
        heykiki_org_id=payload.heykiki_org_id,
        org_secret=None,  # B.6 — no longer generated
    )
