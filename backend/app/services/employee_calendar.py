"""Per-employee Google Calendar connections.

Each employee links their OWN Google account so (a) their personal busy time
feeds the availability engine and (b) CRM-assigned appointments push into their
calendar. Parallels ``services.oauth_tokens`` (the org/company calendar store)
but is keyed by EMPLOYEE, and reuses the same provider registry, Fernet
encryption (SETTINGS_ENC_KEY), and token-refresh logic. The org-level
``oauth_connections`` / ``oauth_purpose_links`` are a separate, untouched store.

Storage: ``employee_calendar_connections`` (migration 0083), unique
(employee_id, provider). The *_encrypted columns never hold plaintext.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.crypto import decrypt, encrypt
from app.db.supabase_client import get_service_client
from app.services import oauth_tokens
from app.services.oauth_providers import get_provider

logger = logging.getLogger(__name__)

_TABLE = "employee_calendar_connections"
DEFAULT_PROVIDER = "google"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_employee_id(org_id: str, user_id: str | None) -> str | None:
    """Map a login ``user_id`` → their ``employees.id`` within the org (the person
    completing the OAuth consent). ``None`` when the user has no employee row."""
    if not user_id:
        return None
    rows = (
        get_service_client()
        .table("employees")
        .select("id")
        .eq("org_id", org_id)
        .eq("user_id", user_id)
        .eq("deleted", False)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0]["id"] if rows else None


def upsert_connection(
    *,
    org_id: str,
    employee_id: str,
    provider: str,
    access_token: str | None,
    refresh_token: str | None,
    expires_at: str | None,
    account_email: str | None,
    scope: str | None = None,
) -> None:
    """Encrypt + upsert an employee's calendar grant. A refresh token is only
    written when supplied (a refresh response may omit it — never wipe the stored
    one). Omitted columns are preserved on update."""
    row: dict = {
        "org_id": org_id,
        "employee_id": employee_id,
        "provider": provider,
        "access_token_encrypted": encrypt(access_token),
        "token_expires_at": expires_at,
        "account_email": account_email,
        "updated_at": _now_iso(),
    }
    if refresh_token:
        row["refresh_token_encrypted"] = encrypt(refresh_token)
    if scope is not None:
        row["scope"] = scope
    get_service_client().table(_TABLE).upsert(
        row, on_conflict="employee_id,provider"
    ).execute()


def get_connection(org_id: str, employee_id: str, provider: str = DEFAULT_PROVIDER) -> dict | None:
    rows = (
        get_service_client()
        .table(_TABLE)
        .select("*")
        .eq("org_id", org_id)
        .eq("employee_id", employee_id)
        .eq("provider", provider)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def get_valid_access_token(
    org_id: str, employee_id: str, provider: str = DEFAULT_PROVIDER, *, now: datetime | None = None
) -> str:
    """Non-expired access token for this employee's calendar, auto-refreshing and
    persisting via the shared ``oauth_tokens.access_token_from_conn`` helper.
    Raises ``OAuthTokenError`` when not connected / no refresh token / refresh fails."""
    conn = get_connection(org_id, employee_id, provider)
    if not conn:
        raise oauth_tokens.OAuthTokenError(
            f"no {provider} calendar connection for employee {employee_id}"
        )

    def _persist(access: str, refresh: str | None, expires_at: str | None) -> None:
        upsert_connection(
            org_id=org_id,
            employee_id=employee_id,
            provider=provider,
            access_token=access,
            refresh_token=refresh,
            expires_at=expires_at,
            account_email=conn.get("account_email"),
        )

    return oauth_tokens.access_token_from_conn(conn, provider, _persist, now=now)


def delete_connection(org_id: str, employee_id: str, provider: str = DEFAULT_PROVIDER) -> int:
    rows = (
        get_service_client()
        .table(_TABLE)
        .delete()
        .eq("org_id", org_id)
        .eq("employee_id", employee_id)
        .eq("provider", provider)
        .execute()
        .data
        or []
    )
    return len(rows)


def revoke_and_delete(org_id: str, employee_id: str, provider: str = DEFAULT_PROVIDER) -> bool:
    """Best-effort revoke the grant at the provider, then delete the local row.
    Returns True if a revoke request returned 2xx. Never raises — the local row is
    deleted regardless so a disconnect always 'sticks'."""
    conn = get_connection(org_id, employee_id, provider)
    revoked = False
    if conn:
        cfg = get_provider(provider)
        revoke_url = cfg.get("revoke_url")
        token = decrypt(conn.get("refresh_token_encrypted")) or decrypt(
            conn.get("access_token_encrypted")
        )
        if revoke_url and token:
            try:
                import httpx

                with httpx.Client(timeout=15.0) as c:
                    r = c.post(
                        revoke_url,
                        data={"token": token},
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                revoked = r.status_code in (200, 204)
            except Exception as exc:  # noqa: BLE001 — revoke is best-effort
                logger.warning("employee calendar revoke failed emp=%s: %s", employee_id, exc)
    delete_connection(org_id, employee_id, provider)
    return revoked


def list_connections(org_id: str) -> dict[str, dict]:
    """``{employee_id: {provider, account_email, connected, token_expires_at}}`` for
    the org — the admin's view of who has linked their calendar. Never returns
    token material; ``connected`` reflects a genuinely decryptable credential."""
    rows = (
        get_service_client()
        .table(_TABLE)
        .select(
            "employee_id, provider, account_email, token_expires_at, "
            "access_token_encrypted, refresh_token_encrypted"
        )
        .eq("org_id", org_id)
        .execute()
        .data
        or []
    )
    out: dict[str, dict] = {}
    for r in rows:
        usable = bool(
            decrypt(r.get("access_token_encrypted")) or decrypt(r.get("refresh_token_encrypted"))
        )
        out[r["employee_id"]] = {
            "provider": r["provider"],
            "account_email": r.get("account_email"),
            "connected": usable,
            "token_expires_at": r.get("token_expires_at"),
        }
    return out
