"""Wave 3 / Agent 3.2 — unified timeline aggregation for /api/calls/{id}/timeline.

Covers:
 - Each event kind is emitted from the right source column.
 - Sort order is newest-first across kinds.
 - Org-scoping: every supabase query filters by the passed org_id.
 - Cross-org call_id returns None (route translates to 404).
 - Empty timeline (call with no inquiries / no actions) still returns the
   call_created event.
 - Inquiry status='open' does NOT emit a status-changed event (no transition
   has happened yet).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app.api.routes import calls as call_routes


# ─── Fake supabase chain (records every call for org-scope assertions) ──────
class _FakeChain:
    def __init__(self, data: list[dict] | None, recorder: list, table: str):
        self._data = data or []
        self._recorder = recorder
        self._table = table

    def _rec(self, method: str, *args, **kwargs):
        self._recorder.append(
            {"table": self._table, "method": method, "args": args, "kwargs": kwargs}
        )
        return self

    def select(self, *a, **k): return self._rec("select", *a, **k)
    def eq(self, *a, **k): return self._rec("eq", *a, **k)
    def in_(self, *a, **k): return self._rec("in_", *a, **k)
    def neq(self, *a, **k): return self._rec("neq", *a, **k)
    def order(self, *a, **k): return self._rec("order", *a, **k)
    def limit(self, *a, **k): return self._rec("limit", *a, **k)

    def execute(self):
        self._recorder.append({"table": self._table, "method": "execute"})
        return MagicMock(data=self._data, count=len(self._data))


class _FakeClient:
    def __init__(self, per_table: dict[str, list[dict]]):
        self.per_table = per_table
        self.recorder: list = []

    def table(self, name: str):
        return _FakeChain(self.per_table.get(name, []), self.recorder, table=name)


ORG = "org-test-uuid"
CALL_ID = "call-1"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ─── 404 / org-scoping ──────────────────────────────────────────────────────
def test_returns_none_when_call_not_in_org(monkeypatch):
    """Cross-org call_id returns None — the route translates this to 404."""
    client = _FakeClient({"calls": []})  # no rows from the eq(org_id) filter
    monkeypatch.setattr(call_routes, "get_service_client", lambda: client)

    result = call_routes._build_timeline(ORG, CALL_ID)

    assert result is None
    # Verify the SELECT was scoped to org_id.
    org_eq_calls = [
        c for c in client.recorder
        if c["method"] == "eq" and c["args"] == ("org_id", ORG)
    ]
    assert len(org_eq_calls) >= 1


def test_every_query_filters_by_org_id(monkeypatch):
    """Each table query carries an .eq('org_id', ORG) — tenant isolation."""
    now = _now()
    client = _FakeClient(
        {
            "calls": [{"id": CALL_ID, "created_at": _iso(now), "started_at": _iso(now), "customer_id": None}],
            "inquiries": [
                {
                    "id": "inq-1",
                    "status": "completed",
                    "title": "Test",
                    "type": None,
                    "created_at": _iso(now - timedelta(hours=2)),
                    "updated_at": _iso(now - timedelta(hours=1)),
                }
            ],
            "appointments": [],
            "cost_estimates": [],
        }
    )
    monkeypatch.setattr(call_routes, "get_service_client", lambda: client)

    call_routes._build_timeline(ORG, CALL_ID)

    org_eq_calls = [
        c for c in client.recorder
        if c["method"] == "eq" and c["args"] == ("org_id", ORG)
    ]
    # Must include: calls (1), inquiries (1), appointments (1), cost_estimates (1)
    # since the inquiry list is non-empty so the appt + kva selects fire.
    assert len(org_eq_calls) >= 4


# ─── Per-kind emission ──────────────────────────────────────────────────────
def test_call_created_event_always_emitted(monkeypatch):
    """Even a brand-new call with no inquiries has the call_created event."""
    now = _now()
    client = _FakeClient(
        {
            "calls": [
                {
                    "id": CALL_ID,
                    "created_at": _iso(now),
                    "started_at": _iso(now),
                    "customer_id": None,
                }
            ],
            "inquiries": [],
            "appointments": [],
            "cost_estimates": [],
        }
    )
    monkeypatch.setattr(call_routes, "get_service_client", lambda: client)

    events = call_routes._build_timeline(ORG, CALL_ID)

    assert events is not None
    assert len(events) == 1
    assert events[0]["kind"] == "call_created"
    assert events[0]["actor_kind"] == "kiki"
    assert events[0]["actor_name"] == "Kiki"
    assert events[0]["entity_id"] == CALL_ID


def test_inquiry_open_status_does_not_emit_event(monkeypatch):
    """Status='open' = no transition yet → no event."""
    now = _now()
    client = _FakeClient(
        {
            "calls": [{"id": CALL_ID, "created_at": _iso(now), "started_at": _iso(now), "customer_id": None}],
            "inquiries": [
                {
                    "id": "inq-1",
                    "status": "open",
                    "title": "Test",
                    "type": None,
                    "created_at": _iso(now - timedelta(hours=1)),
                    "updated_at": _iso(now - timedelta(hours=1)),
                }
            ],
            "appointments": [],
            "cost_estimates": [],
        }
    )
    monkeypatch.setattr(call_routes, "get_service_client", lambda: client)

    events = call_routes._build_timeline(ORG, CALL_ID)

    kinds = [e["kind"] for e in events]
    assert "inquiry_status_changed" not in kinds
    # call_created still present.
    assert "call_created" in kinds


def test_inquiry_status_changed_emitted_for_non_open(monkeypatch):
    """in_progress / completed each emit an inquiry_status_changed event."""
    now = _now()
    client = _FakeClient(
        {
            "calls": [{"id": CALL_ID, "created_at": _iso(now), "started_at": _iso(now), "customer_id": None}],
            "inquiries": [
                {
                    "id": "inq-1",
                    "status": "completed",
                    "title": "Heizung defekt",
                    "type": None,
                    "created_at": _iso(now - timedelta(hours=2)),
                    "updated_at": _iso(now - timedelta(minutes=10)),
                }
            ],
            "appointments": [],
            "cost_estimates": [],
        }
    )
    monkeypatch.setattr(call_routes, "get_service_client", lambda: client)

    events = call_routes._build_timeline(ORG, CALL_ID)

    status_events = [e for e in events if e["kind"] == "inquiry_status_changed"]
    assert len(status_events) == 1
    ev = status_events[0]
    assert ev["entity_id"] == "inq-1"
    assert ev["actor_kind"] == "employee"
    assert "Erledigt" in ev["description"]
    assert ev["extras"]["status"] == "completed"
    assert ev["extras"]["title"] == "Heizung defekt"


def test_appointment_lifecycle_events(monkeypatch):
    """confirmed_at / rejected_at / alternative_proposed_at each emit events."""
    now = _now()
    client = _FakeClient(
        {
            "calls": [{"id": CALL_ID, "created_at": _iso(now), "started_at": _iso(now), "customer_id": None}],
            "inquiries": [
                {
                    "id": "inq-1",
                    "status": "in_progress",
                    "title": "Heizung",
                    "type": None,
                    "created_at": _iso(now - timedelta(hours=3)),
                    "updated_at": _iso(now - timedelta(hours=2)),
                }
            ],
            "appointments": [
                {
                    "id": "appt-confirmed",
                    "inquiry_id": "inq-1",
                    "title": "Vor-Ort-Termin",
                    "scheduled_at": _iso(now + timedelta(days=2)),
                    "created_at": _iso(now - timedelta(hours=2)),
                    "status": "confirmed",
                    "confirmed_at": _iso(now - timedelta(hours=1)),
                    "rejected_at": None,
                    "rejection_reason": None,
                    "alternative_start_time": None,
                    "alternative_proposed_at": None,
                },
                {
                    "id": "appt-rejected",
                    "inquiry_id": "inq-1",
                    "title": "Alter Termin",
                    "scheduled_at": _iso(now + timedelta(days=1)),
                    "created_at": _iso(now - timedelta(hours=4)),
                    "status": "cancelled",
                    "confirmed_at": None,
                    "rejected_at": _iso(now - timedelta(minutes=45)),
                    "rejection_reason": "Kunde nicht erreichbar",
                    "alternative_start_time": None,
                    "alternative_proposed_at": None,
                },
                {
                    "id": "appt-alt",
                    "inquiry_id": "inq-1",
                    "title": "Verschiebung",
                    "scheduled_at": _iso(now + timedelta(days=3)),
                    "created_at": _iso(now - timedelta(hours=2)),
                    "status": "pending",
                    "confirmed_at": None,
                    "rejected_at": None,
                    "rejection_reason": None,
                    "alternative_start_time": _iso(now + timedelta(days=5)),
                    "alternative_proposed_at": _iso(now - timedelta(minutes=30)),
                },
            ],
            "cost_estimates": [],
        }
    )
    monkeypatch.setattr(call_routes, "get_service_client", lambda: client)

    events = call_routes._build_timeline(ORG, CALL_ID)

    kinds = {e["kind"] for e in events}
    assert "appointment_confirmed" in kinds
    assert "appointment_rejected" in kinds
    assert "alternative_proposed" in kinds

    # Reason is surfaced on the rejected event extras.
    rej = next(e for e in events if e["kind"] == "appointment_rejected")
    assert rej["extras"]["reason"] == "Kunde nicht erreichbar"


def test_kva_lifecycle_events(monkeypatch):
    """sent_at / accepted_at / rejected_at each emit kva_* events."""
    now = _now()
    client = _FakeClient(
        {
            "calls": [{"id": CALL_ID, "created_at": _iso(now), "started_at": _iso(now), "customer_id": None}],
            "inquiries": [
                {
                    "id": "inq-1",
                    "status": "in_progress",
                    "title": "T",
                    "type": None,
                    "created_at": _iso(now - timedelta(hours=3)),
                    "updated_at": _iso(now - timedelta(hours=2)),
                }
            ],
            "appointments": [],
            "cost_estimates": [
                {
                    "id": "kva-1",
                    "inquiry_id": "inq-1",
                    "number": "KVA-2026-001",
                    "total": 1234.56,
                    "created_at": _iso(now - timedelta(days=2)),
                    "sent_at": _iso(now - timedelta(days=1)),
                    "accepted_at": _iso(now - timedelta(hours=4)),
                    "rejected_at": None,
                    "status": "accepted",
                },
                {
                    "id": "kva-2",
                    "inquiry_id": "inq-1",
                    "number": "KVA-2026-002",
                    "total": 50,
                    "created_at": _iso(now - timedelta(days=3)),
                    "sent_at": _iso(now - timedelta(days=2)),
                    "accepted_at": None,
                    "rejected_at": _iso(now - timedelta(hours=2)),
                    "status": "rejected",
                },
            ],
        }
    )
    monkeypatch.setattr(call_routes, "get_service_client", lambda: client)

    events = call_routes._build_timeline(ORG, CALL_ID)

    kinds = [e["kind"] for e in events]
    assert kinds.count("kva_sent") == 2
    assert kinds.count("kva_accepted") == 1
    assert kinds.count("kva_rejected") == 1

    # Customer is the actor on accept/reject (it's the customer's decision).
    accepted = next(e for e in events if e["kind"] == "kva_accepted")
    assert accepted["actor_kind"] == "system"
    assert accepted["actor_name"] == "Kunde"

    # Number flows into extras.
    sent_events = [e for e in events if e["kind"] == "kva_sent"]
    nums = {e["extras"].get("number") for e in sent_events}
    assert nums == {"KVA-2026-001", "KVA-2026-002"}


# ─── Sort order ─────────────────────────────────────────────────────────────
def test_events_sorted_newest_first(monkeypatch):
    """Across all event kinds, the final list is newest-first by timestamp."""
    now = _now()
    client = _FakeClient(
        {
            "calls": [
                {
                    "id": CALL_ID,
                    "created_at": _iso(now - timedelta(days=5)),
                    "started_at": _iso(now - timedelta(days=5)),
                    "customer_id": None,
                }
            ],
            "inquiries": [
                {
                    "id": "inq-1",
                    "status": "completed",
                    "title": "T",
                    "type": None,
                    "created_at": _iso(now - timedelta(days=5)),
                    "updated_at": _iso(now - timedelta(hours=1)),
                }
            ],
            "appointments": [
                {
                    "id": "appt-1",
                    "inquiry_id": "inq-1",
                    "title": "Termin",
                    "scheduled_at": _iso(now),
                    "created_at": _iso(now - timedelta(days=3)),
                    "status": "confirmed",
                    "confirmed_at": _iso(now - timedelta(days=2)),
                    "rejected_at": None,
                    "rejection_reason": None,
                    "alternative_start_time": None,
                    "alternative_proposed_at": None,
                },
            ],
            "cost_estimates": [
                {
                    "id": "kva-1",
                    "inquiry_id": "inq-1",
                    "number": "KVA-1",
                    "total": 100,
                    "created_at": _iso(now - timedelta(days=4)),
                    "sent_at": _iso(now - timedelta(days=3)),
                    "accepted_at": None,
                    "rejected_at": None,
                    "status": "sent",
                },
            ],
        }
    )
    monkeypatch.setattr(call_routes, "get_service_client", lambda: client)

    events = call_routes._build_timeline(ORG, CALL_ID)

    timestamps = [e["timestamp"] for e in events]
    # Strictly descending.
    assert timestamps == sorted(timestamps, reverse=True)
    # Spot-check: the newest event is the inquiry status flip (1h ago).
    assert events[0]["kind"] == "inquiry_status_changed"
    # The oldest is call_created (5 days ago).
    assert events[-1]["kind"] == "call_created"
