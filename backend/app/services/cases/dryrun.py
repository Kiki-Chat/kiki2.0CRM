"""Dry-run the case matchmaker over one org. Reads the DB + calls OpenAI; writes
NOTHING to the DB. Prints a report and writes VORGANG_GROUPING_DRYRUN.md/.json at
the repo root. Run:

    cd backend && .venv/bin/python -m app.services.cases.dryrun [org_id_prefix]
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter

from app.db.supabase_client import get_service_client
from app.services.ai import client as ai_client
from app.services.ai import usage as ai_usage
from app.services.cases.grouper import propose_cases_for_org

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))


def _resolve_org(prefix: str) -> tuple[str, str]:
    c = get_service_client()
    for r in (c.table("organizations").select("id, name").execute().data or []):
        if str(r["id"]).startswith(prefix):
            return r["id"], r.get("name") or "?"
    raise SystemExit(f"no org matching {prefix!r}")


def main() -> None:
    prefix = sys.argv[1] if len(sys.argv) > 1 else "04acd916"
    if not ai_client.is_configured():
        raise SystemExit("OPENAI not configured (OPENAI_API_KEY missing)")
    org_id, org_name = _resolve_org(prefix)
    if not ai_usage.within_cap(org_id):
        raise SystemExit("monthly AI cost cap reached — aborting")

    t0 = time.time()
    res = propose_cases_for_org(org_id)
    dt = round(time.time() - t0, 2)

    custs = res["customers"]
    multi = [c for c in custs if c["n_inquiries"] >= 2]
    tot_inq = sum(c["n_inquiries"] for c in custs)
    all_cases = [case for c in custs for case in c["cases"]]
    tot_cases = len(all_cases)
    tiers = Counter(case["tier"] for case in all_cases)
    merged = [case for case in all_cases if len(case["members"]) >= 2]
    inq_merged = sum(len(case["members"]) for case in merged)
    etok = sum(c["tokens"]["embed"] for c in custs)
    ptok = sum(c["tokens"]["prompt"] for c in custs)
    ctok = sum(c["tokens"]["completion"] for c in custs)
    cost = round(sum(c["cost"] for c in custs), 6)
    confs = [case["confidence"] for case in merged]
    avg_conf = round(sum(confs) / len(confs), 2) if confs else 0.0
    model = custs[0]["model"] if custs else "gpt-4o-mini"

    lines: list[str] = []

    def p(s: str = "") -> None:
        print(s)
        lines.append(s)

    p(f"# Vorgang grouping — DRY RUN ({org_name})")
    p("")
    p("## How it ran")
    p(f"- Pipeline: real signal (topic + call summaries + appointment) → text-embedding-3-small")
    p(f"  cosine pre-cluster → {model} adjudication (JSON, temp 0, conservative, no prose).")
    p(f"- Scope: {len(custs)} customers ({len(multi)} with ≥2 inquiries → sent to the LLM).")
    p(f"- Runtime {dt}s · tokens: embed {etok}, prompt {ptok}, completion {ctok} · est. cost **${cost}**.")
    p("")
    p("## Results")
    comp = round(tot_inq / tot_cases, 2) if tot_cases else 0
    p(f"- Inquiries in: **{tot_inq}** → proposed cases out: **{tot_cases}**  (compression {comp}×).")
    p(f"- Real merges (multi-inquiry cases): **{len(merged)}**, folding **{inq_merged}** inquiries together.")
    p(f"- Tiers: auto(≥.80)={tiers.get('auto', 0)} · review(.50–.79)={tiers.get('review', 0)} · "
      f"low(<.50)={tiers.get('low', 0)} · single={tiers.get('single', 0)} · avg merge conf {avg_conf}.")
    p("")
    p("## Per customer")
    for c in custs:
        merges = [x for x in c["cases"] if len(x["members"]) >= 2]
        p(f"### {c['customer_name'] or c['customer_id'][:8]} — {c['n_inquiries']} inquiries → "
          f"{len(c['cases'])} cases ({len(merges)} merged)")
        if c.get("error"):
            p(f"  ⚠️ {c['error']}")
        for case in merges:
            p(f"- **{case['label']}** · conf {case['confidence']} · _{case['tier']}_ · {', '.join(case['members'])}")
            p(f"    ↳ {case['reason']}")
        singles = [x["members"][0] for x in c["cases"] if len(x["members"]) == 1]
        if singles:
            p(f"- _standalone ({len(singles)}):_ " + ", ".join(singles))
        p("")

    md = "\n".join(lines)
    with open(os.path.join(_REPO, "VORGANG_GROUPING_DRYRUN.md"), "w") as f:
        f.write(md + "\n")
    with open(os.path.join(_REPO, "VORGANG_GROUPING_DRYRUN.json"), "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print("\n[written] VORGANG_GROUPING_DRYRUN.md / .json")


if __name__ == "__main__":
    main()
