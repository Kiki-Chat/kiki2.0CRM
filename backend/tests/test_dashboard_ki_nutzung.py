"""Cluster 5 — KI-Nutzung Tag/Woche/Monat/Zeitraum window.

Hermetic: _ki_window is pure (now is injected); _ki_nutzung runs against a fake
supabase client. Verifies the window boundaries + that the selected period scopes
minutes/calls while the quota context stays monthly.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

from app.api.routes import dashboard as dash


def _now() -> datetime:
    # Wednesday 2026-06-17 14:30 Berlin — mid-month, mid-week.
    return datetime(2026, 6, 17, 14, 30, tzinfo=dash.BERLIN)


def test_ki_window_month():
    start, end, ps, pe, label, x, by_hour = dash._ki_window("month", None, None, _now())
    assert start.date() == date(2026, 6, 1) and start.hour == 0
    assert end.date() == date(2026, 7, 1)
    assert ps.date() == date(2026, 5, 1) and pe.date() == date(2026, 6, 1)
    assert label == "Dieser Monat" and x == "Tag" and by_hour is False


def test_ki_window_day():
    start, end, ps, pe, label, x, by_hour = dash._ki_window("day", None, None, _now())
    assert start.date() == date(2026, 6, 17) and start.hour == 0
    assert end.date() == date(2026, 6, 18)
    assert ps.date() == date(2026, 6, 16) and pe.date() == date(2026, 6, 17)
    assert label == "Heute" and x == "Uhrzeit" and by_hour is True


def test_ki_window_week_starts_monday():
    start, end, ps, pe, label, x, by_hour = dash._ki_window("week", None, None, _now())
    assert start.weekday() == 0 and start.hour == 0   # Monday
    assert (end - start) == timedelta(days=7)
    assert (start - ps) == timedelta(days=7) and pe == start
    assert start.date() == date(2026, 6, 15)          # the Monday of that week
    assert label == "Diese Woche" and by_hour is False


def test_ki_window_custom_range():
    start, end, ps, pe, label, x, by_hour = dash._ki_window("range", "2026-06-10", "2026-06-12", _now())
    assert start.date() == date(2026, 6, 10) and start.hour == 0
    assert end.date() == date(2026, 6, 13)            # to-date inclusive → +1 day
    assert (start - ps) == timedelta(days=3)          # prev window = same length
    assert pe == start and label == "Zeitraum" and x == "Datum"


# ─── _ki_nutzung end-to-end against a fake client ────────────────────────────
class _FakeChain:
    def __init__(self, table, db):
        self.table, self.db = table, db

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        r = MagicMock()
        r.data = list(self.db.get(self.table, []))
        return r


class _FakeClient:
    def __init__(self, db):
        self.db = db

    def table(self, name):
        return _FakeChain(name, self.db)


def test_ki_nutzung_month_scopes_recent_call(monkeypatch):
    now = dash._now()
    recent = (now - timedelta(minutes=2)).isoformat()  # in this month/week/day
    db = {
        "organizations": [{"ai_minutes_quota": 500}],
        "calls": [{"id": "c1", "customer_id": None, "direction": "inbound",
                   "started_at": recent, "duration_seconds": 180, "status": "completed",
                   "created_at": recent}],
        "customers": [],
    }
    monkeypatch.setattr(dash, "get_service_client", lambda: _FakeClient(db))
    out = dash._ki_nutzung("org-1", "month")
    assert out["period"] == "month" and out["period_label"] == "Dieser Monat"
    assert out["kpis"]["minutes_used"] == 3 and out["kpis"]["calls_count"] == 1
    assert out["kpis"]["minutes_quota"] == 500
    assert out["kpis"]["month_minutes_used"] == 3
    # contract keys the frontend depends on
    assert isinstance(out["series"], list) and out["series_x_label"] == "Tag"
    for key in ("previous_minutes", "previous_calls", "previous_avg_duration"):
        assert key in out["kpis"]


def test_ki_nutzung_range_excludes_out_of_window(monkeypatch):
    # A call from 2020 is outside any current window → 0 minutes, but the request
    # still returns the full contract.
    db = {
        "organizations": [{"ai_minutes_quota": 0}],
        "calls": [{"id": "old", "customer_id": None, "direction": "inbound",
                   "started_at": "2020-01-01T10:00:00+00:00", "duration_seconds": 600,
                   "status": "completed", "created_at": "2020-01-01T10:05:00+00:00"}],
        "customers": [],
    }
    monkeypatch.setattr(dash, "get_service_client", lambda: _FakeClient(db))
    out = dash._ki_nutzung("org-1", "range", "2026-06-10", "2026-06-12")
    assert out["period"] == "range" and out["kpis"]["minutes_used"] == 0
    assert out["kpis"]["calls_count"] == 0
