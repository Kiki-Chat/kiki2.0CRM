import secrets

from fastapi import HTTPException, status

from app.db.supabase_client import get_service_client
from app.schemas.provision import ProvisionRequest, ProvisionResponse

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


def provision_org(payload: ProvisionRequest) -> ProvisionResponse:
    """Create org + admin user + default agent_config + org secret.

    Rejects duplicates on heykiki_org_id OR login_email (no silent overwrite).
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

    org_secret = secrets.token_urlsafe(32)

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

        client.table("org_secrets").insert(
            {"org_id": org_id, "secret": org_secret}
        ).execute()
    except Exception:
        # Best-effort rollback of the auth user so a retry can succeed cleanly.
        try:
            client.auth.admin.delete_user(user_id)
        except Exception:
            pass
        raise

    return ProvisionResponse(
        org_id=org_id,
        user_id=user_id,
        heykiki_org_id=payload.heykiki_org_id,
        org_secret=org_secret,
    )
