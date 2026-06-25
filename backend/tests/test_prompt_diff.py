"""Hermetic tests for the read-only prompt-difference classifier.

No network, no DB: the live EL read (get_agent_config) and the template render
(render_prompt_for_org) are monkeypatched.
"""
from __future__ import annotations

from app.services import prompt_diff as pd

ORG_ID = "00000000-0000-0000-0000-000000000222"
AGENT_ID = "agent_diff_test"

_TEMPLATE = """# Rolle
Du bist Kiki, die Telefon-Assistentin.
Du nimmst Anliegen auf und vereinbarst Termine.
# Datenaufnahme
Frage nach Name und Telefonnummer.
Es ist {{system__time}}."""


def _cfg(prompt: str) -> dict:
    return {"conversation_config": {"agent": {"prompt": {"prompt": prompt}}}}


def _wire(monkeypatch, *, live: str, template: str = _TEMPLATE):
    monkeypatch.setattr(pd, "get_agent_config", lambda _aid: _cfg(live))
    monkeypatch.setattr(pd, "render_prompt_for_org", lambda *a, **k: template)


def test_default_when_live_matches_template(monkeypatch):
    _wire(monkeypatch, live=_TEMPLATE)
    out = pd.classify_agent_prompt(ORG_ID, AGENT_ID, "ACME")
    assert out["available"] is True
    assert out["status"] == "DEFAULT"
    assert out["coverage_pct"] == 100.0
    assert out["added_count"] == 0


def test_custom_when_live_diverges(monkeypatch):
    live = """Rolle
Du bist Gabi, eine lockere Assistentin für KFZ.
Notdienst nur von 8 bis 20 Uhr.
Verfügbare Mitarbeiter: Herr Nebel, Frau Klein.
Am 14.05.2026 ist Feiertag."""
    _wire(monkeypatch, live=live)
    out = pd.classify_agent_prompt(ORG_ID, AGENT_ID, "ACME")
    assert out["available"] is True
    assert out["status"] == "CUSTOM"
    assert out["coverage_pct"] < 55.0
    assert out["added_count"] >= 3
    # The customer's own lines surface as samples (lowercased, marker-stripped).
    assert any("herr nebel" in s for s in out["sample_added"])


def test_unavailable_when_live_empty(monkeypatch):
    _wire(monkeypatch, live="   ")
    out = pd.classify_agent_prompt(ORG_ID, AGENT_ID, "ACME")
    assert out["available"] is False
    assert out["status"] is None
    assert out["error"]


def test_unavailable_when_live_read_raises(monkeypatch):
    def _boom(_aid):
        raise RuntimeError("EL 503")

    monkeypatch.setattr(pd, "get_agent_config", _boom)
    monkeypatch.setattr(pd, "render_prompt_for_org", lambda *a, **k: _TEMPLATE)
    out = pd.classify_agent_prompt(ORG_ID, AGENT_ID, "ACME")
    assert out["available"] is False
    assert "nicht lesbar" in (out["error"] or "")


def test_unavailable_when_template_render_raises(monkeypatch):
    monkeypatch.setattr(pd, "get_agent_config", lambda _aid: _cfg("Du bist Kiki."))

    def _boom(*a, **k):
        raise RuntimeError("missing config")

    monkeypatch.setattr(pd, "render_prompt_for_org", _boom)
    out = pd.classify_agent_prompt(ORG_ID, AGENT_ID, "ACME")
    assert out["available"] is False
    assert "Template" in (out["error"] or "")
