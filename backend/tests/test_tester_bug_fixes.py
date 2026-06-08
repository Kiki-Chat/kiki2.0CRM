"""Behavioral tests for the tester-reported bug fixes (2026-06-06 batch).

Exercises the ACTUAL fixed functions against a small fake Supabase client:
  * Bug 1 — employee create rejects a duplicate email (per org, non-deleted).
  * Bug 3 — calendar appointment list enriches customer name/phone/address.
  * Bug 2c — reschedule worklist card resolves a call_id (inquiry, else conv).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routes import actions as ax
from app.api.routes import appointments as ap
from app.api.routes import employees as emp
from app.schemas.admin import EmployeeCreate

ORG = "org-1"


# ─── minimal fake Supabase query builder ─────────────────────────────────────
class _Result:
    def __init__(self, data):
        self.data = data


class _Exec:
    def __init__(self, rows):
        self._rows = rows

    def eq(self, *a, **k):
        return self

    def execute(self):
        return _Result(self._rows)


class _Query:
    def __init__(self, rows):
        self._rows = [dict(r) for r in rows]

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._rows = [r for r in self._rows if str(r.get(col)) == str(val)]
        return self

    def neq(self, col, val):
        self._rows = [r for r in self._rows if str(r.get(col)) != str(val)]
        return self

    def in_(self, col, vals):
        s = {str(v) for v in vals}
        self._rows = [r for r in self._rows if str(r.get(col)) in s]
        return self

    def ilike(self, col, pat):
        p = pat.strip().lower()
        self._rows = [r for r in self._rows if (r.get(col) or "").strip().lower() == p]
        return self

    def gte(self, *a, **k):
        return self

    def lt(self, *a, **k):
        return self

    def lte(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    @property
    def not_(self):
        return self

    def is_(self, col, _val):
        # models `not_.is_(col, "null")` → keep rows where col is NOT null
        self._rows = [r for r in self._rows if r.get(col) is not None]
        return self

    def or_(self, *a, **k):
        return self  # OR is modelled by seeding matching rows

    def insert(self, row):
        rows = row if isinstance(row, list) else [row]
        return _Exec(rows)

    def update(self, *a, **k):
        return _Exec([])

    def execute(self):
        return _Result(self._rows)


class _FakeClient:
    def __init__(self, tables):
        self._tables = tables

    def table(self, name):
        return _Query(self._tables.get(name, []))


# ─── Bug 1 — duplicate employee email ────────────────────────────────────────
def _emp_client(monkeypatch, employees_rows):
    client = _FakeClient({"employees": employees_rows})
    monkeypatch.setattr(emp, "get_service_client", lambda: client)
    return client


def test_employee_duplicate_email_is_rejected(monkeypatch):
    _emp_client(monkeypatch, [{"org_id": ORG, "email": "dup@x.com", "deleted": False}])
    payload = EmployeeCreate(display_name="Neu", email="DUP@x.com", login_access=False)
    with pytest.raises(HTTPException) as exc:
        emp._create(ORG, payload)
    assert exc.value.status_code == 409


def test_employee_new_email_is_allowed(monkeypatch):
    _emp_client(monkeypatch, [{"org_id": ORG, "email": "other@x.com", "deleted": False}])
    payload = EmployeeCreate(display_name="Neu", email="fresh@x.com", login_access=False)
    created = emp._create(ORG, payload)
    assert created["email"] == "fresh@x.com"


def test_employee_deleted_email_can_be_reused(monkeypatch):
    # A soft-deleted employee must not block re-adding the same email.
    _emp_client(monkeypatch, [{"org_id": ORG, "email": "back@x.com", "deleted": True}])
    payload = EmployeeCreate(display_name="Wieder da", email="back@x.com", login_access=False)
    created = emp._create(ORG, payload)
    assert created["email"] == "back@x.com"


def test_employee_other_org_same_email_is_allowed(monkeypatch):
    _emp_client(monkeypatch, [{"org_id": "other-org", "email": "shared@x.com", "deleted": False}])
    payload = EmployeeCreate(display_name="Neu", email="shared@x.com", login_access=False)
    created = emp._create(ORG, payload)
    assert created["email"] == "shared@x.com"


# ─── Bug 3 — calendar enriches customer name/phone/address ───────────────────
def test_appointments_list_enriches_customer_contact(monkeypatch):
    client = _FakeClient(
        {
            "appointments": [
                {
                    "id": "a1", "org_id": ORG, "customer_id": "c1",
                    "assigned_employee_id": None, "scheduled_at": "2026-06-10T09:00:00Z",
                }
            ],
            "customers": [
                {
                    "id": "c1", "org_id": ORG, "full_name": "Max Mustermann",
                    "phone": "+4917012345",
                    "address": {"street": "Hauptstr 1", "zip": "48155", "city": "Münster"},
                }
            ],
        }
    )
    monkeypatch.setattr(ap, "get_service_client", lambda: client)
    out = ap._list(ORG, None, None)
    assert out[0]["customer_name"] == "Max Mustermann"
    assert out[0]["customer_phone"] == "+4917012345"
    assert out[0]["customer_address"] == "Hauptstr 1, 48155 Münster"


def test_appointments_list_private_appt_has_no_customer(monkeypatch):
    client = _FakeClient(
        {
            "appointments": [
                {"id": "a2", "org_id": ORG, "customer_id": None, "assigned_employee_id": None, "scheduled_at": "x"}
            ]
        }
    )
    monkeypatch.setattr(ap, "get_service_client", lambda: client)
    out = ap._list(ORG, None, None)
    assert out[0]["customer_name"] is None
    assert out[0]["customer_phone"] is None
    assert out[0]["customer_address"] is None


# ─── Bug 2c — reschedule worklist card resolves a call_id ────────────────────
def test_alt_time_proposal_resolves_call_id_via_inquiry():
    client = _FakeClient(
        {
            "appointments": [
                {
                    "id": "ap1", "org_id": ORG, "inquiry_id": "inq1", "customer_id": "c1", "title": "Termin",
                    "created_at": "t", "status": "confirmed", "source_conversation_id": None,
                    "alternative_proposed_at": None, "alternative_start_time": None,
                    "customer_proposed_at": "2026-06-06T10:00:00Z",
                    "customer_proposed_start_time": "2026-06-12T14:00:00Z",
                }
            ],
            "customers": [{"id": "c1", "org_id": ORG, "full_name": "Max"}],
            "inquiries": [{"id": "inq1", "org_id": ORG, "call_id": "call99"}],
            "calls": [],
        }
    )
    out = ax._alt_time_proposal(client, ORG)
    assert len(out) == 1
    assert out[0]["kind"] == "alt_time_proposal"
    assert out[0]["call_id"] == "call99"


def test_alt_time_proposal_resolves_call_id_via_conversation():
    client = _FakeClient(
        {
            "appointments": [
                {
                    "id": "ap2", "org_id": ORG, "inquiry_id": None, "customer_id": "c1", "title": "Termin",
                    "created_at": "t", "status": "confirmed", "source_conversation_id": "conv1",
                    "alternative_proposed_at": None, "alternative_start_time": None,
                    "customer_proposed_at": "2026-06-06T10:00:00Z",
                    "customer_proposed_start_time": "2026-06-12T14:00:00Z",
                }
            ],
            "customers": [{"id": "c1", "org_id": ORG, "full_name": "Max"}],
            "inquiries": [],
            "calls": [{"id": "call77", "org_id": ORG, "elevenlabs_conversation_id": "conv1"}],
        }
    )
    out = ax._alt_time_proposal(client, ORG)
    assert len(out) == 1
    assert out[0]["call_id"] == "call77"
