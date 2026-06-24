"""3-tier email send chain for HeyKiki Portal (P1.8 Phase 3, Wave 1.2).

Fallback order per ``send_email()`` call (each tier is tried in turn; if every
tier raises, the last exception is re-raised so callers can record a failure):

1. **OAuth (Gmail API / Microsoft Graph)** — when the org has linked Google or
   Microsoft via P1.8 OAuth, refresh the access token and send via the
   provider's REST API. Provider choice is determined by
   ``email_configs.oauth_provider`` (mutually exclusive per org).
2. **Customer SMTP** — the org's own SMTP credentials stored on
   ``email_configs.smtp_*``. Decrypts the password via Fernet
   (``app.core.crypto``).
3. **HeyKiki Brevo SMTP fallback** — central no-reply relay so emails go out
   even when an org hasn't configured anything. Credentials come from env
   vars ``BREVO_SMTP_USERNAME`` / ``BREVO_SMTP_PASSWORD``.

Each attempt is logged. Errors in earlier tiers are captured but never
silent — they're surfaced in ``SendResult.fallback_chain`` and the logs.

Hermetic-test note: every external call (token refresh HTTP, Gmail/Graph
API HTTP, ``smtplib.SMTP``/``SMTP_SSL``) is at module scope so tests can
monkeypatch them without spinning up real services.
"""
from __future__ import annotations

import base64
import logging
import smtplib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any, Literal
from uuid import UUID

import httpx

from app.core.config import settings
from app.core.crypto import decrypt, encrypt
from app.db.supabase_client import get_service_client

log = logging.getLogger(__name__)

ProviderUsed = Literal["gmail_oauth", "ms_oauth", "customer_smtp", "brevo_smtp"]


# ─── Public types ────────────────────────────────────────────────────────────
@dataclass
class Attachment:
    """A single file to attach to the outgoing email.

    ``filename`` is what the recipient sees. ``content`` is the raw bytes.
    ``mime_type`` is the IANA media type (defaults to ``application/pdf``
    because the dominant use case here is Angebot / Rechnung PDF attachments).
    """
    filename: str
    content: bytes
    mime_type: str = "application/pdf"


@dataclass
class SendResult:
    success: bool
    provider_used: ProviderUsed | None
    message_id: str | None
    error: str | None
    fallback_chain: list[str] = field(default_factory=list)


# ─── Public API ──────────────────────────────────────────────────────────────
def send_email(
    *,
    org_id: UUID | str,
    to_email: str,
    subject: str,
    body_html: str,
    body_text: str | None = None,
    attachments: list[Attachment] | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    reply_to: str | None = None,
) -> SendResult:
    """Send an email with the 3-tier fallback chain.

    Raises ``RuntimeError`` only when every tier fails (so the caller is
    forced to handle a hard failure). Partial failures (e.g. OAuth fails but
    SMTP succeeds) are reported in ``SendResult.fallback_chain``.
    """
    # Fail-safe (B6): never attempt a send with an empty recipient. Route callers
    # already guard (Angebot/invoice → 400), but this protects every current + future
    # caller from silently emitting to an empty "To:".
    if not (to_email and str(to_email).strip()):
        raise RuntimeError("Keine Empfänger-E-Mail angegeben.")
    org_id_str = str(org_id)
    attachments = attachments or []
    cc = cc or []
    bcc = bcc or []
    chain: list[str] = []
    last_error: str | None = None

    config = _load_email_config(org_id_str)
    org_name = _load_org_name(org_id_str)

    # Reply-To is ALWAYS the company's own email (the org's contact address), so
    # every recipient reply lands with the COMPANY — never the Brevo relay /
    # HeyKiki "via" address, and never a per-connection sending account. HeyKiki
    # only triggers the mail; we deliberately do NOT route replies per sending
    # account (one consistent reply target across every email type: appointment
    # calls/emails, Angebot, invoice, employee invite, test mail). Falls back to the
    # caller-supplied reply_to only when the org has no email on file.
    org_email = _load_org_email(org_id_str)
    reply_to = org_email or (reply_to or "").strip() or None

    # ── Tier 1: OAuth (Gmail / Microsoft) ─────────────────────────────────
    if config and config.get("oauth_provider") and config.get(
        "oauth_refresh_token_encrypted"
    ):
        oauth_provider = config["oauth_provider"]
        try:
            msg_id = _send_via_oauth(
                config=config,
                org_id=org_id_str,
                to_email=to_email,
                subject=subject,
                body_html=body_html,
                body_text=body_text,
                attachments=attachments,
                cc=cc,
                bcc=bcc,
                reply_to=reply_to,
            )
            chain.append(f"{_oauth_tag(oauth_provider)}_success")
            log.info(
                "email_send org=%s tier=oauth provider=%s to=%s status=success",
                org_id_str, oauth_provider, to_email,
            )
            return SendResult(
                success=True,
                provider_used=_oauth_provider_used(oauth_provider),
                message_id=msg_id,
                error=None,
                fallback_chain=chain,
            )
        except Exception as exc:  # noqa: BLE001 — fall through to next tier
            chain.append(f"{_oauth_tag(oauth_provider)}_failed")
            last_error = f"oauth({oauth_provider}): {exc}"
            log.warning(
                "email_send org=%s tier=oauth provider=%s to=%s status=failed err=%s",
                org_id_str, oauth_provider, to_email, exc,
            )

    # ── Tier 2: customer SMTP ──────────────────────────────────────────────
    if config and config.get("smtp_host"):
        try:
            msg_id = _send_via_customer_smtp(
                config=config,
                org_name=org_name,
                to_email=to_email,
                subject=subject,
                body_html=body_html,
                body_text=body_text,
                attachments=attachments,
                cc=cc,
                bcc=bcc,
                reply_to=reply_to,
            )
            chain.append("customer_smtp_success")
            log.info(
                "email_send org=%s tier=customer_smtp host=%s to=%s status=success",
                org_id_str, config.get("smtp_host"), to_email,
            )
            return SendResult(
                success=True,
                provider_used="customer_smtp",
                message_id=msg_id,
                error=None,
                fallback_chain=chain,
            )
        except Exception as exc:  # noqa: BLE001
            chain.append("customer_smtp_failed")
            last_error = f"customer_smtp: {exc}"
            log.warning(
                "email_send org=%s tier=customer_smtp host=%s to=%s status=failed err=%s",
                org_id_str, config.get("smtp_host"), to_email, exc,
            )

    # ── Tier 3: HeyKiki Brevo fallback ─────────────────────────────────────
    try:
        msg_id = _send_via_brevo(
            org_name=org_name,
            to_email=to_email,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            attachments=attachments,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
        )
        chain.append("brevo_smtp_success")
        log.info(
            "email_send org=%s tier=brevo_smtp to=%s status=success",
            org_id_str, to_email,
        )
        return SendResult(
            success=True,
            provider_used="brevo_smtp",
            message_id=msg_id,
            error=None,
            fallback_chain=chain,
        )
    except Exception as exc:  # noqa: BLE001
        chain.append("brevo_smtp_failed")
        last_error = f"brevo_smtp: {exc}"
        log.error(
            "email_send org=%s tier=brevo_smtp to=%s status=failed err=%s",
            org_id_str, to_email, exc,
        )

    # If we got here every tier failed.
    err_summary = f"All email tiers failed. chain={chain}. last_error={last_error}"
    log.error("email_send org=%s ALL_FAILED chain=%s", org_id_str, chain)
    raise RuntimeError(err_summary)


# ─── Config + org lookup (DB) ────────────────────────────────────────────────
def _load_email_config(org_id: str) -> dict[str, Any] | None:
    """Fetch the org's email_configs row, or None if no row exists.

    Wrapped in a try/except: a transient Supabase blip on a config lookup
    must not block the fallback to Brevo (which is independent of per-org
    config).
    """
    try:
        client = get_service_client()
        rows = (
            client.table("email_configs")
            .select("*")
            .eq("org_id", org_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001
        log.warning("email_send org=%s config_lookup_failed err=%s", org_id, exc)
        return None


def _load_org_name(org_id: str) -> str | None:
    """Fetch the org's display name (used as default From-name)."""
    try:
        client = get_service_client()
        rows = (
            client.table("organizations")
            .select("name")
            .eq("id", org_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0].get("name") if rows else None
    except Exception as exc:  # noqa: BLE001
        log.warning("email_send org=%s org_lookup_failed err=%s", org_id, exc)
        return None


def _load_org_email(org_id: str) -> str | None:
    """Fetch the org's own contact email — the canonical Reply-To so replies
    always reach the COMPANY (never the Brevo relay or a per-connection account)."""
    try:
        client = get_service_client()
        rows = (
            client.table("organizations")
            .select("email")
            .eq("id", org_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        return ((rows[0].get("email") if rows else None) or "").strip() or None
    except Exception as exc:  # noqa: BLE001
        log.warning("email_send org=%s org_email_lookup_failed err=%s", org_id, exc)
        return None


def _oauth_tag(provider: str) -> str:
    """Internal short-tag used in fallback_chain strings."""
    return "gmail_oauth" if provider == "google" else "ms_oauth"


def _oauth_provider_used(provider: str) -> ProviderUsed:
    return "gmail_oauth" if provider == "google" else "ms_oauth"


# ─── Tier 1: OAuth send ──────────────────────────────────────────────────────
def _send_via_oauth(
    *,
    config: dict[str, Any],
    org_id: str,
    to_email: str,
    subject: str,
    body_html: str,
    body_text: str | None,
    attachments: list[Attachment],
    cc: list[str],
    bcc: list[str],
    reply_to: str | None = None,
) -> str | None:
    """Refresh the OAuth access token (if needed), then dispatch to the
    Gmail or Microsoft Graph send helper."""
    provider = config["oauth_provider"]
    access_token = _ensure_access_token(config=config, org_id=org_id)
    sender_email = config.get("oauth_account_email") or config.get("smtp_sender_email")

    if provider == "google":
        return _gmail_api_send(
            access_token=access_token,
            sender_email=sender_email,
            to_email=to_email,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            attachments=attachments,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
        )
    if provider == "microsoft":
        return _ms_graph_send(
            access_token=access_token,
            sender_email=sender_email,
            to_email=to_email,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            attachments=attachments,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
        )
    raise RuntimeError(f"Unknown oauth_provider: {provider!r}")


def _ensure_access_token(*, config: dict[str, Any], org_id: str) -> str:
    """Return a valid access token, refreshing if expired or near-expiry.

    Tokens are refreshed when missing, expired, or within 60s of expiry.
    On refresh, the new tokens are persisted via ``_persist_refreshed_tokens``.
    """
    expires_at_raw = config.get("oauth_token_expires_at")
    expires_at = _parse_iso(expires_at_raw)
    now = datetime.now(timezone.utc)
    access_encrypted = config.get("oauth_access_token_encrypted")
    access_token = decrypt(access_encrypted) if access_encrypted else None

    # If we have an access token AND it's not near expiry, use it.
    if access_token and expires_at and expires_at - now > timedelta(seconds=60):
        return access_token

    # Otherwise refresh.
    refresh_token = decrypt(config["oauth_refresh_token_encrypted"])
    if not refresh_token:
        raise RuntimeError("oauth refresh token undecryptable")
    new_access, new_expires_in = _refresh_oauth_token(
        provider=config["oauth_provider"], refresh_token=refresh_token,
    )
    new_expires_at = (
        now + timedelta(seconds=new_expires_in)
    ).isoformat() if new_expires_in else None
    _persist_refreshed_tokens(
        org_id=org_id,
        access_token=new_access,
        expires_at=new_expires_at,
    )
    return new_access


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _refresh_oauth_token(*, provider: str, refresh_token: str) -> tuple[str, int]:
    """POST to the provider's token endpoint with ``grant_type=refresh_token``.

    Returns ``(access_token, expires_in_seconds)``. Raises on non-2xx.
    """
    if provider == "google":
        token_url = "https://oauth2.googleapis.com/token"
        client_id = settings.google_client_id
        client_secret = settings.google_client_secret
    elif provider == "microsoft":
        token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        client_id = settings.ms_client_id
        client_secret = settings.ms_client_secret
    else:
        raise RuntimeError(f"Unknown oauth provider: {provider!r}")

    if not client_id or not client_secret:
        raise RuntimeError(
            f"OAuth credentials missing for {provider!r} — refresh impossible. "
            f"Set {provider.upper()}_CLIENT_ID / _CLIENT_SECRET per "
            "P1.8_OAUTH_SETUP.md."
        )

    body = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    with httpx.Client(timeout=20.0) as client:
        r = client.post(token_url, data=body, headers={"Accept": "application/json"})
    if r.status_code != 200:
        raise RuntimeError(
            f"oauth refresh ({provider}) {r.status_code}: {r.text[:300]}"
        )
    data = r.json()
    access = data.get("access_token")
    if not access:
        raise RuntimeError(f"oauth refresh ({provider}) returned no access_token")
    expires_in = int(data.get("expires_in") or 3600)
    return access, expires_in


def _persist_refreshed_tokens(
    *, org_id: str, access_token: str, expires_at: str | None,
) -> None:
    """Re-encrypt and persist a freshly-minted access token."""
    try:
        client = get_service_client()
        client.table("email_configs").update(
            {
                "oauth_access_token_encrypted": encrypt(access_token),
                "oauth_token_expires_at": expires_at,
            }
        ).eq("org_id", org_id).execute()
    except Exception as exc:  # noqa: BLE001 — token refresh succeeded; persistence is best-effort
        log.warning(
            "email_send org=%s token_persist_failed err=%s "
            "(send proceeds with in-memory token)",
            org_id, exc,
        )


# ─── Tier 1a: Gmail API send ─────────────────────────────────────────────────
def _gmail_api_send(
    *,
    access_token: str,
    sender_email: str | None,
    to_email: str,
    subject: str,
    body_html: str,
    body_text: str | None,
    attachments: list[Attachment],
    cc: list[str],
    bcc: list[str],
    reply_to: str | None = None,
) -> str | None:
    """Send via Gmail API ``users.messages.send``.

    Builds an RFC 5322 MIME message, base64url-encodes it (Gmail's required
    transport encoding), and POSTs to the v1 endpoint. Returns the Gmail
    message id on success.
    """
    msg = _build_mime_message(
        sender_email=sender_email,
        reply_to_email=reply_to,
        to_email=to_email,
        subject=subject,
        body_html=body_html,
        body_text=body_text,
        attachments=attachments,
        cc=cc,
        bcc=bcc,
    )
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            json={"raw": raw},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )
    if r.status_code not in (200, 202):
        raise RuntimeError(f"gmail send {r.status_code}: {r.text[:300]}")
    return (r.json() or {}).get("id")


# ─── Tier 1b: Microsoft Graph send ───────────────────────────────────────────
def _ms_graph_send(
    *,
    access_token: str,
    sender_email: str | None,
    to_email: str,
    subject: str,
    body_html: str,
    body_text: str | None,  # noqa: ARG001 — Graph picks one body type; we send HTML
    attachments: list[Attachment],
    cc: list[str],
    bcc: list[str],
    reply_to: str | None = None,
) -> str | None:
    """Send via Microsoft Graph ``/me/sendMail``.

    Graph attachments are base64-encoded JSON; the API returns 202 Accepted
    with no body / id, so ``None`` is returned for ``message_id``.
    """
    def _addrs(emails: list[str]) -> list[dict]:
        return [{"emailAddress": {"address": e}} for e in emails if e]

    body_payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body_html},
            "toRecipients": _addrs([to_email]),
            "ccRecipients": _addrs(cc),
            "bccRecipients": _addrs(bcc),
        },
        "saveToSentItems": True,
    }
    if sender_email:
        body_payload["message"]["from"] = {
            "emailAddress": {"address": sender_email},
        }
    if reply_to:
        body_payload["message"]["replyTo"] = _addrs([reply_to])
    if attachments:
        body_payload["message"]["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": a.filename,
                "contentType": a.mime_type,
                "contentBytes": base64.b64encode(a.content).decode("ascii"),
            }
            for a in attachments
        ]

    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            "https://graph.microsoft.com/v1.0/me/sendMail",
            json=body_payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )
    # Graph returns 202 Accepted on success, with no body.
    if r.status_code not in (200, 202):
        raise RuntimeError(f"ms graph send {r.status_code}: {r.text[:300]}")
    return None


# ─── Tier 2: customer SMTP ────────────────────────────────────────────────────
def _send_via_customer_smtp(
    *,
    config: dict[str, Any],
    org_name: str | None,
    to_email: str,
    subject: str,
    body_html: str,
    body_text: str | None,
    attachments: list[Attachment],
    cc: list[str],
    bcc: list[str],
    reply_to: str | None = None,
) -> str | None:
    """Send via the org's stored SMTP credentials.

    Mirrors the SSL/STARTTLS choice already in
    ``settings._send_email``. Decrypts the password via Fernet; sender
    name/email default to org name + smtp_username if not explicitly set.
    """
    host = config["smtp_host"]
    port = int(config.get("smtp_port") or 465)
    username = config.get("smtp_username") or ""
    password = decrypt(config.get("smtp_password_encrypted")) or ""
    sender = (
        config.get("smtp_sender_email")
        or username
        or "no-reply@heykiki.de"
    )
    sender_name = config.get("smtp_sender_name") or org_name or "HeyKiki"
    use_ssl = bool(config.get("use_ssl", True))

    msg = _build_mime_message(
        sender_email=sender,
        sender_name=sender_name,
        reply_to_email=reply_to,
        to_email=to_email,
        subject=subject,
        body_html=body_html,
        body_text=body_text,
        attachments=attachments,
        cc=cc,
        bcc=bcc,
    )

    return _smtp_send(
        host=host,
        port=port,
        username=username,
        password=password,
        use_ssl=use_ssl,
        msg=msg,
    )


# ─── Tier 3: Brevo fallback ──────────────────────────────────────────────────
def _send_via_brevo(
    *,
    org_name: str | None,
    to_email: str,
    subject: str,
    body_html: str,
    body_text: str | None,
    attachments: list[Attachment],
    cc: list[str],
    bcc: list[str],
    reply_to: str | None = None,
) -> str | None:
    """Send via HeyKiki's central Brevo relay using Brevo's transactional HTTP
    API (``api.brevo.com/v3/smtp/email``, HTTPS/443) — NOT SMTP.

    Used when the org hasn't configured anything OR every per-org tier failed.
    We use the HTTP API rather than SMTP because Railway's egress blocks
    outbound SMTP (port 587 connect-times-out), whereas 443 works. Credential is
    the Brevo API key (``BREVO_API_KEY``); if unset, raises (caller surfaces the
    chain). Contract is identical to the prior SMTP impl: return the provider
    message id on success, raise on any non-2xx so ``send_email`` records
    ``brevo_smtp_failed`` and the fallback chain is unchanged.
    """
    api_key = settings.brevo_api_key
    sender_email = settings.brevo_smtp_from_address
    # From-name is "<org> via HeyKiki" so recipients see who the email is
    # nominally from — even when the relay envelope is heykiki.de.
    sender_name = (
        f"{org_name} via {settings.brevo_smtp_from_name}"
        if org_name else settings.brevo_smtp_from_name
    )

    if not api_key:
        raise RuntimeError(
            "Brevo API key not configured (BREVO_API_KEY env var)."
        )

    payload: dict[str, Any] = {
        "sender": {"email": sender_email, "name": sender_name},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": body_html,
        "textContent": body_text or _html_to_text_fallback(body_html),
    }
    if cc:
        payload["cc"] = [{"email": e} for e in cc if e]
    if bcc:
        payload["bcc"] = [{"email": e} for e in bcc if e]
    if reply_to:  # per-customer Reply-To (org email) — #21
        payload["replyTo"] = {"email": reply_to}
    if attachments:
        payload["attachment"] = [
            {
                "name": a.filename,
                "content": base64.b64encode(a.content).decode("ascii"),
            }
            for a in attachments
        ]

    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            "https://api.brevo.com/v3/smtp/email",
            json=payload,
            headers={
                "api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
    if r.status_code not in (200, 201, 202):
        raise RuntimeError(f"brevo api {r.status_code}: {r.text[:300]}")
    return (r.json() or {}).get("messageId")


# ─── Shared MIME builder + SMTP transport ────────────────────────────────────
def _build_mime_message(
    *,
    sender_email: str | None,
    to_email: str,
    subject: str,
    body_html: str,
    body_text: str | None,
    attachments: list[Attachment],
    cc: list[str],
    bcc: list[str],
    sender_name: str | None = None,
    reply_to_email: str | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    if sender_email:
        msg["From"] = f"{sender_name} <{sender_email}>" if sender_name else sender_email
    msg["To"] = to_email
    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        msg["Bcc"] = ", ".join(bcc)
    if reply_to_email:
        msg["Reply-To"] = reply_to_email

    # Plain-text fallback; HTML is the rich body. Even all-HTML clients are
    # happier seeing a multipart/alternative.
    text_body = body_text or _html_to_text_fallback(body_html)
    msg.set_content(text_body)
    msg.add_alternative(body_html, subtype="html")

    for a in attachments:
        # add_attachment infers maintype/subtype from a "type/subtype" string.
        maintype, _, subtype = a.mime_type.partition("/")
        msg.add_attachment(
            a.content,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=a.filename,
        )
    return msg


def _html_to_text_fallback(body_html: str) -> str:
    """Crude HTML→text fallback so mailbox text/plain parts aren't empty.

    Not a perfect renderer (we're not pulling in beautifulsoup just for this),
    but better than nothing — strips tags + collapses whitespace.
    """
    import re
    text = re.sub(r"<br\s*/?>", "\n", body_html, flags=re.I)
    text = re.sub(r"</p>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _smtp_send(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    use_ssl: bool,
    msg: EmailMessage,
) -> str | None:
    """Open an SMTP / SMTP_SSL session, authenticate if creds given, send.

    Returns the ``Message-Id`` header (set by smtplib when send_message is
    called) so callers can correlate.
    """
    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=20) as srv:
            if username and password:
                srv.login(username, password)
            srv.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=20) as srv:
            srv.ehlo()
            try:
                srv.starttls()
                srv.ehlo()
            except smtplib.SMTPNotSupportedError:
                # Some test relays don't speak STARTTLS — proceed plaintext.
                pass
            if username and password:
                srv.login(username, password)
            srv.send_message(msg)
    return msg.get("Message-Id")
