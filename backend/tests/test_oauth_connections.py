"""P3 — OAuth connection/token foundation (provider-agnostic).

Hermetic (no real provider traffic; httpx + DB faked):
  * oauth_tokens: encrypted storage, list_connections leak-check, and
    get_valid_access_token refresh logic (valid → no-op, expired → refresh +
    persist, missing connection / missing refresh token → raise).
  * _refresh_access_token posts grant_type=refresh_token.
  * provider registry: Calendly present; authorize URL building (scope present
    for Google, omitted for Calendly).
  * persistence: Google writes oauth_connections + mirrors email_configs;
    Calendly writes oauth_connections only.
  * disconnect clears the email_configs mirror only for email providers.
  * Calendly userinfo nesting unwrap; signed-state round-trip + guards.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api import deps
from app.api.routes import oauth as oauth_routes
from app.core.config import settings as cfg
from app.core.crypto import decrypt
from app.services import oauth_tokens
from app.services.oauth_providers import PROVIDERS
from app.services.oauth_tokens import OAuthTokenError


# ─── fakes ───────────────────────────────────────────────────────────────────
class _TokChain:
    def __init__(self, table, db):
        self.table = table
        self.db = db
        self.filters: dict = {}
        self._op = None
        self._payload = None

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def limit(self, *a, **k):
        return self

    def upsert(self, row, on_conflict=None):
        self._op = "upsert"
        self._payload = row
        self.db.upserts.append((self.table, row, on_conflict))
        return self

    def delete(self):
        self._op = "delete"
        return self

    def execute(self):
        res = MagicMock()
        if self._op == "upsert":
            res.data = [self._payload]
        else:
            res.data = self.db.match(self.table, self.filters)
        return res


class _TokDB:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.upserts: list = []

    def match(self, table, filters):
        return [
            r
            for r in self.rows.get(table, [])
            if all(r.get(k) == v for k, v in filters.items())
        ]

    def table(self, name):
        return _TokChain(name, self)


class _RecClient:
    """Records email_configs upserts/updates for the oauth route tests."""

    def __init__(self):
        self.upserts: list = []
        self.updates: list = []

    def table(self, name):
        outer = self

        class _C:
            def __init__(self):
                self.name = name
                self._u = None

            def upsert(self, row, on_conflict=None):
                outer.upserts.append((name, row, on_conflict))
                return self

            def update(self, row):
                self._u = row
                return self

            def eq(self, *a, **k):
                return self

            def execute(self):
                if self._u is not None:
                    outer.updates.append((name, self._u))
                r = MagicMock()
                r.data = []
                return r

        return _C()


def _user(org_id="org-1"):
    return deps.CurrentUser(
        id="u1", email="a@b.de", org_id=org_id, role="org_admin", full_name=None
    )


_NOW = datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc)


# ─── oauth_tokens: storage + refresh ─────────────────────────────────────────
def test_upsert_connection_encrypts_tokens(monkeypatch):
    db = _TokDB()
    monkeypatch.setattr(oauth_tokens, "get_service_client", lambda: db)
    oauth_tokens.upsert_connection(
        org_id="org-1",
        provider="google",
        access_token="ACCESS-PLAIN",
        refresh_token="REFRESH-PLAIN",
        expires_at=None,
        account_email="x@y.de",
        scope="calendar",
    )
    _, row, on_conflict = db.upserts[0]
    assert on_conflict == "org_id,provider"
    assert row["access_token_encrypted"] != "ACCESS-PLAIN"
    assert decrypt(row["access_token_encrypted"]) == "ACCESS-PLAIN"
    assert decrypt(row["refresh_token_encrypted"]) == "REFRESH-PLAIN"


def test_get_valid_access_token_returns_stored_when_fresh(monkeypatch):
    from app.core.crypto import encrypt

    row = {
        "org_id": "org-1",
        "provider": "google",
        "access_token_encrypted": encrypt("STILL-GOOD"),
        "refresh_token_encrypted": encrypt("RT"),
        "token_expires_at": (_NOW + timedelta(hours=1)).isoformat(),
    }
    db = _TokDB({"oauth_connections": [row]})
    monkeypatch.setattr(oauth_tokens, "get_service_client", lambda: db)
    no_refresh = MagicMock(side_effect=AssertionError("should not refresh"))
    monkeypatch.setattr(oauth_tokens, "_refresh_access_token", no_refresh)

    token = oauth_tokens.get_valid_access_token("org-1", "google", now=_NOW)
    assert token == "STILL-GOOD"


def test_get_valid_access_token_refreshes_when_expired(monkeypatch):
    from app.core.crypto import encrypt

    row = {
        "org_id": "org-1",
        "provider": "google",
        "access_token_encrypted": encrypt("OLD"),
        "refresh_token_encrypted": encrypt("RT"),
        "token_expires_at": (_NOW - timedelta(hours=1)).isoformat(),
    }
    db = _TokDB({"oauth_connections": [row]})
    monkeypatch.setattr(oauth_tokens, "get_service_client", lambda: db)
    monkeypatch.setattr(
        oauth_tokens,
        "_refresh_access_token",
        lambda provider, refresh: {"access_token": "NEW", "expires_in": 3600},
    )

    token = oauth_tokens.get_valid_access_token("org-1", "google", now=_NOW)
    assert token == "NEW"
    # Persisted the refreshed token; no new refresh token => key not written.
    _, persisted, _ = db.upserts[-1]
    assert decrypt(persisted["access_token_encrypted"]) == "NEW"
    assert "refresh_token_encrypted" not in persisted


def test_get_valid_access_token_no_connection_raises(monkeypatch):
    monkeypatch.setattr(oauth_tokens, "get_service_client", lambda: _TokDB())
    with pytest.raises(OAuthTokenError):
        oauth_tokens.get_valid_access_token("org-1", "google", now=_NOW)


def test_get_valid_access_token_no_refresh_token_raises(monkeypatch):
    from app.core.crypto import encrypt

    row = {
        "org_id": "org-1",
        "provider": "google",
        "access_token_encrypted": encrypt("OLD"),
        "refresh_token_encrypted": None,
        "token_expires_at": (_NOW - timedelta(hours=1)).isoformat(),
    }
    monkeypatch.setattr(
        oauth_tokens, "get_service_client", lambda: _TokDB({"oauth_connections": [row]})
    )
    with pytest.raises(OAuthTokenError):
        oauth_tokens.get_valid_access_token("org-1", "google", now=_NOW)


def test_list_connections_never_leaks_tokens(monkeypatch):
    from app.core.crypto import encrypt

    rows = [
        {
            "org_id": "org-1",
            "provider": "google",
            "account_email": "g@x.de",
            "token_expires_at": None,
            "access_token_encrypted": encrypt("SECRET"),
            "refresh_token_encrypted": encrypt("SECRET2"),
        }
    ]
    monkeypatch.setattr(
        oauth_tokens, "get_service_client", lambda: _TokDB({"oauth_connections": rows})
    )
    out = oauth_tokens.list_connections("org-1")
    assert out == [
        {
            "provider": "google",
            "connected": True,
            "account_email": "g@x.de",
            "token_expires_at": None,
        }
    ]
    assert "access_token_encrypted" not in out[0]


def test_refresh_access_token_posts_grant_type(monkeypatch):
    monkeypatch.setattr(cfg, "google_client_id", "gid")
    monkeypatch.setattr(cfg, "google_client_secret", "gsec")
    captured: dict = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"access_token": "AT", "expires_in": 3600}

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, data=None, headers=None):
            captured["url"] = url
            captured["data"] = data
            return _Resp()

    monkeypatch.setattr(oauth_tokens.httpx, "Client", lambda **kw: _Client())
    out = oauth_tokens._refresh_access_token("google", "RT")
    assert out["access_token"] == "AT"
    assert captured["data"]["grant_type"] == "refresh_token"
    assert captured["data"]["refresh_token"] == "RT"
    assert captured["data"]["client_id"] == "gid"


# ─── provider registry + authorize ───────────────────────────────────────────
def test_calendly_registered():
    assert "calendly" in PROVIDERS
    assert PROVIDERS["calendly"]["token_url"] == "https://auth.calendly.com/oauth/token"
    assert PROVIDERS["calendly"].get("calendar_only") is True


def test_authorize_google_includes_calendar_scope(monkeypatch):
    monkeypatch.setattr(cfg, "google_client_id", "gid")
    monkeypatch.setattr(cfg, "google_client_secret", "gsec")
    out = asyncio.run(oauth_routes.authorize("google", user=_user()))
    url = out["url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "calendar" in url
    assert "state=" in url


def test_authorize_calendly_omits_scope_param(monkeypatch):
    monkeypatch.setattr(cfg, "calendly_client_id", "cid")
    monkeypatch.setattr(cfg, "calendly_client_secret", "csec")
    out = asyncio.run(oauth_routes.authorize("calendly", user=_user()))
    url = out["url"]
    assert url.startswith("https://auth.calendly.com/oauth/authorize?")
    assert "scope=" not in url  # Calendly has no scope list


def test_authorize_unconfigured_provider_503(monkeypatch):
    monkeypatch.setattr(cfg, "google_client_id", "")
    monkeypatch.setattr(cfg, "google_client_secret", "")
    with pytest.raises(HTTPException) as e:
        asyncio.run(oauth_routes.authorize("google", user=_user()))
    assert e.value.status_code == 503


# ─── persistence: canonical store + email mirror ────────────────────────────
def test_persist_tokens_google_writes_both_stores(monkeypatch):
    up = MagicMock()
    monkeypatch.setattr(oauth_routes.oauth_tokens, "upsert_connection", up)
    rec = _RecClient()
    monkeypatch.setattr(oauth_routes, "get_service_client", lambda: rec)

    oauth_routes._persist_tokens(
        org_id="org-1",
        provider="google",
        refresh_token="RT",
        access_token="AT",
        expires_at=None,
        account_email="g@x.de",
        scope="calendar",
    )
    up.assert_called_once()
    assert any(t == "email_configs" for (t, _r, _c) in rec.upserts)


def test_persist_tokens_calendly_writes_canonical_only(monkeypatch):
    up = MagicMock()
    monkeypatch.setattr(oauth_routes.oauth_tokens, "upsert_connection", up)
    rec = _RecClient()
    monkeypatch.setattr(oauth_routes, "get_service_client", lambda: rec)

    oauth_routes._persist_tokens(
        org_id="org-1",
        provider="calendly",
        refresh_token="RT",
        access_token="AT",
        expires_at=None,
        account_email="c@x.de",
    )
    up.assert_called_once()
    assert rec.upserts == []  # no email_configs mirror for calendar-only provider


def test_disconnect_google_clears_email_mirror(monkeypatch):
    monkeypatch.setattr(
        oauth_routes.oauth_tokens, "delete_connection", lambda o, p: 1
    )
    rec = _RecClient()
    monkeypatch.setattr(oauth_routes, "get_service_client", lambda: rec)
    out = asyncio.run(oauth_routes.disconnect("google", user=_user()))
    assert out["success"] is True
    assert any(t == "email_configs" for (t, _u) in rec.updates)


def test_disconnect_calendly_skips_email_mirror(monkeypatch):
    monkeypatch.setattr(
        oauth_routes.oauth_tokens, "delete_connection", lambda o, p: 1
    )
    rec = _RecClient()
    monkeypatch.setattr(oauth_routes, "get_service_client", lambda: rec)
    asyncio.run(oauth_routes.disconnect("calendly", user=_user()))
    assert rec.updates == []  # calendar-only: no email_configs touched


# ─── userinfo + state ────────────────────────────────────────────────────────
def test_fetch_userinfo_unwraps_calendly_resource(monkeypatch):
    class _Resp:
        status_code = 200

        def json(self):
            return {"resource": {"email": "user@calendly", "name": "U"}}

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None):
            return _Resp()

    monkeypatch.setattr(oauth_routes.httpx, "Client", lambda **kw: _Client())
    email = oauth_routes._fetch_userinfo_email(PROVIDERS["calendly"], "tok")
    assert email == "user@calendly"


def test_state_token_roundtrip_and_guards():
    state = oauth_routes._make_state("user-9", "org-9", "google")
    uid, oid = oauth_routes._verify_state(state, "google")
    assert (uid, oid) == ("user-9", "org-9")

    # provider mismatch
    with pytest.raises(HTTPException):
        oauth_routes._verify_state(state, "microsoft")
    # expiry (negative max-age forces the expired branch)
    with pytest.raises(HTTPException):
        oauth_routes._verify_state(state, "google", max_age_sec=-1)
