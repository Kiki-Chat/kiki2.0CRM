"""Bug B regression: the test-mail recipient on the Brevo-FALLBACK path (nothing
connected) must be the REGISTERED USER's email (CurrentUser.email), not org.email.
The earlier fix only covered the OAuth/SMTP paths; this covers the fallback."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from app.api import deps
from app.api.routes import settings as sr


class _Res:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, data):
        self._data = data

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return _Res(self._data)


class _FakeClient:
    def __init__(self, org, ec_rows):
        self.org, self.ec_rows = org, ec_rows

    def table(self, name):
        if name == "organizations":
            return _Q([self.org])
        if name == "email_configs":
            return _Q(self.ec_rows)
        return _Q([])


def _capture_send(monkeypatch):
    captured: dict = {}

    def fake_send(**kw):
        captured.update(kw)
        r = MagicMock()
        r.provider_used = "brevo_smtp"
        r.fallback_chain = ["brevo_smtp_success"]
        return r

    monkeypatch.setattr(sr, "send_email", fake_send)
    return captured


def _user():
    return deps.CurrentUser(
        id="u1", email="admin@user.de", org_id="c4", role="org_admin", full_name=None
    )


def test_testmail_fallback_recipient_is_registered_user(monkeypatch):
    """Nothing connected (no email_configs row) → Brevo fallback → recipient is
    the logged-in user's email, NOT org.email."""
    captured = _capture_send(monkeypatch)
    monkeypatch.setattr(
        sr, "get_service_client",
        lambda: _FakeClient(org={"name": "Muster", "email": "info@kikichat.de"}, ec_rows=[]),
    )
    out = asyncio.run(sr.email_test(user=_user()))
    assert out["success"] is True
    assert captured["to_email"] == "admin@user.de"  # registered user, NOT info@kikichat.de


def test_testmail_recipient_prefers_connected_account(monkeypatch):
    """When OAuth is connected, the test still targets the connected inbox."""
    captured = _capture_send(monkeypatch)
    monkeypatch.setattr(
        sr, "get_service_client",
        lambda: _FakeClient(
            org={"name": "Muster", "email": "info@kikichat.de"},
            ec_rows=[{"oauth_account_email": "connected@gmail.com", "smtp_sender_email": None}],
        ),
    )
    out = asyncio.run(sr.email_test(user=_user()))
    assert captured["to_email"] == "connected@gmail.com"
