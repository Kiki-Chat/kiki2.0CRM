import logging

from fastapi import HTTPException, status

from datetime import datetime, timezone

from app.db.supabase_client import get_service_client
from app.schemas.provision import ProvisionRequest, ProvisionResponse
from app.services.agent_config import (
    attach_hk_tools,
    configure_agent,
    set_conversation_init_webhook,
    verify_agent_health,
)

logger = logging.getLogger(__name__)

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
# (field_key, label, description, is_locked, is_duty, identification_role,
#  sort_order, is_active, linked_setting)
_DEFAULT_REQUIRED_FIELDS = [
    ("name", "Name", "Vor- und Nachname", True, True, None, 0, True, None),
    ("phone", "Telefonnummer", "Rückrufnummer", True, True, "caller_id", 1, True, None),
    ("address", "Adresse", "Anschrift des Kunden / Einsatzorts", True, True, "address", 2, True, None),
    # The customer's concern, now a (locked, reorderable, editable) required field
    # instead of a separate config — so the org controls WHERE in the ask order
    # Kiki captures the problem details. is_locked → can't be deleted, only
    # reordered + its description edited. (Migration 0052 backfills existing orgs.)
    ("problem_description", "Anliegen / Problembeschreibung", "Das Anliegen des Kunden — welche Problem-Details Kiki erfassen soll.", True, True, None, 3, True, None),
    # Leitfaden rework (migration 0060): optional email (off by default) + the
    # three linked offer-steps whose ACTIVE state mirrors agent_configs.
    ("email", "E-Mail-Adresse", "E-Mail des Kunden (für Bestätigungen und Angebote)", False, False, None, 4, False, None),
    ("offer_appointment", "Termin anbieten", "Kiki bietet an dieser Stelle aktiv einen Termin an", True, False, None, 5, True, "appointments_enabled"),
    ("offer_kva", "Angebot anbieten", "Kiki bietet an dieser Stelle aktiv ein unverbindliches Angebot an", True, False, None, 6, True, "kva_enabled"),
    ("offer_price_info", "Preisauskunft", "Kiki beantwortet Preisfragen an dieser Stelle (Richtpreise aus den Artikeln)", True, False, None, 7, True, "price_info_enabled"),
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
            "is_active": is_active,
            "linked_setting": linked_setting,
        }
        for (field_key, label, description, is_locked, is_duty, identification_role,
             sort_order, is_active, linked_setting)
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

    n8n BIND-ONLY seam (additive): when ``payload.agent_externally_managed``
    is True, the ElevenLabs agent (prompt + tools + webhook + bound number)
    has already been BUILT EXTERNALLY by n8n. In that case provision_org
    BINDS the agent instead of (re)configuring it: it stores
    ``elevenlabs_agent_id`` + ``phone_number`` + ``elevenlabs_phone_number_id``
    on the org row, stamps ``agent_provisioned_at=now()``, and runs the
    READ-ONLY ``verify_agent_health`` — but does NOT call ``configure_agent``
    (which would clobber n8n's prompt/tools/webhook). The verify report is
    returned on ``ProvisionResponse.agent_health``. When the flag is False the
    behavior is unchanged (configure_agent is called as before).

    Assumptions for the bind-only path (per n8n contract): n8n sets the EL
    conversation-init webhook to the prod backend URL with the
    ``X-HeyKiki-Secret`` header (the CRM only VERIFIES it, never writes it),
    and n8n passes ``elevenlabs_phone_number_id`` (required for outbound).

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

    # n8n BIND-ONLY: when the agent is externally managed we persist the
    # phone fields + the agent-provisioned stamp on the org row at insert time
    # (n8n already bound the number + built the agent), and we skip the
    # configure_agent step below. Default path leaves these unset.
    bind_only = bool(payload.agent_externally_managed)

    # Inserts that may need to be undone on a later failure.
    org_id: str | None = None
    agent_health: dict | None = None  # populated only on the bind-only path
    try:
        org_row: dict = {
            "heykiki_org_id": payload.heykiki_org_id,
            "name": payload.org_name,
            "slug": payload.heykiki_org_id,
            "elevenlabs_agent_id": payload.elevenlabs_agent_id,
            "email": payload.contact_email,
        }
        # Onboarding-form company address → organizations.address (JSONB {raw}),
        # so the prompt's company profile reflects it. Optional.
        if payload.address and payload.address.strip():
            org_row["address"] = {"raw": payload.address.strip()}
        if bind_only:
            # Store the n8n-bound number + its EL phone_number_id (needed for
            # outbound) and stamp provisioned now — the agent is already live.
            if payload.phone_number is not None:
                org_row["phone_number"] = payload.phone_number
            if payload.elevenlabs_phone_number_id is not None:
                org_row["elevenlabs_phone_number_id"] = (
                    payload.elevenlabs_phone_number_id
                )
            org_row["agent_provisioned_at"] = datetime.now(timezone.utc).isoformat()

        org_res = (
            client.table("organizations")
            .insert(org_row)
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

        agent_cfg_row = {"org_id": org_id, **DEFAULT_AGENT_CONFIG}
        # Onboarding-form trade/genre → agent_configs.trade. Drives the universal
        # trade profile in the prompt; editable later in Kiki-Zentrale (/context).
        if payload.trade and payload.trade.strip():
            agent_cfg_row["trade"] = payload.trade.strip()
        client.table("agent_configs").insert(agent_cfg_row).execute()

        # Seed the 3 mandatory identification fields so every newly-provisioned
        # org has its required-field set from day one (migration 0015 only seeded
        # the test org). Idempotent: only insert when the org has none yet.
        _seed_required_fields(client, org_id)

        # ─── Step B — finalize the ElevenLabs agent ──────────────────────────
        if bind_only:
            # n8n BIND-ONLY: n8n built the agent (prompt + number) externally,
            # but the conversation-init webhook + the 11 hk_ tools are OURS to
            # assign at onboarding (n8n only sets the post-call webhook). Attach
            # them additively (prompt left untouched) — best-effort so a transient
            # EL failure doesn't roll the org back; the verify gate below surfaces
            # any gap. We still do NOT call configure_agent (that would re-apply
            # and clobber n8n's prompt).
            try:
                attach_hk_tools(payload.elevenlabs_agent_id, org_id=org_id)
                set_conversation_init_webhook(
                    payload.elevenlabs_agent_id, org_id=org_id
                )
            except Exception:  # noqa: BLE001 — verify gate surfaces gaps; don't roll back
                logger.warning(
                    "provision bind-only: tool/webhook attach failed for org %s "
                    "agent %s", org_id, payload.elevenlabs_agent_id, exc_info=True,
                )
            agent_health = verify_agent_health(org_id, payload.elevenlabs_agent_id)
        else:
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
        agent_health=agent_health,  # bind-only verify report, else None
    )
