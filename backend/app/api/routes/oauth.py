"""OAuth 2.0 (auth-code) flow for Gmail + Microsoft Graph email integration.

P1.8 Phase 2 scaffolding. The routes use env-var placeholders so they're
already in place when Amber pastes credentials — see P1.8_OAUTH_SETUP.md.

Flow:
  1. Frontend hits GET /api/settings/oauth/{provider}/authorize (authed) →
     returns {url} with a signed state token, opens in a popup.
  2. User authorizes at Google / Microsoft → redirect to
     /api/settings/oauth/{provider}/callback?code=…&state=…
  3. Callback verifies state, exchanges code for tokens, fetches userinfo
     (= the email we're authorized to send AS), encrypts refresh + access
     tokens with the existing SETTINGS_ENC_KEY (Fernet), upserts onto
     email_configs.
  4. POST /api/settings/oauth/{provider}/disconnect (authed) clears tokens.

Token refresh + actual Gmail-send / MS-Graph-send refactor lands in Phase 3
alongside the frontend buttons.
"""
from __future__ import annotations

import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.core.config import settings
from app.core.crypto import decrypt, encrypt
from app.db.supabase_client import get_service_client

router = APIRouter(prefix="/api/settings/oauth", tags=["oauth"])


# ─── Provider config ─────────────────────────────────────────────────────────
PROVIDERS: dict[str, dict[str, Any]] = {
    "google": {
        "client_id_attr": "google_client_id",
        "client_secret_attr": "google_client_secret",
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scopes": [
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/calendar",
            "openid",
            "email",
            "profile",
        ],
        "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
        "userinfo_email_key": "email",
        # Google's "access_type=offline" is what makes the refresh token
        # come back. "prompt=consent" forces re-issue on re-authorize so
        # we never silently lose the refresh token on a re-link.
        "extra_authorize_params": {"access_type": "offline", "prompt": "consent"},
    },
    "microsoft": {
        "client_id_attr": "ms_client_id",
        "client_secret_attr": "ms_client_secret",
        "authorize_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "scopes": [
            "https://graph.microsoft.com/Mail.Send",
            "https://graph.microsoft.com/Calendars.ReadWrite",
            "offline_access",  # refresh-token grant
            "User.Read",
        ],
        "userinfo_url": "https://graph.microsoft.com/v1.0/me",
        "userinfo_email_key": "mail",  # falls back to userPrincipalName below
        "extra_authorize_params": {},
    },
}


def _get_provider(provider: str) -> dict[str, Any]:
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Unknown OAuth provider: {provider}")
    return cfg


def _credentials(provider: str) -> tuple[str, str]:
    cfg = _get_provider(provider)
    cid = getattr(settings, cfg["client_id_attr"])
    csec = getattr(settings, cfg["client_secret_attr"])
    if not cid or not csec:
        raise HTTPException(
            status_code=503,
            detail=(
                f"OAuth nicht konfiguriert für '{provider}'. Bitte die "
                f"Einrichtung gemäß P1.8_OAUTH_SETUP.md abschließen."
            ),
        )
    return cid, csec


def _redirect_uri(provider: str) -> str:
    base = settings.backend_public_url.rstrip("/")
    return f"{base}/api/settings/oauth/{provider}/callback"


# ─── State token: Fernet-encrypted user_id + nonce + ts ─────────────────────
def _make_state(user_id: str, org_id: str, provider: str) -> str:
    payload = f"{user_id}:{org_id}:{provider}:{int(time.time())}:{secrets.token_urlsafe(8)}"
    return encrypt(payload)


def _verify_state(state: str, provider: str, max_age_sec: int = 600) -> tuple[str, str]:
    """Returns (user_id, org_id) on success. Raises 400 on mismatch / expired."""
    try:
        decoded = decrypt(state)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid OAuth state token.")
    parts = decoded.split(":")
    if len(parts) < 5:
        raise HTTPException(status_code=400, detail="Malformed OAuth state token.")
    user_id, org_id, prov, ts_str, _nonce = parts[0], parts[1], parts[2], parts[3], parts[4]
    if prov != provider:
        raise HTTPException(status_code=400, detail="OAuth state provider mismatch.")
    try:
        ts = int(ts_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Malformed OAuth state timestamp.")
    if time.time() - ts > max_age_sec:
        raise HTTPException(status_code=400, detail="OAuth state token expired.")
    return user_id, org_id


# ─── Routes ──────────────────────────────────────────────────────────────────
@router.get("/{provider}/authorize")
async def authorize(
    provider: str,
    user: CurrentUser = Depends(require_org),
) -> dict:
    """Returns the OAuth authorize URL to open in a popup."""
    cfg = _get_provider(provider)
    cid, _ = _credentials(provider)
    state = _make_state(user.id, user.org_id, provider)
    params = {
        "client_id": cid,
        "redirect_uri": _redirect_uri(provider),
        "response_type": "code",
        "scope": " ".join(cfg["scopes"]),
        "state": state,
        **cfg["extra_authorize_params"],
    }
    return {"url": f"{cfg['authorize_url']}?{urlencode(params)}"}


@router.get("/{provider}/callback")
async def callback(
    provider: str,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    """OAuth provider redirects here with code + state.

    Returns an HTML page that closes the popup and posts a message to the
    parent window. No JWT auth on this endpoint (the OAuth provider's
    redirect can't carry one); we authenticate via the signed state token.
    """
    if error:
        return _popup_close_response(success=False, message=f"OAuth-Fehler: {error}")
    if not code or not state:
        return _popup_close_response(success=False, message="Fehlender code oder state.")
    try:
        user_id, org_id = _verify_state(state, provider)
    except HTTPException as exc:
        return _popup_close_response(success=False, message=exc.detail)

    cfg = _get_provider(provider)
    cid, csec = _credentials(provider)

    # Exchange code for tokens.
    try:
        token_data = await run_in_threadpool(
            _exchange_code, cfg, cid, csec, code, _redirect_uri(provider),
        )
    except Exception as exc:  # noqa: BLE001
        return _popup_close_response(
            success=False, message=f"Token-Tausch fehlgeschlagen: {exc}",
        )
    if "refresh_token" not in token_data:
        # Without a refresh token the integration breaks the moment the access
        # token expires (~1h). Force the user to reconnect with the right flags.
        return _popup_close_response(
            success=False,
            message=(
                "Kein refresh_token erhalten. Bitte zuerst die Verknüpfung mit "
                "diesem Konto entfernen (account.google.com / Microsoft-Konto) "
                "und erneut verbinden."
            ),
        )

    # Fetch the email we're authorized to send AS.
    try:
        account_email = await run_in_threadpool(
            _fetch_userinfo_email, cfg, token_data["access_token"],
        )
    except Exception:  # noqa: BLE001
        account_email = None

    expires_in = int(token_data.get("expires_in") or 0)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    ).isoformat() if expires_in else None

    await run_in_threadpool(
        _persist_tokens,
        org_id=org_id,
        provider=provider,
        refresh_token=token_data["refresh_token"],
        access_token=token_data["access_token"],
        expires_at=expires_at,
        account_email=account_email,
    )

    return _popup_close_response(
        success=True,
        message=f"Verbunden mit {account_email or provider}.",
    )


@router.post("/{provider}/disconnect")
async def disconnect(
    provider: str,
    user: CurrentUser = Depends(require_org),
) -> dict:
    """Clear stored OAuth tokens for the calling org's email_configs."""
    _get_provider(provider)  # 404 on unknown provider

    def _do() -> dict:
        client = get_service_client()
        rows = (
            client.table("email_configs")
            .update(
                {
                    "oauth_provider": None,
                    "oauth_refresh_token_encrypted": None,
                    "oauth_access_token_encrypted": None,
                    "oauth_token_expires_at": None,
                    "oauth_account_email": None,
                }
            )
            .eq("org_id", user.org_id)
            .execute()
            .data
            or []
        )
        return {"success": True, "cleared_rows": len(rows)}

    return await run_in_threadpool(_do)


# ─── Helpers (synchronous; run via threadpool) ──────────────────────────────
def _exchange_code(
    cfg: dict[str, Any],
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> dict[str, Any]:
    body = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            cfg["token_url"],
            data=body,
            headers={"Accept": "application/json"},
        )
    if r.status_code != 200:
        raise RuntimeError(f"token endpoint returned {r.status_code}: {r.text[:300]}")
    return r.json()


def _fetch_userinfo_email(cfg: dict[str, Any], access_token: str) -> str | None:
    with httpx.Client(timeout=15.0) as client:
        r = client.get(
            cfg["userinfo_url"],
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if r.status_code != 200:
        return None
    data = r.json() or {}
    # Microsoft returns 'mail' as null for personal accounts; fall back.
    return (
        data.get(cfg["userinfo_email_key"])
        or data.get("userPrincipalName")
        or data.get("email")
    )


def _persist_tokens(
    *,
    org_id: str,
    provider: str,
    refresh_token: str,
    access_token: str,
    expires_at: str | None,
    account_email: str | None,
) -> None:
    """Encrypt tokens with Fernet and upsert onto email_configs."""
    client = get_service_client()
    row = {
        "org_id": org_id,
        "oauth_provider": provider,
        "oauth_refresh_token_encrypted": encrypt(refresh_token),
        "oauth_access_token_encrypted": encrypt(access_token),
        "oauth_token_expires_at": expires_at,
        "oauth_account_email": account_email,
    }
    client.table("email_configs").upsert(row, on_conflict="org_id").execute()


def _popup_close_response(*, success: bool, message: str) -> HTMLResponse:
    """Tiny HTML page that signals the opener window and closes itself."""
    color = "#22c55e" if success else "#ef4444"
    safe_msg = message.replace("<", "&lt;").replace(">", "&gt;")
    payload = f"""
{{"source":"heykiki-oauth","success":{str(success).lower()},"message":"{safe_msg}"}}
""".strip()
    html = f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><title>OAuth</title></head>
<body style="font-family:system-ui,sans-serif;padding:2rem;text-align:center;background:#f8fafc">
  <div style="max-width:32rem;margin:4rem auto;padding:2rem;border-radius:1rem;background:white;box-shadow:0 4px 24px rgba(0,0,0,0.08)">
    <div style="font-size:3rem">{'✓' if success else '✕'}</div>
    <h1 style="color:{color};margin:1rem 0">{message}</h1>
    <p style="color:#64748b">Dieses Fenster schließt sich automatisch.</p>
  </div>
  <script>
    try {{ if (window.opener) window.opener.postMessage({payload}, '*'); }} catch (e) {{}}
    setTimeout(() => window.close(), 1500);
  </script>
</body></html>"""
    return HTMLResponse(content=html, status_code=200)
