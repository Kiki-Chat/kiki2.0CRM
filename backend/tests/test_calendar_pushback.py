"""Calendar write-back (Phase 4): per-event push, echo-loop guard (crm-only),
idempotency, grant resolution via the calendar purpose link, and 404 handling.

Hermetic — events.insert is mocked; nothing is pushed to a live Google calendar.
"""
from __future__ import annotations

import pytest

from app.services import calendar_sync as cs


class _Res:
    def __init__(self, data):
        self.data = data


class _PushChain:
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

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self._op == "update":
            self.parent.updates.append(self._payload)
            return _Res([{}])
        return _Res([self.parent.appt] if self.parent.appt else [])


class _PushClient:
    """Fake client: returns one appointment for select; records update payloads."""

    def __init__(self, appt):
        self.appt = appt
        self.updates: list = []

    def table(self, name):
        return _PushChain(self)


def _appt(**over):
    base = {
        "id": "a1", "source": "crm", "google_event_id": None, "title": "Kundentermin",
        "scheduled_at": "2026-06-02T08:00:00+00:00", "duration_minutes": 90,
        "notes": "Heizung prüfen", "location": {"raw": "Baustelle 1"},
    }
    base.update(over)
    return base


def _no_insert(*a, **k):
    raise AssertionError("_insert_event must NOT be called")


def _patch(monkeypatch, appt, provider="google"):
    client = _PushClient(appt)
    monkeypatch.setattr(cs, "get_service_client", lambda: client)
    monkeypatch.setattr(cs, "calendar_provider", lambda org: provider)
    monkeypatch.setattr(cs, "get_valid_access_token", lambda org, prov: "tok")
    return client


def test_push_crm_event_inserts_and_stores_gid(monkeypatch):
    client = _patch(monkeypatch, _appt())
    captured: dict = {}
    monkeypatch.setattr(cs, "_insert_event", lambda token, body: captured.update(body) or "GEVT123")

    out = cs.push_crm_event_to_google("org-1", "a1")
    assert out == {"success": True, "google_event_id": "GEVT123"}
    assert client.updates == [{"google_event_id": "GEVT123"}]  # stored on the appointment
    assert captured["summary"] == "Kundentermin"
    assert captured["start"]["dateTime"].startswith("2026-06-02T08:00:00")
    assert captured["end"]["dateTime"].startswith("2026-06-02T09:30:00")  # +90 min
    assert captured["location"] == "Baustelle 1"
    assert captured["description"] == "Heizung prüfen"


def test_push_rejects_google_import_event(monkeypatch):
    """ECHO-LOOP GUARD (push side): an imported event is never written back."""
    _patch(monkeypatch, _appt(id="g1", source="google_import", google_event_id="X"))
    monkeypatch.setattr(cs, "_insert_event", _no_insert)
    with pytest.raises(cs.CalendarWriteError) as e:
        cs.push_crm_event_to_google("org-1", "g1")
    assert e.value.status == 400


def test_push_already_pushed_is_idempotent(monkeypatch):
    _patch(monkeypatch, _appt(id="a2", google_event_id="EXISTING"))
    monkeypatch.setattr(cs, "_insert_event", _no_insert)
    out = cs.push_crm_event_to_google("org-1", "a2")
    assert out["already_pushed"] is True and out["google_event_id"] == "EXISTING"


def test_push_requires_google_calendar_linked(monkeypatch):
    _patch(monkeypatch, _appt(id="a3"), provider=None)  # no calendar provider linked
    monkeypatch.setattr(cs, "_insert_event", _no_insert)
    with pytest.raises(cs.CalendarWriteError) as e:
        cs.push_crm_event_to_google("org-1", "a3")
    assert e.value.status == 409


def test_push_not_found(monkeypatch):
    _patch(monkeypatch, None)
    with pytest.raises(cs.CalendarWriteError) as e:
        cs.push_crm_event_to_google("org-1", "missing")
    assert e.value.status == 404
