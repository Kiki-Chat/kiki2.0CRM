"""OAuth connection storage + automatic access-token refresh (P3).

Canonical store: the ``oauth_connections`` table (one row per org+provider).
Tokens are Fernet-encrypted (SETTINGS_ENC_KEY) — the *_encrypted columns never
hold plaintext. ``get_valid_access_token`` transparently refreshes a stale
access token using the stored refresh token, so calendar API callers never deal
with expiry themselves.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.core.crypto import decrypt, encrypt
from app.db.supabase_client import get_service_client
from app.services.oauth_providers import get_credentials, get_provider

logger = logging.getLogger(__name__)

_TIMEOUT = 30.0
_TABLE = "oauth_connections"


class OAuthTokenError(Exception):
    """No usable connection, or a refresh attempt failed."""


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now(timezone.utc)


def _parse_expiry(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ─── storage ─────────────────────────────────────────────────────────────────
def upsert_connection(
    *,
    org_id: str,
    provider: str,
    access_token: str | None,
    refresh_token: str | None,
    expires_at: str | None,
    account_email: str | None,
    scope: str | None = None,
) -> None:
    """Encrypt + upsert a connection. A refresh token is only written when
    supplied — providers may omit it on a refresh response and we must not wipe
    the stored one. Columns omitted from the payload are preserved on update."""
    row: dict = {
        "org_id": org_id,
        "provider": provider,
        "access_token_encrypted": encrypt(access_token),
        "token_expires_at": expires_at,
        "account_email": account_email,
        "updated_at": _now().isoformat(),
    }
    if refresh_token:
        row["refresh_token_encrypted"] = encrypt(refresh_token)
    if scope is not None:
        row["scope"] = scope
    get_service_client().table(_TABLE).upsert(
        row, on_conflict="org_id,provider"
    ).execute()


def get_connection(org_id: str, provider: str) -> dict | None:
    rows = (
        get_service_client()
        .table(_TABLE)
        .select("*")
        .eq("org_id", org_id)
        .eq("provider", provider)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def list_connections(org_id: str) -> list[dict]:
    """Connection status for the org — never returns token material.

    ``connected`` reflects a genuinely USABLE credential, not mere row-existence:
    a row whose access or refresh token actually decrypts under the current
    ``SETTINGS_ENC_KEY``. A row whose tokens can't be decrypted (wrong/rotated
    key, or a tampered value) is reported ``connected=False`` with
    ``status="token_unreadable"`` — surfacing the problem instead of a misleading
    green badge. The token material itself is never returned (only booleans /
    a status string). ``status`` is one of:
      * ``"ok"``               — at least one token decrypts → usable
      * ``"token_unreadable"`` — ciphertext present but won't decrypt (key issue)
      * ``"no_token"``         — row exists but no ciphertext stored (re-connect)
    """
    rows = (
        get_service_client()
        .table(_TABLE)
        .select(
            "provider, account_email, token_expires_at, updated_at, "
            "access_token_encrypted, refresh_token_encrypted"
        )
        .eq("org_id", org_id)
        .execute()
        .data
        or []
    )
    out: list[dict] = []
    for r in rows:
        has_ciphertext = bool(
            r.get("access_token_encrypted") or r.get("refresh_token_encrypted")
        )
        # decrypt() logs on failure, so a key problem also lands in the logs.
        usable = bool(
            decrypt(r.get("access_token_encrypted"))
            or decrypt(r.get("refresh_token_encrypted"))
        )
        if usable:
            status = "ok"
        elif has_ciphertext:
            status = "token_unreadable"
        else:
            status = "no_token"
        out.append(
            {
                "provider": r["provider"],
                "connected": usable,
                "status": status,
                "account_email": r.get("account_email"),
                "token_expires_at": r.get("token_expires_at"),
            }
        )
    return out


def delete_connection(org_id: str, provider: str) -> int:
    rows = (
        get_service_client()
        .table(_TABLE)
        .delete()
        .eq("org_id", org_id)
        .eq("provider", provider)
        .execute()
        .data
        or []
    )
    return len(rows)


# ─── refresh ─────────────────────────────────────────────────────────────────
def _refresh_access_token(provider: str, refresh_token: str) -> dict:
    cfg = get_provider(provider)
    cid, csec = get_credentials(provider)
    body = {
        "client_id": cid,
        "client_secret": csec,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    with httpx.Client(timeout=_TIMEOUT) as c:
        r = c.post(cfg["token_url"], data=body, headers={"Accept": "application/json"})
    if r.status_code != 200:
        raise OAuthTokenError(
            f"{provider} token refresh failed: {r.status_code} {r.text[:300]}"
        )
    return r.json()


def access_token_from_conn(
    conn: dict,
    provider: str,
    persist,
    *,
    now: datetime | None = None,
    leeway_sec: int = 120,
) -> str:
    """Return a non-expired access token from a connection-row dict, refreshing
    via the stored refresh token when the current one is missing/expired/within
    ``leeway_sec`` of expiry. ``persist(access_token, refresh_token_or_none,
    expires_at_iso)`` stores the refreshed token — org- vs employee-scoped storage
    differs only by this callback. Shared by ``get_valid_access_token`` (org) and
    ``services.employee_calendar`` (per-employee).

    Raises ``OAuthTokenError`` when there is no refresh token or the refresh fails.
    """
    now_dt = _now(now)
    access = decrypt(conn.get("access_token_encrypted"))
    expires_at = _parse_expiry(conn.get("token_expires_at"))
    if access and expires_at and (expires_at - timedelta(seconds=leeway_sec)) > now_dt:
        return access  # still valid

    refresh = decrypt(conn.get("refresh_token_encrypted"))
    if not refresh:
        raise OAuthTokenError(f"{provider} connection has no refresh token — reconnect")

    token_data = _refresh_access_token(provider, refresh)
    new_access = token_data.get("access_token")
    if not new_access:
        raise OAuthTokenError(f"{provider} refresh returned no access_token")

    expires_in = int(token_data.get("expires_in") or 0)
    new_expiry = (now_dt + timedelta(seconds=expires_in)).isoformat() if expires_in else None
    persist(new_access, token_data.get("refresh_token"), new_expiry)  # None → keep stored one
    return new_access


def get_valid_access_token(
    org_id: str, provider: str, *, now: datetime | None = None, leeway_sec: int = 120
) -> str:
    """Return a non-expired access token for (org, provider), refreshing via the
    stored refresh token when needed, and persisting the refreshed token.

    Raises ``OAuthTokenError`` when there is no connection, no refresh token, or
    the refresh request fails.
    """
    conn = get_connection(org_id, provider)
    if not conn:
        raise OAuthTokenError(f"no {provider} connection for org {org_id}")

    def _persist(access: str, refresh: str | None, expires_at: str | None) -> None:
        upsert_connection(
            org_id=org_id,
            provider=provider,
            access_token=access,
            refresh_token=refresh,
            expires_at=expires_at,
            account_email=conn.get("account_email"),
        )

    return access_token_from_conn(conn, provider, _persist, now=now, leeway_sec=leeway_sec)


# ─── per-purpose linkage (which provider serves email vs calendar) ───────────
# Source of truth for the EMAIL and CALENDAR axes. PK (org_id, purpose) makes
# the linkage exclusive — exactly one provider per purpose. A single grant in
# oauth_connections may be referenced by 0, 1, or 2 purpose links.
_LINKS_TABLE = "oauth_purpose_links"
PURPOSES = ("email", "calendar")


def set_purpose_link(
    org_id: str, purpose: str, provider: str, account_email: str | None = None
) -> None:
    """Link ``purpose`` ('email'|'calendar') to ``provider`` for the org. Upsert
    on (org_id, purpose) → switching providers for a purpose replaces the link
    (exclusivity)."""
    get_service_client().table(_LINKS_TABLE).upsert(
        {
            "org_id": org_id,
            "purpose": purpose,
            "provider": provider,
            "account_email": account_email,
            "updated_at": _now().isoformat(),
        },
        on_conflict="org_id,purpose",
    ).execute()


def get_purpose_link(org_id: str, purpose: str) -> dict | None:
    rows = (
        get_service_client()
        .table(_LINKS_TABLE)
        .select("*")
        .eq("org_id", org_id)
        .eq("purpose", purpose)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def list_purpose_links(org_id: str) -> dict[str, dict]:
    """``{purpose: {provider, account_email}}`` for the org."""
    rows = (
        get_service_client()
        .table(_LINKS_TABLE)
        .select("purpose, provider, account_email")
        .eq("org_id", org_id)
        .execute()
        .data
        or []
    )
    return {
        r["purpose"]: {"provider": r["provider"], "account_email": r.get("account_email")}
        for r in rows
    }


def delete_purpose_link(org_id: str, purpose: str) -> str | None:
    """Delete the link for ``purpose``; return the provider it pointed to (or
    None if there was no link)."""
    rows = (
        get_service_client()
        .table(_LINKS_TABLE)
        .delete()
        .eq("org_id", org_id)
        .eq("purpose", purpose)
        .execute()
        .data
        or []
    )
    return rows[0]["provider"] if rows else None


def purposes_for_provider(org_id: str, provider: str) -> list[str]:
    """Which purposes still reference this provider's grant — used to decide
    whether a disconnect should revoke (revoke only when this returns empty)."""
    rows = (
        get_service_client()
        .table(_LINKS_TABLE)
        .select("purpose")
        .eq("org_id", org_id)
        .eq("provider", provider)
        .execute()
        .data
        or []
    )
    return [r["purpose"] for r in rows]


def calendar_provider(org_id: str) -> str | None:
    """The provider serving the org's CALENDAR purpose (or None if unlinked).
    Calendar read/write callers resolve the provider through this, never a
    hardcoded 'google'."""
    link = get_purpose_link(org_id, "calendar")
    return link["provider"] if link else None


# ─── revoke (called only when the LAST purpose using a grant disconnects) ────
def revoke_grant(org_id: str, provider: str) -> bool:
    """Best-effort revoke of the provider grant at its revocation endpoint.

    MUST be called only when no purpose link references the grant anymore (the
    caller checks ``purposes_for_provider``). Returns True if a revoke request
    returned 2xx. Never raises — revocation is best-effort and the caller
    deletes the local row regardless (providers without a revoke endpoint, e.g.
    Microsoft, simply return False)."""
    cfg = get_provider(provider)
    revoke_url = cfg.get("revoke_url")
    conn = get_connection(org_id, provider)
    if not revoke_url or not conn:
        return False
    # Revoking the refresh token revokes the whole grant at Google; fall back to
    # the access token if no refresh token is stored.
    token = decrypt(conn.get("refresh_token_encrypted")) or decrypt(
        conn.get("access_token_encrypted")
    )
    if not token:
        return False
    try:
        with httpx.Client(timeout=_TIMEOUT) as c:
            r = c.post(
                revoke_url,
                data={"token": token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        ok = r.status_code in (200, 204)
        logger.info(
            "oauth_revoke org=%s provider=%s status=%s ok=%s",
            org_id, provider, r.status_code, ok,
        )
        return ok
    except Exception as exc:  # noqa: BLE001 — revoke is best-effort
        logger.warning("oauth_revoke org=%s provider=%s failed err=%s", org_id, provider, exc)
        return False
