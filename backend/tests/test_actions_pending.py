"""Wave 2 / Agent 2.2 — pending Aktionen aggregation behavior.

Covers:
 - Each per-kind aggregator returns the right shape and filters out
   inappropriate rows.
 - The combined `_aggregate` function sorts by priority desc, due_at asc
   nulls last, created_at desc (stable).
 - Org-scoping: every supabase query for a per-kind aggregator filters by
   the passed org_id (verified by inspecting the recorded .eq() calls on
   the mock client).
 - Kinds that have no current schema implementation (callback_owed,
   alt_time_proposal) return [].
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

from app.api.routes import actions as ax


# ─── Fake supabase chain ────────────────────────────────────────────────────
class _FakeChain:
    """Records every method call so tests can assert org-scoping. Returns the
    canned data passed in on instantiation when .execute() is called."""

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
    def order(self, *a, **k): return self._rec("order", *a, **k)

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


# ─── Fixtures (org_id we always assert is propagated to .eq) ────────────────
ORG = "org-test-uuid"
OTHER_ORG = "should-never-appear"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ─── termin_anfrage ─────────────────────────────────────────────────────────
def test_termin_anfrage_filters_pending_status_and_includes_customer_name():
    appts = [
        {
            "id": "appt-1",
            "inquiry_id": "inq-1",
            "customer_id": "cust-1",
            "title": "Heizungswartung",
            "scheduled_at": _iso(_now() + timedelta(days=2)),
            "created_at": _iso(_now() - timedelta(hours=3)),
            "status": "pending",
        },
    ]
    customers = [{"id": "cust-1", "full_name": "Max Mustermann"}]
    # The inquiry carries the call_id so the worklist row can open the call whose
    # action card confirms the appointment (resolved via _resolve_call_ids).
    inquiries = [{"id": "inq-1", "call_id": "call-9"}]
    client = _FakeClient({"appointments": appts, "customers": customers, "inquiries": inquiries})

    out = ax._termin_anfrage(client, ORG)

    assert len(out) == 1
    row = out[0]
    assert row["kind"] == "termin_anfrage"
    assert row["id"] == "appt-1"
    assert row["inquiry_id"] == "inq-1"
    assert row["customer_id"] == "cust-1"
    assert row["customer_name"] == "Max Mustermann"
    # call_id is resolved from the linked inquiry so the row opens the call.
    assert row["call_id"] == "call-9"
    assert row["due_at"] == appts[0]["scheduled_at"]
    assert row["priority"] == "normal"
    assert "Heizungswartung" in row["summary"]
    # Org scoping: every .eq("org_id", ORG) was used — appointments, the customer
    # name lookup, AND the inquiry call_id lookup (the appt has no
    # source_conversation_id, so the calls fallback query is skipped).
    eq_org_calls = [
        c for c in client.recorder
        if c["method"] == "eq" and c["args"] == ("org_id", ORG)
    ]
    assert len(eq_org_calls) == 3
    # Status filter pinned to 'pending' (NOT 'pending_confirmation').
    assert any(
        c["method"] == "eq" and c["args"] == ("status", "pending")
        for c in client.recorder
    )


def test_termin_anfrage_falls_back_to_unbekannter_kunde_when_no_customer():
    appts = [
        {
            "id": "appt-2",
            "inquiry_id": None,
            "customer_id": None,
            "title": None,
            "scheduled_at": None,
            "created_at": _iso(_now()),
            "status": "pending",
        },
    ]
    client = _FakeClient({"appointments": appts, "customers": []})
    out = ax._termin_anfrage(client, ORG)
    assert out[0]["customer_name"] == "Unbekannter Kunde"
    # Default title used when row.title is null.
    assert "Termin" in out[0]["summary"]


# ─── kva_to_send ────────────────────────────────────────────────────────────
def test_kva_to_send_returns_draft_rows_with_summary():
    kvas = [
        {
            "id": "kva-1",
            "inquiry_id": "inq-2",
            "customer_id": "cust-2",
            "number": "KVA-2026-00010",
            "total": 1234.56,
            "created_at": _iso(_now() - timedelta(hours=48)),
            "status": "draft",
        },
    ]
    customers = [{"id": "cust-2", "full_name": "Erika Beispiel"}]
    client = _FakeClient({"cost_estimates": kvas, "customers": customers})

    out = ax._kva_to_send(client, ORG)

    assert len(out) == 1
    assert out[0]["kind"] == "kva_to_send"
    assert out[0]["id"] == "kva-1"
    assert out[0]["customer_name"] == "Erika Beispiel"
    assert "KVA-2026-00010" in out[0]["summary"]
    # Due_at is null for KVA-to-send (no scheduled date).
    assert out[0]["due_at"] is None
    # Status filter pinned to 'draft' AND a created_at upper bound (<= now-24h).
    assert any(
        c["method"] == "eq" and c["args"] == ("status", "draft")
        for c in client.recorder
    )
    assert any(c["method"] == "lte" for c in client.recorder)


# ─── kva_pending_acceptance ─────────────────────────────────────────────────
def test_kva_pending_acceptance_drops_rows_with_accepted_or_rejected_timestamp():
    """Belt-and-braces filter: even if a row carries status='sent' AND a
    stale accepted_at / rejected_at, the aggregator must drop it."""
    now = _now()
    kvas = [
        {
            "id": "kva-clean",
            "inquiry_id": None,
            "customer_id": "cust-3",
            "number": "KVA-A",
            "total": 100,
            "sent_at": _iso(now - timedelta(days=2)),
            "accepted_at": None,
            "rejected_at": None,
            "status": "sent",
            "created_at": _iso(now - timedelta(days=3)),
        },
        {
            "id": "kva-already-accepted",
            "inquiry_id": None,
            "customer_id": "cust-3",
            "number": "KVA-B",
            "total": 200,
            "sent_at": _iso(now - timedelta(days=1)),
            "accepted_at": _iso(now - timedelta(hours=2)),
            "rejected_at": None,
            "status": "sent",
            "created_at": _iso(now - timedelta(days=2)),
        },
        {
            "id": "kva-already-rejected",
            "inquiry_id": None,
            "customer_id": "cust-3",
            "number": "KVA-C",
            "total": 300,
            "sent_at": _iso(now - timedelta(days=4)),
            "accepted_at": None,
            "rejected_at": _iso(now - timedelta(hours=1)),
            "status": "sent",
            "created_at": _iso(now - timedelta(days=5)),
        },
    ]
    customers = [{"id": "cust-3", "full_name": "Carlos Test"}]
    client = _FakeClient({"cost_estimates": kvas, "customers": customers})

    out = ax._kva_pending_acceptance(client, ORG)

    ids = [r["id"] for r in out]
    assert ids == ["kva-clean"]
    assert out[0]["kind"] == "kva_pending_acceptance"
    assert out[0]["customer_name"] == "Carlos Test"


# ─── empty kinds ────────────────────────────────────────────────────────────
def test_callback_owed_is_empty_until_schema_lands():
    """Documents the no-op: inquiries.status enum has no 'callback_required'."""
    assert ax._callback_owed(_FakeClient({}), ORG) == []


def test_alt_time_proposal_is_empty_when_no_open_proposals():
    """With no customer/alternative proposals in the DB, the aggregator is empty
    (the schema now has the columns; this asserts the empty-DB path)."""
    assert ax._alt_time_proposal(_FakeClient({}), ORG) == []


# ─── appointment_cancelled (kept visible so the team is informed) ─────────────
def test_appointment_cancelled_surfaces_recent_cancellations():
    appts = [
        {
            "id": "ap-c", "inquiry_id": "inq-c", "customer_id": "cust-c", "title": "Wartung",
            "scheduled_at": _iso(_now() + timedelta(days=1)),
            "cancelled_at": _iso(_now() - timedelta(hours=2)),
            "created_at": _iso(_now() - timedelta(days=1)), "status": "cancelled",
            "source_conversation_id": None,
        },
    ]
    customers = [{"id": "cust-c", "full_name": "Lena Storno"}]
    inquiries = [{"id": "inq-c", "call_id": "call-c"}]
    client = _FakeClient({"appointments": appts, "customers": customers, "inquiries": inquiries})

    out = ax._appointment_cancelled(client, ORG)

    assert len(out) == 1
    row = out[0]
    assert row["kind"] == "appointment_cancelled"
    assert row["id"] == "ap-c"
    assert row["customer_name"] == "Lena Storno"
    # call_id resolved via the inquiry so the worklist row opens the call for context.
    assert row["call_id"] == "call-c"
    assert row["priority"] == "high"
    assert "storniert" in row["summary"].lower()
    # Status filter pinned to 'cancelled'.
    assert any(c["method"] == "eq" and c["args"] == ("status", "cancelled") for c in client.recorder)


def test_appointment_cancelled_empty_when_none():
    assert ax._appointment_cancelled(_FakeClient({"appointments": []}), ORG) == []


# ─── _aggregate sort order ──────────────────────────────────────────────────
def test_aggregate_sort_priority_desc_due_asc_nulls_last_created_desc(monkeypatch):
    """High-priority comes before normal; within a priority, rows with a
    due_at come first (asc), rows without due_at come last but sorted by
    created_at desc among themselves."""
    now = _now()
    # Build items manually and stub each per-kind aggregator. This way the test
    # exercises _aggregate's sort logic in isolation.
    high_with_due_late = {
        "kind": "termin_anfrage",
        "id": "high-due-late",
        "priority": "high",
        "due_at": _iso(now + timedelta(days=5)),
        "created_at": _iso(now - timedelta(days=1)),
    }
    high_with_due_early = {
        "kind": "termin_anfrage",
        "id": "high-due-early",
        "priority": "high",
        "due_at": _iso(now + timedelta(days=1)),
        "created_at": _iso(now - timedelta(days=10)),
    }
    normal_no_due_newer = {
        "kind": "kva_to_send",
        "id": "normal-no-due-newer",
        "priority": "normal",
        "due_at": None,
        "created_at": _iso(now - timedelta(hours=1)),
    }
    normal_no_due_older = {
        "kind": "kva_to_send",
        "id": "normal-no-due-older",
        "priority": "normal",
        "due_at": None,
        "created_at": _iso(now - timedelta(days=2)),
    }
    normal_with_due = {
        "kind": "termin_anfrage",
        "id": "normal-with-due",
        "priority": "normal",
        "due_at": _iso(now + timedelta(days=2)),
        "created_at": _iso(now - timedelta(days=3)),
    }

    monkeypatch.setattr(ax, "get_service_client", lambda: _FakeClient({}))
    monkeypatch.setattr(
        ax, "_termin_anfrage",
        lambda *_: [normal_with_due, high_with_due_late, high_with_due_early],
    )
    monkeypatch.setattr(
        ax, "_kva_to_send",
        lambda *_: [normal_no_due_older, normal_no_due_newer],
    )
    monkeypatch.setattr(ax, "_kva_pending_acceptance", lambda *_: [])
    monkeypatch.setattr(ax, "_callback_owed", lambda *_: [])
    monkeypatch.setattr(ax, "_alt_time_proposal", lambda *_: [])
    monkeypatch.setattr(ax, "_unmatched_reschedule", lambda *_: [])

    out = ax._aggregate(ORG)

    ids = [r["id"] for r in out]
    # Expected order:
    #   high first (priority desc):
    #     - high-due-early (due earlier)
    #     - high-due-late
    #   normal next:
    #     - normal-with-due (has due, comes before nulls)
    #     - normal-no-due-newer (no due, created newest among null-due)
    #     - normal-no-due-older
    assert ids == [
        "high-due-early",
        "high-due-late",
        "normal-with-due",
        "normal-no-due-newer",
        "normal-no-due-older",
    ]


def test_aggregate_with_empty_db_returns_empty_list(monkeypatch):
    monkeypatch.setattr(ax, "get_service_client", lambda: _FakeClient({}))
    monkeypatch.setattr(ax, "_termin_anfrage", lambda *_: [])
    monkeypatch.setattr(ax, "_kva_to_send", lambda *_: [])
    monkeypatch.setattr(ax, "_kva_pending_acceptance", lambda *_: [])
    monkeypatch.setattr(ax, "_callback_owed", lambda *_: [])
    monkeypatch.setattr(ax, "_alt_time_proposal", lambda *_: [])
    monkeypatch.setattr(ax, "_unmatched_reschedule", lambda *_: [])

    assert ax._aggregate(ORG) == []
