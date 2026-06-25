"""Hermetic tests for app.services.agent_config helpers (Step B, 2026-05-27).

No network, no DB. ElevenLabs HTTP + Supabase access are monkeypatched.
"""

from __future__ import annotations

import types

import pytest
from fastapi import HTTPException

from app.services import agent_config as ac


AGENT_ID = "agent_unit_xyz"
ORG_ID = "00000000-0000-0000-0000-000000000111"
ORG_NAME = "ACME Test GmbH"


# ─── Helpers ────────────────────────────────────────────────────────────────
def _stub_workspace_tools(monkeypatch, names: list[str]) -> None:
    """Make _fetch_workspace_tools return {name: f'tool_{name}'} for each name."""
    monkeypatch.setattr(
        ac, "_fetch_workspace_tools", lambda: {n: f"tool_{n}" for n in names}
    )
    # Bust the module-level cache between tests.
    ac._HK_TOOL_ID_CACHE.clear()


# ─── _resolve_hk_tool_ids ────────────────────────────────────────────────────
def test_resolve_returns_all_when_workspace_complete(monkeypatch):
    _stub_workspace_tools(monkeypatch, ac.HK_TOOL_NAMES)
    out = ac._resolve_hk_tool_ids()
    assert set(out.keys()) == set(ac.HK_TOOL_NAMES)
    assert all(v == f"tool_{k}" for k, v in out.items())


def test_resolve_raises_with_missing_tool_names(monkeypatch):
    # workspace is missing one required tool (the first name)
    _stub_workspace_tools(monkeypatch, ac.HK_TOOL_NAMES[1:])
    with pytest.raises(HTTPException) as exc:
        ac._resolve_hk_tool_ids()
    assert exc.value.status_code == 400
    assert ac.HK_TOOL_NAMES[0] in exc.value.detail


def test_resolve_caches_across_calls(monkeypatch):
    calls = {"n": 0}

    def fake_fetch():
        calls["n"] += 1
        return {n: f"tool_{n}" for n in ac.HK_TOOL_NAMES}

    monkeypatch.setattr(ac, "_fetch_workspace_tools", fake_fetch)
    ac._HK_TOOL_ID_CACHE.clear()
    ac._resolve_hk_tool_ids()
    ac._resolve_hk_tool_ids()
    # Second call should hit the cache → only one workspace fetch.
    assert calls["n"] == 1


# ─── fetch_phone_for_agent ───────────────────────────────────────────────────
def test_phone_fetch_returns_e164_for_single_match(monkeypatch):
    monkeypatch.setattr(
        ac, "_list_phone_numbers",
        lambda: [
            {"phone_number": "+4925197590001",
             "assigned_agent": {"agent_id": "other_agent"}},
            {"phone_number": "+4925197593899",
             "assigned_agent": {"agent_id": AGENT_ID}},
        ],
    )
    assert ac.fetch_phone_for_agent(AGENT_ID) == "+4925197593899"


def test_phone_fetch_hard_fails_with_zero_bound(monkeypatch):
    monkeypatch.setattr(
        ac, "_list_phone_numbers",
        lambda: [
            {"phone_number": "+4925197590001",
             "assigned_agent": {"agent_id": "other_agent"}},
        ],
    )
    with pytest.raises(HTTPException) as exc:
        ac.fetch_phone_for_agent(AGENT_ID)
    assert exc.value.status_code == 400
    assert "no phone number" in exc.value.detail.lower()


def test_phone_fetch_picks_first_when_multiple_bound(monkeypatch, caplog):
    monkeypatch.setattr(
        ac, "_list_phone_numbers",
        lambda: [
            {"phone_number": "+4925197590001",
             "assigned_agent": {"agent_id": AGENT_ID}},
            {"phone_number": "+4925197590002",
             "assigned_agent": {"agent_id": AGENT_ID}},
        ],
    )
    with caplog.at_level("WARNING"):
        phone = ac.fetch_phone_for_agent(AGENT_ID)
    assert phone == "+4925197590001"
    # Warning was logged
    assert any("2 phones bound" in rec.message for rec in caplog.records)


def test_phone_fetch_handles_missing_assigned_agent(monkeypatch):
    """Phone rows with no assigned_agent (unassigned) must not crash the match."""
    monkeypatch.setattr(
        ac, "_list_phone_numbers",
        lambda: [
            {"phone_number": "+4925197590001", "assigned_agent": None},
            {"phone_number": "+4925197593899",
             "assigned_agent": {"agent_id": AGENT_ID}},
        ],
    )
    assert ac.fetch_phone_for_agent(AGENT_ID) == "+4925197593899"


# ─── fetch_phone_meta_for_agent: environment surfacing ───────────────────────
def test_phone_meta_surfaces_environment(monkeypatch):
    """The phone's pinned environment (assigned_agent.environment) is returned."""
    monkeypatch.setattr(
        ac, "_list_phone_numbers",
        lambda: [
            {"phone_number": "+4925197593899", "phone_number_id": "phnum_1",
             "assigned_agent": {"agent_id": AGENT_ID, "environment": "uat"}},
        ],
    )
    meta = ac.fetch_phone_meta_for_agent(AGENT_ID)
    assert meta["phone_number_id"] == "phnum_1"
    assert meta["environment"] == "uat"


def test_phone_meta_environment_none_when_unpinned(monkeypatch):
    monkeypatch.setattr(
        ac, "_list_phone_numbers",
        lambda: [
            {"phone_number": "+4925197593899", "phone_number_id": "phnum_1",
             "assigned_agent": {"agent_id": AGENT_ID}},
        ],
    )
    assert ac.fetch_phone_meta_for_agent(AGENT_ID)["environment"] is None


# ─── set_phone_environment: PATCH the phone's environment pin ─────────────────
class _FakeResp:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class _FakePatchClient:
    """Stand-in for httpx.Client capturing a single .patch() call."""

    def __init__(self, rec, status_code, text):
        self._rec, self._status, self._text = rec, status_code, text

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def patch(self, url, headers=None, json=None):
        self._rec.append({"url": url, "headers": headers or {}, "json": json})
        return _FakeResp(self._status, self._text)


def _stub_patch_httpx(monkeypatch, rec, *, status_code=200, text=""):
    """Replace ac.httpx with a namespace whose Client records .patch() calls."""
    monkeypatch.setattr(ac.settings, "elevenlabs_api_key", "sk_test_key")
    fake = types.SimpleNamespace(
        Client=lambda *a, **k: _FakePatchClient(rec, status_code, text)
    )
    monkeypatch.setattr(ac, "httpx", fake)


def test_set_phone_environment_patches_environment_and_carries_agent(monkeypatch):
    rec: list = []
    _stub_patch_httpx(monkeypatch, rec)
    ac.set_phone_environment("phnum_123", "uat", "agent_abc")
    assert len(rec) == 1
    call = rec[0]
    assert call["url"] == "/v1/convai/phone-numbers/phnum_123"
    assert call["json"] == {"environment": "uat", "agent_id": "agent_abc"}
    assert call["headers"]["xi-api-key"] == "sk_test_key"


def test_set_phone_environment_minimal_body_without_agent(monkeypatch):
    rec: list = []
    _stub_patch_httpx(monkeypatch, rec)
    ac.set_phone_environment("phnum_123", "uat")
    assert rec[0]["json"] == {"environment": "uat"}


def test_set_phone_environment_raises_on_non_2xx(monkeypatch):
    rec: list = []
    _stub_patch_httpx(monkeypatch, rec, status_code=422, text="nope")
    with pytest.raises(ac.ElevenLabsWriteError):
        ac.set_phone_environment("phnum_123", "uat")


def test_set_phone_environment_requires_api_key(monkeypatch):
    monkeypatch.setattr(ac.settings, "elevenlabs_api_key", "")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with pytest.raises(ac.ElevenLabsWriteError):
        ac.set_phone_environment("phnum_123", "uat")


# ─── Prompt rendering ────────────────────────────────────────────────────────
def test_render_prompt_substitutes_company_name():
    org = {
        "address": {"street": "Hafenweg 22", "city": "Münster", "postal_code": "48155"},
        "phone_number": "+49251000000",
        "email": "info@testorg.de",
        "trade": "",            # empty → trade clause omitted (not invented)
        "management": {"name": ""},  # empty → director line omitted (not invented)
    }
    out = ac.render_prompt_for_org("Test Org GmbH", org=org)
    # ALL Husmann identity is gone now (name + directors + address + service area).
    assert "Husmann" not in out
    assert "Dreier" not in out
    assert "Herr Husmann und Herr Dreier" not in out  # the formerly-hardcoded director line
    assert "Buxtehude" not in out and "Stader" not in out and "04161" not in out
    assert "Jork" not in out and "Neuenkirchen" not in out  # no service-area towns
    assert "08:00" not in out and "16:00" not in out        # no hardcoded business hours
    # Org identity present instead.
    assert "Test Org GmbH" in out
    assert "Hafenweg 22" in out and "Münster" in out        # address sourced from org
    assert "info@testorg.de" in out                          # email sourced from org
    # Empty fields omitted cleanly (not invented).
    assert "Geschäftsführung:" not in out                    # management.name empty → omitted
    # NO wkp_shared_ tokens; hk_* tools intact; emergency content untouched (deferred).
    assert "wkp_shared_" not in out
    assert "hk_identifyCustomer" in out and "hk_bookAppointment" in out
    assert "Notfall-Definition" in out                       # emergency content left as-is


def test_render_prompt_strips_sendkva_parenthetical():
    out = ac.render_prompt_for_org("X")
    # The full sentence should remain but the (z. B. ... sendKVA ...) example
    # is gone.
    assert "wkp_shared_sendKVA" not in out
    assert "versende nichts" in out
    # The sentence end should be the bare period now, not "müsste** ("
    assert "müsste** (" not in out


# ─── configure_agent: full happy path ────────────────────────────────────────
class _RecordingPatch:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, **kw):
        self.calls.append(kw)
        return {}  # patch_agent_safely returns the post-config dict; not used here


def _build_current_cfg(
    *, tool_ids=None, prompt="OLD", client_events=None,
    webhook_url=None, webhook_enabled=False, override_flags=False,
) -> dict:
    overrides = {
        "enable_conversation_initiation_client_data_from_webhook": webhook_enabled,
    }
    if override_flags:
        overrides["conversation_config_override"] = {
            "agent": {
                "first_message": True,
                "language": True,
                "prompt": {"prompt": True},
            }
        }
    return {
        "agent_id": AGENT_ID,
        "conversation_config": {
            "agent": {
                "prompt": {
                    "prompt": prompt,
                    "tool_ids": list(tool_ids or []),
                }
            },
            "conversation": {
                "client_events": list(client_events or ["audio"]),
            },
        },
        "platform_settings": {
            "workspace_overrides": {
                "conversation_initiation_client_data_webhook": (
                    {"url": webhook_url} if webhook_url else {}
                ),
            },
            "overrides": overrides,
        },
    }


def _wire_configure_agent(monkeypatch, *, current_cfg, provisioned=False, phones=None):
    """Stub every external dep of configure_agent and return the patch recorder."""
    rec = _RecordingPatch()
    monkeypatch.setattr(ac, "patch_agent_safely", rec)
    monkeypatch.setattr(ac, "get_agent_config", lambda _aid: current_cfg)
    monkeypatch.setattr(
        ac, "_list_phone_numbers",
        lambda: phones if phones is not None else [
            {"phone_number": "+4925197593899",
             "assigned_agent": {"agent_id": AGENT_ID}},
        ],
    )
    _stub_workspace_tools(monkeypatch, ac.HK_TOOL_NAMES)
    monkeypatch.setattr(ac, "_is_agent_already_provisioned", lambda _o: provisioned)
    monkeypatch.setattr(ac, "_store_phone_on_org", lambda *_a, **_k: None)
    monkeypatch.setattr(ac, "_stamp_agent_provisioned", lambda *_a, **_k: None)
    return rec


# ─── attach_hk_tools / set_conversation_init_webhook (shared B.2/B.4 steps) ───
def test_attach_hk_tools_merges_then_noops(monkeypatch):
    _stub_workspace_tools(monkeypatch, ac.HK_TOOL_NAMES)
    rec = _RecordingPatch()
    monkeypatch.setattr(ac, "patch_agent_safely", rec)
    monkeypatch.setattr(ac, "get_agent_config", lambda _a: {})  # no tools yet
    added = ac.attach_hk_tools("agent_x", actor_id="u", org_id="o")
    assert len(added) == len(ac.HK_TOOL_NAMES)
    assert rec.calls and rec.calls[0]["endpoint_label"] == "provision_tools"

    rec2 = _RecordingPatch()
    monkeypatch.setattr(ac, "patch_agent_safely", rec2)
    full = _build_current_cfg(tool_ids=[f"tool_{n}" for n in ac.HK_TOOL_NAMES])
    monkeypatch.setattr(ac, "get_agent_config", lambda _a: full)
    assert ac.attach_hk_tools("agent_x") == []
    assert rec2.calls == []


def test_set_conversation_init_webhook_writes_env_routed_url(monkeypatch):
    rec = _RecordingPatch()
    monkeypatch.setattr(ac, "patch_agent_safely", rec)
    monkeypatch.setattr(ac, "get_agent_config", lambda _a: {})  # unset + disabled
    ac.set_conversation_init_webhook("agent_x", actor_id="u", org_id="o")
    assert len(rec.calls) == 1
    ps = rec.calls[0]["field_patches"]["platform_settings"]
    wh = ps["workspace_overrides"]["conversation_initiation_client_data_webhook"]
    assert wh["url"] == ac._CONVERSATION_INIT_WEBHOOK_URL
    assert wh["url"] == "https://{{system__env_api_host}}/api/elevenlabs/conversation-init"
    assert ps["overrides"]["enable_conversation_initiation_client_data_from_webhook"] is True
    assert rec.calls[0]["endpoint_label"] == "provision_webhook"


def test_set_conversation_init_webhook_noop_when_already_env_routed(monkeypatch):
    rec = _RecordingPatch()
    monkeypatch.setattr(ac, "patch_agent_safely", rec)
    cfg = _build_current_cfg(
        webhook_url=ac._CONVERSATION_INIT_WEBHOOK_URL, webhook_enabled=True
    )
    monkeypatch.setattr(ac, "get_agent_config", lambda _a: cfg)
    ac.set_conversation_init_webhook("agent_x")
    assert rec.calls == []


def test_configure_agent_fresh_full_path(monkeypatch):
    cfg = _build_current_cfg(tool_ids=[], prompt="OLD", client_events=["audio"])
    rec = _wire_configure_agent(monkeypatch, current_cfg=cfg, provisioned=False)

    summary = ac.configure_agent(
        org_id=ORG_ID, agent_id=AGENT_ID, org_name=ORG_NAME,
    )

    # Phone stored
    assert summary["phone_number"] == "+4925197593899"
    # All hk_* tools added
    assert len(summary["tools_attached"]) == len(ac.HK_TOOL_NAMES)
    # Prompt applied (first run)
    assert summary["prompt_applied"] is True
    assert summary["prompt_skipped_reason"] is None
    # Webhook enabled
    assert summary["webhook_enabled"] is True
    # Audio OK (already present, no extra write)
    assert summary["audio_ok"] is True

    endpoints = [c["endpoint_label"] for c in rec.calls]
    # We always write tools + prompt + webhook on first run; audio is no-op when
    # already present.
    assert "provision_tools" in endpoints
    assert "provision_prompt" in endpoints
    assert "provision_webhook" in endpoints
    assert "provision_audio" not in endpoints  # already present
    # B.6: the Path A override whitelist is set on a fresh (untoggled) agent.
    assert "provision_overrides_whitelist" in endpoints
    assert summary["overrides_whitelist_enabled"] is True


def test_configure_agent_rerun_skips_prompt(monkeypatch):
    cfg = _build_current_cfg(
        tool_ids=[f"tool_{n}" for n in ac.HK_TOOL_NAMES],
        prompt="customer hand-edited content",
        client_events=["audio"],
        webhook_url=ac._CONVERSATION_INIT_WEBHOOK_URL,
        webhook_enabled=True,
        override_flags=True,
    )
    rec = _wire_configure_agent(monkeypatch, current_cfg=cfg, provisioned=True)

    summary = ac.configure_agent(
        org_id=ORG_ID, agent_id=AGENT_ID, org_name=ORG_NAME,
    )

    assert summary["prompt_applied"] is False
    assert summary["prompt_skipped_reason"] == "already_provisioned"
    # No tools to add (all 10 already there)
    assert summary["tools_attached"] == []
    # No PATCH calls at all (everything already in desired state)
    assert rec.calls == []


def test_configure_agent_adds_only_missing_audio(monkeypatch):
    cfg = _build_current_cfg(
        tool_ids=[f"tool_{n}" for n in ac.HK_TOOL_NAMES],
        client_events=["interruption"],  # missing audio
        webhook_url=ac._CONVERSATION_INIT_WEBHOOK_URL,
        webhook_enabled=True,
        override_flags=True,
    )
    rec = _wire_configure_agent(monkeypatch, current_cfg=cfg, provisioned=True)

    summary = ac.configure_agent(
        org_id=ORG_ID, agent_id=AGENT_ID, org_name=ORG_NAME,
    )

    assert summary["audio_ok"] is True
    endpoints = [c["endpoint_label"] for c in rec.calls]
    assert endpoints == ["provision_audio"]  # only the audio write
    # The audio write used the safety layer's merge_arrays so audio is added,
    # nothing is stripped from interruption.
    audio_call = rec.calls[0]
    assert ac.CLIENT_EVENTS_PATH in audio_call["merge_arrays"]


def test_configure_agent_zero_phones_is_graceful(monkeypatch):
    # 2.3 — a missing phone no longer aborts the provision. configure_agent
    # records phone_bound=false + the actionable German message and continues
    # with the other steps (B.2-B.6) instead of raising. (Was: raised 400.)
    cfg = _build_current_cfg(
        tool_ids=[f"tool_{n}" for n in ac.HK_TOOL_NAMES],
        client_events=["audio"],
        webhook_url=ac._CONVERSATION_INIT_WEBHOOK_URL,
        webhook_enabled=True,
        override_flags=True,
    )
    rec = _wire_configure_agent(
        monkeypatch, current_cfg=cfg, provisioned=True, phones=[]
    )

    summary = ac.configure_agent(
        org_id=ORG_ID, agent_id=AGENT_ID, org_name=ORG_NAME,
    )

    assert summary["phone_bound"] is False
    assert summary["phone_number"] is None
    assert summary["phone_message"] == ac.NO_PHONE_MESSAGE
    # The rest of the configuration still completed (no abort).
    assert summary["webhook_enabled"] is True
    assert summary["audio_ok"] is True
    assert summary["overrides_whitelist_enabled"] is True


def test_configure_agent_missing_tool_raises(monkeypatch):
    cfg = _build_current_cfg()
    # Stub a workspace missing one of the 10 names — should raise 400.
    monkeypatch.setattr(
        ac, "_fetch_workspace_tools",
        lambda: {n: f"tool_{n}" for n in ac.HK_TOOL_NAMES[:-1]},
    )
    ac._HK_TOOL_ID_CACHE.clear()
    monkeypatch.setattr(ac, "get_agent_config", lambda _a: cfg)
    monkeypatch.setattr(
        ac, "_list_phone_numbers",
        lambda: [
            {"phone_number": "+4925197593899",
             "assigned_agent": {"agent_id": AGENT_ID}},
        ],
    )
    monkeypatch.setattr(ac, "_is_agent_already_provisioned", lambda _o: True)
    monkeypatch.setattr(ac, "_store_phone_on_org", lambda *_a, **_k: None)
    monkeypatch.setattr(ac, "patch_agent_safely", lambda **_k: {})

    with pytest.raises(HTTPException) as exc:
        ac.configure_agent(
            org_id=ORG_ID, agent_id=AGENT_ID, org_name=ORG_NAME,
        )
    assert exc.value.status_code == 400
    assert ac.HK_TOOL_NAMES[-1] in exc.value.detail


# ─── B.6 overrides whitelist ─────────────────────────────────────────────────
def _no_strings(node) -> bool:
    """True iff no string VALUE appears anywhere in the structure (only bool/dict)."""
    if isinstance(node, str):
        return False
    if isinstance(node, dict):
        return all(_no_strings(v) for v in node.values())
    if isinstance(node, list):
        return all(_no_strings(v) for v in node)
    return True


def test_configure_agent_sets_override_whitelist_when_absent(monkeypatch):
    # Fully provisioned EXCEPT the override flags → only the whitelist write fires.
    cfg = _build_current_cfg(
        tool_ids=[f"tool_{n}" for n in ac.HK_TOOL_NAMES],
        prompt="customer hand-edited content",
        client_events=["audio"],
        webhook_url=ac._CONVERSATION_INIT_WEBHOOK_URL,
        webhook_enabled=True,
        override_flags=False,
    )
    rec = _wire_configure_agent(monkeypatch, current_cfg=cfg, provisioned=True)

    summary = ac.configure_agent(org_id=ORG_ID, agent_id=AGENT_ID, org_name=ORG_NAME)

    assert summary["overrides_whitelist_enabled"] is True
    wl = [c for c in rec.calls if c["endpoint_label"] == "provision_overrides_whitelist"]
    assert len(wl) == 1
    call = wl[0]
    # verify is told to enforce the flags (rollback if they don't take).
    assert call["required_override_flags"] is True
    # Sets ONLY the three booleans — no prompt / first_message TEXT written here.
    agent = (
        call["field_patches"]["platform_settings"]["overrides"]
        ["conversation_config_override"]["agent"]
    )
    assert agent == {"first_message": True, "language": True, "prompt": {"prompt": True}}
    assert _no_strings(call["field_patches"]) is True  # never a prompt string


def test_configure_agent_override_whitelist_idempotent(monkeypatch):
    # Flags already true on a fully-provisioned agent → B.6 must NOT patch.
    cfg = _build_current_cfg(
        tool_ids=[f"tool_{n}" for n in ac.HK_TOOL_NAMES],
        prompt="x",
        client_events=["audio"],
        webhook_url=ac._CONVERSATION_INIT_WEBHOOK_URL,
        webhook_enabled=True,
        override_flags=True,
    )
    rec = _wire_configure_agent(monkeypatch, current_cfg=cfg, provisioned=True)

    summary = ac.configure_agent(org_id=ORG_ID, agent_id=AGENT_ID, org_name=ORG_NAME)

    assert summary["overrides_whitelist_enabled"] is True
    assert not any(
        c["endpoint_label"] == "provision_overrides_whitelist" for c in rec.calls
    )
    assert rec.calls == []  # fully provisioned incl. flags → zero writes
