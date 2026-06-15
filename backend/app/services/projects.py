"""Project (Projekt) helpers: numbering + back-office auto-creation."""

import logging

from app.db.supabase_client import get_service_client
from app.services.common import gen_case_number

logger = logging.getLogger(__name__)


def gen_project_number(client, org_id: str) -> str:
    # A project IS the case (the active grouping after the cases↔projects merge),
    # so it gets the same FL-{TOKEN}-{NNNN} number as any other case. Delegates to
    # the single case-number generator so both code paths share one sequence.
    return gen_case_number(client, org_id)


def maybe_create_project_for_appointment(
    org_id: str, appt: dict, user_id: str | None = None, client=None
) -> dict | None:
    """Back-office automation (topic 19): on appointment confirm, auto-create a
    project — which also gives the appointment a planning-board presence — gated by
    agent_configs.projects_enabled + projects_level.

    off / level 1 → nothing. Level 2 → project as 'planning' (draft to review).
    Level 3 → 'active'. No-op if the appointment already has a project. Best-effort:
    never raises (a failure must not roll back the confirmation)."""
    try:
        if appt.get("project_id"):
            return None
        client = client or get_service_client()
        cfg = (
            client.table("agent_configs")
            .select("projects_enabled, projects_level")
            .eq("org_id", org_id)
            .limit(1)
            .execute()
            .data
        )
        row = cfg[0] if cfg else {}
        if not row.get("projects_enabled"):
            return None
        try:
            level = int(row.get("projects_level") or 2)
        except (TypeError, ValueError):
            level = 2
        if level <= 1:
            return None
        proj = {
            "org_id": org_id,
            "customer_id": appt.get("customer_id"),
            "number": gen_project_number(client, org_id),
            "title": appt.get("title") or "Projekt",
            "description": "Automatisch aus bestätigtem Termin erstellt.",
            "status": "active" if level >= 3 else "planning",
            "created_by": user_id,
        }
        created = client.table("projects").insert(proj).execute().data
        project = created[0] if created else None
        if project:
            (
                client.table("appointments")
                .update({"project_id": project["id"]})
                .eq("org_id", org_id)
                .eq("id", appt["id"])
                .execute()
            )
        return project
    except Exception:  # noqa: BLE001 — never break appointment confirmation
        logger.exception("project auto-create failed for appointment %s", appt.get("id"))
        return None
