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
    monkeypatch.setattr(pds, "find_person", lambda cfg, phone, ctx=None: {"vorname": "Govind", "name": "Yadav"})
    out = pds.greeting_for_phone("org1", "+49155")
    assert out == {"greeting": "Hallo Govind Yadav , Willkommen zurück.", "status": "found"}

    monkeypatch.setattr(pds, "find_person", lambda cfg, phone, ctx=None: None)
    out = pds.greeting_for_phone("org1", "+49155")
    assert out["status"] == "new"
    assert "neuer Anrufer" in out["greeting"]


# ─── Audit logging + array-shape tolerance ───────────────────────────────────
def test_find_person_handles_array_wrapped_response(monkeypatch):
    # Real PDS sometimes wraps the object in a 1-element array — must still match.
    _mock_http(monkeypatch, [[{"totalHitCount": 1, "resultList": [{"uuid": "p-1", "vorname": "Max"}]}]])
    assert pds.find_person(_cfg(), "+49155") == {"uuid": "p-1", "vorname": "Max"}


def _capture_client(inserts):
    class _Tbl:
        def insert(self, row):
            inserts.append(row)
            return self
        def execute(self):
            return MagicMock(data=[{}])
    class _Client:
        def table(self, name):
            return _Tbl()
    return _Client()


def test_audit_logs_request_and_raw_response(monkeypatch):
    _mock_http(monkeypatch, [{"totalHitCount": 0, "resultList": []}])
    inserts: list[dict] = []
    monkeypatch.setattr(pds, "get_service_client", lambda: _capture_client(inserts))
    pds.find_person(_cfg(), "+4915511357330", ctx={"org_id": "org1", "operation": "greeting"})
    assert len(inserts) == 1
    row = inserts[0]
    assert row["org_id"] == "org1"
    assert row["operation"] == "greeting"
    assert row["endpoint"] == "person/listpersonen"
    assert row["status"] == "success"
    assert row["request_payload"]["suchwort"] == "004915511357330"
    assert row["response_payload"] == {"totalHitCount": 0, "resultList": []}


def test_audit_skipped_without_ctx(monkeypatch):
    _mock_http(monkeypatch, [{"totalHitCount": 0, "resultList": []}])
    touched: list[int] = []
    monkeypatch.setattr(pds, "get_service_client", lambda: touched.append(1) or MagicMock())
    pds.find_person(_cfg(), "+49155")  # no ctx → no audit write
    assert touched == []


def test_audit_never_raises(monkeypatch):
    _mock_http(monkeypatch, [{"totalHitCount": 0, "resultList": []}])

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(pds, "get_service_client", _boom)
    # audit write blows up → swallowed → find_person still returns its result
    assert pds.find_person(_cfg(), "+49155", ctx={"org_id": "o", "operation": "greeting"}) is None


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


# ─── Route auth: greeting + create-contact are ElevenLabs tool webhooks ───────
# Regression guard for the bug where these used require_org (a logged-in user's
# JWT) — which the voice agent can never present. They MUST authenticate exactly
# like every other tool webhook (resolve_tool_org: X-HeyKiki-Secret / _agentId).
from fastapi.testclient import TestClient  # noqa: E402

from app.api import deps  # noqa: E402
from app.main import app  # noqa: E402

_client = TestClient(app)


def test_greeting_route_uses_tool_org_auth_not_user_jwt(monkeypatch):
    """POST /api/pds/greeting resolves the org via resolve_tool_org and passes it
    to the service — no Authorization header required (the agent has none)."""
    app.dependency_overrides[deps.resolve_tool_org] = lambda: deps.ToolOrg(org_id="org-agent")
    seen = {}
    monkeypatch.setattr(
        pds, "greeting_for_phone",
        lambda org_id, phone: seen.update(org_id=org_id, phone=phone)
        or {"greeting": "Hallo", "status": "found"},
    )
    try:
        # No Authorization header — the agent sends _agentId in the body instead.
        resp = _client.post("/api/pds/greeting", json={"phoneNumber": "+4915511357330", "_agentId": "agent_x"})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"greeting": "Hallo", "status": "found"}
    assert seen == {"org_id": "org-agent", "phone": "+4915511357330"}


def test_create_contact_route_uses_tool_org_auth(monkeypatch):
    app.dependency_overrides[deps.resolve_tool_org] = lambda: deps.ToolOrg(org_id="org-agent")
    seen = {}
    monkeypatch.setattr(
        pds, "create_contact",
        lambda org_id, **kw: seen.update(org_id=org_id, **kw)
        or {"message": "ok", "status": "created", "personUUID": "u1"},
    )
    try:
        resp = _client.post(
            "/api/pds/create-contact",
            json={"fullName": "Govind Yadav", "phoneNumber": "+4915511357330", "_agentId": "agent_x"},
        )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "created"
    assert seen["org_id"] == "org-agent"
    assert seen["full_name"] == "Govind Yadav"