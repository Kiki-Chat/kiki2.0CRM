"""Unified employee availability — the single source of truth for "is this
employee free at a given time?".

Every "busy" signal for an employee is unioned here so the voice slot tool
(``services.appointments.get_available_slots``), the auto-suggest ranking
service, and the CRM assignment picker all agree on who is free:

  • CRM appointments assigned to them (status ``pending``/``confirmed``). This
    INCLUDES their mirrored personal Google-Calendar busy blocks, which land as
    appointments with ``source='google_import'`` stamped with the same
    ``assigned_employee_id`` (see ``services.calendar_sync``).
  • Approved absences — Urlaub / Krankheit / Schulung / … — AND manual
    time-blocks (``employee_absences.type='block'``), both gated on
    ``status='approved'`` so a pending request never blocks a slot.

All datetimes are Europe/Berlin aware. The loaders issue blocking Supabase
reads, so callers must run them inside ``run_in_threadpool`` (the tool routes and
admin routes already do). Ranking N candidates over a window costs TWO queries
total (one appointments read + one absences read), not 2·N — build the busy map
once with :func:`load_busy_map`, then check slots in-memory with :func:`slot_free`.
"""

import logging
from datetime import datetime, timedelta

from app.services.common import BERLIN, run_parallel

logger = logging.getLogger(__name__)

# (start, end) half-open interval in Berlin-aware datetimes.
Interval = tuple[datetime, datetime]

# Appointment statuses that occupy a calendar slot. Mirrors the slot finder in
# ``services.appointments`` — cancelled/completed never block a future slot.
_BUSY_APPT_STATUS = ("pending", "confirmed")

# Appointments store start + duration (no end column), so to catch a long job
# that STARTED before the window but still overlaps it, we widen the lower bound
# of the appointments read by this much and compute true overlap in Python. 24h
# comfortably covers any realistic appointment.
_APPT_BACKSCAN = timedelta(hours=24)


def _parse_iso(value: str | None) -> datetime | None:
    """Parse a DB timestamp to a tz-aware datetime; naive values are read as
    Berlin-local (the DB columns are tz-aware, but stay defensive)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=BERLIN)


def _appt_duration_minutes(row: dict) -> int:
    dur = row.get("duration_minutes") or 60
    try:
        return int(dur)
    except (TypeError, ValueError):
        return 60


def _intervals_conflict(
    busy: list[Interval], start: datetime, end: datetime, buffer_minutes: int = 0
) -> bool:
    """True when [start, end) overlaps any busy interval once each busy interval
    is padded by ``buffer_minutes`` on both sides (travel/prep time). Buffer 0 =
    plain overlap. Same overlap semantics as ``appointments._slot_conflicts``."""
    pad = timedelta(minutes=max(0, buffer_minutes))
    return any(start < b_end + pad and end > b_start - pad for (b_start, b_end) in busy)


def slot_free(
    busy: list[Interval], start: datetime, end: datetime, *, buffer_minutes: int = 0
) -> bool:
    """Pure check: is [start, end) free against a pre-loaded busy list? This is
    the per-candidate, per-slot hot path used by the slot tool and the ranking
    service after one :func:`load_busy_map` call."""
    return not _intervals_conflict(busy, start, end, buffer_minutes)


def load_busy_map(
    client,
    org_id: str,
    employee_ids: list[str],
    window_start: datetime,
    window_end: datetime,
    *,
    exclude_appointment_ids: set[str] | None = None,
) -> dict[str, list[Interval]]:
    """Busy intervals per employee over [window_start, window_end], unioning
    assigned appointments (incl. mirrored Google busy) + approved absences and
    manual blocks. One appointments read + one absences read for the WHOLE set,
    grouped in Python — so ranking many candidates stays 2 queries.

    ``exclude_appointment_ids`` drops specific appointments from the busy set
    (e.g. the appointment being rescheduled, so it doesn't conflict with itself).
    Returns ``{employee_id: [interval, …]}`` with an entry for every requested id
    (empty list when free).
    """
    ids = [e for e in dict.fromkeys(employee_ids) if e]  # dedupe, drop falsy, keep order
    if not ids:
        return {}
    exclude = exclude_appointment_ids or set()
    busy: dict[str, list[Interval]] = {eid: [] for eid in ids}

    appt_lo = (window_start - _APPT_BACKSCAN).isoformat()
    win_hi = window_end.isoformat()

    def _load_appts() -> list[dict]:
        return (
            client.table("appointments")
            .select("id, assigned_employee_id, scheduled_at, duration_minutes")
            .eq("org_id", org_id)
            .in_("assigned_employee_id", ids)
            .in_("status", list(_BUSY_APPT_STATUS))
            .gte("scheduled_at", appt_lo)
            .lte("scheduled_at", win_hi)
            .execute()
            .data
            or []
        )

    def _load_absences() -> list[dict]:
        # Overlap test for spanning absences: starts_at <= window_end AND
        # ends_at >= window_start (an absence beginning before the window but
        # still active inside it must count). 'approved' covers vacations,
        # sickness, training AND manual blocks (type='block').
        return (
            client.table("employee_absences")
            .select("employee_id, starts_at, ends_at")
            .eq("org_id", org_id)
            .eq("status", "approved")
            .in_("employee_id", ids)
            .lte("starts_at", win_hi)
            .gte("ends_at", window_start.isoformat())
            .execute()
            .data
            or []
        )

    appt_rows, absence_rows = run_parallel(_load_appts, _load_absences)

    for a in appt_rows:
        eid = a.get("assigned_employee_id")
        if eid not in busy or a.get("id") in exclude:
            continue
        start = _parse_iso(a.get("scheduled_at"))
        if not start:
            continue
        busy[eid].append((start, start + timedelta(minutes=_appt_duration_minutes(a))))

    for ab in absence_rows:
        eid = ab.get("employee_id")
        if eid not in busy:
            continue
        start = _parse_iso(ab.get("starts_at"))
        end = _parse_iso(ab.get("ends_at"))
        if not start or not end or end <= start:
            continue
        busy[eid].append((start, end))

    return busy


def is_free(
    client,
    org_id: str,
    employee_id: str,
    start: datetime,
    end: datetime,
    *,
    buffer_minutes: int = 0,
    exclude_appointment_ids: set[str] | None = None,
) -> bool:
    """Convenience single-employee check: does this employee have NO conflicting
    appointment / absence / block over [start, end)?"""
    if not employee_id:
        return False
    busy = load_busy_map(
        client, org_id, [employee_id], start, end,
        exclude_appointment_ids=exclude_appointment_ids,
    ).get(employee_id, [])
    return not _intervals_conflict(busy, start, end, buffer_minutes)


def busy_intervals(
    client,
    org_id: str,
    employee_id: str,
    window_start: datetime,
    window_end: datetime,
) -> list[Interval]:
    """All busy intervals for one employee over the window, sorted by start.
    Used to render an employee's blocked time on the calendar (Phase 2)."""
    if not employee_id:
        return []
    intervals = load_busy_map(
        client, org_id, [employee_id], window_start, window_end
    ).get(employee_id, [])
    return sorted(intervals)


def free_employees(
    client,
    org_id: str,
    employee_ids: list[str],
    start: datetime,
    end: datetime,
    *,
    buffer_minutes: int = 0,
) -> list[str]:
    """Subset of ``employee_ids`` with no conflict over [start, end), order
    preserved. One batched load behind it — the building block for "only show
    available names" in the assignment picker and the voice tool."""
    busy_map = load_busy_map(client, org_id, employee_ids, start, end)
    return [
        eid
        for eid in dict.fromkeys(e for e in employee_ids if e)
        if slot_free(busy_map.get(eid, []), start, end, buffer_minutes=buffer_minutes)
    ]
