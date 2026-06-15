"""Auto-file every NEW inquiry into a Projekt (Luca-meeting item 6 — the cases
layer merges INTO projects; Amber's ruling 2026-06-12).

Behaviour on inquiry creation (inbound call, agent tool, post-call ingest):
  * the customer has an OPEN project whose content matches (embedding cosine ≥
    _ATTACH_SIM, the grouper's own strong-similarity bar) → ATTACH to it;
  * otherwise → CREATE a fresh project from the inquiry (one inquiry = its own
    matter until evidence says otherwise — exactly the old case semantics).

Deliberately conservative: attaching to the WRONG project is worse than one
project too many (staff can always re-run the AI grouping / move manually), so
any doubt — no embeddings available, AI cap reached, no clear winner — falls
back to CREATE. Best-effort everywhere: a failure here must never break call
ingest; the inquiry simply stays unfiled (the grouping page picks it up later).

Audit trail reuses the grouping columns on inquiries (case_source/confidence/
reason) — same vocabulary the matchmaker and manual moves use.
"""
from __future__ import annotations

import logging

from app.services.ai import client as ai_client
from app.services.ai import usage as ai_usage
from app.services.projects import gen_project_number

log = logging.getLogger(__name__)

_EMB_MODEL = "text-embedding-3-small"
_ATTACH_SIM = 0.70   # == grouper._STRONG_SIM: only a clearly-same matter attaches
_MAX_OPEN_PROJECTS = 8   # newest open projects considered for a match
_MEMBER_SAMPLE = 6       # member inquiries sampled per project for its signal


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


def _project_signal(client, org_id: str, project: dict) -> str:
    members = (
        client.table("inquiries")
        .select("id, subject, title")
        .eq("org_id", org_id).eq("project_id", project["id"])
        .neq("status", "deleted").order("created_at", desc=True)
        .limit(_MEMBER_SAMPLE).execute().data or []
    )
    content = _call_content(client, org_id, [m["id"] for m in members], with_transcript=False)
    member_txt = "; ".join(
        f"{m.get('subject') or m.get('title') or ''} {content.get(m['id'], '')}".strip()[:140]
        for m in members if (m.get("subject") or m.get("title") or content.get(m["id"]))
    )
    head = f"{project.get('title') or ''} {project.get('description') or ''}".strip()
    return f"{head} | {member_txt}".replace("\n", " ")[:700]


def _create_project_for_inquiry(client, org_id: str, inquiry: dict) -> dict:
    project = client.table("projects").insert({
        "org_id": org_id,
        "customer_id": inquiry.get("customer_id"),
        "number": gen_project_number(client, org_id),
        "title": (inquiry.get("subject") or inquiry.get("title") or "Neue Anfrage")[:120],
        "description": "Automatisch aus neuer Anfrage erstellt.",
        "status": "active",
    }).execute().data[0]
    client.table("inquiries").update({
        "project_id": project["id"],
        "case_source": "ai",
        "case_confidence": 1.0,
        "case_reason": "automatisch: neues Projekt",
    }).eq("org_id", org_id).eq("id", inquiry["id"]).execute()
    return project


def _attach(client, org_id: str, inquiry: dict, project: dict, sim: float) -> dict:
    client.table("inquiries").update({
        "project_id": project["id"],
        "case_source": "ai",
        "case_confidence": round(sim, 2),
        "case_reason": f"automatisch zugeordnet (Ähnlichkeit {sim:.2f})",
    }).eq("org_id", org_id).eq("id", inquiry["id"]).execute()
    return project


def auto_assign_inquiry_to_project(client, org_id: str, inquiry: dict) -> dict | None:
    """Attach-or-create (see module docstring). Returns the project, or None when
    the inquiry is already filed. Raises nothing — call sites stay safe anyway."""
    if inquiry.get("project_id"):
        return None

    customer_id = inquiry.get("customer_id")
    open_projects: list[dict] = []
    if customer_id:
        open_projects = (
            client.table("projects")
            .select("id, title, description, status")
            .eq("org_id", org_id).eq("customer_id", customer_id)
            .in_("status", ["planning", "active"])
            .order("created_at", desc=True).limit(_MAX_OPEN_PROJECTS)
            .execute().data or []
        )

    if open_projects:
        try:
            if ai_usage.within_cap(org_id):
                # The new call's own content (summary + transcript) is what decides
                # which case it belongs to — not its headline subject.
                inq_content = _call_content(client, org_id, [inquiry["id"]], with_transcript=True).get(inquiry["id"], "")
                texts = [_inquiry_signal(inquiry, inq_content)] + [
                    _project_signal(client, org_id, p) for p in open_projects
                ]
                vecs, _tok = ai_client.embed(texts, model=_EMB_MODEL)
                sims = [(_cosine(vecs[0], vecs[i + 1]), p) for i, p in enumerate(open_projects)]
                sims.sort(key=lambda x: x[0], reverse=True)
                best_sim, best_project = sims[0]
                if best_sim >= _ATTACH_SIM:
                    return _attach(client, org_id, inquiry, best_project, best_sim)
        except Exception as exc:  # noqa: BLE001 — doubt → create, never block
            log.warning("projects_auto: similarity match failed (org=%s): %s", org_id, exc)

    return _create_project_for_inquiry(client, org_id, inquiry)


def safe_auto_assign(client, org_id: str, inquiry: dict) -> dict | None:
    """The call-site wrapper: NOTHING here may break inquiry creation/ingest."""
    try:
        return auto_assign_inquiry_to_project(client, org_id, inquiry)
    except Exception as exc:  # noqa: BLE001
        log.warning("projects_auto: auto-assign failed (org=%s inquiry=%s): %s",
                    org_id, inquiry.get("id"), exc)
        return None
