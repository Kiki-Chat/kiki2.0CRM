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

import logging

from app.services.ai import client as ai_client
from app.services.ai import usage as ai_usage
from app.services.cases.titles import existing_case_titles, make_unique_case_title
from app.services.common import gen_case_number

log = logging.getLogger(__name__)

_EMB_MODEL = "text-embedding-3-small"
_ATTACH_SIM = 0.70   # == grouper._STRONG_SIM: only a clearly-same matter attaches
_MAX_OPEN_CASES = 8   # newest open cases considered for a match
_MEMBER_SAMPLE = 6       # member inquiries sampled per case for its signal


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


def auto_assign_inquiry_to_case(client, org_id: str, inquiry: dict) -> dict | None:
    """Attach-or-create (see module docstring). Returns the case, or None when
    the inquiry is already filed. Raises nothing — call sites stay safe anyway."""
    if inquiry.get("case_id"):
        return None

    customer_id = inquiry.get("customer_id")
    open_cases: list[dict] = []
    if customer_id:
        open_cases = (
            client.table("cases")
            .select("id, title, description, status")
            .eq("org_id", org_id).eq("customer_id", customer_id)
            .in_("status", ["planning", "active"])
            .order("created_at", desc=True).limit(_MAX_OPEN_CASES)
            .execute().data or []
        )

    if open_cases:
        try:
            if ai_usage.within_cap(org_id):
                # The new call's own content (summary + transcript) is what decides
                # which case it belongs to — not its headline subject.
                inq_content = _call_content(client, org_id, [inquiry["id"]], with_transcript=True).get(inquiry["id"], "")
                texts = [_inquiry_signal(inquiry, inq_content)] + [
                    _case_signal(client, org_id, c) for c in open_cases
                ]
                vecs, _tok = ai_client.embed(texts, model=_EMB_MODEL)
                sims = [(_cosine(vecs[0], vecs[i + 1]), c) for i, c in enumerate(open_cases)]
                sims.sort(key=lambda x: x[0], reverse=True)
                best_sim, best_case = sims[0]
                if best_sim >= _ATTACH_SIM:
                    return _attach(client, org_id, inquiry, best_case, best_sim)
        except Exception as exc:  # noqa: BLE001 — doubt → create, never block
            log.warning("projects_auto: similarity match failed (org=%s): %s", org_id, exc)

    return _create_case_for_inquiry(client, org_id, inquiry)


def safe_auto_assign(client, org_id: str, inquiry: dict) -> dict | None:
    """The call-site wrapper: NOTHING here may break inquiry creation/ingest."""
    try:
        return auto_assign_inquiry_to_case(client, org_id, inquiry)
    except Exception as exc:  # noqa: BLE001
        log.warning("projects_auto: auto-assign failed (org=%s inquiry=%s): %s",
                    org_id, inquiry.get("id"), exc)
        return None
