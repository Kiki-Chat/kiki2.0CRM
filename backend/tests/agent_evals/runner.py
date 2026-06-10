"""Agent-eval runner: replays scenarios.json against the test org's agent via the
ElevenLabs simulate-conversation API (text-only, ALL hk_* tools mocked — no live
webhook is hit, no data is written, no call is placed).

Usage (from backend/, venv active, .env present):

    python -m tests.agent_evals.runner                 # full baseline run
    python -m tests.agent_evals.runner ident_known_caller reschedule_must_change_not_book

Writes results/<UTC-stamp>/ with one JSON per scenario (full simulated
transcript + deterministic scoring) and a summary.json / summary.md.

Deterministic checks only — judge_notes are carried through for a separate
LLM/human grading pass. Costs ElevenLabs LLM credits per run; NOT part of the
pytest suite (see test_fixtures_valid.py for the offline schema check).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

HERE = Path(__file__).parent
API = "https://api.elevenlabs.io"
ALL_HK_TOOLS = [
    "hk_identifyCustomer", "hk_getAvailableAppointments", "hk_bookAppointment",
    "hk_changeAppointment", "hk_cancelAppointment", "hk_createInquiry",
    "hk_searchCustomerInquiries", "hk_updateCustomerData",
    "hk_queryKnowledgeBase", "hk_draftCostEstimate", "hk_transferCall",
]
NEW_TURNS_LIMIT = 30


def _load_env() -> None:
    env = HERE.parent.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v.strip().strip('"'))


def _tool_names_of(turn: dict) -> list[str]:
    names = []
    for x in turn.get("tool_calls") or []:
        if isinstance(x, str):
            names.append(x)
        elif isinstance(x, dict):
            n = x.get("tool_name") or x.get("name")
            if n:
                names.append(n)
    return names


def simulate(key: str, agent_id: str, scenario: dict, fixtures: dict) -> dict:
    mock_lib = fixtures["mock_library"]
    default_mock = fixtures["default_mock"]
    # Every hk_* tool gets a mock so no live webhook can ever fire.
    mocks = {
        t: {"default_return_value": json.dumps(default_mock, ensure_ascii=False),
            "default_is_error": False}
        for t in ALL_HK_TOOLS
    }
    for tool, lib_key in (scenario.get("mocks") or {}).items():
        mocks[tool] = {
            "default_return_value": json.dumps(mock_lib[lib_key], ensure_ascii=False),
            "default_is_error": False,
        }
    body = {
        "simulation_specification": {
            "simulated_user_config": {
                "prompt": {"prompt": scenario["persona"]},
                "language": "de",
            },
            "dynamic_variables": fixtures["dynamic_variables"],
            "tool_mock_config": mocks,
        },
        "new_turns_limit": NEW_TURNS_LIMIT,
    }
    t0 = time.monotonic()
    r = httpx.post(
        f"{API}/v1/convai/agents/{agent_id}/simulate-conversation",
        headers={"xi-api-key": key}, json=body, timeout=600,
    )
    elapsed = time.monotonic() - t0
    r.raise_for_status()
    out = r.json()
    out["_wall_seconds"] = round(elapsed, 1)
    return out


def score(scenario: dict, sim: dict) -> dict:
    turns = sim.get("simulated_conversation") or []
    called: list[str] = []
    for t in turns:
        called.extend(_tool_names_of(t))
    agent_text = "\n".join(
        (t.get("message") or "") for t in turns if t.get("role") == "agent"
    )
    failures: list[str] = []
    warnings: list[str] = []

    for tool in scenario.get("must_call") or []:
        if tool not in called:
            failures.append(f"must_call missing: {tool}")
    any_of = scenario.get("must_call_any") or []
    if any_of and not any(t in called for t in any_of):
        failures.append(f"must_call_any missing: one of {any_of}")
    for tool in scenario.get("must_not_call") or []:
        if tool in called:
            failures.append(f"must_not_call violated: {tool}")
    for tool in scenario.get("should_call") or []:
        if tool not in called:
            warnings.append(f"should_call missing (soft): {tool}")
    for pat in scenario.get("must_contain_any") or []:
        # must_contain_any: ANY single pattern matching is enough.
        if re.search(pat, agent_text, re.IGNORECASE):
            break
    else:
        if scenario.get("must_contain_any"):
            failures.append(
                f"must_contain_any: none of {scenario['must_contain_any']} found"
            )
    for pat in scenario.get("must_not_contain") or []:
        m = re.search(pat, agent_text, re.IGNORECASE)
        if m:
            failures.append(f"must_not_contain violated: {pat!r} -> {m.group(0)[:80]!r}")

    return {
        "id": scenario["id"],
        "bucket": scenario["bucket"],
        "passed": not failures,
        "failures": failures,
        "warnings": warnings,
        "tools_called": called,
        "agent_turns": sum(1 for t in turns if t.get("role") == "agent"),
        "wall_seconds": sim.get("_wall_seconds"),
        "judge_notes": scenario.get("judge_notes"),
    }


def main(argv: list[str]) -> int:
    _load_env()
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        print("ELEVENLABS_API_KEY not set (backend/.env)", file=sys.stderr)
        return 2
    fixtures = json.loads((HERE / "scenarios.json").read_text())
    agent_id = fixtures["agent_id"]
    wanted = set(argv) if argv else None
    scenarios = [
        s for s in fixtures["scenarios"] if wanted is None or s["id"] in wanted
    ]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    outdir = HERE / "results" / stamp
    outdir.mkdir(parents=True, exist_ok=True)

    results = []
    for s in scenarios:
        print(f"▶ {s['id']} …", flush=True)
        try:
            sim = simulate(key, agent_id, s, fixtures)
        except Exception as e:  # noqa: BLE001 — record and continue
            results.append({"id": s["id"], "bucket": s["bucket"], "passed": False,
                            "failures": [f"simulation error: {e}"], "warnings": [],
                            "tools_called": [], "judge_notes": s.get("judge_notes")})
            print(f"  ✗ simulation error: {e}")
            continue
        res = score(s, sim)
        results.append(res)
        (outdir / f"{s['id']}.json").write_text(
            json.dumps({"scenario": s, "result": res, "simulation": sim},
                       ensure_ascii=False, indent=2)
        )
        mark = "✓" if res["passed"] else "✗"
        print(f"  {mark} tools={res['tools_called']} "
              f"failures={res['failures']} warnings={res['warnings']}")

    passed = sum(1 for r in results if r["passed"])
    summary = {
        "stamp": stamp,
        "agent_id": agent_id,
        "pass_rate": f"{passed}/{len(results)}",
        "results": results,
    }
    (outdir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )
    lines = [f"# Agent eval run {stamp}", "",
             f"Agent: `{agent_id}`  Pass rate: **{passed}/{len(results)}**", "",
             "| scenario | bucket | result | failures | warnings |",
             "|---|---|---|---|---|"]
    for r in results:
        lines.append(
            f"| {r['id']} | {r['bucket']} | {'PASS' if r['passed'] else 'FAIL'} | "
            f"{'; '.join(r['failures']) or '—'} | {'; '.join(r['warnings']) or '—'} |"
        )
    (outdir / "summary.md").write_text("\n".join(lines) + "\n")
    print(f"\nPass rate: {passed}/{len(results)} — results in {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
