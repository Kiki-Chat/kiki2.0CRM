"""Apply the case matchmaker across one org — materialise the grouping so it can be
tested on the real screens. Idempotent: clears the org's existing cases first (case_id
auto-nulls via ON DELETE SET NULL), then re-groups every customer. Run:

    cd backend && .venv/bin/python -m app.services.cases.apply_run [org_prefix]
"""
from __future__ import annotations

import sys
from collections import Counter

from app.db.supabase_client import get_service_client
from app.services.ai import client as ai_client
from app.services.ai import usage as ai_usage
from app.services.cases.grouper import propose_cases_for_customer
from app.services.common import gen_case_number


def _resolve_org(client, prefix: str) -> tuple[str, str]:
    for r in (client.table("organizations").select("id, name").execute().data or []):
        if str(r["id"]).startswith(prefix):
            return r["id"], r.get("name") or "?"
    raise SystemExit(f"no org matching {prefix!r}")


def main() -> None:
    prefix = sys.argv[1] if len(sys.argv) > 1 else "04acd916"
    if not ai_client.is_configured():
        raise SystemExit("OPENAI not configured")
    client = get_service_client()
    org_id, org_name = _resolve_org(client, prefix)
    if not ai_usage.within_cap(org_id):
        raise SystemExit("monthly AI cost cap reached")
    print(f"APPLY grouping — {org_name} ({org_id[:8]})")

    # Idempotent reset: clear this org's cases + the per-inquiry case audit fields.
    client.table("inquiries").update(
        {"case_id": None, "case_confidence": None, "case_reason": None, "case_source": None}
    ).eq("org_id", org_id).execute()
    client.table("cases").delete().eq("org_id", org_id).execute()

    rows = client.table("inquiries").select("customer_id").eq("org_id", org_id).neq("status", "deleted").execute().data or []
    counts = Counter(r["customer_id"] for r in rows if r.get("customer_id"))
    cids = list(counts.keys())
    names: dict[str, str] = {}
    if cids:
        for r in (client.table("customers").select("id, full_name").eq("org_id", org_id).in_("id", cids).execute().data or []):
            names[r["id"]] = r.get("full_name")

    total_cases = total_grouped = 0
    for cid, _ in counts.most_common():
        prop = propose_cases_for_customer(client, org_id, cid, names.get(cid))
        merges = [c for c in prop["cases"] if len(c["members"]) >= 2]
        if not merges:
            continue
        numrows = (
            client.table("inquiries").select("id, number")
            .eq("org_id", org_id).eq("customer_id", cid).neq("status", "deleted").execute().data or []
        )
        id_by_num = {r["number"]: r["id"] for r in numrows}
        print(f"\n{names.get(cid) or cid[:8]} — {prop['n_inquiries']} inq → {len(merges)} cases ({prop['model']}):")
        for c in merges:
            ids = [id_by_num[m] for m in c["members"] if m in id_by_num]
            if not ids:
                continue
            case = client.table("cases").insert(
                {"org_id": org_id, "customer_id": cid,
                 "title": (c["label"] or "Vorgang")[:120],
                 "status": "active",
                 "description": "Aus KI-Gruppierung erstellt (Offline-Lauf).",
                 "number": gen_case_number(client, org_id)}
            ).execute().data[0]
            client.table("inquiries").update(
                {"case_id": case["id"], "case_confidence": c["confidence"],
                 "case_reason": ((c["reason"] or "")[:200] or None), "case_source": "ai"}
            ).eq("org_id", org_id).in_("id", ids).execute()
            total_cases += 1
            total_grouped += len(ids)
            print(f"  [{c['tier']}] {c['confidence']} :: {c['label']} :: {', '.join(c['members'])}")

    print(f"\nDONE — {total_cases} cases created, {total_grouped} inquiries grouped into them.")


if __name__ == "__main__":
    main()
