"""Employee welcome-invite email (Wave 2).

When an org-admin creates an employee WITH login access, we send a branded
German welcome email through the existing 3-tier send pipeline
(``email_send.send_email``). The email contains the employee's login ID (their
email) and a SECURE SET-PASSWORD LINK — never a password. The employee clicks
the link and sets their own password, so no credential is transmitted and the
admin never learns it (preserves credential privacy).

The link is a Supabase Auth action link (``auth.admin.generate_link``):
  * ``type="invite"``  → for a brand-new login (also creates the auth user;
    Supabase does NOT send its own email when generate_link is used).
  * ``type="recovery"`` → for an existing login (resend / set a new password).
It redirects to ``{frontend_public_url}/set-password`` where the recovered
session lets the page call ``auth.updateUser({password})``. That redirect path
must be on Supabase Auth's Redirect-URL allow-list for the link to resolve.
"""
from __future__ import annotations

import html as _html
import logging

import httpx

from app.core.config import settings
from app.db.supabase_client import get_service_client
from app.services import email_send, email_templates

log = logging.getLogger(__name__)


def _set_password_redirect() -> str:
    return f"{settings.public_app_url}/set-password"


def revoke_user_sessions(user_id: str) -> None:
    """Revoke ALL sessions + refresh tokens for ``user_id`` via the GoTrue admin
    logout endpoint, so a REUSED login (recreate-by-email) can never be accessed
    by its previous holder. The high-level client's ``auth.admin.sign_out`` needs
    a JWT, not a user id, so we call the admin REST endpoint directly with the
    service-role key. Best-effort: the caller wraps this and records a warning."""
    base = (settings.supabase_url or "").rstrip("/")
    key = settings.supabase_service_role_key or ""
    if not base or not key:
        raise RuntimeError("Supabase URL/service key not configured")
    resp = httpx.post(
        f"{base}/auth/v1/admin/users/{user_id}/logout",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=10.0,
    )
    if resp.status_code not in (200, 204):
        raise RuntimeError(f"admin logout HTTP {resp.status_code}: {resp.text[:200]}")


def generate_set_password_link(email: str, *, new_user: bool) -> tuple[str, str | None]:
    """Generate a Supabase set-password action link for ``email``.

    ``new_user=True`` → ``invite`` (creates the auth user, returns the link, no
    Supabase email sent). ``new_user=False`` → ``recovery`` (existing user).

    Returns ``(action_link, user_id)``; ``user_id`` is populated for the invite
    path (the freshly-created auth user) and may be ``None`` for recovery.
    """
    client = get_service_client()
    res = client.auth.admin.generate_link(
        {
            "type": "invite" if new_user else "recovery",
            "email": email,
            "options": {"redirect_to": _set_password_redirect()},
        }
    )
    props = getattr(res, "properties", None)
    action_link = getattr(props, "action_link", None) if props else None
    if not action_link:
        raise RuntimeError("Supabase generate_link returned no action_link")
    user = getattr(res, "user", None)
    user_id = getattr(user, "id", None) if user else None
    return action_link, user_id


def build_welcome_email_html(
    *, company_name: str | None, display_name: str | None,
    login_email: str, set_password_link: str,
) -> str:
    """Branded German welcome email body (wrapped in the shared shell).

    IMPORTANT: contains the login ID + the set-password LINK only — never a
    password.
    """
    company = company_name or "HeyKiki"
    name = (display_name or "").strip()
    greeting = f"Willkommen im Team, {_html.escape(name)}!" if name else "Willkommen im Team!"
    p = (
        "margin: 0 0 14px 0; color: #555555; font-size: 14px; line-height: 1.6; "
        "font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;"
    )
    body = (
        f'<h2 style="margin: 0 0 16px 0; color: #03423A; font-size: 18px; '
        f'font-family: \'Segoe UI\', Tahoma, Geneva, Verdana, Arial, sans-serif;">{greeting}</h2>'
        f'<p style="{p}">Sie wurden von <strong>{_html.escape(company)}</strong> zum '
        f'HeyKiki-Portal eingeladen.</p>'
        f'<p style="{p}">Ihre Anmelde-E-Mail (Login-ID):<br>'
        f'<strong>{_html.escape(login_email)}</strong></p>'
        f'<p style="{p}">Bitte legen Sie über den folgenden sicheren Link Ihr '
        f'persönliches Passwort fest:</p>'
        f'<p style="text-align: center; margin: 26px 0;">'
        f'<a href="{set_password_link}" style="display: inline-block; '
        f'background-color: #03423A; color: #ffffff; padding: 12px 30px; '
        f'border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 15px; '
        f'font-family: \'Segoe UI\', Tahoma, Geneva, Verdana, Arial, sans-serif;">'
        f'Passwort festlegen</a></p>'
        f'<p style="{p} font-size: 12px; color: #888888;">Aus Sicherheitsgründen '
        f'enthält diese E-Mail kein Passwort. Sie vergeben Ihr Passwort selbst über '
        f'den Link oben. Falls Sie diese Einladung nicht erwartet haben, können Sie '
        f'diese E-Mail ignorieren.</p>'
    )
    return email_templates.render_email(company_name=company, body_html=body)


def send_employee_welcome(
    *, org_id: str, company_name: str | None, display_name: str | None,
    login_email: str, set_password_link: str,
) -> None:
    """Send the branded welcome email via the org's 3-tier send chain.

    Raises if every tier fails (so the caller can record a warning). The body
    NEVER contains a password — only the login ID + set-password link.
    """
    html = build_welcome_email_html(
        company_name=company_name, display_name=display_name,
        login_email=login_email, set_password_link=set_password_link,
    )
    subject = f"Willkommen bei {company_name or 'HeyKiki'} – Ihr Zugang"
    email_send.send_email(
        org_id=org_id,
        to_email=login_email,
        subject=subject,
        body_html=html,
    )
