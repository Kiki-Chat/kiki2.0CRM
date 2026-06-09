"""LLM case matchmaker — groups a customer's fragmented inquiries into real
"Vorgang" (case) clusters.

The data showed there is NO single shared key across a matter's records except the
customer, and the only real signal is semantic (topic + what the call/appointment is
about — the inquiry `notes` are boilerplate). So:

  1. Gather the REAL signal per inquiry — topic + the linked call summaries +
     appointment date/topic (NOT the boilerplate notes).
  2. Embeddings pre-pass (text-embedding-3-small): cosine-cluster the obvious matches
     cheaply, and hand the LLM candidate hints — so it only adjudicates.
  3. LLM adjudication (gpt-4o-mini, temp 0, JSON-only, terse): final grouping into
     cases with a confidence (0-1) + a short reason each. Conservative — merge only
     when clearly one matter; when unsure, keep separate.
  4. Confidence tiers: >=0.80 auto, 0.50-0.79 review, single = standalone.

PURE PROPOSAL — writes nothing to the DB. The dry-run runner reports; applying the
grouping (stamping case_id) is a separate, approved step.
"""
from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter

from app.core.config import settings
from app.db.supabase_client import get_service_client
from app.services.ai import client as ai_client
from app.services.ai import usage as ai_usage

log = logging.getLogger(__name__)

AUTO = 0.80
REVIEW = 0.50
_EMB_MODEL = "text-embedding-3-small"
_STRONG_SIM = 0.70  # union-find candidate threshold (conservative — under-merge, let the LLM join)


def _truncate(s: str | None, n: int) -> str:
    return (s or "").strip().replace("\n", " ")[:n]


def _gather_signals(client, org_id: str, customer_id: str) -> list[dict]:
    """Compact per-inquiry signal: number, topic, type, call summaries, appt info."""
    inqs = (
        client.table("inquiries")
        .select("id, number, subject, title, type, status, created_at")
        .eq("org_id", org_id).eq("customer_id", customer_id)
        .neq("status", "deleted").order("created_at")
        .execute().data or []
    )
    if not inqs:
        return []
    ids = [i["id"] for i in inqs]
    calls = (
        client.table("calls")
        .select("inquiry_id, summary_title, summary, direction, started_at")
        .eq("org_id", org_id).in_("inquiry_id", ids).is_("deleted_at", "null")
        .execute().data or []
    )
    appts = (
        client.table("appointments")
        .select("inquiry_id, title, scheduled_at")
        .eq("org_id", org_id).in_("inquiry_id", ids)
        .execute().data or []
    )
    calls_by: dict[str, list[dict]] = {}
    for c in calls:
        calls_by.setdefault(c["inquiry_id"], []).append(c)
    appts_by: dict[str, list[dict]] = {}
    for a in appts:
        appts_by.setdefault(a["inquiry_id"], []).append(a)

    out: list[dict] = []
    for i in inqs:
        topic = i.get("subject") or i.get("title") or "Anfrage"
        cs = calls_by.get(i["id"], [])
        call_titles = ", ".join(_truncate(c.get("summary_title"), 60) for c in cs if c.get("summary_title"))
        call_dir = ",".join(sorted({c.get("direction") or "?" for c in cs})) if cs else "—"
        summ = _truncate(next((c.get("summary") for c in cs if c.get("summary")), ""), 160)
        ap = appts_by.get(i["id"], [])
        appt_txt = "; ".join(
            f"{_truncate(a.get('title'), 40)} {(a.get('scheduled_at') or '')[:10]}".strip() for a in ap
        )
        signal = (
            f"[{i['number']}] {topic} | typ={i.get('type')} dir={call_dir} "
            f"| anrufe: {call_titles or '—'} | termin: {appt_txt or '—'} "
            f"| {summ} | {(i.get('created_at') or '')[:10]}"
        )
        out.append({"id": i["id"], "number": i["number"], "topic": topic, "signal": _truncate(signal, 340)})
    return out


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _candidate_clusters(numbers: list[str], vecs: list[list[float]]) -> list[list[str]]:
    """Union-find at _STRONG_SIM → candidate clusters of inquiry numbers."""
    n = len(numbers)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for x in range(n):
        for y in range(x + 1, n):
            if _cosine(vecs[x], vecs[y]) >= _STRONG_SIM:
                parent[find(x)] = find(y)
    groups: dict[int, list[str]] = {}
    for idx in range(n):
        groups.setdefault(find(idx), []).append(numbers[idx])
    return list(groups.values())


_SYS = (
    "Du gruppierst die Anfragen EINES Kunden in einzelne reale Vorgänge (Fälle) eines "
    "Handwerker-CRM. Ein Vorgang = EIN zugrunde liegendes Anliegen samt seinem "
    "Termin-Lebenszyklus (Erstanfrage → Buchung → Bestätigung/Verschiebung/Stornierung → "
    "Rückfragen). Führe NUR zusammen, wenn es eindeutig dasselbe Anliegen ist; im Zweifel "
    "getrennt lassen. Bestätigungs-, Verschiebungs- und Stornierungsanrufe gehören zum "
    "Vorgang des Termins, auf den sie sich beziehen (per Datum/Thema zuordnen). Jede "
    "Anfragenummer MUSS in genau einem Vorgang vorkommen. Antworte NUR mit JSON."
)


def _parse_json(text: str) -> dict:
    text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    return json.loads(text)


def propose_cases_for_customer(client, org_id: str, customer_id: str, customer_name: str | None = None) -> dict:
    sigs = _gather_signals(client, org_id, customer_id)
    model = settings.openai_classifier_model
    result: dict = {
        "customer_id": customer_id, "customer_name": customer_name, "n_inquiries": len(sigs),
        "cases": [], "tokens": {"embed": 0, "prompt": 0, "completion": 0}, "cost": 0.0,
        "model": model, "error": None,
    }
    if len(sigs) <= 1:
        result["cases"] = [
            {"label": s["topic"], "members": [s["number"]], "confidence": 1.0, "reason": "einzige Anfrage", "tier": "single"}
            for s in sigs
        ]
        return result

    numbers = [s["number"] for s in sigs]

    # 1. embeddings pre-pass → candidate clusters (cheap recall)
    candidates: list[list[str]]
    try:
        vecs, etoks = ai_client.embed([s["signal"] for s in sigs], model=_EMB_MODEL)
        result["tokens"]["embed"] = etoks
        candidates = _candidate_clusters(numbers, vecs)
    except Exception as exc:  # noqa: BLE001
        log.warning("grouper: embed failed (%s)", exc)
        candidates = [[x] for x in numbers]

    # 2. LLM adjudication (terse JSON)
    cand_txt = "\n".join("- " + " + ".join(c) for c in candidates if len(c) > 1) or "(keine offensichtlichen)"
    inv = "\n".join(s["signal"] for s in sigs)
    user = (
        f"Kunde: {customer_name or customer_id}\n\nANFRAGEN:\n{inv}\n\n"
        f"Embedding-Kandidaten (evtl. gleicher Vorgang):\n{cand_txt}\n\n"
        'Gib JSON: {"cases":[{"label":"kurzes Thema","members":["ANF-..."],'
        '"confidence":0.0-1.0,"reason":"<=12 Wörter"}]}'
    )
    try:
        resp = ai_client.chat(
            [{"role": "system", "content": _SYS}, {"role": "user", "content": user}],
            model=model, temperature=0.0, response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or "{}"
        u = getattr(resp, "usage", None)
        pt = getattr(u, "prompt_tokens", 0) or 0
        ct = getattr(u, "completion_tokens", 0) or 0
        result["tokens"]["prompt"], result["tokens"]["completion"] = pt, ct
        ai_usage.log_usage(org_id=org_id, user_id=None, feature="case_grouping", model=model, prompt_tokens=pt, completion_tokens=ct)
        cases = _parse_json(content).get("cases") or []
    except Exception as exc:  # noqa: BLE001
        log.warning("grouper: llm failed (%s)", exc)
        result["error"] = str(exc)[:200]
        cases = [{"label": s["topic"], "members": [s["number"]], "confidence": 0.0, "reason": "Fallback (LLM-Fehler)"} for s in sigs]

    # validate coverage: each number in exactly one case; uncovered → own case
    seen: set[str] = set()
    clean: list[dict] = []
    for c in cases:
        members = [m for m in (c.get("members") or []) if m in numbers and m not in seen]
        if not members:
            continue
        seen.update(members)
        conf = max(0.0, min(1.0, float(c.get("confidence") or 0.0)))
        tier = "single" if len(members) == 1 else ("auto" if conf >= AUTO else ("review" if conf >= REVIEW else "low"))
        clean.append({"label": c.get("label") or "Vorgang", "members": members, "confidence": round(conf, 2), "reason": _truncate(c.get("reason"), 90), "tier": tier})
    for s in sigs:
        if s["number"] not in seen:
            clean.append({"label": s["topic"], "members": [s["number"]], "confidence": 1.0, "reason": "nicht gruppiert", "tier": "single"})

    result["cases"] = clean
    result["cost"] = ai_usage.estimate_cost(model, result["tokens"]["prompt"], result["tokens"]["completion"]) + round(result["tokens"]["embed"] / 1000 * 0.00002, 6)
    return result


def propose_cases_for_org(org_id: str) -> dict:
    client = get_service_client()
    rows = (
        client.table("inquiries").select("customer_id")
        .eq("org_id", org_id).neq("status", "deleted")
        .execute().data or []
    )
    counts = Counter(r["customer_id"] for r in rows if r.get("customer_id"))
    cids = list(counts.keys())
    names: dict[str, str | None] = {}
    if cids:
        for r in (client.table("customers").select("id, full_name").eq("org_id", org_id).in_("id", cids).execute().data or []):
            names[r["id"]] = r.get("full_name")
    per = [propose_cases_for_customer(client, org_id, cid, names.get(cid)) for cid, _ in counts.most_common()]
    return {"org_id": org_id, "customers": per}
