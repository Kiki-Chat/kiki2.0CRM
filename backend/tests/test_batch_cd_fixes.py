"""Batch C (emergency transfer) + Batch D (numbering integrity) — audit fixes
2026-06-11. Hermetic.

C1: _fetch_kz_config now selects forwarding_number, so the legacy emergency
    fallback in build_transfer_tool / render_emergency_block actually fires.
C2a: staff-transfer dedupe only applies against an emergency entry that was
     actually ADDED (disabled Notdienst + same number no longer drops the tool).
C2b: transfer destination numbers are validated at save time (422 on garbage).
D1: gen_case_number / gen_inquiry_number are MAX+1 (no re-issue after deletes);
    the DB unique indexes (migration 0065) back them.
D2: get_org_code re-derives on a unique-violation instead of returning the
    colliding code.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api.routes.kiki_zentrale import _validate_dialable
from app.services import common
from app.services.agent_config import build_transfer_tool


# ─── C1 + C2a: build_transfer_tool ────────────────────────────────────────────
def test_transfer_tool_falls_back_to_forwarding_number():
    tool = build_transfer_tool({
        "emergency_enabled": True,
        "emergency_number": "",
        "forwarding_number": "0151 234 5678",   # legacy field, now actually read
    })
    assert tool is not None
    dests = [t["transfer_destination"]["phone_number"] for t in tool["params"]["transfers"]]
    assert "+491512345678" in dests


def test_staff_transfer_survives_disabled_emergency_with_same_number():
    # Old bug: staff == emergency and Notdienst OFF → both entries dropped.
    tool = build_transfer_tool({
        "emergency_enabled": False,
        "emergency_number": "+49301234567",
        "incoming_forwarding_number": "+49301234567",
    })
    assert tool is not None
    transfers = tool["params"]["transfers"]
    assert len(transfers) == 1 and "MITARBEITER" in transfers[0]["condition"]


def test_staff_deduped_when_emergency_active_same_number():
    tool = build_transfer_tool({
        "emergency_enabled": True,
        "emergency_number": "+49301234567",
        "incoming_forwarding_number": "+49301234567",
    })
    transfers = tool["params"]["transfers"]
    assert len(transfers) == 1 and "NOTDIENST" in transfers[0]["condition"]


# ─── C2b: dialable validation at save ─────────────────────────────────────────
@pytest.mark.parametrize("ok", ["+49 151 2345678", "0151-2345678", "+1 (555) 123-4567", "", None, "  "])
def test_validate_dialable_accepts_real_numbers_and_blank(ok):
    _validate_dialable(ok, "Test")  # must not raise


@pytest.mark.parametrize("bad", ["abc", "+49abc123", "12345", "+12", "00 hello", "151234"])
def test_validate_dialable_rejects_garbage(bad):
    with pytest.raises(HTTPException) as exc:
        _validate_dialable(bad, "Notdienst-Nummer")
    assert exc.value.status_code == 422
    assert "Notdienst-Nummer" in exc.value.detail


# ─── fakes for D ──────────────────────────────────────────────────────────────
class _Chain:
    def __init__(self, db, table):
        self._db, self._t = db, table

    @property
    def not_(self):
        return self

    def update(self, payload):
        self._db.updates.append((self._t, payload))
        if self._db.raise_on_update > 0:
            self._db.raise_on_update -= 1
            raise RuntimeError("duplicate key value violates unique constraint")
        return self

    def __getattr__(self, _name):
        return lambda *a, **k: self

    def execute(self):
        r = MagicMock()
        r.data = self._db._next(self._t)
        r.count = self._db.counts.pop(0) if self._db.counts else 0
        return r


class _DB:
    def __init__(self, resp, counts=None, raise_on_update=0):
        self._resp = {k: list(v) for k, v in resp.items()}
        self.counts = list(counts or [])
        self.updates: list = []
        self.raise_on_update = raise_on_update

    def _next(self, t):
        q = self._resp.get(t)
        return q.pop(0) if q else []

    def table(self, n):
        return _Chain(self, n)


# ─── D2: get_org_code retry-on-conflict ───────────────────────────────────────
def test_get_org_code_rederives_on_unique_violation():
    db = _DB(
        {"organizations": [[{"id": "o1", "code": None}], [], []]},
        counts=[0, 4, 5],       # row-select (unused), then K05 collides, re-count → K06
        raise_on_update=1,      # first UPDATE raises (sibling won the race)
    )
    code = common.get_org_code(db, "o1")
    assert code == "K06"        # NOT the colliding K05
    assert len(db.updates) == 2


def test_get_org_code_returns_stored_code_fast_path():
    db = _DB({"organizations": [[{"id": "o1", "code": "K03"}]]})
    assert common.get_org_code(db, "o1") == "K03"
    assert db.updates == []


# ─── D1: MAX+1 generators (no re-issue after deletes) ─────────────────────────
def _year():
    return common.now_berlin().year


def test_gen_case_number_max_plus_one_skips_deleted_gap(monkeypatch):
    # Cases (Vorgänge) are numbered VG-{token}-NNNN over the cases table. 5 existed,
    # #3 deleted → 4 rows remain, highest suffix 0005.
    db = _DB({
        "cases": [[{"number": "VG-KC007-0005"}, {"number": "VG-KC007-0004"}]],
        "organizations": [[{"id": "o1", "code": "K01", "case_prefix": "KC007"}]],
    })
    assert common.gen_case_number(db, "o1") == "VG-KC007-0006"  # COUNT+1 would re-issue 0005


def test_gen_inquiry_number_max_plus_one(monkeypatch):
    db = _DB({
        "inquiries": [[{"number": "ANF-KC007-0012"}]],
        "organizations": [[{"id": "o1", "code": "K01", "case_prefix": "KC007"}]],
    })
    assert common.gen_inquiry_number(db, "o1") == "ANF-KC007-0013"


def test_gen_case_number_first(monkeypatch):
    db = _DB({
        "cases": [[]],
        "organizations": [[{"id": "o1", "code": "K02", "case_prefix": "KC007"}]],
    })
    assert common.gen_case_number(db, "o1") == "VG-KC007-0001"
