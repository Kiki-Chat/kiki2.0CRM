"""Hermetic tests for the Batch-2 backend verify gate + graceful no-phone.

Covers:
  * verify_agent_health — green (all 7 checks pass) vs. each individual red
    check (hk_tools_attached, webhook_url_is_prod, webhook_enabled,
    audio_event_present, prompt_rendered, override_flags_on, phone_bound), plus
    the unreachable-agent path.
  * configure_agent — graceful no-phone: a missing phone does NOT abort the
    provision; B.2-B.6 still run, phone_bound=false + the actionable German
    message is recorded, and the happy path stays identical when a phone IS bound.

No network, no DB: ElevenLabs HTTP + Supabase access are monkeypatched.
"""

from __future__ import annotations

import copy

import pytest
from fastapi import HTTPException

from app.services import agent_config as ac
from app.services.elevenlabs_agent import (
    CLIENT_EVENTS_PATH,
    OVERRIDES_WHITELIST_AGENT_PATH,
    PROMPT_PATH,
    REQUIRED_AUDIO_EVENT,
    TOOL_IDS_PATH,
    WEBHOOK_ENABLED_PATH,
    WEBHOOK_URL_PATH,
    _set_path,
)


AGENT_ID = "agent_verify_xyz"
ORG_ID = "00000000-0000-0000-0000-000000000222"
ORG_NAME = "Verify Test GmbH"

# tool_id values the stubbed workspace returns for each hk_* name.
_TOOL_IDS = [f"tool_{n}" for n in ac.HK_TOOL_NAMES]


# ─── builders ─────────────────────────────────────────────────────────────────
def _green_config() -> dict:
    """A live-agent config dict where every contract check passes."""
    cfg: dict = {}
    _set_path(cfg, TOOL_IDS_PATH, list(_TOOL_IDS))
    _set_path(cfg, WEBHOOK_URL_PATH, ac._PROD_WEBHOOK_URL)
    _set_path(cfg, WEBHOOK_ENABLED_PATH, True)
    _set_path(cfg, CLIENT_EVENTS_PATH, [REQUIRED_AUDIO_EVENT])
    _set_path(cfg, PROMPT_PATH, "Du bist Kiki, die Telefonassistentin von Verify Test GmbH.")
    _set_path(
        cfg,
        OVERRIDES_WHITELIST_AGENT_PATH,
        {"first_message": True, "language": True, "prompt": {"prompt": True}},
    )
    return cfg


def _stub_green_environment(
    monkeypatch,
    *,
    config: dict,
    phone: str | None = "+4925197593899",
    stored_phone: str | None = None,
):
    """Wire up verify_agent_health's external reads against a given config + phone.

    ``phone`` is the number bound LIVE to the agent in ElevenLabs; ``stored_phone``
    is the number cached on the org row (organizations.phone_number). Either one
    satisfies phone_bound — the stored fallback is mocked here so the verify tests
    stay hermetic (no live DB read)."""
    monkeypatch.setattr(ac, "get_agent_config", lambda agent_id: copy.deepcopy(config))
    monkeypatch.setattr(ac, "_fetch_provisioned_at", lambda org_id: "2026-06-17T10:00:00+00:00")
    monkeypatch.setattr(ac, "_fetch_org_phone", lambda org_id: stored_phone)
    # Tool resolution → all hk_* names map to tool_<name>.
    monkeypatch.setattr(
        ac, "_fetch_workspace_tools", lambda: {n: f"tool_{n}" for n in ac.HK_TOOL_NAMES}
    )
    ac._HK_TOOL_ID_CACHE.clear()

    if phone is None:
        def _no_phone(agent_id):
            raise HTTPException(status_code=400, detail="no phone number assigned")

        monkeypatch.setattr(ac, "fetch_phone_meta_for_agent", _no_phone)
    else:
        monkeypatch.setattr(
            ac,
            "fetch_phone_meta_for_agent",
            lambda agent_id: {"phone_number": phone, "phone_number_id": "pid_1"},
        )


def _check_by_name(report: dict, name: str) -> dict:
    for c in report["checks"]:
        if c["name"] == name:
            return c
    raise AssertionError(f"check {name!r} not present in report")


# ─── verify_agent_health: green ──────────────────────────────────────────────
def test_verify_all_green(monkeypatch):
    _stub_green_environment(monkeypatch, config=_green_config())
    report = ac.verify_agent_health(ORG_ID, AGENT_ID)
    assert report["ok"] is True
    assert report["provisioned_at"] == "2026-06-17T10:00:00+00:00"
    names = [c["name"] for c in report["checks"]]
    assert names == [
        "hk_tools_attached",
        "webhook_url_is_prod",
        "webhook_enabled",
        "audio_event_present",
        "prompt_rendered",
        "override_flags_on",
        "phone_bound",
    ]
    assert all(c["ok"] for c in report["checks"])


# ─── verify_agent_health: each red check ─────────────────────────────────────
def test_verify_red_missing_tool(monkeypatch):
    cfg = _green_config()
    # Drop one tool id from the agent → hk_tools_attached red.
    _set_path(cfg, TOOL_IDS_PATH, list(_TOOL_IDS[1:]))
    _stub_green_environment(monkeypatch, config=cfg)
    report = ac.verify_agent_health(ORG_ID, AGENT_ID)
    assert report["ok"] is False
    tools = _check_by_name(report, "hk_tools_attached")
    assert tools["ok"] is False
    assert ac.HK_TOOL_NAMES[0] in tools["detail"]


def test_verify_red_webhook_url_not_prod(monkeypatch):
    cfg = _green_config()
    _set_path(cfg, WEBHOOK_URL_PATH, "http://localhost:8000/api/elevenlabs/conversation-init")
    _stub_green_environment(monkeypatch, config=cfg)
    report = ac.verify_agent_health(ORG_ID, AGENT_ID)
    assert report["ok"] is False
    assert _check_by_name(report, "webhook_url_is_prod")["ok"] is False
    # The other checks remain green.
    assert _check_by_name(report, "webhook_enabled")["ok"] is True


def test_verify_red_webhook_disabled(monkeypatch):
    cfg = _green_config()
    _set_path(cfg, WEBHOOK_ENABLED_PATH, False)
    _stub_green_environment(monkeypatch, config=cfg)
    report = ac.verify_agent_health(ORG_ID, AGENT_ID)
    assert report["ok"] is False
    assert _check_by_name(report, "webhook_enabled")["ok"] is False


def test_verify_red_audio_missing(monkeypatch):
    cfg = _green_config()
    _set_path(cfg, CLIENT_EVENTS_PATH, ["transcript"])  # no 'audio'
    _stub_green_environment(monkeypatch, config=cfg)
    report = ac.verify_agent_health(ORG_ID, AGENT_ID)
    assert report["ok"] is False
    assert _check_by_name(report, "audio_event_present")["ok"] is False


def test_verify_red_prompt_empty(monkeypatch):
    cfg = _green_config()
    _set_path(cfg, PROMPT_PATH, "   ")
    _stub_green_environment(monkeypatch, config=cfg)
    report = ac.verify_agent_health(ORG_ID, AGENT_ID)
    assert report["ok"] is False
    assert _check_by_name(report, "prompt_rendered")["ok"] is False


def test_verify_red_prompt_unsubstituted_token(monkeypatch):
    cfg = _green_config()
    _set_path(cfg, PROMPT_PATH, "Du bist Kiki von {{COMPANY_NAME}}.")
    _stub_green_environment(monkeypatch, config=cfg)
    report = ac.verify_agent_health(ORG_ID, AGENT_ID)
    assert report["ok"] is False
    prompt = _check_by_name(report, "prompt_rendered")
    assert prompt["ok"] is False
    assert "{{" in prompt["detail"] or "Platzhalter" in prompt["detail"]


def test_verify_green_keeps_el_dynamic_variables(monkeypatch):
    # EL dynamic variables ({{system__*}} / lowercase) legitimately remain in the
    # prompt and must NOT trip prompt_rendered — only UPPER_SNAKE CRM tokens do.
    cfg = _green_config()
    _set_path(
        cfg, PROMPT_PATH,
        "Du bist Kiki. Es ist {{system__time}}, Anrufer-Nr {{system__caller_id}}.",
    )
    _stub_green_environment(monkeypatch, config=cfg)
    report = ac.verify_agent_health(ORG_ID, AGENT_ID)
    assert _check_by_name(report, "prompt_rendered")["ok"] is True
    assert report["ok"] is True


def test_verify_red_override_flags_off(monkeypatch):
    cfg = _green_config()
    _set_path(
        cfg,
        OVERRIDES_WHITELIST_AGENT_PATH,
        {"first_message": True, "language": False, "prompt": {"prompt": True}},
    )
    _stub_green_environment(monkeypatch, config=cfg)
    report = ac.verify_agent_health(ORG_ID, AGENT_ID)
    assert report["ok"] is False
    assert _check_by_name(report, "override_flags_on")["ok"] is False


def test_verify_red_no_phone(monkeypatch):
    # No live EL number AND no number stored on the org → phone_bound red.
    _stub_green_environment(
        monkeypatch, config=_green_config(), phone=None, stored_phone=None
    )
    report = ac.verify_agent_health(ORG_ID, AGENT_ID)
    assert report["ok"] is False
    phone = _check_by_name(report, "phone_bound")
    assert phone["ok"] is False
    assert phone["detail"] == ac.NO_PHONE_MESSAGE
    # Everything else stays green — only the phone check is red.
    others = [c for c in report["checks"] if c["name"] != "phone_bound"]
    assert all(c["ok"] for c in others)


def test_verify_phone_from_stored_record(monkeypatch):
    # No number bound live in EL, but one is cached on the org row (synced from
    # the Sprach-ID / typed at create) → phone_bound GREEN. This is the #2 fix:
    # editing/syncing the number resolves the phone health problem.
    _stub_green_environment(
        monkeypatch, config=_green_config(), phone=None, stored_phone="+4930123456"
    )
    report = ac.verify_agent_health(ORG_ID, AGENT_ID)
    phone = _check_by_name(report, "phone_bound")
    assert phone["ok"] is True
    assert "+4930123456" in phone["detail"]
    assert "Org-Datensatz" in phone["detail"]  # signals it came from the cache
    assert report["ok"] is True


def test_verify_unreachable_agent_all_red(monkeypatch):
    def _boom(agent_id):
        raise RuntimeError("EL 503")

    monkeypatch.setattr(ac, "get_agent_config", _boom)
    monkeypatch.setattr(ac, "_fetch_provisioned_at", lambda org_id: None)
    report = ac.verify_agent_health(ORG_ID, AGENT_ID)
    assert report["ok"] is False
    assert report["provisioned_at"] is None
    assert len(report["checks"]) == 7
    assert all(c["ok"] is False for c in report["checks"])


# ─── configure_agent: graceful no-phone (2.3) ────────────────────────────────
def _stub_configure_environment(monkeypatch, *, phone_raises: bool):
    """Stub every external write/read configure_agent performs so we can assert
    the no-phone branch runs B.2-B.6 and records the graceful signal."""
    calls = {"patches": [], "stamped": False, "stored_phone": None}

    # B.1 phone
    if phone_raises:
        def _phone(agent_id):
            raise HTTPException(status_code=400, detail="no phone number assigned")
    else:
        def _phone(agent_id):
            return {"phone_number": "+4925197593899", "phone_number_id": "pid_1"}
    monkeypatch.setattr(ac, "fetch_phone_meta_for_agent", _phone)
    monkeypatch.setattr(
        ac, "_store_phone_on_org",
        lambda org_id, num, pid=None: calls.__setitem__("stored_phone", num),
    )

    # provisioned-at state (first run) + stamp
    monkeypatch.setattr(ac, "_is_agent_already_provisioned", lambda org_id: False)
    monkeypatch.setattr(
        ac, "_stamp_agent_provisioned", lambda org_id: calls.__setitem__("stamped", True)
    )

    # B.2 tools
    monkeypatch.setattr(
        ac, "_fetch_workspace_tools", lambda: {n: f"tool_{n}" for n in ac.HK_TOOL_NAMES}
    )
    ac._HK_TOOL_ID_CACHE.clear()

    # B.3 prompt rendering + org identity (kept trivial; we don't assert prompt text)
    monkeypatch.setattr(ac, "_fetch_org_identity", lambda org_id: {"name": ORG_NAME})
    monkeypatch.setattr(
        ac, "render_prompt_for_org", lambda *a, **k: "Gerenderter Prompt ohne Platzhalter."
    )

    # The live-agent reads between steps: tool_ids empty (so B.2 patches), prompt
    # empty (so B.3 patches), no audio (so B.5 patches), no override flags (so B.6
    # patches), webhook unset (so B.4 patches). A fresh agent.
    monkeypatch.setattr(ac, "get_agent_config", lambda agent_id: {})

    def _fake_patch(*, agent_id, field_patches, endpoint_label, **kw):
        calls["patches"].append(endpoint_label)

    monkeypatch.setattr(ac, "patch_agent_safely", _fake_patch)
    return calls


def test_configure_agent_graceful_no_phone(monkeypatch):
    calls = _stub_configure_environment(monkeypatch, phone_raises=True)
    summary = ac.configure_agent(org_id=ORG_ID, agent_id=AGENT_ID, org_name=ORG_NAME)

    # Provision did NOT abort — phone signal recorded, message actionable.
    assert summary["phone_bound"] is False
    assert summary["phone_number"] is None
    assert summary["phone_message"] == ac.NO_PHONE_MESSAGE
    assert (
        summary["phone_message"]
        == "Keine Telefonnummer im ElevenLabs-Agent hinterlegt — bitte zuerst eine Nummer zuweisen"
    )

    # B.2-B.6 still ran (tools, prompt, webhook, audio, overrides) + org stamped.
    assert "provision_tools" in calls["patches"]
    assert "provision_prompt" in calls["patches"]
    assert "provision_webhook" in calls["patches"]
    assert "provision_audio" in calls["patches"]
    assert "provision_overrides_whitelist" in calls["patches"]
    assert calls["stamped"] is True

    # The rest of the summary still reports the configured steps.
    assert summary["webhook_enabled"] is True
    assert summary["audio_ok"] is True
    assert summary["overrides_whitelist_enabled"] is True
    assert summary["prompt_applied"] is True


def test_configure_agent_happy_path_with_phone(monkeypatch):
    calls = _stub_configure_environment(monkeypatch, phone_raises=False)
    summary = ac.configure_agent(org_id=ORG_ID, agent_id=AGENT_ID, org_name=ORG_NAME)

    # Happy path unchanged: phone bound + stored, no graceful message.
    assert summary["phone_bound"] is True
    assert summary["phone_number"] == "+4925197593899"
    assert summary["phone_number_id"] == "pid_1"
    assert summary["phone_message"] is None
    assert calls["stored_phone"] == "+4925197593899"
    # Same configuration steps ran.
    assert "provision_tools" in calls["patches"]
    assert calls["stamped"] is True
