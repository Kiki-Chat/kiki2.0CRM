"""Offline schema check for the agent-eval fixtures — keeps scenarios.json honest
without any network call. The actual eval (runner.py) costs ElevenLabs credits
and is run manually / per prompt change, never as part of the pytest suite."""
import json
import re
from pathlib import Path

FIXTURES = json.loads((Path(__file__).parent / "scenarios.json").read_text())

KNOWN_TOOLS = {
    "hk_identifyCustomer", "hk_getAvailableAppointments", "hk_bookAppointment",
    "hk_changeAppointment", "hk_cancelAppointment", "hk_createInquiry",
    "hk_searchCustomerInquiries", "hk_updateCustomerData",
    "hk_queryKnowledgeBase", "hk_draftCostEstimate", "hk_transferCall",
    "transfer_to_number", "transfer_to_agent", "end_call",
}


def test_fixture_top_level():
    assert FIXTURES["agent_id"].startswith("agent_")
    dyn = FIXTURES["dynamic_variables"]
    for k in ("system__caller_id", "system__agent_id", "system__call_sid",
              "system__conversation_id"):
        assert k in dyn
    assert FIXTURES["scenarios"], "no scenarios defined"


def test_scenarios_well_formed():
    ids = set()
    for s in FIXTURES["scenarios"]:
        assert s["id"] not in ids, f"duplicate id {s['id']}"
        ids.add(s["id"])
        assert s["bucket"] and s["persona"] and s["judge_notes"]
        for key in ("must_call", "must_not_call", "must_call_any", "should_call"):
            for tool in s.get(key) or []:
                assert tool in KNOWN_TOOLS, f"{s['id']}: unknown tool {tool} in {key}"
        for lib_key in (s.get("mocks") or {}).values():
            assert lib_key in FIXTURES["mock_library"], (
                f"{s['id']}: unknown mock {lib_key}"
            )
        for key in ("must_contain_any", "must_not_contain"):
            for pat in s.get(key) or []:
                re.compile(pat)  # raises on an invalid regex


def test_scenario_buckets_cover_brief():
    buckets = {s["bucket"] for s in FIXTURES["scenarios"]}
    assert {"identification", "booking", "emergency", "price", "guardrails"} <= buckets
