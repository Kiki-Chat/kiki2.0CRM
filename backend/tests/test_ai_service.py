"""Unit tests for the centralized AI service (Phase 0 — dormant-by-default).

No network or DB: the disabled path needs neither, and the enabled path is
exercised through the ``set_test_client`` injection hook (a fake OpenAI client).
"""
import pytest

from app.services.ai import client as ai_client
from app.services.ai import usage


class _FakeCompletions:
    def __init__(self, recorder: list[dict]):
        self._rec = recorder

    def create(self, **kwargs):
        self._rec.append(kwargs)
        return {"ok": True}


class _FakeChat:
    def __init__(self, recorder: list[dict]):
        self.completions = _FakeCompletions(recorder)


class _FakeClient:
    def __init__(self):
        self.calls: list[dict] = []
        self.chat = _FakeChat(self.calls)


def test_disabled_when_no_key(monkeypatch):
    monkeypatch.setattr(ai_client.settings, "openai_api_key", "")
    ai_client.set_test_client(None)  # resets init state
    assert ai_client.is_configured() is False
    with pytest.raises(ai_client.AIServiceDisabled):
        ai_client.chat([{"role": "user", "content": "hi"}])
    with pytest.raises(ai_client.AIServiceDisabled):
        ai_client.stream_chat([{"role": "user", "content": "hi"}])


def test_test_client_injection_routes_calls():
    fake = _FakeClient()
    ai_client.set_test_client(fake)
    try:
        assert ai_client.is_configured() is True
        resp = ai_client.chat(
            [{"role": "user", "content": "hi"}],
            tools=[{"type": "function"}],
            tool_choice="auto",
        )
        assert resp == {"ok": True}
        sent = fake.calls[-1]
        assert sent["model"]  # defaulted from config
        assert sent["tools"] and sent["tool_choice"] == "auto"
        assert "stream" not in sent

        ai_client.stream_chat([{"role": "user", "content": "hi"}])
        assert fake.calls[-1]["stream"] is True
    finally:
        ai_client.set_test_client(None)


def test_estimate_cost_known_and_unknown_model():
    known = usage.estimate_cost("gpt-4o-mini", 1000, 1000)
    assert known == round(0.00015 + 0.0006, 6)
    # Unknown model falls back to the default (mini) price — never silently free.
    assert usage.estimate_cost("some-future-model", 1000, 1000) == known
    assert usage.estimate_cost("gpt-4o-mini", 0, 0) == 0.0


def test_within_cap_disabled_when_no_cap(monkeypatch):
    monkeypatch.setattr(usage.settings, "copilot_monthly_cost_cap_usd", 0)
    assert usage.within_cap("any-org") is True  # no DB hit when cap is 0
