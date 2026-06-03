"""Hermetic tests for the dynamic (placeholder-template) prompt pipeline.

No network, no DB. The render_*_block helpers are pure; rerender_and_push_for_org
is exercised with a fake Supabase client + a recorded patch_agent_safely.
"""

from __future__ import annotations

import re

from app.services import agent_config as ac

ORG_ID = "00000000-0000-0000-0000-000000000222"

_SYS = re.compile(r"\{\{(?!system__)[^}]+\}\}")  # any non-system leftover token


def _leftover(text: str) -> list[str]:
    return sorted(set(_SYS.findall(text)))


# ─── render_required_fields_block ────────────────────────────────────────────
def test_required_fields_empty_has_sensible_fallback():
    out = ac.render_required_fields_block([])
    assert "Name" in out and "Telefonnummer" in out


def test_required_fields_lists_label_description_and_optional():
    fields = [
        {"label": "Name", "description": "Vor- und Nachname", "is_duty": True,
         "identification_role": None},
        {"label": "Kundennummer", "description": "Falls vorhanden", "is_duty": False,
         "identification_role": "customer_number"},
    ]
    out = ac.render_required_fields_block(fields)
    assert "Name" in out and "Vor- und Nachname" in out
    assert "Kundennummer" in out and "Falls vorhanden" in out
    assert "optional" in out.lower()  # the non-Pflicht field is marked optional


# ─── render_problem_description_block ────────────────────────────────────────
def test_problem_description_empty_is_blank():
    assert ac.render_problem_description_block(None) == ""
    assert ac.render_problem_description_block("   ") == ""


def test_problem_description_includes_text():
    txt = "Bei Heizungsproblemen Hersteller und Baujahr erfragen."
    assert txt in ac.render_problem_description_block(txt)


# ─── render_appointment_categories_block ─────────────────────────────────────
def test_categories_empty_fallback_has_no_hardcoded_wartung():
    out = ac.render_appointment_categories_block([])
    assert "Wartung" not in out
    assert "naheliegendste" in out.lower()


def test_categories_render_name_duration_employee_description():
    cats = [
        {"name": "Heizungswartung", "duration_minutes": 90,
         "description": "Jährliche Wartung", "employee_name": "Luca"},
    ]
    out = ac.render_appointment_categories_block(cats)
    assert "Heizungswartung" in out and "90" in out
    assert "Jährliche Wartung" in out and "Luca" in out


# ─── render_scheduling_rules_block ───────────────────────────────────────────
def test_scheduling_disabled_says_no_booking():
    out = ac.render_scheduling_rules_block({"scheduling_enabled": False})
    assert "hk_bookAppointment" in out
    # must instruct NOT to book
    assert "KEINE" in out or "keine" in out


def test_scheduling_enabled_renders_lead_time_and_clock():
    out = ac.render_scheduling_rules_block(
        {"scheduling_enabled": True, "lead_time_days": 2,
         "lead_time_only_weekdays": True, "lead_time_earliest_clock": "13:00"}
    )
    assert "2" in out and "Werktage" in out
    assert "13:00" in out


# ─── render_emergency_block ──────────────────────────────────────────────────
def test_emergency_disabled_says_no_notdienst():
    out = ac.render_emergency_block({"emergency_enabled": False})
    assert "Kein Notdienst" in out


def test_emergency_enabled_lists_configured_keywords():
    out = ac.render_emergency_block(
        {"emergency_enabled": True,
         "emergency_keywords": ["Rohrbruch", "Gasgeruch"],
         "emergency_only_outside_business_hours": True}
    )
    assert "Rohrbruch" in out and "Gasgeruch" in out
    assert "NOTFALL" in out


# ─── render_prompt_for_org (name-only, no DB) ────────────────────────────────
def test_render_prompt_name_only_fills_tokens_no_residue():
    p = ac.render_prompt_for_org("Testfirma GmbH", {"trade": "Elektro"})
    assert "Testfirma GmbH" in p
    assert "Elektro" in p
    assert _leftover(p) == []  # every {{...}} token filled (system vars excepted)
    # de-Husmanned: no demo identity literals survive
    for bad in ("Husmann", "Dreier", "Buxtehude", "Stader"):
        assert bad not in p


def test_render_prompt_trade_fallback_when_missing():
    p = ac.render_prompt_for_org("Nur Name GmbH", {})
    assert _leftover(p) == []
    assert "Nur Name GmbH" in p


# ─── rerender_and_push_for_org gating (fake client) ──────────────────────────
class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, data):
        self._data = data

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return _Resp(self._data)


class _Client:
    def __init__(self, tables):
        self._tables = tables

    def table(self, name):
        return _Query(self._tables.get(name, []))


def test_rerender_skips_on_manual_override(monkeypatch):
    monkeypatch.setattr(
        ac, "get_service_client",
        lambda: _Client({"agent_configs": [{"prompt_manual_override": True}]}),
    )
    res = ac.rerender_and_push_for_org(org_id=ORG_ID, endpoint_label="kz_test")
    assert res == {"updated": False, "reason": "manual_override"}


def test_rerender_soft_noop_when_no_agent(monkeypatch):
    monkeypatch.setattr(
        ac, "get_service_client",
        lambda: _Client({
            "agent_configs": [{"prompt_manual_override": False}],
            "organizations": [{"name": "X GmbH", "elevenlabs_agent_id": None}],
        }),
    )
    res = ac.rerender_and_push_for_org(org_id=ORG_ID, endpoint_label="kz_test")
    assert res == {"updated": False, "reason": "no_agent"}


def test_rerender_pushes_via_patch_agent_safely(monkeypatch):
    monkeypatch.setattr(
        ac, "get_service_client",
        lambda: _Client({
            "agent_configs": [{"prompt_manual_override": False}],
            "organizations": [{"name": "X GmbH", "elevenlabs_agent_id": "agent_xyz"}],
        }),
    )
    monkeypatch.setattr(ac, "_fetch_org_identity", lambda oid: {"name": "X GmbH"})
    monkeypatch.setattr(ac, "render_prompt_for_org", lambda *a, **k: "RENDERED PROMPT")
    calls = {}

    def _rec(**kw):
        calls.update(kw)
        return {"ok": True}

    monkeypatch.setattr(ac, "patch_agent_safely", _rec)
    res = ac.rerender_and_push_for_org(
        org_id=ORG_ID, actor_id="u1", endpoint_label="kz_emergency"
    )
    assert res == {"updated": True}
    assert calls["agent_id"] == "agent_xyz"
    assert calls["endpoint_label"] == "kz_emergency"
    assert calls["merge_arrays"] == []
    # prompt is written at the conversation_config.agent.prompt.prompt path
    assert (
        calls["field_patches"]["conversation_config"]["agent"]["prompt"]["prompt"]
        == "RENDERED PROMPT"
    )
