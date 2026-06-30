"""Two-stage scheduling (employee↔technician split) — Track A, Phase 2.

The whole module is INERT unless an org has flipped
``agent_configs.scheduling_two_stage_enabled`` (default OFF). When OFF, the
caller's legacy single-stage path runs unchanged.

Model (see EMPLOYEE_TECHNICIAN_REDESIGN.md):
  * Ticket  → an OFFICE employee (coordinator), routed by DEPARTMENT/vertical.
              Their calendar gates nothing. Lives on appointments.coordinator_employee_id.
  * Job     → the visiting TECHNICIAN, on a first-class ``appointment_jobs`` row.
              The technician's availability gates the slot. The technician is a
              SUGGESTION (status='suggested') until the appointment is confirmed;
              on confirm the job → 'dispatched' and the technician is notified.

Technician selection ladder (product rule):
    HARD FILTER: competent for the department  AND  free at the slot
    RANK:        continuity → fewest open jobs → customer preference → name

Everything here is best-effort and defensive — a routing hiccup must never block
a booking. Department/competence falls back to the existing free-text
``activity_area`` match so an org with no departments configured still works.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.db.supabase_client import get_service_client
from app.services.appointment_classifier import _tokens

logger = logging.getLogger(__name__)

# appointment_jobs statuses that still occupy a technician (an "open job").
OPEN_JOB_STATUSES = ("suggested", "confirmed", "dispatched", "en_route")


def two_stage_enabled(client, org_id: str) -> bool:
    """Per-org kill-switch (agent_configs.scheduling_two_stage_enabled). Default
    OFF; a missing column (pre-migration) reads as OFF so this never breaks
    booking on a backend that predates 0090."""
    try:
        rows = (
            client.table("agent_configs")
            .select("scheduling_two_stage_enabled")
            .eq("org_id", org_id)
            .limit(1)
            .execute()
            .data
        )
    except Exception:  # noqa: BLE001 — column not migrated yet → OFF
        return False
    return bool(rows[0].get("scheduling_two_stage_enabled")) if rows else False


# ── department / vertical resolution ────────────────────────────────────────

def resolve_department(client, org_id: str, *, category_name: str | None, summary: str | None) -> dict | None:
    """Best-effort match of the call signal to a department by name-token overlap.
    Returns the department row (id, name, kind) or None. Never raises."""
    try:
        signal = _tokens(f"{category_name or ''} {summary or ''}")
        if not signal:
            return None
        rows = (
            client.table("departments")
            .select("id, name, kind, is_active")
            .eq("org_id", org_id)
            .eq("is_active", True)
            .execute()
            .data
            or []
        )
        best, best_score = None, 0
        for d in rows:
            score = len(signal & _tokens(d.get("name") or ""))
            if score > best_score:
                best, best_score = d, score
        return best if best_score > 0 else None
    except Exception as exc:  # noqa: BLE001 — routing is best-effort
        logger.warning("resolve_department failed (org %s): %s", org_id, str(exc)[:200])
        return None


def department_owner(client, org_id: str, department_id: str | None) -> dict | None:
    """The OFFICE employee who owns/manages a vertical (employee_departments.is_owner).
    This is the ticket coordinator. Returns the employee dict or None."""
    if not department_id:
        return None
    try:
        links = (
            client.table("employee_departments")
            .select("employee_id, is_owner")
            .eq("org_id", org_id)
            .eq("department_id", department_id)
            .eq("is_owner", True)
            .execute()
            .data
            or []
        )
        for link in links:
            emp = (
                client.table("employees")
                .select("id, display_name, is_active, worker_kind")
                .eq("org_id", org_id)
                .eq("id", link["employee_id"])
                .limit(1)
                .execute()
                .data
            )
            if emp and emp[0].get("is_active"):
                return emp[0]
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("department_owner failed (org %s): %s", org_id, str(exc)[:200])
        return None


def technician_pool(
    client,
    org_id: str,
    *,
    department_id: str | None,
    category_name: str | None,
    summary: str | None,
) -> list[dict]:
    """Candidate technicians for a job, with fallback so a slot is always offerable.

    1. Technicians (worker_kind in technician/both) linked to the matched
       department via ``employee_departments``.
    2. If no department match / no members: technicians whose free-text
       ``activity_area`` overlaps the signal.
    3. If still empty: any active technician.

    Each entry carries ``skill_score`` (department member = 2, activity_area
    overlap = token count, plain fallback = 0) so ranking can prefer a real match.
    """
    try:
        techs = (
            client.table("employees")
            .select("id, display_name, activity_area, worker_kind, is_technician, is_active, auto_assign")
            .eq("org_id", org_id)
            .eq("is_active", True)
            .eq("deleted", False)
            .execute()
            .data
            or []
        )
        techs = [t for t in techs if _is_technician(t)]
        if not techs:
            return []
        by_id = {t["id"]: t for t in techs}

        # 1 — department members.
        if department_id:
            member_ids = {
                link["employee_id"]
                for link in (
                    client.table("employee_departments")
                    .select("employee_id")
                    .eq("org_id", org_id)
                    .eq("department_id", department_id)
                    .execute()
                    .data
                    or []
                )
            }
            members = [{**by_id[i], "skill_score": 2} for i in member_ids if i in by_id]
            if members:
                return members

        # 2 — activity_area token overlap.
        signal = _tokens(f"{category_name or ''} {summary or ''}")
        if signal:
            scored = []
            for t in techs:
                area = t.get("activity_area")
                if area and str(area).strip():
                    score = len(signal & _tokens(area))
                    if score > 0:
                        scored.append({**t, "skill_score": score})
            if scored:
                return scored

        # 3 — any active technician.
        return [{**t, "skill_score": 0} for t in techs]
    except Exception as exc:  # noqa: BLE001
        logger.warning("technician_pool failed (org %s): %s", org_id, str(exc)[:200])
        return []


def _is_technician(emp: dict) -> bool:
    """worker_kind in (technician, both) OR the legacy is_technician flag."""
    wk = (emp.get("worker_kind") or "").lower()
    return wk in ("technician", "both") or bool(emp.get("is_technician"))


# ── continuity + workload signals ───────────────────────────────────────────

def last_technician_for(client, org_id: str, customer_id: str | None, department_id: str | None) -> str | None:
    """Continuity: the technician who most recently handled this customer (same
    department when known). Reads finished/dispatched ``appointment_jobs`` for the
    customer's appointments, newest first. Returns a technician_employee_id or None."""
    if not customer_id:
        return None
    try:
        appt_ids = [
            a["id"]
            for a in (
                client.table("appointments")
                .select("id")
                .eq("org_id", org_id)
                .eq("customer_id", customer_id)
                .execute()
                .data
                or []
            )
        ]
        if not appt_ids:
            return None
        q = (
            client.table("appointment_jobs")
            .select("technician_employee_id, department_id, status, created_at")
            .eq("org_id", org_id)
            .in_("appointment_id", appt_ids)
            .in_("status", ["confirmed", "dispatched", "en_route", "done"])
            .order("created_at", desc=True)
        )
        rows = q.execute().data or []
        for r in rows:
            if department_id and r.get("department_id") and r["department_id"] != department_id:
                continue
            if r.get("technician_employee_id"):
                return r["technician_employee_id"]
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("last_technician_for failed (org %s): %s", org_id, str(exc)[:200])
        return None


def open_job_counts(client, org_id: str, technician_ids: list[str]) -> dict[str, int]:
    """Per-technician count of OPEN appointment_jobs (the workload signal). Returns
    {} on any error so a workload hiccup never blocks assignment."""
    ids = [i for i in dict.fromkeys(technician_ids) if i]
    if not ids:
        return {}
    try:
        rows = (
            client.table("appointment_jobs")
            .select("technician_employee_id, status")
            .eq("org_id", org_id)
            .in_("technician_employee_id", ids)
            .in_("status", list(OPEN_JOB_STATUSES))
            .execute()
            .data
            or []
        )
        counts: dict[str, int] = {}
        for r in rows:
            tid = r.get("technician_employee_id")
            if tid:
                counts[tid] = counts.get(tid, 0) + 1
        return counts
    except Exception as exc:  # noqa: BLE001
        logger.warning("open_job_counts failed (org %s): %s", org_id, str(exc)[:200])
        return {}


def customer_preferred_technician(client, org_id: str, customer_id: str | None) -> str | None:
    """Explicit per-customer preferred technician, when the column exists. Guarded
    so a pre-migration backend (no preferred_technician_id) simply returns None."""
    if not customer_id:
        return None
    try:
        rows = (
            client.table("customers")
            .select("preferred_technician_id")
            .eq("org_id", org_id)
            .eq("id", customer_id)
            .limit(1)
            .execute()
            .data
        )
    except Exception:  # noqa: BLE001 — column not present yet
        return None
    return (rows[0].get("preferred_technician_id") if rows else None) or None


# ── the ladder (pure) ───────────────────────────────────────────────────────

def pick_technician_ladder(
    pool: list[dict],
    busy_map: dict[str, list],
    job_counts: dict[str, int],
    *,
    start,
    end,
    continuity_id: str | None = None,
    preferred_id: str | None = None,
    buffer_minutes: int = 0,
) -> dict | None:
    """Pure: the best technician for ONE slot per the product ladder.

    HARD FILTER: free at [start, end). Then rank, first non-tie wins:
        1. continuity  — the technician who last served this customer/issue
        2. workload    — fewest open jobs
        3. preference  — customer's preferred technician
        4. name        — deterministic final tie-break
    Returns the chosen technician dict, or None when nobody in the pool is free.
    """
    from app.services.availability import slot_free

    free = [
        t
        for t in pool
        if t.get("id")
        and slot_free(busy_map.get(t["id"], []), start, end, buffer_minutes=buffer_minutes)
    ]
    if not free:
        return None
    free.sort(
        key=lambda t: (
            0 if t.get("id") == continuity_id else 1,        # continuity first
            int(job_counts.get(t.get("id"), 0)),             # fewest open jobs
            0 if t.get("id") == preferred_id else 1,         # customer preference
            (t.get("display_name") or "").lower(),           # deterministic tie-break
        )
    )
    return free[0]


def suggest_technician(
    client,
    org_id: str,
    *,
    customer_id: str | None,
    department_id: str | None,
    category_name: str | None,
    summary: str | None,
    start: datetime,
    duration_minutes: int,
    buffer_minutes: int = 0,
) -> dict | None:
    """End-to-end suggestion for a concrete slot: build the technician pool, apply
    the ladder, return the chosen technician (or None when none is free). Pure
    reads — never writes, never raises (returns None on error)."""
    from app.services import availability

    try:
        pool = technician_pool(
            client, org_id, department_id=department_id, category_name=category_name, summary=summary
        )
        if not pool:
            return None
        end = start + timedelta(minutes=duration_minutes)
        ids = [t["id"] for t in pool if t.get("id")]
        busy = availability.load_busy_map(client, org_id, ids, start, end)
        counts = open_job_counts(client, org_id, ids)
        continuity = last_technician_for(client, org_id, customer_id, department_id)
        preferred = customer_preferred_technician(client, org_id, customer_id)
        return pick_technician_ladder(
            pool, busy, counts, start=start, end=end,
            continuity_id=continuity, preferred_id=preferred, buffer_minutes=buffer_minutes,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("suggest_technician failed (org %s): %s", org_id, str(exc)[:200])
        return None


# ── writes: suggested job + dispatch-on-confirm ─────────────────────────────

def create_suggested_job(
    client,
    org_id: str,
    appointment_id: str,
    *,
    technician_id: str | None,
    department_id: str | None,
    work_type: str | None,
    scheduled_at: str | None,
    duration_minutes: int | None,
) -> dict | None:
    """Insert an appointment_jobs row in status 'suggested' (no notification yet).
    Best-effort — a job-row failure must not fail the booking."""
    try:
        row = (
            client.table("appointment_jobs")
            .insert(
                {
                    "org_id": org_id,
                    "appointment_id": appointment_id,
                    "technician_employee_id": technician_id,
                    "department_id": department_id,
                    "work_type": work_type,
                    "status": "suggested",
                    "scheduled_at": scheduled_at,
                    "duration_minutes": duration_minutes,
                }
            )
            .execute()
            .data
        )
        return row[0] if row else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("create_suggested_job failed (org %s, appt %s): %s", org_id, appointment_id, str(exc)[:200])
        return None


def suggested_job_for_appointment(client, org_id: str, appointment_id: str) -> dict | None:
    """The current suggested/confirmed job carrying a technician for this
    appointment (newest first), or None."""
    try:
        rows = (
            client.table("appointment_jobs")
            .select("id, technician_employee_id, department_id, work_type, status, scheduled_at, duration_minutes")
            .eq("org_id", org_id)
            .eq("appointment_id", appointment_id)
            .in_("status", ["suggested", "confirmed"])
            .order("created_at", desc=True)
            .execute()
            .data
            or []
        )
        for r in rows:
            if r.get("technician_employee_id"):
                return r
        return rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("suggested_job_for_appointment failed (org %s): %s", org_id, str(exc)[:200])
        return None


def dispatch_job_on_confirm(org_id: str, appointment_id: str) -> dict | None:
    """Called when a two-stage appointment is confirmed: lock the suggested
    technician in. DB-only (the route handles the email notification):
      * mirror the technician onto appointments.assigned_employee_id (read-compat
        so the calendar/dispatch picker shows them) — only if not already set,
      * flip the suggested job → 'dispatched'.
    Returns {job_id, technician_id} or None when there is no suggested technician.
    Best-effort — never raises."""
    try:
        client = get_service_client()
        job = suggested_job_for_appointment(client, org_id, appointment_id)
        if not job or not job.get("technician_employee_id"):
            return None
        tech_id = job["technician_employee_id"]
        appt = (
            client.table("appointments")
            .select("assigned_employee_id")
            .eq("org_id", org_id)
            .eq("id", appointment_id)
            .limit(1)
            .execute()
            .data
        )
        if appt and not appt[0].get("assigned_employee_id"):
            client.table("appointments").update({"assigned_employee_id": tech_id}).eq(
                "org_id", org_id
            ).eq("id", appointment_id).execute()
        client.table("appointment_jobs").update({"status": "dispatched", "updated_at": datetime.now().isoformat()}).eq(
            "org_id", org_id
        ).eq("id", job["id"]).execute()
        return {"job_id": job["id"], "technician_id": tech_id}
    except Exception as exc:  # noqa: BLE001 — confirm must never fail on dispatch bookkeeping
        logger.warning("dispatch_job_on_confirm failed (org %s, appt %s): %s", org_id, appointment_id, str(exc)[:200])
        return None
