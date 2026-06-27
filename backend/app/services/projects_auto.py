"""Auto-file every NEW inquiry into a Fall (Case).

After the Case↔Project split (migration 0073) the grouping ticket is the **case**
(``cases`` table, ``FL-`` number, the renamed former ``projects`` table — so it
carries ``title``/``description``/status planning|active|completed|archived).
A top-layer **Project** sits above cases and is joined manually ("Add to project"),
never auto-created here.

Behaviour on inquiry creation (inbound call, agent tool, post-call ingest):
  * the customer has an OPEN case whose content matches (embedding cosine ≥
    _ATTACH_SIM, the grouper's own strong-similarity bar) → ATTACH to it;
  * otherwise → CREATE a fresh case from the inquiry (one inquiry = its own
    matter until evidence says otherwise).

Deliberately conservative: attaching to the WRONG case is worse than one case too
many (staff can always re-run the AI grouping / move manually), so any doubt — no
embeddings available, AI cap reached, no clear winner — falls back to CREATE.
Best-effort everywhere: a failure here must never break call ingest; the inquiry
simply stays unfiled (the grouping page picks it up later).

Audit trail reuses the grouping columns on inquiries (case_source/confidence/
reason) — same vocabulary the matchmaker and manual moves use.
"""
from __future__ import annotations

import json
import logging

from app.core.config import settings
from app.services.ai import client as ai_client
from app.services.ai import usage as ai_usage
from app.services.cases.summarize import safe_retitle
from app.services.cases.titles import existing_case_titles, make_unique_case_title
from app.services.common import gen_case_number

log = logging.getLogger(__name__)

_EMB_MODEL = "text-embedding-3-small"
_MAX_OPEN_CASES = 8       # newest open cases considered for a match
_MEMBER_SAMPLE = 6        # member inquiries sampled per case for its signal
# Grouping is LLM-judged, not a bare cosine: embeddings only SHORTLIST the caller's
# plausibly-related open tickets, then an LLM decides belongs-vs-new with a confidence.
# High confidence → auto-attach; plausible-but-unsure → create + suggest a merge for a
# human to confirm (never a silent wrong merge — the trust-building rule).
_SHORTLIST_FLOOR = 0.45   # embedding cosine to even show a ticket to the judge
_SHORTLIST_K = 5          # max tickets shown to the judge
_ATTACH_CONF = 0.80       # judge confidence to AUTO-attach
_SUGGEST_CONF = 0.50      # plausible but not confident → create + suggest a merge

_JUDGE_SYS = (
    "Du entscheidest, ob ein NEUER Anruf zu einem bereits OFFENEN Vorgang (Ticket) "
    "DESSELBEN Kunden gehört. Ein Vorgang = EIN konkretes Anliegen. Verschiedene "
    "Probleme (Heizung, Dach, Elektrik, Sanitär) gehören NIE zusammen — nur derselbe "
    "Anliegen-/Termin-Lebenszyklus (Anfrage→Termin→Bestätigung/Storno/Rückfrage zum "
    "SELBEN Anliegen). Sei streng: im Zweifel NEU. Antworte NUR mit JSON."
)


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _call_content(client, org_id: str, inquiry_ids: list[str], with_transcript: bool) -> dict[str, str]:
    """The ACTUAL call content per inquiry — summary (+ the customer's transcript
    turns) — so grouping reads what the call was really about, not the vague (often
    empty) subject. A subject says "Heizung"; the content says which room, which
    error code, which appointment — that's what decides the right case."""
    if not inquiry_ids:
        return {}
    cols = "inquiry_id, summary_title, summary" + (", transcript" if with_transcript else "")
    rows = (
        client.table("calls").select(cols)
        .eq("org_id", org_id).in_("inquiry_id", inquiry_ids).is_("deleted_at", "null")
        .execute().data or []
    )
    by: dict[str, list[str]] = {}
    for c in rows:
        parts = [c.get("summary_title") or "", c.get("summary") or ""]
        if with_transcript and isinstance(c.get("transcript"), list):
            parts.append(" ".join(
                str(t.get("message") or "") for t in c["transcript"]
                if isinstance(t, dict) and (t.get("role") or "") != "agent" and t.get("message")
            ))
        blob = " ".join(p for p in parts if p)
        if blob:
            by.setdefault(c["inquiry_id"], []).append(blob)
    return {k: " ".join(v).replace("\n", " ") for k, v in by.items()}


def _inquiry_signal(inquiry: dict, content: str = "") -> str:
    # The subject is just a headline (often vague/empty); the call content is what
    # actually disambiguates (bedroom vs kitchen heating, F28 vs leak, …).
    parts = [inquiry.get("subject") or inquiry.get("title") or "Anfrage", content, inquiry.get("notes") or ""]
    return " | ".join(p.strip() for p in parts if p).replace("\n", " ")[:700]


def _case_signal(client, org_id: str, case: dict) -> str:
    members = (
        client.table("inquiries")
        .select("id, subject, title")
        .eq("org_id", org_id).eq("case_id", case["id"])
        .neq("status", "deleted").order("created_at", desc=True)
        .limit(_MEMBER_SAMPLE).execute().data or []
    )
    content = _call_content(client, org_id, [m["id"] for m in members], with_transcript=False)
    member_txt = "; ".join(
        f"{m.get('subject') or m.get('title') or ''} {content.get(m['id'], '')}".strip()[:140]
        for m in members if (m.get("subject") or m.get("title") or content.get(m["id"]))
    )
    head = f"{case.get('title') or ''} {case.get('description') or ''}".strip()
    return f"{head} | {member_txt}".replace("\n", " ")[:700]


def _create_case_for_inquiry(client, org_id: str, inquiry: dict) -> dict:
    # Keep Vorgang titles unique per customer so two matters never share a header
    # (the inquiry title — now the German issue_summary — is the base).
    customer_id = inquiry.get("customer_id")
    base = inquiry.get("subject") or inquiry.get("title") or "Neue Anfrage"
    title = make_unique_case_title(
        base, existing_case_titles(client, org_id, customer_id), inquiry.get("created_at")
    )
    case = client.table("cases").insert({
        "org_id": org_id,
        "customer_id": customer_id,
        "number": gen_case_number(client, org_id),
        "title": title,
        "description": "Automatisch aus neuer Anfrage erstellt.",
        "status": "active",
    }).execute().data[0]
    client.table("inquiries").update({
        "case_id": case["id"],
        "case_source": "ai",
        "case_confidence": 1.0,
        "case_reason": "automatisch: neuer Vorgang",
    }).eq("org_id", org_id).eq("id", inquiry["id"]).execute()
    return case


def _attach(client, org_id: str, inquiry: dict, case: dict, sim: float) -> dict:
    client.table("inquiries").update({
        "case_id": case["id"],
        "case_source": "ai",
        "case_confidence": round(sim, 2),
        "case_reason": f"automatisch zugeordnet (Ähnlichkeit {sim:.2f})",
    }).eq("org_id", org_id).eq("id", inquiry["id"]).execute()
    return case


def _judge_attach(org_id: str, inquiry: dict, inq_content: str, shortlist: list[tuple]):
    """LLM: does this new call belong to one of the customer's shortlisted open tickets?
    Returns (matched_case | None, confidence float, reason str)."""
    new_sig = _inquiry_signal(inquiry, inq_content)[:500]
    lines = [f"[{idx}] {sig[:400]}" for idx, (_c, sig) in enumerate(shortlist)]
    user = (
        "NEUER ANRUF:\n" + new_sig + "\n\n"
        "OFFENE VORGÄNGE desselben Kunden:\n" + "\n".join(lines) + "\n\n"
        "Gehört der neue Anruf zu GENAU EINEM dieser Vorgänge (dasselbe konkrete "
        "Anliegen / derselbe Termin) oder ist es ein NEUES Anliegen? "
        'JSON: {"match": <Index oder null>, "confidence": 0.0-1.0, "reason": "<=10 Wörter"}'
    )
    resp = ai_client.chat(
        [{"role": "system", "content": _JUDGE_SYS}, {"role": "user", "content": user}],
        model=settings.openai_classifier_model,
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    u = getattr(resp, "usage", None)
    ai_usage.log_usage(
        org_id=org_id, user_id=None, feature="case_attach_judge",
        model=settings.openai_classifier_model,
        prompt_tokens=getattr(u, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(u, "completion_tokens", 0) or 0,
    )
    raw = json.loads(resp.choices[0].message.content or "{}")
    midx = raw.get("match")
    conf = float(raw.get("confidence") or 0.0)
    reason = str(raw.get("reason") or "")[:200]
    if not isinstance(midx, int) or not (0 <= midx < len(shortlist)):
        return None, conf, reason
    return shortlist[midx][0], conf, reason


def _insert_merge_suggestion(client, org_id, customer_id, source_case_id, target_case_id, confidence, reason):
    """Persist a pending 'this new Vorgang probably belongs to that one' suggestion for
    the Open Actions worklist. Best-effort; the unique index drops a same-source dup."""
    try:
        client.table("case_merge_suggestions").insert({
            "org_id": org_id, "customer_id": customer_id,
            "source_case_id": source_case_id, "target_case_id": target_case_id,
            "confidence": round(float(confidence), 2),
            "reason": (reason or "").strip()[:200] or None,
            "status": "pending",
        }).execute()
    except Exception as exc:  # noqa: BLE001 — best-effort
        log.warning("projects_auto: merge suggestion insert failed: %s", str(exc)[:120])


def auto_assign_inquiry_to_case(client, org_id: str, inquiry: dict) -> dict | None:
    """Attach-or-create (see module docstring). Returns the case, or None when
    the inquiry is already filed. Raises nothing — call sites stay safe anyway."""
    if inquiry.get("case_id"):
        return None

    customer_id = inquiry.get("customer_id")
    open_cases: list[dict] = []
    if customer_id:
        # Candidates are scoped to the CALLER (same customer = same number) and to
        # OPEN tickets only (planning/active) — completed/archived are never offered.
        open_cases = (
            client.table("cases")
            .select("id, title, description, status, customer_id, number")
            .eq("org_id", org_id).eq("customer_id", customer_id)
            .in_("status", ["planning", "active"])
            .order("created_at", desc=True).limit(_MAX_OPEN_CASES)
            .execute().data or []
        )

    if open_cases and ai_usage.within_cap(org_id):
        try:
            # The new call's own content (summary + transcript) decides where it belongs.
            inq_content = _call_content(client, org_id, [inquiry["id"]], with_transcript=True).get(inquiry["id"], "")
            texts = [_inquiry_signal(inquiry, inq_content)] + [
                _case_signal(client, org_id, c) for c in open_cases
            ]
            vecs, _tok = ai_client.embed(texts, model=_EMB_MODEL)
            scored = sorted(
                ((_cosine(vecs[0], vecs[i + 1]), open_cases[i], texts[i + 1]) for i in range(len(open_cases))),
                key=lambda x: x[0], reverse=True,
            )
            shortlist = [(c, sig) for sim, c, sig in scored if sim >= _SHORTLIST_FLOOR][:_SHORTLIST_K]
            if shortlist:
                match, conf, reason = _judge_attach(org_id, inquiry, inq_content, shortlist)
                if match and conf >= _ATTACH_CONF:
                    # Confident → attach, then refresh the ticket's summary (title only
                    # moves if this call materially changes the matter).
                    case = _attach(client, org_id, inquiry, match, conf)
                    safe_retitle(client, org_id, case["id"])
                    return case
                # Plausible but not confident → keep this call as its own Vorgang and
                # surface a human-confirmable merge suggestion (never a silent merge).
                case = _create_case_for_inquiry(client, org_id, inquiry)
                if match and conf >= _SUGGEST_CONF:
                    _insert_merge_suggestion(client, org_id, customer_id, case["id"], match["id"], conf, reason)
                return case
        except Exception as exc:  # noqa: BLE001 — doubt → create, never block
            log.warning("projects_auto: matching failed (org=%s): %s", org_id, exc)

    return _create_case_for_inquiry(client, org_id, inquiry)


def safe_auto_assign(client, org_id: str, inquiry: dict) -> dict | None:
    """The call-site wrapper: NOTHING here may break inquiry creation/ingest."""
    try:
        return auto_assign_inquiry_to_case(client, org_id, inquiry)
    except Exception as exc:  # noqa: BLE001
        log.warning("projects_auto: auto-assign failed (org=%s inquiry=%s): %s",
                    org_id, inquiry.get("id"), exc)
        return None
