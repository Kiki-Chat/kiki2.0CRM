"""Post-call: an appointment the agent booked during a conversation fires its
confirmation call+email AFTER the call ends (matched via source_conversation_id),
not mid-call."""
from __future__ import annotations

from unittest.mock import MagicMock

import app.services.appointment_notify as an
from app.services import post_call


class _Chain:
    def __init__(self, db, table):
        self._db, self._t = db, table

    def __getattr__(self, _name):
        return lambda *a, **k: self

    def execute(self):
        r = MagicMock()
        r.data = self._db.get(self._t, [])
        return r


class _DB:
    def __init__(self, resp):
        self._resp = resp

    def get(self, t, d):
        return self._resp.get(t, d)

    def table(self, n):
        return _Chain(self, n)


class _SyncThread:
    """Run the target synchronously so the test can assert on the result."""

    def __init__(self, target=None, daemon=None):
        self._t = target

    def start(self):
        self._t()


def test_post_call_fires_confirmation_for_agent_booking(monkeypatch):
    monkeypatch.setattr(post_call.threading, "Thread", _SyncThread)
    monkeypatch.setattr(post_call, "get_service_client", lambda: _DB({"appointments": [{"id": "appt-x"}]}))
    fired: list = []
    monkeypatch.setattr(an, "notify_appointment_outcome", lambda org, aid, action: fired.append((org, aid, action)))

    post_call._fire_booking_confirmations("org-1", "conv-abc")
    assert fired == [("org-1", "appt-x", "confirm")]


def test_post_call_no_booking_no_fire(monkeypatch):
    monkeypatch.setattr(post_call.threading, "Thread", _SyncThread)
    monkeypatch.setattr(post_call, "get_service_client", lambda: _DB({"appointments": []}))
    fired: list = []
    monkeypatch.setattr(an, "notify_appointment_outcome", lambda *a: fired.append(a))

    post_call._fire_booking_confirmations("org-1", "conv-none")
    assert fired == []
