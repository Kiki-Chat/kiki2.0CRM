"""Batch 8 — Open-Action aggregation regressions.

Bug 2 coverage: unmatched reschedule requests (FORWARDED_TO_TEAM) were invisible.
`_record_unmatched_change_request` (services/appointments.py) inserts an inquiry
of type='appointment_change', status='open', notes prefixed 'NICHT ZUGEORDNET …'
with NO appointment row — so no appointment-derived Open Action ever surfaced.

`_unmatched_reschedule` closes that gap by querying the inquiry directly. These
tests pin two behaviours:
 - it RETURNS the NICHT-ZUGEORDNET inquiry as kind 'reschedule_unmatched', and
 - it does NOT return a *matched* (no-marker) appointment_change/open inquiry —
   that path already surfaces via the customer_proposed_* appointment rows in
   `_alt_time_proposal`, so double-listing must be avoided.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from app.api.routes import actions as ax


# ─── Fake supabase chain (mirrors test_actions_pending, + .ilike) ────────────
class _FakeChain:
    """Records every method call so tests can assert org-scoping / filters.
    Returns the canned data passed in on instantiation when .execute() is called.
    NOTE: the fake does not actually filter; tests assert on the recorded calls
    and supply per-table data that already reflects the intended query result."""

    def __init__(self, data: list[dict] | None = None, recorder: list | None = None, table: str = ""):
        self._data = data or []
        self._recorder = recorder if recorder is not None else []
        self._table = table

    def _rec(self, method: str, *args, **kwargs):
        self._recorder.append({"table": self._table, "method": method, "args": args, "kwargs": kwargs})
        return self

    def select(self, *a, **k): return self._rec("select", *a, **k)
    def eq(self, *a, **k): return self._rec("eq", *a, **k)
    def neq(self, *a, **k): return self._rec("neq", *a, **k)
    def in_(self, *a, **k): return self._rec("in_", *a, **k)
    def is_(self, *a, **k): return self._rec("is_", *a, **k)
    def gte(self, *a, **k): return self._rec("gte", *a, **k)
    def lte(self, *a, **k): return self._rec("lte", *a, **k)
    def ilike(self, *a, **k): return self._rec("ilike", *a, **k)
    def order(self, *a, **k): return self._rec("order", *a, **k)
    def limit(self, *a, **k): return self._rec("limit", *a, **k)

    @property
    def not_(self):  # postgrest exposes `.not_.is_(col, val)`
        return self

    def execute(self):
        self._recorder.append({"table": self._table, "method": "execute"})
        return MagicMock(data=self._data, count=len(self._data))


class _FakeClient:
    """Per-table canned data + a single recorder for all calls."""

    def __init__(self, per_table: dict[str, list[dict]]):
        self.per_table = per_table
        self.recorder: list = []

    def table(self, name: str):
        return _FakeChain(self.per_table.get(name, []), self.recorder, table=name)


ORG = "org-test-uuid"


# ─── _unmatched_reschedule ──────────────────────────────────────────────────
def test_unmatched_reschedule_surfaces_nicht_zugeordnet_inquiry():
    """The NICHT-ZUGEORDNET inquiry must surface as kind 'reschedule_unmatched'
    with the right shape (high priority, inquiry_id == id, no appointment/call)."""
    inquiries = [
        {
            "id": "inq-unmatched",
            "customer_id": "cust-1",
            "created_at": "2026-06-17T08:00:00+00:00",
            "notes": (
                "NICHT ZUGEORDNET — Termin konnte nicht automatisch gefunden "
                "werden, bitte manuell zuordnen.\nWunschtermin neu: morgen 10 Uhr"
            ),
            "status": "open",
            "type": "appointment_change",
        },
    ]
    customers = [{"id": "cust-1", "full_name": "Max Mustermann"}]
    client = _FakeClient({"inquiries": inquiries, "customers": customers})

    out = ax._unmatched_reschedule(client, ORG)

    assert len(out) == 1
    row = out[0]
    assert row["kind"] == "reschedule_unmatched"
    assert row["id"] == "inq-unmatched"
    assert row["inquiry_id"] == "inq-unmatched"
    assert row["customer_id"] == "cust-1"
    assert row["customer_name"] == "Max Mustermann"
    assert row["priority"] == "high"
    assert row["call_id"] is None
    assert row["due_at"] is None
    assert "zugeordnet" in row["summary"].lower()
    # Org-scoping + the discriminating filters were all applied.
    rec = client.recorder
    assert any(c["method"] == "eq" and c["args"] == ("org_id", ORG) for c in rec)
    assert any(c["method"] == "eq" and c["args"] == ("type", "appointment_change") for c in rec)
    assert any(c["method"] == "eq" and c["args"] == ("status", "open") for c in rec)
    # The 'NICHT ZUGEORDNET%' marker is what excludes the matched path.
    assert any(c["method"] == "ilike" and c["args"] == ("notes", "NICHT ZUGEORDNET%") for c in rec)


def test_unmatched_reschedule_excludes_matched_appointment_change():
    """A *matched* appointment_change/open inquiry (no NICHT-ZUGEORDNET marker)
    must NOT be returned here — it surfaces via _alt_time_proposal's
    customer_proposed_* appointment rows, so listing it here would double-count.

    The DB-side `.ilike('notes', 'NICHT ZUGEORDNET%')` filter would exclude it; we
    assert the aggregator emits nothing for a row whose notes lack the marker."""
    # Simulate what postgrest returns AFTER the ilike filter: the matched inquiry
    # (notes don't start with the marker) is already filtered out → empty result.
    client = _FakeClient({"inquiries": [], "customers": []})

    out = ax._unmatched_reschedule(client, ORG)

    assert out == []
    # And the marker filter is the thing doing the exclusion.
    assert any(
        c["method"] == "ilike" and c["args"] == ("notes", "NICHT ZUGEORDNET%")
        for c in client.recorder
    )


def test_unmatched_reschedule_empty_when_no_rows():
    assert ax._unmatched_reschedule(_FakeClient({"inquiries": []}), ORG) == []


# ─── _reschedule_pending (orange "Termin verschoben" card, L2 human final say) ─
def test_reschedule_pending_surfaces_recently_rescheduled_confirmed_appt():
    """A CONFIRMED appointment with a recent rescheduled_at must surface as kind
    'reschedule_pending' (high priority, the NEW slot as due_at) so the handler can
    give the final say after the outbound confirmation call."""
    appts = [
        {
            "id": "appt-9",
            "inquiry_id": "inq-9",
            "customer_id": "cust-1",
            "title": "Heizungswartung",
            "scheduled_at": "2026-06-22T12:30:00+00:00",
            "rescheduled_at": "2026-06-21T09:00:00+00:00",
            "created_at": "2026-06-10T08:00:00+00:00",
            "status": "confirmed",
            "source_conversation_id": None,
        },
    ]
    customers = [{"id": "cust-1", "full_name": "Max Mustermann"}]
    client = _FakeClient({"appointments": appts, "customers": customers, "inquiries": [], "calls": []})

    out = ax._reschedule_pending(client, ORG)

    assert len(out) == 1
    row = out[0]
    assert row["kind"] == "reschedule_pending"
    assert row["id"] == "appt-9"
    assert row["customer_name"] == "Max Mustermann"
    assert row["priority"] == "high"
    assert row["due_at"] == "2026-06-22T12:30:00+00:00"  # the NEW slot
    assert "verschoben" in row["summary"].lower()
    # Scoped to this org, only CONFIRMED appts, only those rescheduled recently.
    rec = client.recorder
    assert any(c["method"] == "eq" and c["args"] == ("org_id", ORG) for c in rec)
    assert any(c["method"] == "eq" and c["args"] == ("status", "confirmed") for c in rec)
    assert any(c["method"] == "gte" and c["args"][0] == "rescheduled_at" for c in rec)


def test_reschedule_pending_empty_when_no_rows():
    assert ax._reschedule_pending(_FakeClient({"appointments": []}), ORG) == []


# ─── _appointment_confirmed (green "Bestätigt" stage, persists 40d) ──────────
def test_appointment_confirmed_surfaces_confirmed_excludes_recent_reschedule():
    appts = [
        {"id": "a-conf", "inquiry_id": "i1", "customer_id": "c1", "title": "Wartung",
         "scheduled_at": "2099-01-02T10:00:00+00:00", "rescheduled_at": None,
         "created_at": "2099-01-01T08:00:00+00:00", "status": "confirmed", "source_conversation_id": None},
        # recently rescheduled → belongs to reschedule_pending, must be excluded here
        {"id": "a-resched", "inquiry_id": "i2", "customer_id": "c1", "title": "Reparatur",
         "scheduled_at": "2099-01-03T10:00:00+00:00", "rescheduled_at": "2099-01-02T09:00:00+00:00",
         "created_at": "2099-01-01T08:00:00+00:00", "status": "confirmed", "source_conversation_id": None},
    ]
    client = _FakeClient({"appointments": appts, "customers": [{"id": "c1", "full_name": "Max"}],
                          "inquiries": [], "calls": []})
    out = ax._appointment_confirmed(client, ORG)
    ids = [r["id"] for r in out]
    assert "a-conf" in ids and "a-resched" not in ids
    row = next(r for r in out if r["id"] == "a-conf")
    assert row["kind"] == "appointment_confirmed" and "bestätigt" in row["summary"].lower()
    assert row["priority"] == "normal"
    rec = client.recorder
    assert any(c["method"] == "eq" and c["args"] == ("status", "confirmed") for c in rec)
    assert any(c["method"] == "gte" and c["args"][0] == "created_at" for c in rec)


# ─── _kva_accepted (green → "Rechnung erstellen") ───────────────────────────
def test_kva_accepted_surfaces_accepted_offers():
    ce = [{"id": "ce1", "inquiry_id": "i1", "customer_id": "c1", "number": "AG-001",
           "total": 100, "created_at": "2026-06-01T00:00:00+00:00", "status": "accepted",
           "accepted_at": "2026-06-02T00:00:00+00:00"}]
    client = _FakeClient({"cost_estimates": ce, "customers": [{"id": "c1", "full_name": "Max"}]})
    out = ax._kva_accepted(client, ORG)
    assert len(out) == 1 and out[0]["kind"] == "kva_accepted"
    assert "angenommen" in out[0]["summary"].lower()
    assert any(c["method"] == "eq" and c["args"] == ("status", "accepted") for c in client.recorder)


# ─── _kva_closed (slate informational, 40d window) ──────────────────────────
def test_kva_closed_surfaces_recent_rejection():
    ce = [{"id": "ce2", "inquiry_id": "i1", "customer_id": "c1", "number": "AG-002",
           "status": "rejected", "rejected_at": "2099-01-01T00:00:00+00:00",
           "updated_at": None, "created_at": "2099-01-01T00:00:00+00:00"}]
    client = _FakeClient({"cost_estimates": ce, "customers": [{"id": "c1", "full_name": "Max"}]})
    out = ax._kva_closed(client, ORG)
    assert len(out) == 1 and out[0]["kind"] == "kva_closed"
    assert "abgelehnt" in out[0]["summary"].lower()


def test_kva_closed_drops_old_closures():
    ce = [{"id": "ce3", "customer_id": "c1", "number": "AG-003", "status": "rejected",
           "rejected_at": "2000-01-01T00:00:00+00:00", "updated_at": None,
           "created_at": "2000-01-01T00:00:00+00:00"}]
    client = _FakeClient({"cost_estimates": ce, "customers": []})
    assert ax._kva_closed(client, ORG) == []  # closed >40d ago → dropped


# ─── _invoice_cancelled (slate informational) ───────────────────────────────
def test_invoice_cancelled_surfaces_cancelled():
    inv = [{"id": "inv1", "customer_id": "c1", "number": "R-001", "status": "cancelled",
            "cancelled_at": "2099-01-01T00:00:00+00:00", "created_at": "2099-01-01T00:00:00+00:00"}]
    client = _FakeClient({"invoices": inv, "customers": [{"id": "c1", "full_name": "Max"}]})
    out = ax._invoice_cancelled(client, ORG)
    assert len(out) == 1 and out[0]["kind"] == "invoice_cancelled"
    assert "storniert" in out[0]["summary"].lower()
    assert any(c["method"] == "eq" and c["args"] == ("status", "cancelled") for c in client.recorder)
