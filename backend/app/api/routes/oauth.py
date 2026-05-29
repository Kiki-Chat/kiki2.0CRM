"""OAuth 2.0 (auth-code) flow for Google / Microsoft / Calendly.

A single google/microsoft consent grants BOTH calendar + email scopes, so one
connection per provider serves both. Calendly is calendar-only.

Flow:
  1. Frontend hits GET /api/settings/oauth/{provider}/authorize (authed) →
     returns {url} with a signed state token, opens it in a popup.
  2. User authorizes → redirect to /api/settings/oauth/{provider}/callback?code=…&state=…
  3. Callback verifies state, exchanges code for tokens, fetches userinfo (the
     account email), encrypts refresh + access tokens with SETTINGS_ENC_KEY
     (Fernet) and persists them to the canonical oauth_connections store —
     mirroring onto email_configs for google/microsoft so the (separate)
     email-send track keeps working unchanged.
  4. POST /api/settings/oauth/{provider}/disconnect (authed) clears tokens.
  5. GET /api/settings/oauth/connections (authed) reports connection status.

Automatic access-token refresh lives in services/oauth_tokens.py
(get_valid_access_token); calendar read/write callers use that, never the raw
stored token.
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
from app.core.crypto import encrypt
from app.db.supabase_client import get_service_client
from app.services import oauth_tokens
from app.services.oauth_providers import (
    EMAIL_PROVIDERS,
    get_credentials,
    get_provider,
    redirect_uri,
)

router = APIRouter(prefix="/api/settings/oauth", tags=["oauth"])


# ─── State token: Fernet-encrypted user_id + org_id + provider + ts + nonce ──
def _make_state(user_id: str, org_id: str, provider: str) -> str:
    payload = f"{user_id}:{org_id}:{provider}:{int(time.time())}:{secrets.token_urlsafe(8)}"
    return encrypt(payload)


def _verify_state(state: str, provider: str, max_age_sec: int = 600) -> tuple[str, str]:
    """Returns (user_id, org_id) on success. Raises 400 on mismatch / expired."""
    from app.core.crypto import decrypt

    try:
        decoded = decrypt(state)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid OAuth state token.")
    if not decoded:
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
@router.get("/connections")
async def connections(user: CurrentUser = Depends(require_org)) -> dict:
    """Connection status per provider for the calling org (no token material)."""
    rows = await run_in_threadpool(oauth_tokens.list_connections, user.org_id)
    return {"connections": rows}


@router.get("/{provider}/authorize")
async def authorize(
    provider: str,
    user: CurrentUser = Depends(require_org),
) -> dict:
    """Returns the OAuth authorize URL to open in a popup."""
    cfg = get_provider(provider)
    cid, _ = get_credentials(provider)
    state = _make_state(user.id, user.org_id, provider)
    params: dict[str, Any] = {
        "client_id": cid,
        "redirect_uri": redirect_uri(provider),
        "response_type": "code",
        "state": state,
        **cfg["extra_authorize_params"],
    }
    if cfg["scopes"]:
        params["scope"] = " ".join(cfg["scopes"])
    return {"url": f"{cfg['authorize_url']}?{urlencode(params)}"}


@router.get("/{provider}/callback")
async def callback(
    provider: str,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    """OAuth provider redirects here with code + state.

    Returns an HTML page that closes the popup and messages the parent window.
    No JWT auth here (the provider's redirect can't carry one); we authenticate
    via the signed state token.
    """
    if error:
        return _popup_close_response(success=False, message=f"OAuth-Fehler: {error}")
    if not code or not state:
        return _popup_close_response(success=False, message="Fehlender code oder state.")
    try:
        _user_id, org_id = _verify_state(state, provider)
    except HTTPException as exc:
        return _popup_close_response(success=False, message=str(exc.detail))

    cfg = get_provider(provider)
    cid, csec = get_credentials(provider)

    try:
        token_data = await run_in_threadpool(
            _exchange_code, cfg, cid, csec, code, redirect_uri(provider),
        )
    except Exception as exc:  # noqa: BLE001
        return _popup_close_response(
            success=False, message=f"Token-Tausch fehlgeschlagen: {exc}",
        )
    if "refresh_token" not in token_data:
        # Without a refresh token the integration breaks the moment the access
        # token expires. Force a clean reconnect with the right flags.
        return _popup_close_response(
            success=False,
            message=(
                "Kein refresh_token erhalten. Bitte zuerst die Verknüpfung mit "
                "diesem Konto entfernen und erneut verbinden."
            ),
        )

    try:
        account_email = await run_in_threadpool(
            _fetch_userinfo_email, cfg, token_data["access_token"],
        )
    except Exception:  # noqa: BLE001
        account_email = None

    expires_in = int(token_data.get("expires_in") or 0)
    expires_at = (
        (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
        if expires_in
        else None
    )

    await run_in_threadpool(
        _persist_tokens,
        org_id=org_id,
        provider=provider,
        refresh_token=token_data["refresh_token"],
        access_token=token_data["access_token"],
        expires_at=expires_at,
        account_email=account_email,
        scope=token_data.get("scope"),
    )

    return _popup_close_response(
        success=True, message=f"Verbunden mit {account_email or provider}.",
    )


@router.post("/{provider}/disconnect")
async def disconnect(
    provider: str,
    user: CurrentUser = Depends(require_org),
) -> dict:
    """Clear stored OAuth tokens for the calling org + provider."""
    get_provider(provider)  # 404 on unknown provider

    def _do() -> dict:
        cleared = oauth_tokens.delete_connection(user.org_id, provider)
        # Also clear the email_configs mirror for email-capable providers.
        if provider in EMAIL_PROVIDERS:
            get_service_client().table("email_configs").update(
                {
                    "oauth_provider": None,
                    "oauth_refresh_token_encrypted": None,
                    "oauth_access_token_encrypted": None,
                    "oauth_token_expires_at": None,
                    "oauth_account_email": None,
                }
            ).eq("org_id", user.org_id).execute()
        return {"success": True, "cleared": cleared}

    return await run_in_threadpool(_do)


# ─── Helpers (synchronous; run via threadpool) ──────────────────────────────
def _exchange_code(
    cfg: dict[str, Any],
    client_id: str,
    client_secret: str,
    code: str,
    redirect: str,
) -> dict[str, Any]:
    body = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect,
    }
    with httpx.Client(timeout=30.0) as client:
        r = client.post(cfg["token_url"], data=body, headers={"Accept": "application/json"})
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
    # Calendly nests under {"resource": {...}}; Google/MS are flat.
    if isinstance(data.get("resource"), dict):
        data = data["resource"]
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
    scope: str | None = None,
) -> None:
    """Persist to the canonical oauth_connections store, and mirror onto
    email_configs for email-capable providers (keeps the email-send track
    working). Calendly is calendar-only → oauth_connections only."""
    oauth_tokens.upsert_connection(
        org_id=org_id,
        provider=provider,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        account_email=account_email,
        scope=scope,
    )
    if provider in EMAIL_PROVIDERS:
        get_service_client().table("email_configs").upsert(
            {
                "org_id": org_id,
                "oauth_provider": provider,
                "oauth_refresh_token_encrypted": encrypt(refresh_token),
                "oauth_access_token_encrypted": encrypt(access_token),
                "oauth_token_expires_at": expires_at,
                "oauth_account_email": account_email,
            },
            on_conflict="org_id",
        ).execute()


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
