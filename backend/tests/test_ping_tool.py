"""PoC: the diagnostic ping tool + the conversation-init `environment` field that
drives ElevenLabs Environment-Variables routing for ONE shared tool."""
import types

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import conversation_init as ci

client = TestClient(app)


def test_ping_get_reports_backend_identity():
    r = client.get("/api/elevenlabs/tools/ping")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["ok"] is True
    assert b["backend_environment"] == settings.el_environment
    assert settings.el_environment in b["message"]  # agent can read this aloud


def test_ping_post_works_for_el_tool_calls():
    r = client.post("/api/elevenlabs/tools/ping", json={"_toolName": "ping"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_conversation_init_returns_environment(monkeypatch):
    class _T:
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def execute(self): return types.SimpleNamespace(data=[])

    class _C:
        def table(self, n): return _T()

    monkeypatch.setattr(ci, "get_service_client", lambda: _C())
    out = ci.conversation_init("org-1", None)
    assert out["type"] == "conversation_initiation_client_data"
    assert out["environment"] == settings.el_environment
