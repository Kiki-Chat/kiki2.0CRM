"""LLM case matchmaker — groups a customer's fragmented inquiries into real
"Vorgang" (case) clusters. v2: tuned against the dry-run's over-merge failure.

Pipeline (token-frugal, guardrailed):
  1. Rich per-inquiry signal — topic + ALL linked call summaries + appointment
     date/topic (the inquiry `notes` are boilerplate; the matter lives here — esp.
     the appointment date a confirm/cancel call names).
  2. Embeddings (text-embedding-3-small): cosine candidate hints AND a deterministic
     separation guardrail.
  3. LLM adjudication — gpt-4o for large/dense customers, gpt-4o-mini for small;
     temp 0, JSON-only, a HARD prompt: many small cases, never merge different
     problems (Heizung ≠ Dach ≠ Elektrik), lifecycle is the only reason to merge.
  4. Guardrails (deterministic — these fix the over-merge the dry-run exposed):
     a. Topical-outlier ejection — a TOPICAL inquiry whose max embedding similarity
        to its case-mates is below a floor is split out. Action/follow-up calls
        (generic text like "German Greeting") are EXEMPT so they stay attached.
     b. Size-capped confidence — a case bigger than _SIZE_REVIEW can never be 'auto';
        it always drops to human review regardless of the LLM's score.

PURE PROPOSAL — writes nothing. The dry-run runner reports; applying is separate.
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
_STRONG_SIM = 0.70        # union-find candidate hint
_SEPARATION_FLOOR = 0.30  # below this, two TOPICAL inquiries are different problems
_BIG = 12                 # >= this many inquiries → use the stronger model
_BIG_MODEL = "gpt-4o"
_SIZE_REVIEW = 6          # a case larger than this can never be 'auto'

# Action/follow-up calls carry generic text ("Cancel Appointment", "German Greeting")
# — they legitimately belong to a matter despite low topical similarity, so they are
# EXEMPT from the outlier-ejection guardrail.
_ACTION_KW = (
    "confirm", "confirmation", "cancel", "reschedul", "greeting", "voicemail",
    "bestätig", "bestaetig", "storn", "absage", "verschieb", "änderungswunsch",
    "aenderungswunsch", "follow", "nachfass", "erinnerung", "reminder",
)


def _truncate(s, n: int) -> str:
    return (s or "").strip().replace("\n", " ")[:n]


def _is_action(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in _ACTION_KW)


def _gather_signals(client, org_id: str, customer_id: str) -> list[dict]:
    # Only UNGROUPED inquiries — the matchmaker proposes NEW groupings for what
    # isn't filed yet; it never re-proposes (and duplicates) existing groups.
    # Projects merge (item 6): "ungrouped" = project_id IS NULL — the grouper's
    # output materialises as Projekte now, not cases.
    inqs = (
        client.table("inquiries")
        .select("id, number, subject, title, type, status, created_at")
        .eq("org_id", org_id).eq("customer_id", customer_id)
        .neq("status", "deleted").is_("project_id", "null").order("created_at").execute().data or []
    )
    if not inqs:
        return []
    ids = [i["id"] for i in inqs]
    calls = (
        client.table("calls")
        .select("inquiry_id, summary_title, summary, direction, started_at, transcript")
        .eq("org_id", org_id).in_("inquiry_id", ids).is_("deleted_at", "null").execute().data or []
    )
    appts = (
        client.table("appointments").select("inquiry_id, title, scheduled_at")
        .eq("org_id", org_id).in_("inquiry_id", ids).execute().data or []
    )
    calls_by: dict[str, list[dict]] = {}
    appts_by: dict[str, list[dict]] = {}
    for c in calls:
        calls_by.setdefault(c["inquiry_id"], []).append(c)
    for a in appts:
        appts_by.setdefault(a["inquiry_id"], []).append(a)

    out: list[dict] = []
    for i in inqs:
        topic = i.get("subject") or i.get("title") or "Anfrage"
        cs = calls_by.get(i["id"], [])
        titles = ", ".join(_truncate(c.get("summary_title"), 50) for c in cs if c.get("summary_title"))
        cdir = ",".join(sorted({c.get("direction") or "?" for c in cs})) if cs else "—"
        # Content, not just the headline: call summaries + the customer's own
        # transcript words — that's what distinguishes e.g. bedroom from kitchen
        # heating when the subject only says "Heizung".
        summ_parts = [c.get("summary") or "" for c in cs]
        for c in cs:
            tr = c.get("transcript")
            if isinstance(tr, list):
                summ_parts.append(" ".join(
                    str(t.get("message") or "") for t in tr
                    if isinstance(t, dict) and (t.get("role") or "") != "agent" and t.get("message")
                ))
        summ = _truncate(" ".join(p for p in summ_parts if p), 500)
        ap = appts_by.get(i["id"], [])
        appt_txt = "; ".join(f"{_truncate(a.get('title'), 36)}@{(a.get('scheduled_at') or '')[:10]}" for a in ap)
        signal = (
            f"[{i['number']}] {topic} | typ={i.get('type')} ri={cdir} "
            f"| anrufe: {titles or '—'} | termin: {appt_txt or '—'} | {summ}"
        )
        out.append({
            "id": i["id"], "number": i["number"], "topic": topic,
            "is_action": _is_action(f"{topic} {titles}"),
            "signal": _truncate(signal, 700),
        })
    return out


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _candidate_clusters(numbers, vecs) -> list[list[str]]:
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
    "Du ordnest die Anfragen EINES Kunden den realen Vorgängen (Fällen) eines "
    "Handwerker-CRM zu. Ein Vorgang = EIN konkretes Anliegen (z. B. 'Dach undicht "
    "Garage'), NICHT eine Gewerk-Kategorie ('Heizung allgemein'). REGELN: "
    "(1) Unterschiedliche Probleme NIEMALS zusammenführen — Heizung, Dach, Elektrik, "
    "Sanitär sind immer getrennte Vorgänge. "
    "(2) Der EINZIGE Grund zum Zusammenführen ist derselbe Termin-Lebenszyklus: "
    "Erstanfrage → Buchung → Bestätigung/Verschiebung/Stornierung → Rückfrage. "
    "(3) Bestätigungs-/Storno-/Verschiebungsanrufe gehören zum Vorgang DES Termins, "
    "den sie nennen (per Datum/Thema im Anruftext zuordnen). "
    "(4) Lieber viele kleine, präzise Vorgänge als wenige große. Ein Vorgang mit >6 "
    "Anfragen ist fast immer falsch. "
    "(5) Jede Anfragenummer in genau EINEM Vorgang. Antworte NUR mit JSON."
)


def _parse_json(text: str) -> dict:
    text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    return json.loads(text)


def _eject_outliers(members, num_to_vec, num_to_action):
    """(kept, ejected) — a TOPICAL member whose max similarity to the other members is
    below the floor is ejected. Action-calls (generic text) are exempt."""
    if len(members) < 2:
        return members, []
    kept, ejected = [], []
    for m in members:
        if num_to_action.get(m):
            kept.append(m)
            continue
        vm = num_to_vec.get(m)
        others = [o for o in members if o != m and num_to_vec.get(o) is not None]
        if vm is None or not others:
            kept.append(m)
            continue
        best = max(_cosine(vm, num_to_vec[o]) for o in others)
        (ejected if best < _SEPARATION_FLOOR else kept).append(m)
    return kept, ejected


def propose_cases_for_customer(client, org_id: str, customer_id: str, customer_name: str | None = None) -> dict:
    sigs = _gather_signals(client, org_id, customer_id)
    n = len(sigs)
    model = _BIG_MODEL if n >= _BIG else settings.openai_classifier_model
    result: dict = {
        "customer_id": customer_id, "customer_name": customer_name, "n_inquiries": n,
        "cases": [], "tokens": {"embed": 0, "prompt": 0, "completion": 0}, "cost": 0.0,
        "model": model, "error": None,
    }
    if n <= 1:
        result["cases"] = [
            {"label": s["topic"], "members": [s["number"]], "confidence": 1.0, "reason": "einzige Anfrage", "tier": "single"}
            for s in sigs
        ]
        return result

    numbers = [s["number"] for s in sigs]
    num_to_action = {s["number"]: s["is_action"] for s in sigs}
    num_to_vec: dict[str, list[float]] = {}
    candidates: list[list[str]]
    try:
        vecs, etok = ai_client.embed([s["signal"] for s in sigs], model=_EMB_MODEL)
        result["tokens"]["embed"] = etok
        num_to_vec = {numbers[i]: vecs[i] for i in range(n)}
        candidates = _candidate_clusters(numbers, vecs)
    except Exception as exc:  # noqa: BLE001
        log.warning("grouper: embed failed (%s)", exc)
        candidates = [[x] for x in numbers]

    cand_txt = "\n".join("- " + " + ".join(c) for c in candidates if len(c) > 1) or "(keine)"
    user = (
        f"Kunde: {customer_name or customer_id}\n\nANFRAGEN:\n"
        + "\n".join(s["signal"] for s in sigs)
        + f"\n\nÄhnliche Paare (Hinweis — nur bei GLEICHEM Anliegen zusammenführen):\n{cand_txt}\n\n"
        'JSON: {"cases":[{"label":"konkretes Thema","members":["<Anfragenummer>"],"confidence":0.0-1.0,"reason":"<=12 Wörter"}]}'
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

    # coverage: each number in exactly one case; uncovered → own case
    seen: set[str] = set()
    raw: list[dict] = []
    for c in cases:
        members = [m for m in (c.get("members") or []) if m in numbers and m not in seen]
        if not members:
            continue
        seen.update(members)
        raw.append({
            "label": c.get("label") or "Vorgang", "members": members,
            "confidence": max(0.0, min(1.0, float(c.get("confidence") or 0.0))),
            "reason": _truncate(c.get("reason"), 90),
        })
    for s in sigs:
        if s["number"] not in seen:
            raw.append({"label": s["topic"], "members": [s["number"]], "confidence": 1.0, "reason": "nicht gruppiert"})

    # guardrails: outlier ejection + size-capped confidence
    clean: list[dict] = []
    for c in raw:
        kept, ejected = _eject_outliers(c["members"], num_to_vec, num_to_action)
        for e in ejected:
            esig = next((s for s in sigs if s["number"] == e), None)
            clean.append({"label": esig["topic"] if esig else "Vorgang", "members": [e], "confidence": 1.0,
                          "reason": "ausgegliedert: anderes Anliegen (Ähnlichkeit zu gering)", "tier": "single"})
        if not kept:
            continue
        size = len(kept)
        conf = c["confidence"]
        if size == 1:
            tier = "single"
        elif size > _SIZE_REVIEW:
            tier, conf = "review", min(conf, 0.79)
        elif conf >= AUTO:
            tier = "auto"
        elif conf >= REVIEW:
            tier = "review"
        else:
            tier = "low"
        clean.append({"label": c["label"], "members": kept, "confidence": round(conf, 2), "reason": c["reason"], "tier": tier})

    result["cases"] = clean
    result["cost"] = round(
        ai_usage.estimate_cost(model, result["tokens"]["prompt"], result["tokens"]["completion"])
        + result["tokens"]["embed"] / 1000 * 0.00002, 6
    )
    return result


def propose_cases_for_org(org_id: str) -> dict:
    client = get_service_client()
    rows = client.table("inquiries").select("customer_id").eq("org_id", org_id).neq("status", "deleted").execute().data or []
    counts = Counter(r["customer_id"] for r in rows if r.get("customer_id"))
    cids = list(counts.keys())
    names: dict[str, str | None] = {}
    if cids:
        for r in (client.table("customers").select("id, full_name").eq("org_id", org_id).in_("id", cids).execute().data or []):
            names[r["id"]] = r.get("full_name")
    per = [propose_cases_for_customer(client, org_id, cid, names.get(cid)) for cid, _ in counts.most_common()]
    return {"org_id": org_id, "customers": per}
