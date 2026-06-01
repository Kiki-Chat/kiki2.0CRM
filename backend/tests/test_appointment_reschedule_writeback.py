"""change_appointment ADDITIVE enhancement (migration 0037, stop-condition).

The agent's hk_changeAppointment now ALSO stamps the customer's requested slot
onto the matched appointment (customer_proposed_*) so a human can approve it in
one click — WITHOUT altering the existing appointment_change inquiry creation or
the tool's return contract (the purely-additive constraint Amber set).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from app.schemas.tools import ChangeAppointmentRequest
from app.services import appointments as appt_service


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
        # select / eq / in_ / gte / order / limit / ilike / ... → chainable no-ops
        return lambda *a, **k: self

    def execute(self):
        r = MagicMock()
        r.data = self._db._next(self._t)
        r.count = self._db.counts.get(self._t, 0)
        return r


class _DB:
    def __init__(self, resp, counts=None):
        self._resp = {k: list(v) for k, v in resp.items()}
        self.counts = counts or {}
        self.inserts: list = []
        self.updates: list = []

    def _next(self, t):
        q = self._resp.get(t)
        return q.pop(0) if q else []

    def table(self, n):
        return _Chain(self, n)


def test_change_appointment_stamps_customer_proposal_additively(monkeypatch):
    db = _DB(
        {
            "customers": [[{"id": "cust-1", "full_name": "Max", "phone": "+49170"}]],
            "appointments": [[{"id": "appt-9", "scheduled_at": "2026-06-10T08:00:00+00:00"}]],
            # gen_inquiry_number reads count only (data unused), THEN the insert returns the row.
            "inquiries": [[], [{"id": "inq-1"}]],
        },
        counts={"inquiries": 0},
    )
    monkeypatch.setattr(appt_service, "get_service_client", lambda: db)

    payload = ChangeAppointmentRequest(
        phoneNumber="+49170", newDate="2026-06-15", newTime="14:00", reason="später",
    )
    out = appt_service.change_appointment("org-1", payload)

    # 1) Return contract UNCHANGED (existing agent-facing behaviour preserved).
    assert out["success"] is True
    assert out["status"] == "PENDING_CONFIRMATION"
    assert out["changeRequestId"] == "inq-1"

    # 2) The appointment_change inquiry is still created (additive, not replaced).
    assert any(t == "inquiries" for (t, _p) in db.inserts)

    # 3) NEW additive stamp on the matched appointment → enables one-click approval.
    appt_updates = [p for (t, p) in db.updates if t == "appointments"]
    assert appt_updates, "expected a customer_proposed_* stamp on the appointment"
    stamp = appt_updates[-1]
    assert stamp["customer_proposed_start_time"]
    assert stamp["customer_proposed_at"]
    assert stamp["customer_proposal_source"] == "agent_call"
