"""OAuth provider registry (P3).

Shared by the auth-code routes (``api/routes/oauth.py``) and the token-refresh
service (``services/oauth_tokens.py``) so there is one source of truth for
authorize/token/userinfo URLs, scopes and credential lookup.

A single google / microsoft consent grants BOTH calendar + email scopes, so one
connection per provider serves both. Calendly is calendar-only.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.core.config import settings

# Providers that ALSO drive the email-send path (email_configs.oauth_*). The
# OAuth callback mirrors tokens onto email_configs for these so Amber's
# (separate) email-send track keeps working unchanged. Calendly is excluded.
EMAIL_PROVIDERS = {"google", "microsoft"}

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
        # access_type=offline is what makes the refresh token come back;
        # prompt=consent forces re-issue on re-link so we never silently lose it.
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
        "userinfo_email_key": "mail",  # falls back to userPrincipalName in the route
        "extra_authorize_params": {},
    },
    "calendly": {
        "client_id_attr": "calendly_client_id",
        "client_secret_attr": "calendly_client_secret",
        "authorize_url": "https://auth.calendly.com/oauth/authorize",
        "token_url": "https://auth.calendly.com/oauth/token",
        # Calendly issues a default scope on the auth-code grant; no scope param.
        "scopes": [],
        "userinfo_url": "https://api.calendly.com/users/me",
        # Calendly nests the user under {"resource": {"email": ...}}; the route's
        # _fetch_userinfo_email unwraps "resource" before reading this key.
        "userinfo_email_key": "email",
        "extra_authorize_params": {},
        "calendar_only": True,
    },
}


def get_provider(provider: str) -> dict[str, Any]:
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Unknown OAuth provider: {provider}")
    return cfg


def get_credentials(provider: str) -> tuple[str, str]:
    """Return (client_id, client_secret) or raise 503 when not configured."""
    cfg = get_provider(provider)
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


def redirect_uri(provider: str) -> str:
    base = settings.backend_public_url.rstrip("/")
    return f"{base}/api/settings/oauth/{provider}/callback"
