"""OAuth 2.0 (auth-code) flow for Google / Microsoft / Calendly — PER-PURPOSE.

The EMAIL and CALENDAR axes are INDEPENDENT. Each consent is tied to a *purpose*
('email' | 'calendar') carried in the signed state token. A single provider
grant (one ``oauth_connections`` row) may serve one OR both purposes; the
``oauth_purpose_links`` table records exactly one provider per (org, purpose),
so the axes are independent and exclusivity is DB-enforced (PK org_id+purpose).

Flow:
  1. GET  /{provider}/authorize?purpose=email|calendar (authed) → {url} with a
     signed state token (provider + purpose); opened in a popup.
  2. Provider redirects → GET /{provider}/callback?code&state.
  3. Callback exchanges the code, stores the grant in oauth_connections, links
     the purpose, and — ONLY when purpose=email on google/microsoft — mirrors
     tokens onto email_configs (the unchanged email-send read path).
  4. POST /{provider}/link?purpose=… (authed) — "use the same account": link an
     EXISTING grant to another purpose without a fresh consent.
  5. POST /disconnect?purpose=email|calendar (authed) — PURPOSE-SCOPED. Drops the
     link; revokes + deletes the underlying grant ONLY when no purpose still
     uses it (so disconnecting calendar never kills a shared email grant).
  6. GET  /connections (authed) — grants + per-purpose linkage (no token data).

Automatic access-token refresh: services/oauth_tokens.get_valid_access_token.
"""
from __future__ import annotations

import logging
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
from app.services import calendar_sync, oauth_tokens
from app.services.oauth_providers import (
    EMAIL_PROVIDERS,
    can_serve,
    get_credentials,
    get_provider,
    redirect_uri,
)

router = APIRouter(prefix="/api/settings/oauth", tags=["oauth"])

log = logging.getLogger(__name__)

_VALID_PURPOSES = ("email", "calendar")


def _auto_sync_calendar(org_id: str, provider: str, purpose: str) -> None:
    """On a fresh CALENDAR connect (or reuse-link), pull the provider's events so
    the CRM shows the owner's busy time immediately — no manual 'Jetzt
    synchronisieren' click at the connection point. Only Google has a working
    read-sync today. BEST-EFFORT: the grant is already persisted, so a sync
    failure must never fail the connect; it's idempotent + read-only, so the
    Kalender page's sync button (or the next auto-sync) recovers cleanly."""
    if purpose != "calendar" or provider != "google":
        return
    try:
        calendar_sync.pull_google_events(org_id)
    except Exception:  # noqa: BLE001 — connect already succeeded; sync is best-effort
        log.warning("auto-sync after calendar connect failed for org=%s", org_id, exc_info=True)


# ─── State token: Fernet(user_id:org_id:provider:purpose:ts:nonce) ───────────
def _make_state(user_id: str, org_id: str, provider: str, purpose: str) -> str:
    payload = (
        f"{user_id}:{org_id}:{provider}:{purpose}:{int(time.time())}:"
        f"{secrets.token_urlsafe(8)}"
    )
    return encrypt(payload)


def _verify_state(state: str, provider: str, max_age_sec: int = 600) -> tuple[str, str, str]:
    """Returns (user_id, org_id, purpose). Raises 400 on mismatch / expired.
    Tolerates a legacy 5-part state (no purpose) → defaults purpose='email'."""
    from app.core.crypto import decrypt

    try:
        decoded = decrypt(state)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid OAuth state token.")
    if not decoded:
        raise HTTPException(status_code=400, detail="Invalid OAuth state token.")
    parts = decoded.split(":")
    if len(parts) >= 6:
        user_id, org_id, prov, purpose, ts_str = parts[0], parts[1], parts[2], parts[3], parts[4]
    elif len(parts) == 5:  # legacy pre-purpose state
        user_id, org_id, prov, ts_str = parts[0], parts[1], parts[2], parts[3]
        purpose = "email"
    else:
        raise HTTPException(status_code=400, detail="Malformed OAuth state token.")
    if prov != provider:
        raise HTTPException(status_code=400, detail="OAuth state provider mismatch.")
    if purpose not in _VALID_PURPOSES:
        raise HTTPException(status_code=400, detail="OAuth state purpose invalid.")
    try:
        ts = int(ts_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Malformed OAuth state timestamp.")
    if time.time() - ts > max_age_sec:
        raise HTTPException(status_code=400, detail="OAuth state token expired.")
    return user_id, org_id, purpose


# ─── Routes ──────────────────────────────────────────────────────────────────
@router.get("/connections")
async def connections(user: CurrentUser = Depends(require_org)) -> dict:
    """Grants (per provider) + per-purpose linkage for the org. No token material.

    ``purposes`` is ``{email|calendar: {provider, account_email}}`` — the
    frontend drives both exclusivity cards off this.
    """
    def _do() -> dict:
        return {
            "connections": oauth_tokens.list_connections(user.org_id),
            "purposes": oauth_tokens.list_purpose_links(user.org_id),
        }

    return await run_in_threadpool(_do)


@router.get("/{provider}/authorize")
async def authorize(
    provider: str,
    purpose: str = "email",
    user: CurrentUser = Depends(require_org),
) -> dict:
    """Return the OAuth authorize URL to open in a popup, tied to a purpose."""
    cfg = get_provider(provider)
    if purpose not in _VALID_PURPOSES:
        raise HTTPException(status_code=400, detail=f"Unbekannter Zweck: {purpose}")
    if not can_serve(provider, purpose):
        raise HTTPException(
            status_code=400,
            detail=f"'{provider}' kann den Zweck '{purpose}' nicht erfüllen.",
        )
    cid, _ = get_credentials(provider)
    state = _make_state(user.id, user.org_id, provider, purpose)
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
    """Provider redirects here with code + state. Returns an HTML page that
    messages the opener and closes the popup. Authenticated via the signed
    state token (the provider redirect can't carry a JWT)."""
    if error:
        return _popup_close_response(success=False, message=f"OAuth-Fehler: {error}")
    if not code or not state:
        return _popup_close_response(success=False, message="Fehlender code oder state.")
    try:
        _user_id, org_id, purpose = _verify_state(state, provider)
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
        _persist_grant_and_link,
        org_id=org_id,
        provider=provider,
        purpose=purpose,
        refresh_token=token_data["refresh_token"],
        access_token=token_data["access_token"],
        expires_at=expires_at,
        account_email=account_email,
        scope=token_data.get("scope"),
    )

    # Auto-sync on connect (B3): a fresh Google calendar grant pulls events now,
    # so the connection point needs no manual sync button. Best-effort.
    await run_in_threadpool(_auto_sync_calendar, org_id, provider, purpose)

    label = "E-Mail" if purpose == "email" else "Kalender"
    return _popup_close_response(
        success=True, message=f"{label} verbunden mit {account_email or provider}.",
    )


@router.post("/{provider}/link")
async def link_purpose(
    provider: str,
    purpose: str = Query(...),
    user: CurrentUser = Depends(require_org),
) -> dict:
    """"Use the same account": link an EXISTING grant to another purpose without
    a fresh consent (e.g. reuse the connected Google account for calendar).

    Valid only when the provider already has a grant AND can serve the purpose
    (google/microsoft consent already covers both email + calendar scopes)."""
    get_provider(provider)  # 404 on unknown provider
    if purpose not in _VALID_PURPOSES:
        raise HTTPException(status_code=400, detail=f"Unbekannter Zweck: {purpose}")
    if not can_serve(provider, purpose):
        raise HTTPException(
            status_code=400,
            detail=f"'{provider}' kann den Zweck '{purpose}' nicht erfüllen.",
        )

    def _do() -> dict:
        conn = oauth_tokens.get_connection(user.org_id, provider)
        if not conn:
            raise HTTPException(
                status_code=409,
                detail=f"'{provider}' ist nicht verbunden — bitte zuerst verbinden.",
            )
        oauth_tokens.set_purpose_link(user.org_id, purpose, provider, conn.get("account_email"))
        if purpose == "email" and provider in EMAIL_PROVIDERS:
            _mirror_email_from_connection(user.org_id, provider, conn)
        # Reusing an existing grant for calendar should also sync immediately (B3).
        _auto_sync_calendar(user.org_id, provider, purpose)
        return {
            "success": True,
            "purpose": purpose,
            "provider": provider,
            "account_email": conn.get("account_email"),
        }

    return await run_in_threadpool(_do)


@router.post("/disconnect")
async def disconnect(
    purpose: str = Query(...),
    user: CurrentUser = Depends(require_org),
) -> dict:
    """PURPOSE-SCOPED disconnect.

    Drops the link for ``purpose``; revokes + deletes the underlying grant ONLY
    when no purpose still uses it. So disconnecting calendar when email shares
    the same Google grant just drops the calendar link — the grant (and email)
    stay intact and NOTHING is revoked.
    """
    if purpose not in _VALID_PURPOSES:
        raise HTTPException(status_code=400, detail=f"Unbekannter Zweck: {purpose}")

    def _do() -> dict:
        provider = oauth_tokens.delete_purpose_link(user.org_id, purpose)
        if not provider:
            return {"success": True, "purpose": purpose, "nothing_linked": True}
        # Email purpose → drop the email-send mirror (email no longer uses it).
        if purpose == "email":
            _clear_email_mirror(user.org_id)
        # Calendar purpose → purge this org's imported (google_import) events so
        # stale blocked-time doesn't survive into a later-linked provider's view.
        # Scoped to source='google_import'; native crm appointments are untouched.
        elif purpose == "calendar":
            calendar_sync.purge_imported_events(user.org_id)
        # Revoke + delete the grant ONLY if no purpose still references it.
        remaining = oauth_tokens.purposes_for_provider(user.org_id, provider)
        revoked = False
        if not remaining:
            revoked = oauth_tokens.revoke_grant(user.org_id, provider)
            oauth_tokens.delete_connection(user.org_id, provider)
        return {
            "success": True,
            "purpose": purpose,
            "provider": provider,
            "grant_revoked": revoked,
            "grant_kept": bool(remaining),
            "still_used_by": remaining,
        }

    return await run_in_threadpool(_do)


# ─── Persistence helpers ─────────────────────────────────────────────────────
def _persist_grant_and_link(
    *,
    org_id: str,
    provider: str,
    purpose: str,
    refresh_token: str,
    access_token: str,
    expires_at: str | None,
    account_email: str | None,
    scope: str | None = None,
) -> None:
    """Store the grant (canonical), link the purpose, and — email purpose on an
    email-capable provider ONLY — mirror tokens onto email_configs for the
    (unchanged) email-send read path. A calendar connect never touches
    email_configs."""
    oauth_tokens.upsert_connection(
        org_id=org_id,
        provider=provider,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        account_email=account_email,
        scope=scope,
    )
    oauth_tokens.set_purpose_link(org_id, purpose, provider, account_email)
    if purpose == "email" and provider in EMAIL_PROVIDERS:
        _mirror_email_plain(
            org_id, provider, refresh_token, access_token, expires_at, account_email
        )


def _mirror_email_plain(
    org_id: str,
    provider: str,
    refresh_token: str,
    access_token: str,
    expires_at: str | None,
    account_email: str | None,
) -> None:
    """Mirror freshly-exchanged (plaintext) tokens onto email_configs."""
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


def _mirror_email_from_connection(org_id: str, provider: str, conn: dict) -> None:
    """Mirror from an EXISTING grant — copy the already-encrypted blobs as-is
    (same SETTINGS_ENC_KEY), used by the 'use the same account' link path."""
    get_service_client().table("email_configs").upsert(
        {
            "org_id": org_id,
            "oauth_provider": provider,
            "oauth_refresh_token_encrypted": conn.get("refresh_token_encrypted"),
            "oauth_access_token_encrypted": conn.get("access_token_encrypted"),
            "oauth_token_expires_at": conn.get("token_expires_at"),
            "oauth_account_email": conn.get("account_email"),
        },
        on_conflict="org_id",
    ).execute()


def _clear_email_mirror(org_id: str) -> None:
    get_service_client().table("email_configs").update(
        {
            "oauth_provider": None,
            "oauth_refresh_token_encrypted": None,
            "oauth_access_token_encrypted": None,
            "oauth_token_expires_at": None,
            "oauth_account_email": None,
        }
    ).eq("org_id", org_id).execute()


# ─── Token-exchange helpers (synchronous; run via threadpool) ────────────────
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
