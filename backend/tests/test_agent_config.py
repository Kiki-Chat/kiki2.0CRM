"""Hermetic tests for app.services.agent_config helpers (Step B, 2026-05-27).

No network, no DB. ElevenLabs HTTP + Supabase access are monkeypatched.
"""

from __future__ import annotations

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
    # workspace has only 9 of 10
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


# ─── Prompt rendering ────────────────────────────────────────────────────────
def test_render_prompt_substitutes_company_name():
    out = ac.render_prompt_for_org("Test Org GmbH")
    # Husmann & Dreier GmbH gone (replaced)
    assert "Husmann & Dreier GmbH" not in out
    assert "Husmann und Dreier" not in out
    # 2026-05-27 Wave 3 V.2 regression: the bare "Husmann & Dreier" form (no
    # GmbH suffix, no "und" variant) was initially omitted from substitution —
    # 4 instances in headings/prose on lines 93, 161, 164, 214 leaked through.
    # This assertion locks the fix.
    assert "Husmann & Dreier" not in out
    # Org name appears
    assert "Test Org GmbH" in out
    # NO wkp_shared_ tokens remain
    assert "wkp_shared_" not in out
    # The hk_* tool names are present (sanity: the mapping landed in the template)
    assert "hk_identifyCustomer" in out
    assert "hk_bookAppointment" in out
    # The director-name lines (lines 919-920) are intentionally NOT substituted —
    # those are bespoke per-org content that needs its own future field.
    assert "Herr Husmann und Herr Dreier" in out


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


def test_configure_agent_fresh_full_path(monkeypatch):
    cfg = _build_current_cfg(tool_ids=[], prompt="OLD", client_events=["audio"])
    rec = _wire_configure_agent(monkeypatch, current_cfg=cfg, provisioned=False)

    summary = ac.configure_agent(
        org_id=ORG_ID, agent_id=AGENT_ID, org_name=ORG_NAME,
    )

    # Phone stored
    assert summary["phone_number"] == "+4925197593899"
    # All 10 tools added
    assert len(summary["tools_attached"]) == 10
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
        webhook_url=(
            "http://localhost:8000/api/elevenlabs/conversation-init"
        ),
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
        webhook_url=(
            "http://localhost:8000/api/elevenlabs/conversation-init"
        ),
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


def test_configure_agent_zero_phones_raises(monkeypatch):
    cfg = _build_current_cfg()
    _wire_configure_agent(monkeypatch, current_cfg=cfg, phones=[])

    with pytest.raises(HTTPException) as exc:
        ac.configure_agent(
            org_id=ORG_ID, agent_id=AGENT_ID, org_name=ORG_NAME,
        )
    assert exc.value.status_code == 400


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
        webhook_url="http://localhost:8000/api/elevenlabs/conversation-init",
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
        webhook_url="http://localhost:8000/api/elevenlabs/conversation-init",
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
