"""Availability- + workload-aware assignment suggestions.

Fuses three signals into one ranked answer to "who should take this, and when?":

  • COMPETENCE — the skill pool from ``services.dispatch.rank_candidates``
    (employees whose Tätigkeitsbereich matches the call). When the work is
    domain-agnostic (Finanzierung, Online-Termin — no trade skill), it falls
    back to the appointment category's default employee, then any active
    employee, so a slot is always offerable.
  • AVAILABILITY — ``services.availability`` (assigned appointments + approved
    absences + manual blocks + mirrored personal Google busy).
  • WORKLOAD — count of OPEN Fälle each candidate already carries
    (``case_employees`` ⨝ ``cases``), so the least-loaded competent person wins.

The voice slot tool and the CRM assignment picker both build on this, so a phone
booking and an admin's manual pick rank people identically. Category supplies the
DURATION; this module never lets the category dictate WHO (skill does) — only the
fallback when no skill matches.
"""

import logging

from app.services.availability import load_busy_map, slot_free
from app.services.dispatch import rank_candidates

logger = logging.getLogger(__name__)

# Case statuses that count as CLOSED — everything else is an "open ticket" for
# the workload signal. Single source of truth (the employees roster imports it).
CLOSED_CASE_STATUSES = {"completed", "done", "closed", "archived", "cancelled"}


def open_ticket_counts(client, org_id: str, employee_ids: list[str]) -> dict[str, int]:
    """Per-employee count of OPEN Fälle they're assigned to (``case_employees`` ⨝
    ``cases``). "Open" = case status NOT in :data:`CLOSED_CASE_STATUSES`. One
    membership read + one status read, counted in Python. Best-effort — returns
    ``{}`` on any error so a workload hiccup never blocks an assignment."""
    ids = [e for e in dict.fromkeys(employee_ids) if e]
    if not ids:
        return {}
    try:
        ce = (
            client.table("case_employees")
            .select("case_id, employee_id")
            .in_("employee_id", ids)
            .execute()
            .data
            or []
        )
        case_ids = list({r["case_id"] for r in ce if r.get("case_id")})
        open_ids: set[str] = set()
        if case_ids:
            for c in (
                client.table("cases")
                .select("id, status")
                .eq("org_id", org_id)
                .in_("id", case_ids)
                .execute()
                .data
                or []
            ):
                if (c.get("status") or "") not in CLOSED_CASE_STATUSES:
                    open_ids.add(c["id"])
        counts: dict[str, int] = {}
        for r in ce:
            if r.get("case_id") in open_ids:
                counts[r["employee_id"]] = counts.get(r["employee_id"], 0) + 1
        return counts
    except Exception as exc:  # noqa: BLE001 — workload is a soft signal
        logger.warning("open_ticket_counts failed (org %s): %s", org_id, str(exc)[:200])
        return {}


def _active_employee(client, org_id: str, employee_id: str | None) -> dict | None:
    if not employee_id:
        return None
    rows = (
        client.table("employees")
        .select("id, display_name, activity_area, is_active")
        .eq("org_id", org_id)
        .eq("id", employee_id)
        .eq("deleted", False)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows and rows[0].get("is_active") else None


def _active_employees(client, org_id: str) -> list[dict]:
    return (
        client.table("employees")
        .select("id, display_name, activity_area, is_active")
        .eq("org_id", org_id)
        .eq("deleted", False)
        .eq("is_active", True)
        .order("display_name")
        .execute()
        .data
        or []
    )


def build_pool(
    client,
    org_id: str,
    *,
    category_name: str | None,
    summary: str | None,
    category_default_employee_id: str | None = None,
    require_auto_assign: bool = True,
) -> list[dict]:
    """The candidate pool for a call's signal, WITH fallback.

    Skill pool first (``rank_candidates`` — competence drives WHO). If that is
    empty (no trade-skill match, e.g. a finance/online category), fall back to
    the category's configured default employee, then to any active employee.
    Every entry carries a ``skill_score`` (0 for fallback entries) so downstream
    ranking can still prefer a genuine skill match.
    """
    pool = rank_candidates(
        client,
        org_id,
        category_name=category_name,
        summary=summary,
        require_auto_assign=require_auto_assign,
    )
    if pool:
        return pool
    # Fallback 1 — the category's default employee (domain-agnostic work).
    emp = _active_employee(client, org_id, category_default_employee_id)
    if emp:
        return [{**emp, "skill_score": 0}]
    # Fallback 2 — any active employee, so a slot is still offerable.
    return [{**e, "skill_score": 0} for e in _active_employees(client, org_id)]


def pick_for_slot(
    pool: list[dict],
    busy_map: dict[str, list],
    workload: dict[str, int],
    start,
    end,
    *,
    buffer_minutes: int = 0,
) -> dict | None:
    """Pure: the best FREE candidate for ONE slot — highest skill, then fewest
    open tickets, then name. ``None`` when nobody in the pool is free.

    The hot path of the voice slot tool's per-slot loop: build ``busy_map`` once
    with :func:`availability.load_busy_map` and ``workload`` once with
    :func:`open_ticket_counts`, then call this for every candidate slot.
    """
    free = [
        e
        for e in pool
        if e.get("id")
        and slot_free(busy_map.get(e["id"], []), start, end, buffer_minutes=buffer_minutes)
    ]
    if not free:
        return None
    free.sort(
        key=lambda e: (
            -int(e.get("skill_score") or 0),
            int(workload.get(e["id"], 0)),
            (e.get("display_name") or "").lower(),
        )
    )
    return free[0]


def rank_for_slot(
    client,
    org_id: str,
    pool: list[dict],
    start,
    end,
    *,
    buffer_minutes: int = 0,
    workload: dict[str, int] | None = None,
) -> list[dict]:
    """Annotate + sort a pool for a concrete [start, end): AVAILABLE first, then
    highest skill, then fewest open tickets, then name. The head is the
    recommendation. Each entry gains ``available`` (bool) and ``open_tickets``."""
    ids = [e["id"] for e in pool if e.get("id")]
    busy = load_busy_map(client, org_id, ids, start, end)
    if workload is None:
        workload = open_ticket_counts(client, org_id, ids)
    annotated = [
        {
            **e,
            "available": bool(
                e.get("id")
                and slot_free(busy.get(e["id"], []), start, end, buffer_minutes=buffer_minutes)
            ),
            "open_tickets": int(workload.get(e.get("id"), 0)),
        }
        for e in pool
    ]
    annotated.sort(
        key=lambda e: (
            not e["available"],                 # available (True) before busy
            -int(e.get("skill_score") or 0),    # better skill first
            e["open_tickets"],                  # fewer tickets first
            (e.get("display_name") or "").lower(),
        )
    )
    return annotated


def recommend(
    client,
    org_id: str,
    *,
    category_name: str | None,
    summary: str | None,
    start,
    end,
    category_default_employee_id: str | None = None,
    buffer_minutes: int = 0,
    require_auto_assign: bool = True,
) -> dict:
    """One-call suggestion for a concrete time: build the pool, rank it for
    [start, end], and surface the recommended assignee (top candidate that is
    actually free). Used by the CRM assignment picker.

    Returns ``{recommended, candidates, any_available}`` where ``recommended`` is
    ``None`` when no competent person is free at that time (the caller then offers
    an alternative slot)."""
    pool = build_pool(
        client,
        org_id,
        category_name=category_name,
        summary=summary,
        category_default_employee_id=category_default_employee_id,
        require_auto_assign=require_auto_assign,
    )
    ranked = rank_for_slot(client, org_id, pool, start, end, buffer_minutes=buffer_minutes)
    top = ranked[0] if ranked else None
    return {
        "recommended": top if (top and top["available"]) else None,
        "candidates": ranked,
        "any_available": any(e["available"] for e in ranked),
    }
