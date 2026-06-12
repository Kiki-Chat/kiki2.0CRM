"""run_due_reschedule_expiry — the bug-#3 safety-timer sweep. Hermetic.

Covers the hardening added after the 2026-06-11 audit (the sweep previously had
ZERO test coverage):
  • B1 — the cancel UPDATE is CONDITIONAL on the proposal still being pending, so
    a human approving/declining in the gap between SELECT and UPDATE is not
    overwritten (the sweep neither cancels nor calls the customer).
  • B5 — an L3 auto-cancel only fires inside the org's outbound time window.
  • L1/L2 are only flagged; L3-within-window cancels + notifies + frees Google.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.services import appointments as appt_svc
from app.services import appointment_notify
from app.services import calendar_sync
from app.services import outbound_dispatch


class _Chain:
    def __init__(self, table, db):
        self.table, self.db = table, db

    @property
    def not_(self):
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def neq(self, *a, **k):
        return self

    def lt(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def update(self, payload):
        self.db.updates.append((self.table, payload))
        return self

    def execute(self):
        rows = self.db.pop(self.table)
        res = MagicMock()
        res.data = rows
        res.count = len(rows)
        return res


class _DB:
    def __init__(self, responses):
        self.resp = {k: list(v) for k, v in responses.items()}
        self.updates = []

    def pop(self, table):
        q = self.resp.get(table)
        return q.pop(0) if q else []

    def table(self, name):
        return _Chain(name, self)


_WINDOW = {"outbound_time_from": "09:00", "outbound_time_to": "17:00", "outbound_weekdays": []}
# 2026-06-15 is a Monday; 10:00 UTC = 12:00 Berlin (inside 09–17), 01:00 UTC = 03:00 (outside).
_IN_WINDOW = datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc)
_OUT_WINDOW = datetime(2026, 6, 15, 1, 0, tzinfo=timezone.utc)


def _wire(monkeypatch, db, *, level=3):
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    monkeypatch.setattr(appt_svc, "_get_kiki_level", lambda c, o: level)
    # The sweep now scopes the query to L3 orgs up front (no L1/L2 starvation).
    monkeypatch.setattr(
        outbound_dispatch, "_l3_org_ids",
        lambda db_, only: (["org-1"] if level >= 3 else []),
    )
    notified, gdeleted = [], []
    monkeypatch.setattr(
        appointment_notify, "notify_appointment_outcome",
        lambda org, aid, kind, **k: notified.append((org, aid, kind)),
    )
    monkeypatch.setattr(
        calendar_sync, "delete_google_event",
        lambda org, gid: gdeleted.append(gid),
    )
    return notified, gdeleted


def _row(**over):
    return {"id": "a", "org_id": "org-1", "reschedule_replace_intent": True,
            "google_event_id": "g1", **over}


def test_l3_within_window_cancels_notifies_and_frees_google(monkeypatch):
    db = _DB({
        "appointments": [[_row()], [_row(status="cancelled")]],  # SELECT, then UPDATE result
        "agent_configs": [[_WINDOW]],
    })
    notified, gdeleted = _wire(monkeypatch, db, level=3)
    out = outbound_dispatch.run_due_reschedule_expiry(now=_IN_WINDOW)
    assert out["expired"] == 1 and out["cancelled"] == 1 and out["raced"] == 0
    assert notified == [("org-1", "a", "cancel")]
    assert gdeleted == ["g1"]
    # the cancel UPDATE wiped the proposal markers
    payload = db.updates[0][1]
    assert payload["status"] == "cancelled" and payload["customer_proposed_at"] is None


def test_b1_race_conditional_update_no_rows_skips_notify(monkeypatch):
    # A human approved in the gap → the conditional UPDATE matches 0 rows.
    db = _DB({
        "appointments": [[_row()], []],   # SELECT returns the row, UPDATE returns nothing
        "agent_configs": [[_WINDOW]],
    })
    notified, gdeleted = _wire(monkeypatch, db, level=3)
    out = outbound_dispatch.run_due_reschedule_expiry(now=_IN_WINDOW)
    assert out["raced"] == 1 and out["cancelled"] == 0 and out["expired"] == 0
    assert notified == []           # NO customer call placed
    assert gdeleted == []


def test_b5_outside_window_defers_l3_cancel(monkeypatch):
    db = _DB({
        "appointments": [[_row()]],   # only the SELECT — no UPDATE should run
        "agent_configs": [[_WINDOW]],
    })
    notified, gdeleted = _wire(monkeypatch, db, level=3)
    out = outbound_dispatch.run_due_reschedule_expiry(now=_OUT_WINDOW)
    assert out["deferred"] == 1 and out["cancelled"] == 0 and out["expired"] == 0
    assert db.updates == [] and notified == []


def test_l1_l2_excluded_from_sweep_never_cancels(monkeypatch):
    # L1/L2 orgs are no longer selected at all (no starvation of L3 rows); the
    # sweep returns immediately and touches nothing.
    db = _DB({"appointments": [[_row()]]})
    notified, gdeleted = _wire(monkeypatch, db, level=2)
    out = outbound_dispatch.run_due_reschedule_expiry(now=_IN_WINDOW)
    assert out["due"] == 0 and out["cancelled"] == 0
    assert db.updates == [] and notified == []


def test_l3_org_ids_filters_by_appointments_level():
    rows = [
        {"org_id": "a", "appointments_level": 3, "kiki_level": 2},
        {"org_id": "b", "appointments_level": 2, "kiki_level": 3},
        {"org_id": "c", "appointments_level": None, "kiki_level": 3},  # legacy fallback
        {"org_id": "d", "appointments_level": None, "kiki_level": None},  # default 2
    ]

    class _Q:
        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def execute(self):
            return type("R", (), {"data": rows})()

    class _DBx:
        def table(self, _n):
            return _Q()

    assert outbound_dispatch._l3_org_ids(_DBx(), None) == ["a", "c"]
