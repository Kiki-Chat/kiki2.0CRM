from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status
from starlette.concurrency import run_in_threadpool

from app.core.security import JWTError, decode_supabase_jwt
from app.db.supabase_client import get_service_client


@dataclass
class CurrentUser:
    id: str
    email: str | None
    org_id: str | None
    role: str | None
    full_name: str | None


async def get_current_user(
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    token = authorization.split(" ", 1)[1]
    try:
        claims = decode_supabase_jwt(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
        )

    # The Supabase client is synchronous; run it off the event loop so this async
    # dependency (hit on EVERY authenticated request) never blocks the worker.
    def _load_user_row() -> dict:
        res = (
            get_service_client()
            .table("users")
            .select("id, email, org_id, role, full_name")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else {}

    row = await run_in_threadpool(_load_user_row)
    return CurrentUser(
        id=user_id,
        email=row.get("email") or claims.get("email"),
        org_id=row.get("org_id"),
        role=row.get("role"),
        full_name=row.get("full_name"),
    )


def require_org(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not attached to an organization",
        )
    # P0.6 — block login when org is disabled. Super-admins bypass so they
    # can still re-enable orgs from the super-admin panel.
    if user.role != "super_admin":
        client = get_service_client()
        org_rows = (
            client.table("organizations")
            .select("disabled_at")
            .eq("id", user.org_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        if org_rows and org_rows[0].get("disabled_at"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Diese Organisation ist deaktiviert.",
            )
    return user


def require_super_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Gate for /api/super-admin/* endpoints. Allows any user whose
    public.users.role = 'super_admin' (regardless of org_id binding)."""
    if user.role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nur Super-Admins dürfen diesen Bereich nutzen.",
        )
    return user


def require_org_admin(user: CurrentUser = Depends(require_org)) -> CurrentUser:
    """Gate for org-management actions (Wave 2 three-tier model).

    Chains on ``require_org`` (so the caller is in a present, non-disabled org)
    and additionally requires an admin role. Plain ``employee`` logins get 403.

    Allowed roles: ``org_admin`` (the Meister/client) and ``super_admin``
    (HeyKiki, when acting inside an org context). Applied to every endpoint that
    manages users/credentials/roles or mutates billing/settings/agent config —
    the things an employee must NOT be able to do.
    """
    if user.role not in ("org_admin", "super_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nur Administratoren dürfen diese Aktion ausführen.",
        )
    return user


def verify_post_call_secret(
    x_heykiki_secret: str | None = Header(default=None, alias="X-HeyKiki-Secret"),
) -> None:
    """Shared-secret gate for the N8N → backend post-call hop."""
    from app.core.config import settings

    allowed = {settings.post_call_webhook_secret, settings.master_webhook_secret}
    allowed.discard("")
    if not x_heykiki_secret or x_heykiki_secret not in allowed:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid HeyKiki secret",
        )


def verify_master_secret(x_heykiki_secret: str | None = Header(default=None)) -> None:
    from app.core.config import settings

    if not x_heykiki_secret or x_heykiki_secret != settings.master_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid HeyKiki secret",
        )


# ─── ElevenLabs tool webhooks ────────────────────────────────────────────────
@dataclass
class ToolOrg:
    org_id: str


def _lookup_org_id(secret: str | None, agent_id: str | None) -> str | None:
    """Resolve org_id from the per-org secret header or the agent id (sync DB)."""
    client = get_service_client()
    if secret:
        res = (
            client.table("org_secrets")
            .select("org_id")
            .eq("secret", secret)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]["org_id"]
    if agent_id:
        res = (
            client.table("organizations")
            .select("id")
            .eq("elevenlabs_agent_id", agent_id)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]["id"]
    return None


async def resolve_tool_org(
    request: Request,
    x_heykiki_secret: str | None = Header(default=None, alias="X-HeyKiki-Secret"),
) -> ToolOrg:
    """Resolve the calling organization for an ElevenLabs tool webhook.

    Tries the X-HeyKiki-Secret header first, then falls back to the ``_agentId``
    in the request body (ElevenLabs sends agent id as a dynamic variable but no
    secret header). Reading the JSON body here is safe — Starlette caches it, so
    the route's Pydantic model still parses normally.
    """
    agent_id: str | None = None
    try:
        body = await request.json()
        if isinstance(body, dict):
            # Tool webhooks send `_agentId`; the conversation-init webhook sends `agent_id`.
            agent_id = body.get("_agentId") or body.get("agent_id")
    except Exception:
        pass

    org_id = await run_in_threadpool(_lookup_org_id, x_heykiki_secret, agent_id)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not resolve organization from secret or agent id",
        )
    return ToolOrg(org_id=org_id)
