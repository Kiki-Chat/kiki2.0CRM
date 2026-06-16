"""Top-layer Project (Projekt) helpers: numbering + back-office auto-creation.

After the Case↔Project split (migration 0073) a **Project** is the restored top
container that bundles cases (``PR-{TOKEN}-NNNN``). The **Case** (``FL-``) is the
grouping ticket below it — its number/creation lives with the case code
(``common.gen_case_number`` + ``projects_auto`` / ``cases`` routes)."""

import logging

from app.db.supabase_client import get_service_client
from app.services.common import _max_seq_for_token, gen_case_number, get_org_token

logger = logging.getLogger(__name__)


def gen_project_number(client, org_id: str) -> str:
    """Next top-layer Project number: ``PR-{TOKEN}-{NNNN}`` (e.g. PR-KC007-0001).
    Runs over the (restored) ``projects`` table on its OWN per-org sequence —
    deliberately a different prefix from the case ``FL-`` sequence so the two
    layers never collide even though they share the org token."""
    prefix = f"PR-{get_org_token(client, org_id)}-"
    seq = _max_seq_for_token(client, "projects", org_id, prefix) + 1
    return f"{prefix}{seq:04d}"


def maybe_create_case_for_appointment(
    org_id: str, appt: dict, user_id: str | None = None, client=None
) -> dict | None:
    """Back-office automation (topic 19): on appointment confirm, auto-create a
    **case** (the appointment's grouping ticket → planning presence), gated by
    agent_configs.projects_enabled + projects_level (legacy flag names kept to
    avoid a config migration; they now gate case auto-creation).

    off / level 1 → nothing. Level 2 → case as 'planning' (draft to review).
    Level 3 → 'active'. No-op if the appointment already has a case.
    Best-effort: never raises (a failure must not roll back the confirmation).

    NB: ``cases`` IS the renamed former ``projects`` table (migration 0073), so it
    carries the project schema — ``title`` (not ``label``) and status values
    planning/active/completed/archived."""
    try:
        if appt.get("case_id"):
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
        case = {
            "org_id": org_id,
            "customer_id": appt.get("customer_id"),
            "number": gen_case_number(client, org_id),
            "title": appt.get("title") or "Termin",
            "description": "Automatisch aus bestätigtem Termin erstellt.",
            "status": "active" if level >= 3 else "planning",
            "created_by": user_id,
        }
        created = client.table("cases").insert(case).execute().data
        case_row = created[0] if created else None
        if case_row:
            (
                client.table("appointments")
                .update({"case_id": case_row["id"]})
                .eq("org_id", org_id)
                .eq("id", appt["id"])
                .execute()
            )
        return case_row
    except Exception:  # noqa: BLE001 — never break appointment confirmation
        logger.exception("case auto-create failed for appointment %s", appt.get("id"))
        return None
