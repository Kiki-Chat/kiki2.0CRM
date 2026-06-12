"""PDS integration — the n8n-workflow ports are the contract under test:
phone +→00, subject normalisation into the 9 categories, the German
ANRUFPROTOKOLL task for found/unknown callers, the greeting contract, and the
auto-sync gating (only ready+enabled configs; failures never raise)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services import pds


# ─── Pure ports of the n8n Code nodes ────────────────────────────────────────
def test_transform_phone_plus_to_00():
    assert pds.transform_phone("+4915511357330") == "004915511357330"
    assert pds.transform_phone("004915511357330") == "004915511357330"
    assert pds.transform_phone(None) == ""


def test_normalize_subject_exact_case_insensitive_fallback():
    assert pds.normalize_subject("Terminanfrage") == "Terminanfrage"
    assert pds.normalize_subject("terminanfrage") == "Terminanfrage"
    assert pds.normalize_subject("Quatsch") == "Allgemeine Anfrage"
    assert pds.normalize_subject(None) == "Allgemeine Anfrage"


def test_build_task_found_person():
    call_data = {
        "originalPhone": "+4915511357330",
        "duration": 134,
        "callTitle": "New appointment booked May second",
        "summary": "Caller requested an appointment.",
        "subject": "Terminanfrage",
        "transcriptLink": "https://t.example/x",
        "timestamp": "2026-06-12T08:00:00+00:00",
    }
    person = {"uuid": "p-1", "vorname": "Govind", "name": "Yadav"}
    task = pds.build_task(call_data, person)
    assert task["personUUID"] == "p-1"
    assert task["personName"] == "Govind Yadav"
    assert task["subject"].startswith("Terminanfrage: New appointment booked May second - ")
    assert "(Unbekannt)" not in task["subject"]
    assert "📞 ANRUFPROTOKOLL" in task["description"]
    assert "Anrufer: Govind Yadav" in task["description"]
    assert "Dauer: 2m 14s" in task["description"]
    assert "Transkript/Aufzeichnung: https://t.example/x" in task["description"]
    assert "manuell zuordnen" not in task["description"]


def test_build_task_unknown_caller():
    call_data = {
        "originalPhone": "+491234", "duration": 61, "callTitle": "",
        "summary": "S", "subject": "Beschwerde", "transcriptLink": "",
        "timestamp": "2026-06-12T08:00:00+00:00",
    }
    task = pds.build_task(call_data, None)
    assert task["personUUID"] is None
    assert "(Unbekannt)" in task["subject"]
    assert "Kontakt nicht gefunden" in task["description"]
    assert "⚠️ HINWEIS" in task["description"]
    assert "Dauer: 1m 1s" in task["description"]


# ─── HTTP-level ops (httpx mocked) ───────────────────────────────────────────
def _cfg(**over):
    base = {"api_url": "https://41309.pdscloud.de", "api_key_encrypted": "enc", "sync_entities": {}}
    base.update(over)
    return base


def _mock_http(monkeypatch, responses: list[dict]):
    calls: list[tuple[str, dict]] = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append((url, json))
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = responses[min(len(calls) - 1, len(responses) - 1)]
        return resp

    monkeypatch.setattr(pds.httpx, "post", fake_post)
    monkeypatch.setattr(pds, "decrypt", lambda v: "tok")
    return calls


def test_find_person_hits_listpersonen_with_00_phone(monkeypatch):
    calls = _mock_http(monkeypatch, [{"totalHitCount": 1, "resultList": [{"uuid": "p-9", "vorname": "Max"}]}])
    person = pds.find_person(_cfg(), "+49155")
    assert person == {"uuid": "p-9", "vorname": "Max"}
    url, body = calls[0]
    assert url == "https://41309.pdscloud.de/pds/rest/api/person/listpersonen"
    assert body["suchwort"] == "0049155"
    assert body["suchfelder"] == ["ALLES"]


def test_find_person_none_on_zero_hits(monkeypatch):
    _mock_http(monkeypatch, [{"totalHitCount": 0, "resultList": []}])
    assert pds.find_person(_cfg(), "+49155") is None


def test_create_task_uses_type_uuid_override(monkeypatch):
    calls = _mock_http(monkeypatch, [{"uuid": "task-1"}])
    pds.create_task(
        _cfg(sync_entities={"task_type_uuid": "custom-uuid"}),
        {"subject": "S", "description": "D", "timestamp": "T", "personUUID": "p-1"},
    )
    _, body = calls[0]
    assert body["typUUID"] == "custom-uuid"
    assert body["personUUID"] == "p-1"
    assert body["betreff"] == "S"


def test_post_raises_german_on_401(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        resp = MagicMock()
        resp.status_code = 401
        return resp

    monkeypatch.setattr(pds.httpx, "post", fake_post)
    monkeypatch.setattr(pds, "decrypt", lambda v: "tok")
    with pytest.raises(pds.PdsError, match="API-Schlüssel"):
        pds._post(_cfg(), "person/listpersonen", {})


# ─── Greeting contract (workflow 2a) ─────────────────────────────────────────
def test_greeting_found_and_new(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(pds, "get_service_client", lambda: client)
    monkeypatch.setattr(pds, "get_config", lambda c, o: _cfg())
    monkeypatch.setattr(pds, "find_person", lambda cfg, phone: {"vorname": "Govind", "name": "Yadav"})
    out = pds.greeting_for_phone("org1", "+49155")
    assert out == {"greeting": "Hallo Govind Yadav , Willkommen zurück.", "status": "found"}

    monkeypatch.setattr(pds, "find_person", lambda cfg, phone: None)
    out = pds.greeting_for_phone("org1", "+49155")
    assert out["status"] == "new"
    assert "neuer Anrufer" in out["greeting"]


# ─── Auto-sync gating ────────────────────────────────────────────────────────
def test_safe_auto_log_skips_when_not_enabled(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(pds, "get_config", lambda c, o: _cfg(auto_sync_enabled=False))
    called = []
    monkeypatch.setattr(pds, "log_call", lambda o, c: called.append(1))
    pds.safe_auto_log_call(client, "org1", {"id": "c1"})
    assert called == []


def test_safe_auto_log_skips_already_synced(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(pds, "get_config", lambda c, o: _cfg(auto_sync_enabled=True))
    called = []
    monkeypatch.setattr(pds, "log_call", lambda o, c: called.append(1))
    pds.safe_auto_log_call(client, "org1", {"id": "c1", "pds_synced_at": "2026-06-12T08:00:00Z"})
    assert called == []


def test_safe_auto_log_never_raises(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(pds, "get_config", lambda c, o: _cfg(auto_sync_enabled=True))

    def _boom(o, c):
        raise pds.PdsError("down")

    monkeypatch.setattr(pds, "log_call", _boom)
    pds.safe_auto_log_call(client, "org1", {"id": "c1"})  # must not raise