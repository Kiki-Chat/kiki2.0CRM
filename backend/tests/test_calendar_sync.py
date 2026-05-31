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
    monkeypatch.setattr(cs, "_crm_owned_event_ids", lambda c, o: set())
    monkeypatch.setattr(cs, "_existing_google_rows", lambda c, o, a, b: {})
    monkeypatch.setattr(cs, "_apply_rows", lambda c, o, rows, existing: (len(rows), 0))
    monkeypatch.setattr(cs, "_reconcile_deletions", lambda c, o, existing, seen, now: 0)
    monkeypatch.setattr(cs, "_detach_vanished_pushed", lambda c, o, a, b, s, n: 0)

    res = cs.pull_google_events(ORG, now=NOW)
    assert res == {
        "success": True, "fetched": 1, "created": 1, "updated": 0,
        "cancelled": 0, "detached": 0, "synced_at": NOW.isoformat(), "window_days": 60,
    }


# ─── Bug A: disconnect purges ONLY imported events (crm rows are safe) ────────
def test_purge_imported_events_scoped_to_google_import(monkeypatch):
    """purge deletes ONLY source='google_import' rows for the org — native crm
    appointments (source='crm') are never matched, so they survive disconnect."""
    captured: dict = {"eq": {}}

    class _Res:
        data = [{"id": "a"}, {"id": "b"}]

    class _Chain:
        def delete(self):
            captured["delete"] = True
            return self

        def eq(self, col, val):
            captured["eq"][col] = val
            return self

        def execute(self):
            return _Res()

    class _Client:
        def table(self, name):
            captured["table"] = name
            return _Chain()

    monkeypatch.setattr(cs, "get_service_client", lambda: _Client())
    n = cs.purge_imported_events("org-9")
    assert n == 2
    assert captured["table"] == "appointments"
    assert captured["delete"] is True
    # Filtered by org_id AND source='google_import' ONLY → crm/ics never matched.
    assert captured["eq"] == {"org_id": "org-9", "source": "google_import"}


# ─── Phase 4 echo-loop guard (pull side): don't re-import events we pushed ────
def test_pull_skips_crm_owned_pushed_events(monkeypatch):
    monkeypatch.setattr(cs, "get_valid_access_token", lambda o, p: "tok")
    events = [
        {"id": "PUSHED1", "status": "confirmed", "summary": "Mine",
         "start": {"dateTime": "2026-06-02T10:00:00Z"}, "end": {"dateTime": "2026-06-02T11:00:00Z"}},
        {"id": "EXT2", "status": "confirmed", "summary": "External",
         "start": {"dateTime": "2026-06-03T10:00:00Z"}, "end": {"dateTime": "2026-06-03T11:00:00Z"}},
    ]
    monkeypatch.setattr(cs, "_fetch_events", lambda t, a, b: events)
    monkeypatch.setattr(cs, "get_service_client", lambda: object())
    monkeypatch.setattr(cs, "_crm_owned_event_ids", lambda c, o: {"PUSHED1"})
    captured: dict = {}
    monkeypatch.setattr(cs, "_existing_google_rows", lambda c, o, a, b: {})
    monkeypatch.setattr(
        cs, "_apply_rows",
        lambda c, o, rows, existing: (
            captured.update({"ids": [r["google_event_id"] for r in rows]}) or (len(rows), 0)
        ),
    )
    monkeypatch.setattr(cs, "_reconcile_deletions", lambda c, o, e, s, n: 0)
    monkeypatch.setattr(cs, "_detach_vanished_pushed", lambda c, o, a, b, s, n: 0)
    cs.pull_google_events("org-1", now=NOW)
    assert captured["ids"] == ["EXT2"]  # PUSHED1 (our own pushed event) skipped


# ─── Google deletion → CRM (the data-safety invariant) ───────────────────────
class _RecRes:
    def __init__(self, data):
        self.data = data


def test_reconcile_cancels_vanished_google_import():
    """source='google_import' whose Google event vanished → status='cancelled'."""
    class _Chain:
        def __init__(self, parent):
            self.parent = parent
            self._payload = None

        def update(self, row):
            self._payload = row
            return self

        def eq(self, *a, **k):
            return self

        def execute(self):
            self.parent.updates.append(self._payload)
            return _RecRes([{}])

    class _Client:
        def __init__(self):
            self.updates: list = []

        def table(self, name):
            return _Chain(self)

    client = _Client()
    existing = {"G1": {"id": "i1", "status": "confirmed"}, "G2": {"id": "i2", "status": "confirmed"}}
    n = cs._reconcile_deletions(client, "org-1", existing, {"G2"}, NOW)  # G1 vanished
    assert n == 1
    assert client.updates == [{"status": "cancelled", "last_synced_at": NOW.isoformat()}]


def test_detach_vanished_pushed_keeps_crm_row_and_clears_link():
    """SAFETY INVARIANT: a pushed source='crm' event that vanished in Google is
    NEVER deleted — only its google_event_id link is detached; the row survives."""
    class _Chain:
        def __init__(self, parent):
            self.parent = parent
            self._op = "select"
            self._payload = None

        def select(self, *a, **k):
            self._op = "select"
            return self

        def update(self, row):
            self._op = "update"
            self._payload = row
            return self

        def delete(self):  # must NEVER be called by detach
            self.parent.deleted = True
            return self

        def eq(self, *a, **k):
            return self

        def gte(self, *a, **k):
            return self

        def lte(self, *a, **k):
            return self

        def execute(self):
            if self._op == "update":
                self.parent.updates.append(self._payload)
                return _RecRes([{}])
            return _RecRes(self.parent.rows)

    class _Client:
        def __init__(self, rows):
            self.rows = rows
            self.updates: list = []
            self.deleted = False

        def table(self, name):
            return _Chain(self)

    client = _Client([
        {"id": "crm1", "google_event_id": "VANISHED"},     # pushed, gone from Google
        {"id": "crm2", "google_event_id": "STILL_THERE"},  # pushed, still present
        {"id": "crm3", "google_event_id": None},           # never pushed
    ])
    n = cs._detach_vanished_pushed(client, "org-1", "t0", "t1", {"STILL_THERE"}, NOW)
    assert n == 1
    assert client.updates == [{"google_event_id": None}]  # only crm1 detached
    assert client.deleted is False  # the row is NEVER hard-deleted
