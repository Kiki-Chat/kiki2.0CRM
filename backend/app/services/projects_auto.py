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


def _inquiry_signal(inquiry: dict) -> str:
    parts = [inquiry.get("subject") or inquiry.get("title") or "Anfrage", inquiry.get("notes") or ""]
    return " | ".join(p.strip().replace("\n", " ") for p in parts if p)[:360]


def _project_signal(client, org_id: str, project: dict) -> str:
    members = (
        client.table("inquiries")
        .select("subject, title, notes")
        .eq("org_id", org_id).eq("project_id", project["id"])
        .neq("status", "deleted").order("created_at", desc=True)
        .limit(_MEMBER_SAMPLE).execute().data or []
    )
    member_txt = "; ".join(
        (m.get("subject") or m.get("title") or "")[:60] for m in members if (m.get("subject") or m.get("title"))
    )
    head = f"{project.get('title') or ''} {project.get('description') or ''}".strip()
    return f"{head} | {member_txt}".replace("\n", " ")[:360]


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
                texts = [_inquiry_signal(inquiry)] + [
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
