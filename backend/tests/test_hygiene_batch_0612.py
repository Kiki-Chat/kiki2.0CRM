"""Hygiene batch — the 5 deferred audit items, resolved 2026-06-12. Hermetic.

1. rerender_and_push_for_org supersede check (stale-push race).
3. apply_cases folds only UNGROUPED inquiries (no orphaned empty cases).
4. conversation_init always supplies voicemailMessage (inbound default).
5. move_inquiry_case rejects a target case of a DIFFERENT customer.
(Item 2, expiry-sweep starvation, is covered in test_reschedule_expiry.py.)
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api import deps
from app.api.routes import cases as cases_routes
from app.services import agent_config as ac
from app.services import conversation_init as ci


def _user(org_id="org-1", role="org_admin") -> deps.CurrentUser:
    return deps.CurrentUser(id="u1", email="a@b.de", org_id=org_id, role=role, full_name=None)


class _Chain:
    def __init__(self, db, table):
        self._db, self._t = db, table

    @property
    def not_(self):
        return self

    def insert(self, payload):
        self._db.inserts.append((self._t, payload))
        return self

    def update(self, payload):
        self._db.updates.append((self._t, payload))
        return self

    def __getattr__(self, _name):
        return lambda *a, **k: self

    def execute(self):
        r = MagicMock()
        r.data = self._db._next(self._t)
        r.count = len(r.data)
        return r


class _DB:
    def __init__(self, resp):
        self._resp = {k: list(v) for k, v in resp.items()}
        self.inserts: list = []
        self.updates: list = []

    def _next(self, t):
        q = self._resp.get(t)
        return q.pop(0) if q else []

    def table(self, n):
        return _Chain(self, n)


# ─── 1. stale-push supersede ──────────────────────────────────────────────────
def test_rerender_skips_when_superseded(monkeypatch):
    db = _DB({
        "agent_configs": [[{"prompt_manual_override": False}], [{"agent_sync_seq": 6}]],
        "organizations": [[{"name": "Org", "elevenlabs_agent_id": "agent-1"}]],
    })
    monkeypatch.setattr(ac, "get_service_client", lambda: db)
    monkeypatch.setattr(ac, "patch_agent_safely", lambda **k: pytest.fail("must not push a stale render"))

    out = ac.rerender_and_push_for_org(org_id="o1", endpoint_label="x", expected_seq=5)
    assert out == {"updated": False, "reason": "superseded"}


def test_rerender_pushes_when_seq_current(monkeypatch):
    pushed = {"n": 0}
    db = _DB({
        "agent_configs": [[{"prompt_manual_override": False}], [{"agent_sync_seq": 5}]],
        "organizations": [[{"name": "Org", "elevenlabs_agent_id": "agent-1"}]],
    })
    monkeypatch.setattr(ac, "get_service_client", lambda: db)
    monkeypatch.setattr(ac, "_fetch_org_identity", lambda o: {"name": "Org"})
    monkeypatch.setattr(ac, "render_prompt_for_org", lambda *a, **k: "PROMPT")
    monkeypatch.setattr(ac, "patch_agent_safely", lambda **k: pushed.__setitem__("n", 1))

    out = ac.rerender_and_push_for_org(org_id="o1", endpoint_label="x", expected_seq=5)
    assert out == {"updated": True} and pushed["n"] == 1


# ─── 3. apply_cases folds only ungrouped ──────────────────────────────────────
def test_apply_cases_skips_already_grouped_no_empty_case(monkeypatch):
    # The inquiry select returns [] (all members already have a case) → no case
    # is created, nothing is stamped.
    db = _DB({
        "customers": [[{"id": "cust-1"}]],   # validate_fk_in_org
        "inquiries": [[]],                   # case_id-null filter → none fresh
    })
    monkeypatch.setattr(cases_routes, "get_service_client", lambda: db)
    monkeypatch.setattr(cases_routes, "validate_fk_in_org", lambda *a, **k: None)

    payload = cases_routes.ApplyIn(
        customer_id="cust-1",
        groups=[cases_routes.GroupIn(label="X", members=["ANF-1", "ANF-2"])],
    )
    out = asyncio.run(cases_routes.apply_cases(payload, user=_user()))
    assert out["count"] == 0
    assert [t for (t, _p) in db.inserts if t == "cases"] == []  # no empty case minted


# ─── 4. voicemailMessage default on inbound ───────────────────────────────────
def test_conversation_init_sets_voicemail_default(monkeypatch):
    db = _DB({
        "customers": [[]],                       # unknown caller
        "organizations": [[{"name": "Fliesen Schmidt"}]],
        "agent_configs": [[]],                   # _pick_welcome_message
    })
    monkeypatch.setattr(ci, "get_service_client", lambda: db)
    out = ci.conversation_init("org-1", caller_id="+490000")
    vm = out["dynamic_variables"]["voicemailMessage"]
    assert "Fliesen Schmidt" in vm and vm.strip() != ""


# ─── 5. move_inquiry_case same-customer guard ─────────────────────────────────
def test_move_inquiry_case_rejects_other_customers_case(monkeypatch):
    db = _DB({
        "inquiries": [[{"id": "inq-1", "customer_id": "cust-A"}]],
        "cases": [[{"id": "case-B", "customer_id": "cust-B"}]],  # belongs to another customer
    })
    monkeypatch.setattr(cases_routes, "get_service_client", lambda: db)
    monkeypatch.setattr(cases_routes, "validate_fk_in_org", lambda *a, **k: None)

    payload = cases_routes.MoveIn(case_id="case-B")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(cases_routes.move_inquiry_case("inq-1", payload, user=_user()))
    assert exc.value.status_code == 422
    assert "anderen Kunden" in exc.value.detail


def test_move_inquiry_case_allows_same_customer(monkeypatch):
    db = _DB({
        "inquiries": [[{"id": "inq-1", "customer_id": "cust-A"}]],
        "cases": [[{"id": "case-A", "customer_id": "cust-A"}]],
    })
    monkeypatch.setattr(cases_routes, "get_service_client", lambda: db)
    monkeypatch.setattr(cases_routes, "validate_fk_in_org", lambda *a, **k: None)

    payload = cases_routes.MoveIn(case_id="case-A")
    out = asyncio.run(cases_routes.move_inquiry_case("inq-1", payload, user=_user()))
    assert out["success"] is True and out["case_id"] == "case-A"
