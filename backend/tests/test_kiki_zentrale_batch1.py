"""Hermetic unit tests for Kiki-Zentrale Batch 1 (true undo/rewind + drift safety).

No network, no DB. ElevenLabs HTTP + Supabase access are monkeypatched.

Covers:
  1.1  restore re-applies platform_settings + guards empty objects
  1.3  drift dirty-stamp / clear + force bypass
  1.4  sync_system_tools_for_org categorized reasons
  1.5  reconcile aborts on unresolved tool; never drops a non-hk_ id
"""

from __future__ import annotations

import copy

import httpx
import pytest

from app.services import agent_config as ac
from app.services import elevenlabs_agent as ea

AGENT = "agent_batch1_xyz"


def base_cfg(agent_id: str = AGENT) -> dict:
    return {
        "agent_id": agent_id,
        "name": "Demo",
        "conversation_config": {
            "agent": {
                "first_message": "Hi",
                "language": "de",
                "prompt": {
                    "prompt": "OLD PROMPT",
                    "tools": [],
                    "tool_ids": [],
                    "knowledge_base": [],
                },
            },
            "tts": {"voice_id": "v1"},
            "conversation": {"client_events": ["audio", "interruption"]},
        },
        "platform_settings": {
            "overrides": {
                "enable_conversation_initiation_client_data_from_webhook": True,
                "conversation_config_override": {
                    "agent": {
                        "first_message": True,
                        "language": True,
                        "prompt": {"prompt": True},
                    }
                },
            },
            "workspace_overrides": {
                "conversation_initiation_client_data_webhook": {
                    "url": "https://api.heykiki.test/api/elevenlabs/conversation-init",
                    "request_headers": {"X-HeyKiki-Secret": "shh"},
                }
            },
        },
    }


# ─── 1.1 restore helper tests (pure) ─────────────────────────────────────────
def test_non_empty_dict_drops_empties():
    assert ea._non_empty_dict({}) is None
    assert ea._non_empty_dict(None) is None
    assert ea._non_empty_dict({"a": {}}) is None
    assert ea._non_empty_dict({"a": None}) is None
    assert ea._non_empty_dict({"a": {"b": {}}}) is None
    # Non-empty leaf survives; empty siblings are pruned.
    out = ea._non_empty_dict({"a": {"b": 1, "c": {}}, "d": {}})
    assert out == {"a": {"b": 1}}


def test_restore_full_includes_platform_settings(monkeypatch):
    captured = {}

    def fake_patch(agent_id, body):
        captured["body"] = body
        return None

    monkeypatch.setattr(ea, "_patch_agent", fake_patch)
    ea._restore_full(AGENT, base_cfg())
    body = captured["body"]
    assert "conversation_config" in body
    assert "platform_settings" in body  # 1.1: restored, not dropped
    # The webhook override survived (NEVER blanked to {}).
    wh = ea._get_path(
        body,
        "platform_settings.workspace_overrides."
        "conversation_initiation_client_data_webhook",
    )
    assert wh and wh.get("url")
    assert body["platform_settings"]["overrides"][
        "enable_conversation_initiation_client_data_from_webhook"
    ] is True


def test_restore_full_drops_empty_platform_settings(monkeypatch):
    captured = {}
    monkeypatch.setattr(ea, "_patch_agent", lambda a, b: captured.setdefault("body", b))
    cfg = base_cfg()
    cfg["platform_settings"] = {}  # empty → must be dropped, never PATCHed as {}
    ea._restore_full(AGENT, cfg)
    assert "platform_settings" not in captured["body"]


def test_restore_full_drops_empty_webhook_subobject(monkeypatch):
    captured = {}
    monkeypatch.setattr(ea, "_patch_agent", lambda a, b: captured.setdefault("body", b))
    cfg = base_cfg()
    # An empty webhook sub-object must NOT be carried as {} (would clear it).
    cfg["platform_settings"]["workspace_overrides"][
        "conversation_initiation_client_data_webhook"
    ] = {}
    ea._restore_full(AGENT, cfg)
    ws = (
        captured["body"].get("platform_settings", {}).get("workspace_overrides", {})
    )
    assert "conversation_initiation_client_data_webhook" not in ws
    # but the still-present overrides survive
    assert captured["body"]["platform_settings"]["overrides"]


# ─── Shared fakes (EL server + DB) ───────────────────────────────────────────
class _HTTP:
    def __init__(self, status=200, text="ok"):
        self.status_code = status
        self.text = text


def _deep_apply(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_apply(dst[k], v)
        else:
            dst[k] = v


class FakeServer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.patches = []

    def get(self, agent_id):
        return copy.deepcopy(self.cfg)

    def patch(self, agent_id, body):
        self.patches.append(copy.deepcopy(body))
        _deep_apply(self.cfg, body)
        return _HTTP(200, "ok")


class _Res:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, table, store):
        self.table = table
        self.store = store
        self._op = "select"
        self._payload = None

    def select(self, *a, **k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def upsert(self, payload, **k):
        self._op = "upsert"
        self._payload = payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, *a, **k):
        return self

    def neq(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def gt(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def execute(self):
        if self._op == "insert":
            self.store["inserts"].append((self.table, self._payload))
            data = (
                [{"id": "snap-1"}]
                if self.table == "agent_config_snapshots"
                else [dict(self._payload, id="row-1")]
            )
            return _Res(data)
        if self._op in ("update", "upsert"):
            self.store["updates"].append((self.table, self._payload))
            return _Res([])
        return _Res(self.store["canned"].get(self.table, []))


class FakeDB:
    def __init__(self, canned):
        self.store = {"canned": canned, "inserts": [], "updates": []}

    def table(self, name):
        return _Q(name, self.store)


def _wire_ea(monkeypatch, server, db):
    monkeypatch.setattr(ea, "get_service_client", lambda: db)
    monkeypatch.setattr(ea, "get_agent_config", server.get)
    monkeypatch.setattr(ea, "_patch_agent", server.patch)


# ─── 1.3 drift: stamp on manual_override no-op, clear on success, force bypass ─
def test_drift_stamps_dirty_on_manual_override(monkeypatch):
    db = FakeDB(
        {
            "agent_configs": [{"prompt_manual_override": True, "config_dirty_since": None}],
            "organizations": [{"name": "ACME", "elevenlabs_agent_id": AGENT}],
        }
    )
    monkeypatch.setattr(ac, "get_service_client", lambda: db)

    out = ac.rerender_and_push_for_org(org_id="o1", endpoint_label="kz_x")
    assert out == {"updated": False, "reason": "manual_override"}
    # A config_dirty_since stamp was written.
    dirty_updates = [
        p for t, p in db.store["updates"]
        if t == "agent_configs" and "config_dirty_since" in p and p["config_dirty_since"]
    ]
    assert dirty_updates, "expected config_dirty_since to be stamped"


def test_drift_does_not_restamp_when_already_dirty(monkeypatch):
    db = FakeDB(
        {
            "agent_configs": [
                {"prompt_manual_override": True, "config_dirty_since": "2026-01-01T00:00:00Z"}
            ],
            "organizations": [{"name": "ACME", "elevenlabs_agent_id": AGENT}],
        }
    )
    monkeypatch.setattr(ac, "get_service_client", lambda: db)
    ac.rerender_and_push_for_org(org_id="o1", endpoint_label="kz_x")
    # Already dirty → no new stamp write.
    dirty_updates = [
        p for t, p in db.store["updates"]
        if t == "agent_configs" and "config_dirty_since" in p
    ]
    assert dirty_updates == []


def test_force_bypasses_manual_override_and_clears_dirty(monkeypatch):
    server = FakeServer(base_cfg())
    db = FakeDB(
        {
            "agent_configs": [{"prompt_manual_override": True, "config_dirty_since": "x"}],
            "organizations": [{"name": "ACME", "elevenlabs_agent_id": AGENT}],
        }
    )
    monkeypatch.setattr(ac, "get_service_client", lambda: db)
    _wire_ea(monkeypatch, server, db)
    # render must not require a real template
    monkeypatch.setattr(ac, "render_prompt_for_org", lambda *a, **k: "FORCED PROMPT")
    monkeypatch.setattr(ac, "_fetch_org_identity", lambda org_id: {"name": "ACME"})

    out = ac.rerender_and_push_for_org(
        org_id="o1", endpoint_label="kz_force_resync", expected_seq=5, force=True
    )
    assert out == {"updated": True}
    # The prompt push happened despite manual_override.
    assert server.patches, "force=True should have pushed despite override"
    # config_dirty_since cleared (set to None) + last_repush_at stamped.
    cleared = [
        p for t, p in db.store["updates"]
        if t == "agent_configs"
        and p.get("config_dirty_since") is None
        and p.get("last_repush_at")
    ]
    assert cleared, "successful push should clear dirty + stamp last_repush_at"


def test_compute_drift_shape(monkeypatch):
    db = FakeDB(
        {
            "agent_configs": [
                {
                    "prompt_manual_override": True,
                    "config_dirty_since": "2026-06-17T10:00:00Z",
                    "last_repush_at": "2026-06-16T09:00:00Z",
                }
            ]
        }
    )
    monkeypatch.setattr(ac, "get_service_client", lambda: db)
    out = ac.compute_drift("o1")
    assert out == {
        "drift": True,
        "dirty_since": "2026-06-17T10:00:00Z",
        "manual_override": True,
        "last_repush_at": "2026-06-16T09:00:00Z",
    }


def test_compute_drift_no_drift_when_clean(monkeypatch):
    db = FakeDB(
        {"agent_configs": [{"prompt_manual_override": False, "config_dirty_since": None}]}
    )
    monkeypatch.setattr(ac, "get_service_client", lambda: db)
    out = ac.compute_drift("o1")
    assert out["drift"] is False and out["dirty_since"] is None


# ─── 1.4 system-tools sync: categorized reasons ──────────────────────────────
def _kz_db():
    return FakeDB(
        {
            "organizations": [{"elevenlabs_agent_id": AGENT}],
            "agent_configs": [{"emergency_enabled": False}],
        }
    )


def test_sync_system_tools_no_agent(monkeypatch):
    db = FakeDB({"organizations": [{"elevenlabs_agent_id": None}]})
    monkeypatch.setattr(ac, "get_service_client", lambda: db)
    out = ac.sync_system_tools_for_org("o1")
    assert out == {"updated": False, "reason": "no_agent"}


def test_sync_system_tools_verify_failed_reason(monkeypatch):
    db = _kz_db()
    monkeypatch.setattr(ac, "get_service_client", lambda: db)
    monkeypatch.setattr(ac, "_fetch_kz_config", lambda org_id: {"emergency_enabled": False})
    monkeypatch.setattr(ac, "build_transfer_tool", lambda cfg: None)
    monkeypatch.setattr(ac, "build_voicemail_tool", lambda: {"name": "vm"})
    monkeypatch.setattr(ac, "build_transfer_to_agent_tool", lambda a: {"name": "ta"})

    def boom(**kwargs):
        raise ea.VerificationFailedError("audio missing; rolled back")

    monkeypatch.setattr(ac, "patch_agent_safely", boom)
    out = ac.sync_system_tools_for_org("o1")
    assert out["updated"] is False
    assert out["reason"].startswith("verify_failed:")


def test_sync_system_tools_el_error_reason(monkeypatch):
    db = _kz_db()
    monkeypatch.setattr(ac, "get_service_client", lambda: db)
    monkeypatch.setattr(ac, "_fetch_kz_config", lambda org_id: {"emergency_enabled": False})
    monkeypatch.setattr(ac, "build_transfer_tool", lambda cfg: None)
    monkeypatch.setattr(ac, "build_voicemail_tool", lambda: {"name": "vm"})
    monkeypatch.setattr(ac, "build_transfer_to_agent_tool", lambda a: {"name": "ta"})

    def boom(**kwargs):
        raise ea.ElevenLabsWriteError("PATCH failed 500")

    monkeypatch.setattr(ac, "patch_agent_safely", boom)
    out = ac.sync_system_tools_for_org("o1")
    assert out["updated"] is False
    assert out["reason"].startswith("el_error:")


def test_sync_system_tools_retries_once_on_transient_then_succeeds(monkeypatch):
    db = _kz_db()
    monkeypatch.setattr(ac, "get_service_client", lambda: db)
    monkeypatch.setattr(ac, "_fetch_kz_config", lambda org_id: {"emergency_enabled": False})
    monkeypatch.setattr(ac, "build_transfer_tool", lambda cfg: None)
    monkeypatch.setattr(ac, "build_voicemail_tool", lambda: {"name": "vm"})
    monkeypatch.setattr(ac, "build_transfer_to_agent_tool", lambda a: {"name": "ta"})

    calls = {"n": 0}

    def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("transient")
        return {}

    monkeypatch.setattr(ac, "patch_agent_safely", flaky)
    out = ac.sync_system_tools_for_org("o1")
    assert out == {"updated": True}
    assert calls["n"] == 2  # one retry


def test_sync_system_tools_does_not_retry_verify_failed(monkeypatch):
    db = _kz_db()
    monkeypatch.setattr(ac, "get_service_client", lambda: db)
    monkeypatch.setattr(ac, "_fetch_kz_config", lambda org_id: {"emergency_enabled": False})
    monkeypatch.setattr(ac, "build_transfer_tool", lambda cfg: None)
    monkeypatch.setattr(ac, "build_voicemail_tool", lambda: {"name": "vm"})
    monkeypatch.setattr(ac, "build_transfer_to_agent_tool", lambda a: {"name": "ta"})

    calls = {"n": 0}

    def boom(**kwargs):
        calls["n"] += 1
        raise ea.VerificationFailedError("rolled back")

    monkeypatch.setattr(ac, "patch_agent_safely", boom)
    ac.sync_system_tools_for_org("o1")
    assert calls["n"] == 1  # VerificationFailedError is NEVER retried


# ─── 1.5 reconcile_hk_tool_ids: abort on unresolved; preserve non-hk_ ids ─────
def _stub_resolve(monkeypatch, names):
    """All names resolve to tool_<name>."""
    monkeypatch.setattr(
        ac, "_resolve_hk_tool_ids", lambda required=None: {n: f"tool_{n}" for n in (required or names)}
    )


def test_reconcile_aborts_when_a_tool_fails_to_resolve(monkeypatch):
    from fastapi import HTTPException

    def raise_resolve(required=None):
        raise HTTPException(status_code=400, detail="missing hk_createInquiry")

    monkeypatch.setattr(ac, "_resolve_hk_tool_ids", raise_resolve)
    # If resolve aborts, get_agent_config / patch must NEVER be called.
    monkeypatch.setattr(
        ac, "get_agent_config", lambda a: (_ for _ in ()).throw(AssertionError("should not GET"))
    )
    monkeypatch.setattr(
        ac, "patch_agent_safely",
        lambda **k: (_ for _ in ()).throw(AssertionError("should not PATCH")),
    )
    out = ac.reconcile_hk_tool_ids("o1", AGENT, actor_id="u1")
    assert out["removed"] == [] and out["desired"] == []
    assert out["reason"].startswith("resolve_failed:")


def test_reconcile_preserves_unknown_non_hk_ids(monkeypatch):
    _stub_resolve(monkeypatch, ac.HK_TOOL_NAMES)
    desired_hk = [f"tool_{n}" for n in ac.HK_TOOL_NAMES]
    # Current = a custom (non-hk_) id + a STALE hk_ id no longer desired + one good hk_ id.
    current_ids = ["custom_tool_keepme", "tool_OLD_hk_stale"] + desired_hk[:1]
    cfg = base_cfg()
    ea._set_path(cfg, ea.TOOL_IDS_PATH, current_ids)

    captured = {}

    def fake_patch(**kwargs):
        captured["field_patches"] = kwargs["field_patches"]
        captured["merge_arrays"] = kwargs["merge_arrays"]
        return {}

    monkeypatch.setattr(ac, "get_agent_config", lambda a: copy.deepcopy(cfg))
    monkeypatch.setattr(ac, "patch_agent_safely", fake_patch)

    out = ac.reconcile_hk_tool_ids("o1", AGENT, actor_id="u1")
    written = ea._get_path(captured["field_patches"], ea.TOOL_IDS_PATH)
    # Custom id preserved.
    assert "custom_tool_keepme" in written
    # NOTE: "tool_OLD_hk_stale" is NOT one of the resolved hk_ ids, so it is treated
    # as an UNKNOWN id and PRESERVED (reconcile only drops ids it positively knows
    # are hk_). The desired set contains all 11 resolved ids.
    assert "tool_OLD_hk_stale" in written  # unknown → preserved (never mass-removed)
    for tid in desired_hk:
        assert tid in written
    # Explicit replacement, NOT a union.
    assert captured["merge_arrays"] == []


def test_reconcile_noop_when_already_reconciled(monkeypatch):
    _stub_resolve(monkeypatch, ac.HK_TOOL_NAMES)
    desired_hk = [f"tool_{n}" for n in ac.HK_TOOL_NAMES]
    cfg = base_cfg()
    ea._set_path(cfg, ea.TOOL_IDS_PATH, list(desired_hk))
    monkeypatch.setattr(ac, "get_agent_config", lambda a: copy.deepcopy(cfg))
    monkeypatch.setattr(
        ac, "patch_agent_safely",
        lambda **k: (_ for _ in ()).throw(AssertionError("should not PATCH on no-op")),
    )
    out = ac.reconcile_hk_tool_ids("o1", AGENT, actor_id="u1")
    assert out["removed"] == []
    assert set(out["kept"]) == set(desired_hk)
