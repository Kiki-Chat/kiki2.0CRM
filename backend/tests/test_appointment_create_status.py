"""The appointment create-path honours an optional initial status.

Default (calendar / planning-board) → 'confirmed'. The call-log create modal
passes 'pending' so the new appointment enters the open-action confirmation
stage. Any other value falls back to 'confirmed' (only those two are accepted)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import app.api.routes.appointments as appt
from app.api.deps import CurrentUser
from app.schemas.admin import AppointmentCreate

# A safely-future slot: the create-path now blocks backdating, so the fixture
# must lie in the future or the 422 guard fires before the status logic runs.
_FUTURE = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")


class _InsertChain:
    def __init__(self, sink):
        self.sink = sink

    def insert(self, row):
        self.sink["row"] = row
        return self

    def execute(self):
        return MagicMock(data=[{**self.sink["row"], "id": "appt-new"}])


class _Client:
    def __init__(self, sink):
        self.sink = sink

    def table(self, _name):
        return _InsertChain(self.sink)


def _user():
    return CurrentUser(id="u-1", email="admin@x.de", org_id="org-A", role="org_admin", full_name="Admin")


def _make(monkeypatch, **kw):
    sink: dict = {}
    monkeypatch.setattr(appt, "get_service_client", lambda: _Client(sink))
    monkeypatch.setattr(appt, "validate_fk_in_org", lambda *a, **k: None)
    monkeypatch.setattr(appt, "enforce_self_assignment", lambda *a, **k: None)
    appt._create(_user(), AppointmentCreate(scheduled_at=_FUTURE, **kw))
    return sink["row"]


def test_create_defaults_to_confirmed(monkeypatch):
    assert _make(monkeypatch)["status"] == "confirmed"


def test_create_honours_pending(monkeypatch):
    assert _make(monkeypatch, status="pending")["status"] == "pending"


def test_create_rejects_unknown_status_falls_back_to_confirmed(monkeypatch):
    assert _make(monkeypatch, status="garbage")["status"] == "confirmed"
