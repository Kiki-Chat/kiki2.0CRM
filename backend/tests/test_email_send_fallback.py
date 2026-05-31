"""Hermetic tests for the 3-tier email_send fallback chain (P1.8 Phase 3, Wave 1.2).

No network. The OAuth refresh HTTP, Gmail / Graph send HTTP, and stdlib
``smtplib.SMTP`` / ``SMTP_SSL`` are all monkeypatched so each tier can be
forced to succeed or fail in isolation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any

import httpx
import pytest

from app.core.crypto import encrypt
from app.services import email_send as es
from app.services.email_send import Attachment, send_email

ORG_ID = "00000000-0000-0000-0000-0000000000aa"
TO_EMAIL = "kunde@example.com"


# ─── Test helpers ────────────────────────────────────────────────────────────
def _far_future() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()


def _config_oauth_google(*, valid_token: bool = True) -> dict[str, Any]:
    return {
        "org_id": ORG_ID,
        "oauth_provider": "google",
        "oauth_refresh_token_encrypted": encrypt("refresh-tok-google"),
        "oauth_access_token_encrypted": encrypt("access-tok-google"),
        "oauth_token_expires_at": _far_future() if valid_token else None,
        "oauth_account_email": "agrawalamber01@gmail.com",
    }


def _config_oauth_microsoft() -> dict[str, Any]:
    return {
        "org_id": ORG_ID,
        "oauth_provider": "microsoft",
        "oauth_refresh_token_encrypted": encrypt("refresh-tok-ms"),
        "oauth_access_token_encrypted": encrypt("access-tok-ms"),
        "oauth_token_expires_at": _far_future(),
        "oauth_account_email": "amber@example.onmicrosoft.com",
    }


def _config_smtp() -> dict[str, Any]:
    return {
        "org_id": ORG_ID,
        "smtp_host": "mail.example.com",
        "smtp_port": 465,
        "smtp_username": "amber@example.com",
        "smtp_password_encrypted": encrypt("smtp-secret"),
        "smtp_sender_email": "amber@example.com",
        "smtp_sender_name": "Amber Test",
        "use_ssl": True,
    }


def _config_oauth_plus_smtp() -> dict[str, Any]:
    return {**_config_oauth_google(), **_config_smtp()}


class _FakeSMTP:
    """Drop-in replacement for ``smtplib.SMTP`` / ``SMTP_SSL`` that records
    calls and either succeeds or raises depending on ``should_fail``."""

    instances: list["_FakeSMTP"] = []

    def __init__(self, host: str, port: int, timeout: int = 0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.logged_in = False
        self.sent: list[EmailMessage] = []
        type(self).instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        return None

    def starttls(self):
        return None

    def login(self, user: str, pw: str):
        self.logged_in = True

    def send_message(self, msg: EmailMessage):
        self.sent.append(msg)


class _FakeSMTPFail(_FakeSMTP):
    """Like _FakeSMTP but raises on send_message."""
    def send_message(self, msg: EmailMessage):
        raise RuntimeError(f"SMTP failure ({self.host}:{self.port})")


def _patch_db(monkeypatch, *, email_config: dict | None, org_name: str | None = "Test Org GmbH"):
    """Patch _load_email_config and _load_org_name (no DB)."""
    monkeypatch.setattr(es, "_load_email_config", lambda org_id: email_config)
    monkeypatch.setattr(es, "_load_org_name", lambda org_id: org_name)
    # Also stub _persist_refreshed_tokens so we don't hit Supabase.
    monkeypatch.setattr(
        es, "_persist_refreshed_tokens",
        lambda *, org_id, access_token, expires_at: None,
    )


def _patch_brevo_creds(monkeypatch, *, api_key: str = "brevo-api-key"):
    # Tier-3 now uses Brevo's HTTP API (BREVO_API_KEY), not SMTP creds.
    monkeypatch.setattr(es.settings, "brevo_api_key", api_key, raising=False)


def _patch_oauth_creds(monkeypatch):
    """Set provider client_id/secret so the refresh path doesn't bail."""
    monkeypatch.setattr(es.settings, "google_client_id", "gid", raising=False)
    monkeypatch.setattr(es.settings, "google_client_secret", "gsec", raising=False)
    monkeypatch.setattr(es.settings, "ms_client_id", "mid", raising=False)
    monkeypatch.setattr(es.settings, "ms_client_secret", "msec", raising=False)


def _fake_httpx_post(responses: dict[str, httpx.Response]):
    """Build an httpx.Client.post replacement that returns canned responses keyed by URL substring."""
    def _post(self, url: str, *args, **kwargs):  # noqa: ARG001
        for key, resp in responses.items():
            if key in url:
                return resp
        return httpx.Response(404, text=f"unmocked url {url}")
    return _post


# ─── Tier 1: OAuth succeeds → no SMTP attempted ──────────────────────────────
def test_oauth_gmail_success_no_smtp(monkeypatch):
    """Gmail OAuth send succeeds → result.provider_used == 'gmail_oauth',
    SMTP layer is never opened."""
    _patch_db(monkeypatch, email_config=_config_oauth_google())
    _patch_oauth_creds(monkeypatch)
    _FakeSMTP.instances.clear()

    monkeypatch.setattr(
        httpx.Client, "post",
        _fake_httpx_post({
            "gmail.googleapis.com": httpx.Response(200, json={"id": "msg-gmail-1"}),
            # No refresh because access token is far-future-valid.
        }),
    )
    monkeypatch.setattr("smtplib.SMTP_SSL", _FakeSMTP)
    monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)

    res = send_email(
        org_id=ORG_ID,
        to_email=TO_EMAIL,
        subject="Test KVA",
        body_html="<p>hi</p>",
        attachments=[Attachment(filename="x.pdf", content=b"%PDF-1.4 fake")],
    )
    assert res.success is True
    assert res.provider_used == "gmail_oauth"
    assert res.message_id == "msg-gmail-1"
    assert res.fallback_chain == ["gmail_oauth_success"]
    assert _FakeSMTP.instances == []  # SMTP never touched


def test_oauth_microsoft_success_no_smtp(monkeypatch):
    """MS Graph OAuth send (status 202 Accepted) → provider_used == 'ms_oauth'."""
    _patch_db(monkeypatch, email_config=_config_oauth_microsoft())
    _patch_oauth_creds(monkeypatch)
    _FakeSMTP.instances.clear()

    monkeypatch.setattr(
        httpx.Client, "post",
        _fake_httpx_post({
            "graph.microsoft.com": httpx.Response(202, text=""),
        }),
    )
    monkeypatch.setattr("smtplib.SMTP_SSL", _FakeSMTP)
    monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)

    res = send_email(
        org_id=ORG_ID,
        to_email=TO_EMAIL,
        subject="Test invoice",
        body_html="<p>Rechnung anbei.</p>",
    )
    assert res.success is True
    assert res.provider_used == "ms_oauth"
    assert res.fallback_chain == ["ms_oauth_success"]
    assert _FakeSMTP.instances == []


# ─── Tier 1 → 2 fallback ─────────────────────────────────────────────────────
def test_oauth_failed_customer_smtp_succeeds(monkeypatch):
    """Gmail returns 500 → fall back to customer SMTP → succeeds."""
    _patch_db(monkeypatch, email_config=_config_oauth_plus_smtp())
    _patch_oauth_creds(monkeypatch)
    _FakeSMTP.instances.clear()

    monkeypatch.setattr(
        httpx.Client, "post",
        _fake_httpx_post({
            "gmail.googleapis.com": httpx.Response(500, text="upstream error"),
        }),
    )
    monkeypatch.setattr("smtplib.SMTP_SSL", _FakeSMTP)
    monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)

    res = send_email(
        org_id=ORG_ID,
        to_email=TO_EMAIL,
        subject="Test",
        body_html="<p>hi</p>",
    )
    assert res.success is True
    assert res.provider_used == "customer_smtp"
    assert res.fallback_chain == ["gmail_oauth_failed", "customer_smtp_success"]
    # One SMTP_SSL session opened to the customer's host
    assert len(_FakeSMTP.instances) == 1
    assert _FakeSMTP.instances[0].host == "mail.example.com"
    assert _FakeSMTP.instances[0].logged_in is True


# ─── Tier 1 + 2 fail → Tier 3 (Brevo) succeeds ──────────────────────────────
def test_oauth_and_customer_smtp_fail_brevo_succeeds(monkeypatch):
    """Both OAuth and customer SMTP fail; Brevo (HTTP API) is reached and succeeds."""
    _patch_db(monkeypatch, email_config=_config_oauth_plus_smtp())
    _patch_oauth_creds(monkeypatch)
    _patch_brevo_creds(monkeypatch)
    _FakeSMTP.instances.clear()

    monkeypatch.setattr(
        httpx.Client, "post",
        _fake_httpx_post({
            "gmail.googleapis.com": httpx.Response(503, text="busy"),
            "api.brevo.com": httpx.Response(201, json={"messageId": "brevo-1"}),
        }),
    )

    # Customer SMTP SSL fails; Brevo now goes via the HTTP API (no SMTP at all).
    def fake_smtp_ssl(host, port, timeout=0):
        return _FakeSMTPFail(host, port, timeout)
    def fake_smtp(host, port, timeout=0):
        return _FakeSMTPFail(host, port, timeout)
    monkeypatch.setattr("smtplib.SMTP_SSL", fake_smtp_ssl)
    monkeypatch.setattr("smtplib.SMTP", fake_smtp)

    res = send_email(
        org_id=ORG_ID,
        to_email=TO_EMAIL,
        subject="Test",
        body_html="<p>hi</p>",
    )
    assert res.success is True
    assert res.provider_used == "brevo_smtp"
    assert res.message_id == "brevo-1"
    assert res.fallback_chain == [
        "gmail_oauth_failed",
        "customer_smtp_failed",
        "brevo_smtp_success",
    ]
    # Only the customer SMTP attempt opens an SMTP session; Brevo is HTTP now.
    assert len(_FakeSMTP.instances) == 1
    assert _FakeSMTP.instances[0].host == "mail.example.com"


# ─── All three fail → raises with full chain in message ──────────────────────
def test_all_three_tiers_fail_raises(monkeypatch):
    """Every tier fails → RuntimeError with full fallback_chain summary."""
    _patch_db(monkeypatch, email_config=_config_oauth_plus_smtp())
    _patch_oauth_creds(monkeypatch)
    _patch_brevo_creds(monkeypatch)
    _FakeSMTP.instances.clear()

    monkeypatch.setattr(
        httpx.Client, "post",
        _fake_httpx_post({
            "gmail.googleapis.com": httpx.Response(500, text="fail"),
        }),
    )

    def fake_smtp_ssl(host, port, timeout=0):
        return _FakeSMTPFail(host, port, timeout)
    def fake_smtp(host, port, timeout=0):
        return _FakeSMTPFail(host, port, timeout)
    monkeypatch.setattr("smtplib.SMTP_SSL", fake_smtp_ssl)
    monkeypatch.setattr("smtplib.SMTP", fake_smtp)

    with pytest.raises(RuntimeError) as exc:
        send_email(
            org_id=ORG_ID, to_email=TO_EMAIL,
            subject="Test", body_html="<p>hi</p>",
        )
    msg = str(exc.value)
    assert "All email tiers failed" in msg
    assert "gmail_oauth_failed" in msg
    assert "customer_smtp_failed" in msg
    assert "brevo_smtp_failed" in msg


# ─── No OAuth + no customer SMTP → goes straight to Brevo ───────────────────
def test_no_config_goes_straight_to_brevo(monkeypatch):
    """Org has no email_configs row at all → fallback chain skips tiers 1+2."""
    _patch_db(monkeypatch, email_config=None)
    _patch_brevo_creds(monkeypatch)
    _FakeSMTP.instances.clear()

    monkeypatch.setattr(
        httpx.Client, "post",
        _fake_httpx_post({
            "api.brevo.com": httpx.Response(201, json={"messageId": "brevo-2"}),
        }),
    )
    monkeypatch.setattr("smtplib.SMTP_SSL", _FakeSMTP)
    monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)

    res = send_email(
        org_id=ORG_ID, to_email=TO_EMAIL,
        subject="Test", body_html="<p>hi</p>",
    )
    assert res.success is True
    assert res.provider_used == "brevo_smtp"
    assert res.fallback_chain == ["brevo_smtp_success"]
    # Brevo is HTTP now → no SMTP session opened at all.
    assert _FakeSMTP.instances == []


def test_smtp_only_config_skips_oauth_tier(monkeypatch):
    """Org has SMTP but no OAuth → tier 1 is skipped entirely; tier 2 succeeds."""
    _patch_db(monkeypatch, email_config=_config_smtp())
    _FakeSMTP.instances.clear()

    monkeypatch.setattr("smtplib.SMTP_SSL", _FakeSMTP)
    monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)

    res = send_email(
        org_id=ORG_ID, to_email=TO_EMAIL,
        subject="Test", body_html="<p>hi</p>",
    )
    assert res.success is True
    assert res.provider_used == "customer_smtp"
    assert res.fallback_chain == ["customer_smtp_success"]
    assert len(_FakeSMTP.instances) == 1
    assert _FakeSMTP.instances[0].host == "mail.example.com"


# ─── Token refresh path is exercised when access token is expired ───────────
def test_oauth_refresh_triggers_when_access_token_expired(monkeypatch):
    """Expired access token → refresh endpoint hit, then send proceeds."""
    cfg = _config_oauth_google(valid_token=False)
    # Force expired by setting the timestamp to the past
    cfg["oauth_token_expires_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat()
    _patch_db(monkeypatch, email_config=cfg)
    _patch_oauth_creds(monkeypatch)
    _FakeSMTP.instances.clear()

    refresh_called = {"n": 0}
    def fake_post(self, url, *args, **kwargs):  # noqa: ARG001
        if "oauth2.googleapis.com/token" in url:
            refresh_called["n"] += 1
            return httpx.Response(
                200,
                json={"access_token": "freshly-refreshed", "expires_in": 3600},
            )
        if "gmail.googleapis.com" in url:
            # Verify the refreshed token gets used downstream.
            auth = kwargs.get("headers", {}).get("Authorization", "")
            assert "freshly-refreshed" in auth, f"Authorization was {auth!r}"
            return httpx.Response(200, json={"id": "msg-after-refresh"})
        return httpx.Response(404, text=f"unmocked {url}")
    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr("smtplib.SMTP_SSL", _FakeSMTP)
    monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)

    res = send_email(
        org_id=ORG_ID, to_email=TO_EMAIL,
        subject="Test", body_html="<p>hi</p>",
    )
    assert res.success is True
    assert res.provider_used == "gmail_oauth"
    assert res.message_id == "msg-after-refresh"
    assert refresh_called["n"] == 1


# ─── Brevo creds missing while reaching tier 3 → raises with reason in chain ──
def test_brevo_creds_missing_at_last_tier_raises(monkeypatch):
    """No OAuth, no customer SMTP, and Brevo API key blank → tier 3 fails on
    config check and the overall call raises with chain populated."""
    _patch_db(monkeypatch, email_config=None)
    _patch_brevo_creds(monkeypatch, api_key="")
    _FakeSMTP.instances.clear()

    monkeypatch.setattr("smtplib.SMTP_SSL", _FakeSMTP)
    monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)

    with pytest.raises(RuntimeError) as exc:
        send_email(
            org_id=ORG_ID, to_email=TO_EMAIL,
            subject="Test", body_html="<p>hi</p>",
        )
    assert "Brevo API key not configured" in str(exc.value)
    assert "brevo_smtp_failed" in str(exc.value)


# ─── Smoke: MIME builder handles attachments + Cc + html→text fallback ──────
def test_mime_builder_attaches_pdf_and_includes_cc():
    msg = es._build_mime_message(
        sender_email="from@example.com",
        sender_name="Sender Name",
        to_email="to@example.com",
        subject="Subj",
        body_html="<p>Hello <b>world</b></p>",
        body_text=None,
        attachments=[Attachment(filename="kva.pdf", content=b"%PDF-1.4 fake")],
        cc=["cc@example.com"],
        bcc=[],
    )
    assert msg["Subject"] == "Subj"
    assert msg["From"] == "Sender Name <from@example.com>"
    assert msg["To"] == "to@example.com"
    assert msg["Cc"] == "cc@example.com"
    # Multipart with both text/plain (auto-generated from HTML) and text/html
    parts = [(p.get_content_type(), p.get_filename()) for p in msg.walk()]
    assert ("text/plain", None) in parts
    assert ("text/html", None) in parts
    assert ("application/pdf", "kva.pdf") in parts


# ─── The shipped fix: Brevo failures on 443 (non-2xx OR timeout) are HANDLED ──
@pytest.mark.parametrize("mode", ["http_401", "http_500", "timeout"])
def test_brevo_failure_modes_handled_not_unhandled_crash(monkeypatch, mode):
    """Regression guard for the exact bug this change fixes: a Brevo failure on
    the HTTP API — a non-2xx response (401 / 500) OR an httpx timeout/transport
    error — must be CAUGHT by send_email's broad ``except Exception``, recorded
    as ``brevo_smtp_failed``, and surface as the orderly
    ``RuntimeError('All email tiers failed…')``. A raw httpx error must NEVER
    escape send_email (the original failure mode was an unhandled timeout)."""
    _patch_db(monkeypatch, email_config=None)   # no OAuth, no customer SMTP → straight to Brevo
    _patch_brevo_creds(monkeypatch)             # Brevo API key present
    _FakeSMTP.instances.clear()

    def fake_post(self, url, *args, **kwargs):  # noqa: ARG001
        assert "api.brevo.com" in url
        if mode == "http_401":
            return httpx.Response(401, text="unauthorized")
        if mode == "http_500":
            return httpx.Response(500, text="brevo upstream error")
        raise httpx.ConnectTimeout("connect timed out")  # the production failure on 443
    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr("smtplib.SMTP_SSL", _FakeSMTP)
    monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)

    # RuntimeError (the handled summary) — NOT httpx.*. If the Tier-3 except were
    # narrow, the timeout case would escape as httpx.ConnectTimeout and fail here.
    with pytest.raises(RuntimeError) as exc:
        send_email(org_id=ORG_ID, to_email=TO_EMAIL, subject="T", body_html="<p>x</p>")
    msg = str(exc.value)
    assert "All email tiers failed" in msg
    assert "brevo_smtp_failed" in msg
    assert _FakeSMTP.instances == []  # Brevo is HTTP now — no SMTP session opened


# ─── Reply-To resolves to the CONNECTED sending account (not the org email) ──
def test_reply_to_defaults_to_connected_oauth_account(monkeypatch):
    """Gmail connected → Reply-To is the connected account (oauth_account_email),
    NOT the caller-supplied org email — so a recipient's reply reaches the
    tradesperson's own inbox."""
    _patch_db(monkeypatch, email_config=_config_oauth_google())
    _patch_oauth_creds(monkeypatch)
    captured: dict = {}
    monkeypatch.setattr(es, "_gmail_api_send", lambda **kw: captured.update(kw) or "msg-1")

    res = send_email(
        org_id=ORG_ID, to_email=TO_EMAIL, subject="S", body_html="<p>x</p>",
        reply_to="info@kikichat.de",  # caller's org email — must be overridden
    )
    assert res.provider_used == "gmail_oauth"
    assert captured["reply_to"] == "agrawalamber01@gmail.com"


def test_reply_to_uses_smtp_sender_when_only_smtp(monkeypatch):
    """SMTP-only org → Reply-To is the configured SMTP sender address."""
    _patch_db(monkeypatch, email_config=_config_smtp())
    captured: dict = {}
    monkeypatch.setattr(es, "_send_via_customer_smtp", lambda **kw: captured.update(kw) or "m")

    res = send_email(
        org_id=ORG_ID, to_email=TO_EMAIL, subject="S", body_html="<p>x</p>",
        reply_to="info@kikichat.de",
    )
    assert res.provider_used == "customer_smtp"
    assert captured["reply_to"] == "amber@example.com"


def test_reply_to_falls_back_to_caller_when_nothing_connected(monkeypatch):
    """No OAuth + no customer SMTP → Reply-To stays the caller-supplied org email."""
    _patch_db(monkeypatch, email_config=None)
    _patch_brevo_creds(monkeypatch)
    captured: dict = {}
    monkeypatch.setattr(es, "_send_via_brevo", lambda **kw: captured.update(kw) or "b")

    res = send_email(
        org_id=ORG_ID, to_email=TO_EMAIL, subject="S", body_html="<p>x</p>",
        reply_to="info@kikichat.de",
    )
    assert res.provider_used == "brevo_smtp"
    assert captured["reply_to"] == "info@kikichat.de"
