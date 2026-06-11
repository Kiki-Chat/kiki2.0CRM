"""Tester-reported fixes, 2026-06-11 batch. Hermetic.

1. Editing a customer's phone/email to another customer's → 409 (create already
   blocked; update slipped through).
2. A KNOWN customer (exact-name match) giving a different number on a call gets
   it attached as phone2 instead of becoming a duplicate row.
3. Pre-dial liveness re-check: an appointment cancelled after a call was
   selected/claimed must not be dialed (occasion-aware).
4. Confirm requires a concrete scheduled_at (in addition to the employee guard).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api import deps
from app.api.routes import appointments as appt_routes
from app.api.routes import customers as cust_routes
from app.schemas.admin import CustomerUpsert
from app.services import customers as cust_service
from app.services import outbound_dispatch


def _org_user(org_id="org-1") -> deps.CurrentUser:
    return deps.CurrentUser(
        id="u1", email="a@b.de", org_id=org_id, role="org_admin", full_name=None
    )


class _Chain:
    def __init__(self, db, table):
        self._db, self._t = db, table

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


# ─── 1. duplicate-phone guard on customer EDIT ────────────────────────────────
def test_update_customer_409_when_phone_belongs_to_another(monkeypatch):
    db = _DB({"customers": [[{"id": "me", "full_name": "Ich"}]]})
    monkeypatch.setattr(cust_routes, "get_service_client", lambda: db)
    monkeypatch.setattr(
        cust_routes, "find_existing_customer",
        lambda *a, **k: {"id": "other", "customer_number": "KI-000002"},
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(cust_routes.update_customer(
            "me", CustomerUpsert(phone="+4915511111111"), user=_org_user()
        ))
    assert exc.value.status_code == 409
    assert "KI-000002" in exc.value.detail


def test_update_customer_own_number_is_not_a_duplicate(monkeypatch):
    """Re-saving a customer with their OWN number must not 409 (the dedup hit is
    the row being edited itself)."""
    me = {"id": "me", "full_name": "Ich"}
    db = _DB({"customers": [[me], [{**me, "phone": "+4915511111111"}]]})
    monkeypatch.setattr(cust_routes, "get_service_client", lambda: db)
    monkeypatch.setattr(
        cust_routes, "find_existing_customer", lambda *a, **k: {"id": "me"}
    )
    out = asyncio.run(cust_routes.update_customer(
        "me", CustomerUpsert(phone="+4915511111111"), user=_org_user()
    ))
    assert out["id"] == "me"
    assert db.updates  # the update went through


# ─── 2. known customer + new number → phone2, not a duplicate row ─────────────
def test_get_or_create_attaches_new_number_as_phone2(monkeypatch):
    db = _DB({"customers": [
        [{"id": "c1", "full_name": "Govind Yadav", "phone": "+4915511357330",
          "phone2": None, "customer_number": "KD-1"}],
    ]})
    monkeypatch.setattr(cust_service, "get_service_client", lambda: db)
    monkeypatch.setattr(cust_service, "find_existing_customer", lambda *a, **k: None)

    out = cust_service.get_or_create_customer(
        "org-1", phone="0155 222 333 44", name="Govind Yadav"
    )
    assert out["id"] == "c1"                      # reused, NOT a new row
    assert db.inserts == []                       # nothing created
    assert db.updates and db.updates[0][1]["phone2"] == "+4915522233344"


def test_get_or_create_ambiguous_name_still_creates(monkeypatch):
    """Two same-name customers → never guess-merge; create as before."""
    db = _DB({"customers": [
        [{"id": "c1", "full_name": "Max"}, {"id": "c2", "full_name": "Max"}],
        [{"id": "c3", "full_name": "Max", "phone": "+4915599999999"}],  # insert result
    ]})
    monkeypatch.setattr(cust_service, "get_service_client", lambda: db)
    monkeypatch.setattr(cust_service, "find_existing_customer", lambda *a, **k: None)
    monkeypatch.setattr(cust_service, "gen_customer_number", lambda c, o: "KD-9")

    out = cust_service.get_or_create_customer("org-1", phone="+4915599999999", name="Max")
    assert db.inserts and db.inserts[0][0] == "customers"
    assert out is not None


# ─── 3. pre-dial liveness re-check ────────────────────────────────────────────
def _spec(key="appointment_reminder"):
    return SimpleNamespace(key=key, referenz_typ="Termin", to_number_of=None)


def test_dispatch_skips_cancelled_appointment(monkeypatch):
    db = _DB({"appointments": [[{"status": "cancelled"}]]})
    out = outbound_dispatch._dispatch_one(
        db, org={}, org_id="org-1", spec=_spec(), record={"id": "a", "customer_id": "c"},
        customer={"id": "c", "phone": "+49170"}, inquiry_id=None, cycle_no=1,
        to_number_override=None, dry_run=False, now=datetime.now(timezone.utc),
    )
    assert out == {"skipped": "record_inactive", "referenz_id": "a", "status": "cancelled"}


def test_dispatch_cancellation_call_requires_cancelled_state(monkeypatch):
    """The cancellation occasion is the inverse: it must NOT announce a
    cancellation for an appointment that is still pending/confirmed."""
    db = _DB({"appointments": [[{"status": "pending"}]]})
    out = outbound_dispatch._dispatch_one(
        db, org={}, org_id="org-1", spec=_spec("appointment_cancellation"),
        record={"id": "a", "customer_id": "c"}, customer={"id": "c", "phone": "+49170"},
        inquiry_id=None, cycle_no=1, to_number_override=None, dry_run=False,
        now=datetime.now(timezone.utc),
    )
    assert out["skipped"] == "record_inactive" and out["status"] == "pending"


# ─── 4. confirm requires scheduled_at ─────────────────────────────────────────
def test_confirm_409_when_no_scheduled_time(monkeypatch):
    pending = {"id": "a", "org_id": "org-1", "status": "pending",
               "assigned_employee_id": "emp-1", "scheduled_at": None}
    db = _DB({"appointments": [[pending]]})
    monkeypatch.setattr(appt_routes, "get_service_client", lambda: db)
    monkeypatch.setattr(appt_routes, "notify_appointment_outcome", lambda *a, **k: {})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(appt_routes.confirm_appointment("a", user=_org_user()))
    assert exc.value.status_code == 409
    assert "Zeitpunkt" in exc.value.detail
