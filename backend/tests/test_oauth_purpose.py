"""Per-purpose OAuth linkage (email vs calendar are independent axes).

Hermetic (no DB / no provider traffic): purpose-link storage mechanism, calendar
provider resolution, best-effort revoke, the purpose-scoped disconnect with
revoke-ONLY-on-last-purpose, and the 'use the same account' link path.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api import deps
from app.api.routes import oauth as oauth_routes
from app.services import oauth_tokens


def _user(org_id="org-1"):
    return deps.CurrentUser(
        id="u1", email="a@b.de", org_id=org_id, role="org_admin", full_name=None
    )


# ─── fake supabase client (records ops; select/eq/neq/limit/order/upsert/delete/update) ──
class _Chain:
    def __init__(self, table, db):
        self.table, self.db, self.filters, self._op, self._payload = table, db, {}, None, None

    def select(self, *a, **k):
        return self

    def eq(self, c, v):
        self.filters[c] = v
        return self

    def neq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def upsert(self, row, on_conflict=None):
        self._op, self._payload = "upsert", row
        self.db.ops.append(("upsert", self.table, row, on_conflict))
        return self

    def update(self, row):
        self._op, self._payload = "update", row
        self.db.ops.append(("update", self.table, row, None))
        return self

    def delete(self):
        self._op = "delete"
        return self

    def execute(self):
        res = MagicMock()
        if self._op == "upsert":
            res.data = [self._payload]
        elif self._op == "delete":
            res.data = self.db.match(self.table, self.filters)
        elif self._op == "update":
            res.data = []
        else:
            res.data = self.db.match(self.table, self.filters)
        return res


class _DB:
    def __init__(self, rows=None):
        self.rows, self.ops = rows or {}, []

    def match(self, table, filters):
        return [
            r for r in self.rows.get(table, [])
            if all(r.get(k) == v for k, v in filters.items())
        ]

    def table(self, name):
        return _Chain(name, self)


def _email_ops(db):
    return [op for op in db.ops if op[1] == "email_configs"]


# ─── purpose-link storage + resolution ───────────────────────────────────────
def test_set_purpose_link_upserts_with_exclusive_conflict_key(monkeypatch):
    db = _DB()
    monkeypatch.setattr(oauth_tokens, "get_service_client", lambda: db)
    oauth_tokens.set_purpose_link("org-1", "email", "google", "g@x.de")
    op, table, row, on_conflict = db.ops[0]
    # PK (org_id, purpose) → one provider per purpose (exclusivity is DB-enforced).
    assert (op, table, on_conflict) == ("upsert", "oauth_purpose_links", "org_id,purpose")
    assert row["purpose"] == "email" and row["provider"] == "google"


def test_calendar_provider_resolves_from_link(monkeypatch):
    db = _DB({"oauth_purpose_links": [
        {"org_id": "org-1", "purpose": "calendar", "provider": "calendly"},
    ]})
    monkeypatch.setattr(oauth_tokens, "get_service_client", lambda: db)
    assert oauth_tokens.calendar_provider("org-1") == "calendly"
    assert oauth_tokens.calendar_provider("org-2") is None  # unlinked


def test_purposes_for_provider(monkeypatch):
    db = _DB({"oauth_purpose_links": [
        {"org_id": "org-1", "purpose": "email", "provider": "google"},
        {"org_id": "org-1", "purpose": "calendar", "provider": "google"},
    ]})
    monkeypatch.setattr(oauth_tokens, "get_service_client", lambda: db)
    assert set(oauth_tokens.purposes_for_provider("org-1", "google")) == {"email", "calendar"}
    assert oauth_tokens.purposes_for_provider("org-1", "calendly") == []


# ─── revoke (best-effort) ─────────────────────────────────────────────────────
def test_revoke_grant_posts_refresh_token_to_google_revoke(monkeypatch):
    from app.core.crypto import encrypt
    conn = {"refresh_token_encrypted": encrypt("RT"), "access_token_encrypted": encrypt("AT")}
    monkeypatch.setattr(oauth_tokens, "get_connection", lambda o, p: conn)
    captured: dict = {}

    class _Resp:
        status_code = 200

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, data=None, headers=None):
            captured["url"] = url
            captured["token"] = (data or {}).get("token")
            return _Resp()

    monkeypatch.setattr(oauth_tokens.httpx, "Client", lambda **kw: _Client())
    assert oauth_tokens.revoke_grant("org-1", "google") is True
    assert captured["url"] == "https://oauth2.googleapis.com/revoke"
    assert captured["token"] == "RT"  # revoking the refresh token kills the whole grant


def test_revoke_grant_noop_when_provider_has_no_revoke_url(monkeypatch):
    from app.core.crypto import encrypt
    monkeypatch.setattr(
        oauth_tokens, "get_connection", lambda o, p: {"refresh_token_encrypted": encrypt("RT")}
    )

    def _boom(**kw):
        raise AssertionError("must not POST when there is no revoke endpoint")

    monkeypatch.setattr(oauth_tokens.httpx, "Client", _boom)
    assert oauth_tokens.revoke_grant("org-1", "microsoft") is False  # MS has no revoke_url


# ─── _persist_grant_and_link: purpose-scoped email mirror ────────────────────
def test_persist_email_google_mirrors_email_configs(monkeypatch):
    monkeypatch.setattr(oauth_routes.oauth_tokens, "upsert_connection", MagicMock())
    monkeypatch.setattr(oauth_routes.oauth_tokens, "set_purpose_link", MagicMock())
    db = _DB()
    monkeypatch.setattr(oauth_routes, "get_service_client", lambda: db)
    oauth_routes._persist_grant_and_link(
        org_id="org-1", provider="google", purpose="email",
        refresh_token="RT", access_token="AT", expires_at=None, account_email="g@x.de",
    )
    assert _email_ops(db)  # email purpose on google → mirror written
    oauth_routes.oauth_tokens.set_purpose_link.assert_called_once()


def test_persist_calendar_google_does_not_mirror_email(monkeypatch):
    monkeypatch.setattr(oauth_routes.oauth_tokens, "upsert_connection", MagicMock())
    monkeypatch.setattr(oauth_routes.oauth_tokens, "set_purpose_link", MagicMock())
    db = _DB()
    monkeypatch.setattr(oauth_routes, "get_service_client", lambda: db)
    oauth_routes._persist_grant_and_link(
        org_id="org-1", provider="google", purpose="calendar",
        refresh_token="RT", access_token="AT", expires_at=None, account_email="g@x.de",
    )
    assert not _email_ops(db)  # a CALENDAR connect must never make google the email sender


# ─── disconnect: revoke ONLY on the last purpose ─────────────────────────────
def test_disconnect_calendar_keeps_grant_shared_with_email(monkeypatch):
    """Google serves BOTH email + calendar; disconnecting calendar drops only the
    calendar link — the grant (and email) stay, NOTHING is revoked."""
    monkeypatch.setattr(oauth_routes.oauth_tokens, "delete_purpose_link", lambda o, pur: "google")
    monkeypatch.setattr(oauth_routes.oauth_tokens, "purposes_for_provider", lambda o, p: ["email"])
    revoke, delete = MagicMock(), MagicMock()
    monkeypatch.setattr(oauth_routes.oauth_tokens, "revoke_grant", revoke)
    monkeypatch.setattr(oauth_routes.oauth_tokens, "delete_connection", delete)
    db = _DB()
    monkeypatch.setattr(oauth_routes, "get_service_client", lambda: db)
    monkeypatch.setattr(oauth_routes.calendar_sync, "purge_imported_events", MagicMock())

    out = asyncio.run(oauth_routes.disconnect(purpose="calendar", user=_user()))
    assert out["grant_kept"] is True and out["grant_revoked"] is False
    revoke.assert_not_called()
    delete.assert_not_called()
    assert not _email_ops(db)  # calendar disconnect never touches the email mirror


def test_disconnect_email_as_last_purpose_revokes_and_deletes(monkeypatch):
    """Google serves ONLY email; disconnecting email revokes + deletes the grant
    and clears the email mirror."""
    monkeypatch.setattr(oauth_routes.oauth_tokens, "delete_purpose_link", lambda o, pur: "google")
    monkeypatch.setattr(oauth_routes.oauth_tokens, "purposes_for_provider", lambda o, p: [])
    revoke, delete = MagicMock(return_value=True), MagicMock(return_value=1)
    monkeypatch.setattr(oauth_routes.oauth_tokens, "revoke_grant", revoke)
    monkeypatch.setattr(oauth_routes.oauth_tokens, "delete_connection", delete)
    db = _DB()
    monkeypatch.setattr(oauth_routes, "get_service_client", lambda: db)

    out = asyncio.run(oauth_routes.disconnect(purpose="email", user=_user()))
    assert out["grant_kept"] is False and out["grant_revoked"] is True
    revoke.assert_called_once_with("org-1", "google")
    delete.assert_called_once_with("org-1", "google")
    assert _email_ops(db)  # email mirror cleared


def test_disconnect_nothing_linked_is_noop(monkeypatch):
    monkeypatch.setattr(oauth_routes.oauth_tokens, "delete_purpose_link", lambda o, pur: None)
    out = asyncio.run(oauth_routes.disconnect(purpose="calendar", user=_user()))
    assert out.get("nothing_linked") is True


# ─── link ("use the same account") ───────────────────────────────────────────
def test_link_reuses_existing_grant_for_calendar_no_email_mirror(monkeypatch):
    monkeypatch.setattr(
        oauth_routes.oauth_tokens, "get_connection",
        lambda o, p: {"account_email": "g@x.de", "refresh_token_encrypted": "enc"},
    )
    setlink = MagicMock()
    monkeypatch.setattr(oauth_routes.oauth_tokens, "set_purpose_link", setlink)
    sync = MagicMock()
    monkeypatch.setattr(oauth_routes.calendar_sync, "pull_google_events", sync)
    db = _DB()
    monkeypatch.setattr(oauth_routes, "get_service_client", lambda: db)
    out = asyncio.run(oauth_routes.link_purpose("google", purpose="calendar", user=_user()))
    assert out["success"] and out["provider"] == "google"
    setlink.assert_called_once()
    assert not _email_ops(db)  # calendar reuse never mirrors email
    sync.assert_called_once_with("org-1")  # B3: reuse-link auto-syncs the calendar


def test_link_email_requires_existing_grant(monkeypatch):
    monkeypatch.setattr(oauth_routes.oauth_tokens, "set_purpose_link", MagicMock())
    monkeypatch.setattr(oauth_routes.oauth_tokens, "get_connection", lambda o, p: None)
    with pytest.raises(HTTPException) as e:
        asyncio.run(oauth_routes.link_purpose("google", purpose="email", user=_user()))
    assert e.value.status_code == 409


def test_link_rejects_provider_that_cannot_serve_purpose():
    with pytest.raises(HTTPException) as e:  # calendly cannot serve email
        asyncio.run(oauth_routes.link_purpose("calendly", purpose="email", user=_user()))
    assert e.value.status_code == 400


# ─── B3: auto-sync on calendar connect (no manual button at the connect point) ─
def test_auto_sync_calendar_pulls_for_google_calendar(monkeypatch):
    sync = MagicMock()
    monkeypatch.setattr(oauth_routes.calendar_sync, "pull_google_events", sync)
    oauth_routes._auto_sync_calendar("org-9", "google", "calendar")
    sync.assert_called_once_with("org-9")


def test_auto_sync_calendar_skips_email_and_non_google(monkeypatch):
    sync = MagicMock()
    monkeypatch.setattr(oauth_routes.calendar_sync, "pull_google_events", sync)
    oauth_routes._auto_sync_calendar("org-9", "google", "email")        # email purpose
    oauth_routes._auto_sync_calendar("org-9", "microsoft", "calendar")  # non-google
    sync.assert_not_called()


def test_auto_sync_calendar_is_best_effort(monkeypatch):
    def boom(_org):
        raise RuntimeError("google 500")
    monkeypatch.setattr(oauth_routes.calendar_sync, "pull_google_events", boom)
    # Must NOT raise — the grant is already persisted; the sync is best-effort.
    oauth_routes._auto_sync_calendar("org-9", "google", "calendar")


# ─── authorize purpose validation ────────────────────────────────────────────
def test_authorize_rejects_calendly_for_email(monkeypatch):
    from app.core.config import settings as cfg
    monkeypatch.setattr(cfg, "calendly_client_id", "cid")
    monkeypatch.setattr(cfg, "calendly_client_secret", "csec")
    with pytest.raises(HTTPException) as e:
        asyncio.run(oauth_routes.authorize("calendly", purpose="email", user=_user()))
    assert e.value.status_code == 400


# ─── Bug A: disconnecting calendar purges imported events; email never does ──
def test_disconnect_calendar_purges_imported_events(monkeypatch):
    monkeypatch.setattr(oauth_routes.oauth_tokens, "delete_purpose_link", lambda o, pur: "google")
    monkeypatch.setattr(oauth_routes.oauth_tokens, "purposes_for_provider", lambda o, p: [])
    monkeypatch.setattr(oauth_routes.oauth_tokens, "revoke_grant", lambda o, p: True)
    monkeypatch.setattr(oauth_routes.oauth_tokens, "delete_connection", lambda o, p: 1)
    purge = MagicMock(return_value=3)
    monkeypatch.setattr(oauth_routes.calendar_sync, "purge_imported_events", purge)
    monkeypatch.setattr(oauth_routes, "get_service_client", lambda: _DB())

    asyncio.run(oauth_routes.disconnect(purpose="calendar", user=_user()))
    purge.assert_called_once_with("org-1")


def test_disconnect_email_does_not_purge_calendar_events(monkeypatch):
    monkeypatch.setattr(oauth_routes.oauth_tokens, "delete_purpose_link", lambda o, pur: "google")
    monkeypatch.setattr(oauth_routes.oauth_tokens, "purposes_for_provider", lambda o, p: ["calendar"])
    monkeypatch.setattr(oauth_routes.oauth_tokens, "revoke_grant", lambda o, p: True)
    monkeypatch.setattr(oauth_routes.oauth_tokens, "delete_connection", lambda o, p: 1)
    purge = MagicMock()
    monkeypatch.setattr(oauth_routes.calendar_sync, "purge_imported_events", purge)
    monkeypatch.setattr(oauth_routes, "get_service_client", lambda: _DB())

    asyncio.run(oauth_routes.disconnect(purpose="email", user=_user()))
    purge.assert_not_called()
