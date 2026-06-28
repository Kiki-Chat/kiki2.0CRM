"""Tests for per-employee Google busy sync (services/employee_calendar_sync).
Focus: the privacy-critical mapping (opaque, no detail leak, namespaced ids,
skip free/pushed/cancelled), purge scoping, and a pull smoke."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import calendar_sync, employee_calendar, oauth_tokens
from app.services import employee_calendar_sync as ecs


def _ev(gid: str, *, transparency: str | None = None, status: str = "confirmed") -> dict:
    ev = {
        "id": gid,
        "status": status,
        "start": {"dateTime": "2026-07-15T10:00:00+02:00"},
        "end": {"dateTime": "2026-07-15T11:30:00+02:00"},
        "summary": "Zahnarzttermin",          # personal detail — must NOT leak
        "location": "Dr. Müller, Hauptstr. 1",  # personal detail — must NOT leak
        "description": "Wurzelbehandlung",      # personal detail — must NOT leak
    }
    if transparency:
        ev["transparency"] = transparency
    return ev


def _now() -> datetime:
    return datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)


# ─── mapping: opaque + namespaced ────────────────────────────────────────────
def test_to_busy_rows_is_opaque_and_namespaced():
    rows, seen = ecs._to_busy_rows("org", "emp-1", [_ev("g1")], _now(), skip_gids=set())
    assert len(rows) == 1
    r = rows[0]
    assert r["title"] == "Gebucht"                       # opaque label
    assert "notes" not in r and "location" not in r      # no personal detail copied
    assert "Zahnarzt" not in str(r)                       # nothing leaks anywhere
    assert r["google_event_id"] == "emp:emp-1:g1"        # namespaced → no collision
    assert r["source"] == "employee_busy"
    assert r["assigned_employee_id"] == "emp-1"
    assert r["status"] == "confirmed"
    assert r["duration_minutes"] == 90
    assert seen == {"emp:emp-1:g1"}


def test_to_busy_rows_skips_transparent_pushed_and_cancelled():
    events = [
        _ev("free", transparency="transparent"),  # free → not busy
        _ev("pushed"),                             # we pushed it → echo-loop skip
        _ev("gone", status="cancelled"),           # cancelled → skip
        _ev("real"),                               # the only one that counts
    ]
    rows, seen = ecs._to_busy_rows("org", "emp-1", events, _now(), skip_gids={"pushed"})
    assert [r["google_event_id"] for r in rows] == ["emp:emp-1:real"]


# ─── purge scoping ───────────────────────────────────────────────────────────
def test_purge_employee_busy_scoped(monkeypatch):
    chain = MagicMock()
    for m in ("delete", "eq"):
        getattr(chain, m).return_value = chain
    chain.execute.return_value = MagicMock(data=[{"id": "x"}, {"id": "y"}])
    client = MagicMock()
    client.table.return_value = chain
    monkeypatch.setattr(ecs, "get_service_client", lambda: client)
    assert ecs.purge_employee_busy("org", "emp-1") == 2
    eq_calls = [c.args for c in chain.eq.call_args_list]
    assert ("assigned_employee_id", "emp-1") in eq_calls
    assert ("source", "employee_busy") in eq_calls  # never touches real CRM appts


# ─── pull smoke (no network) ─────────────────────────────────────────────────
def _pull_client() -> MagicMock:
    """Fresh chain per .table() call: selects return [] (no pushed/existing),
    insert echoes the inserted rows so created-count works."""
    def make_chain() -> MagicMock:
        chain = MagicMock()
        state: dict = {"rows": [], "is_insert": False}
        for m in ("select", "eq", "neq", "in_", "gte", "lte"):
            getattr(chain, m).return_value = chain

        def _insert(rows, *a, **k):
            state["rows"] = rows
            state["is_insert"] = True
            return chain

        def _execute():
            res = MagicMock()
            res.data = state["rows"] if state["is_insert"] else []
            state["is_insert"] = False
            return res

        chain.insert.side_effect = _insert
        chain.execute.side_effect = _execute
        return chain

    client = MagicMock()
    client.table.side_effect = lambda name: make_chain()
    return client


def test_pull_employee_busy_inserts(monkeypatch):
    monkeypatch.setattr(calendar_sync, "_fetch_events", lambda *a, **k: [_ev("g1"), _ev("g2")])
    monkeypatch.setattr(employee_calendar, "get_valid_access_token", lambda *a, **k: "tok")
    monkeypatch.setattr(ecs, "get_service_client", _pull_client)
    res = ecs.pull_employee_busy("org", "emp-1", now=_now())
    assert res["success"] is True
    assert res["fetched"] == 2
    assert res["created"] == 2


# ─── PUSH / REMOVE (CRM appointment → employee's own Google calendar) ─────────
class _ApptStore:
    """Fake client: the appointments table returns one staged row on select and
    captures the update payload."""

    def __init__(self, appt):
        self.appt = appt
        self.updated = None

    def table(self, name):
        return _ApptQuery(self)


class _ApptQuery:
    def __init__(self, store):
        self.store = store
        self._update = None

    def select(self, *a, **k):
        return self

    def update(self, fields, *a, **k):
        self._update = fields
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self._update is not None:
            self.store.updated = self._update
            return SimpleNamespace(data=[{}])
        return SimpleNamespace(data=[self.store.appt] if self.store.appt else [])


def _crm_appt(**over) -> dict:
    a = {
        "id": "a1", "source": "crm", "status": "confirmed", "assigned_employee_id": "emp1",
        "title": "Job", "scheduled_at": "2026-07-15T10:00:00+02:00", "duration_minutes": 60,
        "notes": None, "location": None, "employee_google_event_id": None,
    }
    a.update(over)
    return a


def test_push_success_stores_gid(monkeypatch):
    store = _ApptStore(_crm_appt())
    monkeypatch.setattr(ecs, "get_service_client", lambda: store)
    monkeypatch.setattr(employee_calendar, "get_valid_access_token", lambda *a, **k: "tok")
    monkeypatch.setattr(calendar_sync, "_insert_event", lambda token, body: "new-gid")
    assert ecs.push_appointment_to_employee("org", "a1") == "new-gid"
    assert store.updated == {"employee_google_event_id": "new-gid"}


def test_push_skips_external_source(monkeypatch):
    store = _ApptStore(_crm_appt(source="employee_busy"))
    monkeypatch.setattr(ecs, "get_service_client", lambda: store)
    assert ecs.push_appointment_to_employee("org", "a1") is None
    assert store.updated is None


def test_push_skips_unassigned(monkeypatch):
    store = _ApptStore(_crm_appt(assigned_employee_id=None))
    monkeypatch.setattr(ecs, "get_service_client", lambda: store)
    assert ecs.push_appointment_to_employee("org", "a1") is None


def test_push_skips_already_pushed(monkeypatch):
    store = _ApptStore(_crm_appt(employee_google_event_id="existing"))
    monkeypatch.setattr(ecs, "get_service_client", lambda: store)
    assert ecs.push_appointment_to_employee("org", "a1") is None


def test_push_skips_when_not_connected(monkeypatch):
    store = _ApptStore(_crm_appt())
    monkeypatch.setattr(ecs, "get_service_client", lambda: store)

    def _raise(*a, **k):
        raise oauth_tokens.OAuthTokenError("not connected")

    monkeypatch.setattr(employee_calendar, "get_valid_access_token", _raise)
    assert ecs.push_appointment_to_employee("org", "a1") is None
    assert store.updated is None


def test_remove_deletes_and_clears(monkeypatch):
    store = _ApptStore({"employee_google_event_id": "gid-1"})
    monkeypatch.setattr(ecs, "get_service_client", lambda: store)
    monkeypatch.setattr(employee_calendar, "get_valid_access_token", lambda *a, **k: "tok")
    monkeypatch.setattr(ecs, "_delete_event", lambda token, gid: True)
    assert ecs.remove_appointment_from_employee("org", "a1", employee_id="emp1") is True
    assert store.updated == {"employee_google_event_id": None}


def test_remove_noop_when_no_gid(monkeypatch):
    store = _ApptStore({"employee_google_event_id": None})
    monkeypatch.setattr(ecs, "get_service_client", lambda: store)
    assert ecs.remove_appointment_from_employee("org", "a1", employee_id="emp1") is False
