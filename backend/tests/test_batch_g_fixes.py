"""Batch G — config-divergence + copilot-session robustness (audit 2026-06-11).

G1: /verhalten runs the ElevenLabs patch BEFORE the DB write (EL failure ⇒
    nothing committed, no silent divergence).
G2: /leitfaden no_prices guard fires BEFORE any row write.
G5: copilot sessions — newest-200 reload, deterministic turn ordering, 404 on
    non-UUID ids, orphan compensation, audit conversation link.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api import deps
from app.api.routes import copilot as cp
from app.api.routes import kiki_zentrale as kz


def _admin(org_id="org-1") -> deps.CurrentUser:
    return deps.CurrentUser(
        id="u1", email="a@b.de", org_id=org_id, role="org_admin", full_name=None
    )


class _Chain:
    def __init__(self, db, table):
        self._db, self._t = db, table

    def insert(self, payload):
        self._db.inserts.append((self._t, payload))
        if self._t in self._db.insert_raises:
            raise RuntimeError("insert failed")
        return self

    def update(self, payload):
        self._db.updates.append((self._t, payload))
        return self

    def delete(self):
        self._db.deletes.append(self._t)
        return self

    def __getattr__(self, _name):
        return lambda *a, **k: self

    def execute(self):
        r = MagicMock()
        r.data = self._db._next(self._t)
        r.count = len(r.data)
        return r


class _DB:
    def __init__(self, resp, insert_raises=()):
        self._resp = {k: list(v) for k, v in resp.items()}
        self.inserts: list = []
        self.updates: list = []
        self.deletes: list = []
        self.insert_raises = set(insert_raises)

    def _next(self, t):
        q = self._resp.get(t)
        return q.pop(0) if q else []

    def table(self, n):
        return _Chain(self, n)


# ─── G1: verhalten EL-first ordering ──────────────────────────────────────────
def test_verhalten_el_failure_commits_nothing(monkeypatch):
    db = _DB({})
    monkeypatch.setattr(kz, "get_service_client", lambda: db)
    monkeypatch.setattr(kz.ea, "get_org_agent_id", lambda org: "agent-1")

    def _boom(**kw):
        raise RuntimeError("EL down")

    monkeypatch.setattr(kz.ea, "patch_agent_safely", _boom)
    monkeypatch.setattr(kz.ac, "begin_sync", lambda org, label: 1)

    payload = kz.VerhaltenUpdate(welcome_message="Hallo!", persona_name="Kiki")
    with pytest.raises(RuntimeError):
        asyncio.run(kz.update_verhalten(payload, MagicMock(), user=_admin()))
    # The DB write must NOT have happened — EL failed first.
    assert db.updates == [] and db.inserts == []


# ─── G2: leitfaden guard before writes ────────────────────────────────────────
def test_leitfaden_no_prices_writes_nothing(monkeypatch):
    items_rows = [
        {"id": "f1", "linked_setting": "price_info_enabled"},
        {"id": "f2", "linked_setting": None},
    ]
    db = _DB({
        "agent_required_fields": [items_rows],
        "catalog_items": [[]],          # no priced Artikel → guard fires
    })
    monkeypatch.setattr(kz, "get_service_client", lambda: db)
    monkeypatch.setattr(kz.ac, "begin_sync", lambda org, label: 1)

    payload = kz.LeitfadenSave(items=[
        kz.LeitfadenItem(id="f1", is_active=True),
        kz.LeitfadenItem(id="f2", is_active=True),
    ])
    with pytest.raises(HTTPException) as exc:
        asyncio.run(kz.save_leitfaden(payload, MagicMock(), user=_admin()))
    assert exc.value.status_code == 422
    # No half-applied save: zero row updates landed before the guard.
    assert db.updates == []


# ─── G5: copilot sessions ─────────────────────────────────────────────────────
def test_get_conversation_404_on_non_uuid(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(cp.get_conversation("abc", user=_admin()))
    assert exc.value.status_code == 404


def test_delete_conversation_404_on_non_uuid(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(cp.delete_conversation("not-a-uuid", user=_admin()))
    assert exc.value.status_code == 404


def test_get_conversation_returns_newest_200_in_chrono_order(monkeypatch):
    cid = "11111111-1111-1111-1111-111111111111"
    # DB returns newest-first (as the desc query would); endpoint must reverse.
    newest_first = [
        {"id": f"m{i}", "role": "user", "content": f"msg {i}", "tool_calls": None,
         "created_at": f"2026-06-12T10:00:{59 - i:02d}+00:00"}
        for i in range(3)
    ]
    db = _DB({
        "copilot_conversations": [[{"id": cid, "title": "T"}]],
        "copilot_messages": [newest_first],
    })
    monkeypatch.setattr(cp, "get_service_client", lambda: db)
    out = asyncio.run(cp.get_conversation(cid, user=_admin()))
    contents = [m["content"] for m in out["messages"]]
    assert contents == ["msg 2", "msg 1", "msg 0"]  # chronological for display
    assert out["truncated"] is False


def test_persist_turn_stamps_distinct_timestamps(monkeypatch):
    db = _DB({
        "copilot_conversations": [[{"id": "22222222-2222-2222-2222-222222222222"}]],
        "copilot_messages": [[]],
    })
    monkeypatch.setattr(cp, "get_service_client", lambda: db)
    cid = cp._persist_turn(_admin(), None, "Hallo", {"content": "Hi"})
    assert cid == "22222222-2222-2222-2222-222222222222"
    msg_inserts = [p for (t, p) in db.inserts if t == "copilot_messages"]
    assert len(msg_inserts) == 1
    user_row, asst_row = msg_inserts[0]
    assert user_row["created_at"] != asst_row["created_at"]  # deterministic order


def test_persist_turn_compensates_orphan_on_message_failure(monkeypatch):
    db = _DB(
        {"copilot_conversations": [[{"id": "33333333-3333-3333-3333-333333333333"}]]},
        insert_raises={"copilot_messages"},
    )
    monkeypatch.setattr(cp, "get_service_client", lambda: db)
    out = cp._persist_turn(_admin(), None, "Hallo", {"content": "Hi"})
    assert out is None                              # original (None) returned
    assert "copilot_conversations" in db.deletes    # empty thread cleaned up


def test_audit_carries_conversation_link(monkeypatch):
    db = _DB({})
    monkeypatch.setattr(cp, "get_service_client", lambda: db)
    cid = "44444444-4444-4444-4444-444444444444"
    cp._audit(_admin(), "create_invoice", {"x": 1}, {"ok": True}, conversation_id=cid)
    assert db.inserts and db.inserts[0][1]["conversation_id"] == cid


def test_audit_nulls_invalid_conversation_id(monkeypatch):
    db = _DB({})
    monkeypatch.setattr(cp, "get_service_client", lambda: db)
    cp._audit(_admin(), "create_invoice", {}, {"ok": True}, conversation_id="junk")
    assert db.inserts[0][1]["conversation_id"] is None
