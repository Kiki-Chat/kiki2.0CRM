"""Live integration tests — hit the REAL test agent + Supabase.

Marked `live`; skip in CI with `-m "not live"`. Every test snapshots the agent
state and restores it, so the agent is left exactly as found.

Test agent (sandbox) and org are the ONLY ones referenced here.
"""

import time

import pytest

from app.core.config import settings
from app.services import elevenlabs_agent as ea

AGENT = "agent_5001ksahz3w7fhx90j71xr800py4"  # test sandbox agent (safe)
ORG_ID = "c4dbf596-86fd-4484-88d9-095b2c082afb"  # kiki-test-007 (real organizations.id)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not settings.elevenlabs_api_key, reason="ELEVENLABS_API_KEY not configured"
    ),
]


def _latest_snapshot_id(org_id: str) -> str:
    db = ea.get_service_client()
    rows = (
        db.table("agent_config_snapshots")
        .select("id")
        .eq("org_id", org_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    return rows[0]["id"]


def test_live_get_agent():
    cfg = ea.get_agent_config(AGENT)
    assert cfg["agent_id"] == AGENT
    ce = ea._get_path(cfg, ea.CLIENT_EVENTS_PATH)
    assert isinstance(ce, list) and "audio" in ce
    assert (ea._get_path(cfg, ea.PROMPT_PATH) or "").strip()
    assert ea._get_path(cfg, ea.VOICE_PATH)


def test_live_audio_assertion_leaves_agent_untouched():
    before = ea.get_agent_config(AGENT)
    ce_before = ea._get_path(before, ea.CLIENT_EVENTS_PATH)
    with pytest.raises(ea.SilentAgentRiskError):
        ea.patch_agent_safely(
            agent_id=AGENT,
            field_patches={
                "conversation_config": {"conversation": {"client_events": ["agent_response"]}}
            },
            actor_id=None,
            org_id=ORG_ID,
            endpoint_label="live_audio_test",
        )
    after = ea.get_agent_config(AGENT)
    assert ea._get_path(after, ea.CLIENT_EVENTS_PATH) == ce_before
    assert "audio" in ea._get_path(after, ea.CLIENT_EVENTS_PATH)


def test_live_cross_org_blocked():
    with pytest.raises(ea.CrossOrgAgentWriteError):
        ea.patch_agent_safely(
            agent_id="agent_not_this_org_0000000000000000",
            field_patches={"name": "nope"},
            actor_id=None,
            org_id=ORG_ID,
            endpoint_label="live_cross_org_test",
        )


def test_live_patch_then_rollback():
    baseline = ea.get_agent_config(AGENT)
    orig_name = baseline.get("name")
    new_name = f"Test-Persona-{int(time.time())}"

    ea.patch_agent_safely(
        agent_id=AGENT,
        field_patches={"name": new_name},
        actor_id=None,
        org_id=ORG_ID,
        endpoint_label="live_name_test",
    )
    assert ea.get_agent_config(AGENT).get("name") == new_name

    snap_id = _latest_snapshot_id(ORG_ID)  # snapshot captured before the name change
    ea.rollback_to_snapshot(snapshot_id=snap_id, actor_id=None)
    assert ea.get_agent_config(AGENT).get("name") == orig_name


def test_live_full_field_round_trip():
    baseline = ea.get_agent_config(AGENT)
    orig_fm = ea._get_path(baseline, ea.FIRST_MESSAGE_PATH)
    known = "Hallo, hier ist Kiki. Wie kann ich helfen?"
    try:
        ea.patch_agent_safely(
            agent_id=AGENT,
            field_patches={"conversation_config": {"agent": {"first_message": known}}},
            actor_id=None,
            org_id=ORG_ID,
            endpoint_label="live_fm_test",
        )
        assert ea._get_path(ea.get_agent_config(AGENT), ea.FIRST_MESSAGE_PATH) == known
        # tools preserved through the write
        assert len(ea._get_path(ea.get_agent_config(AGENT), ea.TOOLS_PATH) or []) >= 1
    finally:
        ea.patch_agent_safely(
            agent_id=AGENT,
            field_patches={"conversation_config": {"agent": {"first_message": orig_fm}}},
            actor_id=None,
            org_id=ORG_ID,
            endpoint_label="live_fm_restore",
        )
    assert ea._get_path(ea.get_agent_config(AGENT), ea.FIRST_MESSAGE_PATH) == orig_fm


def test_live_knowledge_push_remove():
    db = ea.get_service_client()
    base_kb = len(ea.list_knowledge_base(AGENT))
    row = (
        db.table("knowledge_resources")
        .insert(
            {
                "org_id": ORG_ID,
                "kind": "url",
                "source": "https://heykiki.de",
                "display_name": f"Test-KB-{int(time.time())}",
                "status": "pending",
            }
        )
        .execute()
        .data[0]
    )
    rid = row["id"]
    try:
        res = ea.push_knowledge_resource_to_elevenlabs(resource_id=rid)
        assert res["status"] == "ready"
        assert res["chunk_count"] > 0
        assert len(ea.list_knowledge_base(AGENT)) == base_kb + 1
    finally:
        ea.remove_knowledge_resource_from_elevenlabs(resource_id=rid)
        db.table("knowledge_resources").delete().eq("id", rid).execute()
    assert len(ea.list_knowledge_base(AGENT)) == base_kb
