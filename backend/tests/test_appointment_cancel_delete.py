"""CRM cancel/delete → Google propagation (best-effort) + correct CRM state.

Hermetic: calendar_sync.delete_google_event is mocked (no Google call). Verifies
the Google delete is attempted ONLY when the event was pushed (google_event_id
set), and the CRM mutation happens regardless.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from app.api.routes import appointments as ar


class _Res:
    def __init__(self, data):
        self.data = data


class _Chain:
    def __init__(self, parent):
        self.parent = parent
        self._op = "select"

    def select(self, *a, **k):
        self._op = "select"
        return self

    def update(self, row):
        self._op = "update"
        self.parent.updated = row
        return self

    def delete(self):
        self._op = "delete"
        self.parent.deleted = True
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self._op == "select":
            return _Res([self.parent.appt] if self.parent.appt else [])
        if self._op == "update":
            return _Res([{**(self.parent.appt or {}), **self.parent.updated}])
        return _Res([{}])  # delete


class _Client:
    def __init__(self, appt):
        self.appt = appt
        self.updated = None
        self.deleted = False

    def table(self, name):
        return _Chain(self)


def _patch(monkeypatch, appt):
    client = _Client(appt)
    monkeypatch.setattr(ar, "get_service_client", lambda: client)
    dge = MagicMock(return_value=True)
    monkeypatch.setattr(ar.calendar_sync, "delete_google_event", dge)
    return client, dge


def test_cancel_pushed_event_deletes_google_and_clears_link(monkeypatch):
    client, dge = _patch(monkeypatch, {"id": "a1", "status": "confirmed", "google_event_id": "GEVT"})
    out = ar._cancel("org-1", "a1")
    dge.assert_called_once_with("org-1", "GEVT")
    assert client.updated["status"] == "cancelled"
    assert client.updated["google_event_id"] is None
    assert client.updated["cancelled_at"]  # stamped so the timeline + Aktion can surface it
    assert out["status"] == "cancelled"


def test_cancel_without_gid_skips_google(monkeypatch):
    client, dge = _patch(monkeypatch, {"id": "a2", "status": "confirmed", "google_event_id": None})
    ar._cancel("org-1", "a2")
    dge.assert_not_called()
    assert client.updated["status"] == "cancelled"
    assert client.updated["google_event_id"] is None
    assert client.updated["cancelled_at"]


def test_delete_pushed_event_deletes_google_and_removes_row(monkeypatch):
    client, dge = _patch(monkeypatch, {"id": "a3", "status": "confirmed", "google_event_id": "GEVT"})
    ok = ar._delete("org-1", "a3")
    dge.assert_called_once_with("org-1", "GEVT")
    assert ok is True and client.deleted is True


def test_delete_without_gid_skips_google(monkeypatch):
    client, dge = _patch(monkeypatch, {"id": "a4", "status": "confirmed", "google_event_id": None})
    ar._delete("org-1", "a4")
    dge.assert_not_called()
    assert client.deleted is True


def test_cancel_missing_returns_none(monkeypatch):
    _patch(monkeypatch, None)
    assert ar._cancel("org-1", "missing") is None
