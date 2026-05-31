"""Hermetic tests for calendar_sync mapping + orchestration (no network/DB).

The Google fetch and DB helpers are module-scoped so they're monkeypatched here;
the pure mapping (_to_rows / _event_dt) is tested directly.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.services import calendar_sync as cs

ORG = "00000000-0000-0000-0000-0000000000aa"
NOW = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)


# ─── pure mapping ────────────────────────────────────────────────────────────
def test_to_rows_timed_event():
    events = [{
        "id": "ev1", "status": "confirmed", "summary": "Kundentermin",
        "start": {"dateTime": "2026-06-02T10:00:00+02:00"},
        "end": {"dateTime": "2026-06-02T11:30:00+02:00"},
        "location": "Baustelle 1", "updated": "2026-05-30T12:00:00Z",
    }]
    rows, seen = cs._to_rows(ORG, events, NOW)
    assert seen == {"ev1"}
    assert len(rows) == 1
    r = rows[0]
    assert r["google_event_id"] == "ev1"
    assert r["source"] == "google_import"
    assert r["category"] == "google"
    assert r["status"] == "confirmed"           # counts as blocked time
    assert r["title"] == "Kundentermin"
    assert r["duration_minutes"] == 90
    assert r["location"] == {"raw": "Baustelle 1"}
    assert r["scheduled_at"].startswith("2026-06-02T08:00:00")  # 10:00 +02:00 → 08:00 UTC
    assert r["external_updated_at"] == "2026-05-30T12:00:00Z"
    assert r["last_synced_at"] == NOW.isoformat()


def test_to_rows_all_day_event():
    events = [{
        "id": "ev2", "status": "confirmed", "summary": "Urlaub",
        "start": {"date": "2026-06-05"}, "end": {"date": "2026-06-06"},
    }]
    rows, seen = cs._to_rows(ORG, events, NOW)
    assert seen == {"ev2"}
    r = rows[0]
    # 00:00 Berlin (CEST, +02:00) == 22:00 UTC the previous day
    assert r["scheduled_at"].startswith("2026-06-04T22:00:00")
    assert r["duration_minutes"] == 24 * 60


def test_to_rows_skips_cancelled_missing_start_and_no_id():
    events = [
        {"id": "c1", "status": "cancelled", "start": {"dateTime": "2026-06-02T10:00:00Z"}},
        {"id": "no_start", "status": "confirmed"},
        {"status": "confirmed", "start": {"dateTime": "2026-06-02T10:00:00Z"}},  # no id
    ]
    rows, seen = cs._to_rows(ORG, events, NOW)
    assert rows == []
    assert seen == set()


def test_to_rows_default_title_and_duration():
    events = [{"id": "ev3", "status": "confirmed", "start": {"dateTime": "2026-06-02T10:00:00Z"}}]
    rows, _ = cs._to_rows(ORG, events, NOW)
    assert rows[0]["title"] == "(Google-Termin)"
    assert rows[0]["duration_minutes"] == 60  # no end → default


# ─── orchestration (helpers stubbed; no DB/network) ──────────────────────────
def test_pull_google_events_orchestration(monkeypatch):
    monkeypatch.setattr(cs, "get_valid_access_token", lambda org, prov: "tok")
    events = [{
        "id": "ev1", "status": "confirmed", "summary": "X",
        "start": {"dateTime": "2026-06-02T10:00:00Z"},
        "end": {"dateTime": "2026-06-02T11:00:00Z"},
    }]
    monkeypatch.setattr(cs, "_fetch_events", lambda tok, tmin, tmax: events)
    monkeypatch.setattr(cs, "get_service_client", lambda: object())
    monkeypatch.setattr(cs, "_existing_google_rows", lambda c, o, a, b: {})
    monkeypatch.setattr(cs, "_apply_rows", lambda c, o, rows, existing: (len(rows), 0))
    monkeypatch.setattr(cs, "_reconcile_deletions", lambda c, o, existing, seen, now: 0)

    res = cs.pull_google_events(ORG, now=NOW)
    assert res == {
        "success": True, "fetched": 1, "created": 1, "updated": 0,
        "cancelled": 0, "synced_at": NOW.isoformat(), "window_days": 60,
    }
