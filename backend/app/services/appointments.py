"""Appointment tools: get_available_slots, book, cancel, change."""

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from app.db.supabase_client import get_service_client
from app.schemas.tools import (
    BookAppointmentRequest,
    CancelAppointmentRequest,
    ChangeAppointmentRequest,
    GetAvailableAppointmentsRequest,
)
from app.services.common import (
    BERLIN,
    _parse_time,
    fmt_date,
    fmt_time,
    format_address,
    gen_inquiry_number,
    now_berlin,
    parse_when,
    slot_key,
)
from app.services.customers import get_or_create_customer
from app.services.scheduling import WEEKDAY_KEYS, normalize_business_hours

logger = logging.getLogger(__name__)

MAX_SLOTS = 6


def _hour(value: str, fallback: int) -> int:
    try:
        return int(str(value).split(":", 1)[0])
    except (ValueError, AttributeError):
        return fallback


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_iso_date(s: str | None):
    """Parse a natural-language date string to a Berlin calendar date."""
    if not s:
        return None
    dt = parse_when(s, None)
    return dt.astimezone(BERLIN).date() if dt else None


def _scheduling_rules(client, org_id: str) -> dict:
    """The Terminregeln the Kiki-Zentrale UI actually edits (FLAT agent_configs
    columns) merged with the legacy `scheduling` jsonb (business_hours + the old
    lead_days). The flat columns win — previously the slot logic only read the
    jsonb, so buffer/max-per-day/lead-clock saves had no effect (Terminregeln
    'not working')."""
    rows = (
        client.table("agent_configs")
        .select(
            "scheduling, buffer_minutes, max_appointments_per_day, parallel_slots, "
            "lead_time_hours, lead_time_days, lead_time_only_weekdays, "
            "lead_time_earliest_clock"
        )
        .eq("org_id", org_id)
        .limit(1)
        .execute()
        .data
    )
    row = rows[0] if rows else {}
    sched = row.get("scheduling") or {}

    def _int(v, default):
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    lead_hours = row.get("lead_time_hours")
    if lead_hours is None:
        # Fallback chain: flat days column → legacy jsonb lead_days → 1 day.
        lead_days = row.get("lead_time_days")
        if lead_days is None:
            lead_days = sched.get("lead_days", 1)
        lead_hours = _int(lead_days, 1) * 24
    return {
        "business_hours": sched.get("business_hours"),
        "lead_hours": max(0, _int(lead_hours, 24)),
        "lead_only_weekdays": bool(row.get("lead_time_only_weekdays")),
        "earliest_clock": row.get("lead_time_earliest_clock"),
        "buffer_minutes": max(0, _int(row.get("buffer_minutes"), 0)),
        "max_per_day": max(0, _int(row.get("max_appointments_per_day"), 0)),
        "parallel": max(1, _int(row.get("parallel_slots") or sched.get("parallel_slots"), 1)),
    }


def _add_lead_hours(now: datetime, hours: int, weekdays_only: bool) -> datetime:
    """now + lead time. With weekdays_only, only hours on Mon–Fri count toward
    the lead time (a Friday-afternoon call with 24h lead lands on Monday)."""
    hours = min(max(0, hours), 24 * 90)  # hard cap: 90 days of lead time
    if not weekdays_only:
        return now + timedelta(hours=hours)
    cur = now
    remaining = hours
    while remaining > 0:
        cur += timedelta(hours=1)
        if cur.weekday() < 5:
            remaining -= 1
    return cur


def _earliest_clock_hour(value) -> int | None:
    """'10:00'/'10:00:00' → 10; None/garbage → None."""
    if not value:
        return None
    try:
        return int(str(value).split(":", 1)[0])
    except (TypeError, ValueError):
        return None


def _appt_intervals(existing: list[dict]) -> list[tuple[datetime, datetime]]:
    out = []
    for a in existing:
        start = _parse_iso(a.get("scheduled_at"))
        if not start:
            continue
        dur = a.get("duration_minutes") or 60
        try:
            dur = int(dur)
        except (TypeError, ValueError):
            dur = 60
        out.append((start, start + timedelta(minutes=dur)))
    return out


def _slot_conflicts(
    intervals: list[tuple[datetime, datetime]],
    start: datetime,
    duration_minutes: int,
    buffer_minutes: int,
) -> int:
    """How many existing appointments overlap [start, start+dur) once each
    existing appointment is padded by the configured buffer on both sides."""
    end = start + timedelta(minutes=duration_minutes)
    pad = timedelta(minutes=buffer_minutes)
    return sum(1 for (s, e) in intervals if start < e + pad and end > s - pad)


def _get_kiki_level(client, org_id: str) -> int:
    """The appointments autonomy level (agent_configs.appointments_level), default 2.

    Disabled appointments behave as level 1 (inquiries only). Falls back to the
    legacy single kiki_level when the per-capability column is unset.

    1 = take inquiries only (no appointment rows booked).
    2 = book as a reservation (status='pending'); team confirms afterwards.
    3 = book + auto-confirm POST-call (post_call._fire_level3_confirmations)."""
    rows = (
        client.table("agent_configs")
        .select("appointments_enabled, appointments_level, kiki_level")
        .eq("org_id", org_id)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        return 2
    row = rows[0]
    if row.get("appointments_enabled") is False:
        return 1
    val = row.get("appointments_level")
    if val is None:
        val = row.get("kiki_level")
    try:
        return int(val) if val is not None else 2
    except (TypeError, ValueError):
        return 2


def _reschedule_timeout_hours(client, org_id: str) -> int:
    """Per-org hours a pending reschedule waits before the timer resolves it
    (agent_configs.reschedule_request_timeout_hours, default 24)."""
    rows = (
        client.table("agent_configs")
        .select("reschedule_request_timeout_hours")
        .eq("org_id", org_id)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        return 24
    try:
        val = int(rows[0].get("reschedule_request_timeout_hours"))
        return val if val > 0 else 24
    except (TypeError, ValueError):
        return 24


def _first_employee(client, org_id: str) -> dict | None:
    rows = (
        client.table("employees")
        .select("id, display_name")
        .eq("org_id", org_id)
        .eq("is_active", True)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


def _resolve_category(client, org_id: str, name: str | None) -> dict | None:
    """Case-insensitive exact match of the agent's `kategorie` parameter against
    appointment_categories.name. A match drives the appointment's duration and
    (when configured) the default employee."""
    if not name or not str(name).strip():
        return None
    wanted = str(name).strip().lower()
    rows = (
        client.table("appointment_categories")
        .select("id, name, duration_minutes, default_employee_id")
        .eq("org_id", org_id)
        .execute()
        .data
        or []
    )
    for row in rows:
        if (row.get("name") or "").strip().lower() == wanted:
            return row
    return None


def _employee_by_id(client, org_id: str, employee_id: str | None) -> dict | None:
    if not employee_id:
        return None
    rows = (
        client.table("employees")
        .select("id, display_name, is_active")
        .eq("org_id", org_id)
        .eq("id", employee_id)
        .limit(1)
        .execute()
        .data
    )
    if rows and rows[0].get("is_active"):
        return rows[0]
    return None


def _resolve_slot_assignee(
    client,
    org_id: str,
    *,
    category: dict | None,
    summary: str | None,
    start,
    duration_minutes: int,
) -> dict | None:
    """Pick the responsible employee for a CONCRETE slot: the best AVAILABLE,
    least-loaded, competent candidate (``services.assignment``). This closes the
    long-standing ABSENCE TODO — the agent never pins a slot on someone who is
    already booked, on holiday, or blocked.

    Falls back to a best-effort competent pick (highest skill, then fewest open
    tickets) when the WHOLE competence pool is busy at that time, and to the
    legacy category-default / first-employee chain on any error — so booking
    always resolves *someone* for the team to review. Returns an employee dict
    (``id``, ``display_name``) or ``None`` when the org has no active employee.
    """
    from app.services import assignment, availability

    end = start + timedelta(minutes=duration_minutes)
    cat_default = category.get("default_employee_id") if category else None
    cat_name = category["name"] if category else None
    try:
        buffer = _scheduling_rules(client, org_id).get("buffer_minutes", 0)
        pool = assignment.build_pool(
            client,
            org_id,
            category_name=cat_name,
            summary=summary,
            category_default_employee_id=cat_default,
        )
        if not pool:
            return None
        ids = [e["id"] for e in pool if e.get("id")]
        busy = availability.load_busy_map(client, org_id, ids, start, end)
        workload = assignment.open_ticket_counts(client, org_id, ids)
        pick = assignment.pick_for_slot(pool, busy, workload, start, end, buffer_minutes=buffer)
        chosen = pick or sorted(
            pool,
            key=lambda e: (
                -int(e.get("skill_score") or 0),
                int(workload.get(e.get("id"), 0)),
                (e.get("display_name") or "").lower(),
            ),
        )[0]
        return {"id": chosen["id"], "display_name": chosen.get("display_name")}
    except Exception as exc:  # noqa: BLE001 — availability is best-effort, never blocks booking
        logger.warning("slot assignee resolution failed (org %s): %s", org_id, str(exc)[:200])
        return _employee_by_id(client, org_id, cat_default) or _first_employee(client, org_id)


def _find_customer_by_phone(client, org_id: str, phone: str | None) -> dict | None:
    if not phone:
        return None
    rows = (
        client.table("customers")
        .select("id, full_name, phone")
        .eq("org_id", org_id)
        .eq("phone", phone)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


def _suggest_employee_enabled(client, org_id: str) -> bool:
    """Per-org "Kiki names the assigned employee out loud on the call" toggle
    (``agent_configs.suggest_employee_enabled``). Default OFF: the availability +
    workload ROUTING is always on (the right person is still booked), but the
    spoken NAME is opt-in. Guarded so a missing column (pre-migration) reads as
    OFF instead of breaking the slot finder."""
    try:
        rows = (
            client.table("agent_configs")
            .select("suggest_employee_enabled")
            .eq("org_id", org_id)
            .limit(1)
            .execute()
            .data
        )
    except Exception:  # noqa: BLE001 — column not migrated yet → OFF
        return False
    return bool(rows[0].get("suggest_employee_enabled")) if rows else False


def _collect_slots(
    *,
    start_date,
    days: int,
    business_hours: dict,
    now,
    earliest_dt,
    earliest_clock: int | None,
    max_per_day: int,
    per_day,
    step: int,
    collect_cap: int,
    accept,
) -> list[dict]:
    """Walk business-hours slots over the window, emitting the ones ``accept(dt)``
    approves. ``accept`` returns the chosen employee ``{"id", "name"}`` for the
    slot, or ``None`` to skip it — the ONLY thing that differs between the org-wide
    legacy mode and the per-employee routing mode."""
    slots: list[dict] = []
    # The "Frühester Termin (Uhrzeit)" floor applies on the first day we actually
    # offer slots — NOT on earliest_dt.date(), which can be a skipped weekend/holiday
    # (that would silently bypass earliest_clock on the real first bookable day).
    first_open_day = None
    for offset in range(days):
        day = start_date + timedelta(days=offset)
        bh = business_hours[WEEKDAY_KEYS[day.weekday()]]
        if not bh.get("open"):  # closed day (weekend / holiday config)
            continue
        if max_per_day and per_day.get(day, 0) >= max_per_day:
            continue  # day already at capacity
        if first_open_day is None:
            first_open_day = day
        open_hour = _hour(bh["start"], 8)
        close_hour = _hour(bh["end"], 17)
        brk_start = _hour(bh["break_start"], -1) if bh.get("break_start") else -1
        brk_end = _hour(bh["break_end"], -1) if bh.get("break_end") else -1
        for hour in range(open_hour, close_hour, step):
            if brk_start <= hour < brk_end:  # lunch break
                continue
            dt = datetime(day.year, day.month, day.day, hour, 0, tzinfo=BERLIN)
            if dt <= now or dt < earliest_dt:
                continue
            if day == first_open_day and earliest_clock is not None and hour < earliest_clock:
                continue  # "Frühester Termin (Uhrzeit)" on the first bookable day
            who = accept(dt)
            if who is None:
                continue  # at capacity / nobody competent free
            slots.append(
                {
                    "datetime": dt.isoformat(),
                    "displayDate": fmt_date(dt),
                    "displayTime": fmt_time(dt),
                    "employeeId": who.get("id"),
                    "employeeName": who.get("name") or "Team",
                }
            )
            if len(slots) >= collect_cap:
                return slots
    return slots


# ─── getAvailableAppointments ────────────────────────────────────────────────
def get_available_slots(org_id: str, payload: GetAvailableAppointmentsRequest) -> dict:
    client = get_service_client()
    rules = _scheduling_rules(client, org_id)
    parallel = rules["parallel"]
    buffer_min = rules["buffer_minutes"]
    max_per_day = rules["max_per_day"]
    days = min(int(payload.days or 7), 14)

    # Category supplies the DURATION (and a routing signal); an explicit
    # durationMinutes from the agent still wins. _resolve_category is a no-op
    # (no DB) when the agent passes no category, so the legacy path is unchanged.
    category = _resolve_category(client, org_id, getattr(payload, "category", None))
    dur = int(payload.duration_minutes or 0)
    if dur <= 0 and category and category.get("duration_minutes"):
        try:
            dur = int(category["duration_minutes"])
        except (TypeError, ValueError):
            dur = 0
    dur = max(15, dur) if dur > 0 else 60
    step = max(1, round(dur / 60))

    now = now_berlin()
    # Lead time in HOURS (Kiki-Zentrale Terminregeln): the first bookable moment
    # is now + lead_hours (optionally counting only weekday hours). On that
    # earliest day, slots additionally start no earlier than the configured
    # "Frühester Termin (Uhrzeit)" — later days follow normal business hours.
    earliest_dt = _add_lead_hours(now, rules["lead_hours"], rules["lead_only_weekdays"])
    earliest_date = earliest_dt.date()
    earliest_clock = _earliest_clock_hour(rules["earliest_clock"])
    # Honor the caller's requested date: anchor the search window there (never
    # before the lead time) so a "next Tuesday" request returns Tuesday's slots
    # instead of always the generic earliest ones.
    pref_date = _parse_iso_date(payload.preferred_date)
    if pref_date:
        start_date = max(pref_date, earliest_date)
        days = min(days, 5)
    else:
        start_date = earliest_date
    window_end = datetime.combine(start_date, datetime.min.time(), tzinfo=BERLIN) + timedelta(days=days + 1)
    # A preferred time-of-day biases which slots surface first (and widens
    # collection so the requested hour isn't truncated away by the early break).
    pref_hour = None
    if payload.preferred_time:
        pt = _parse_time(payload.preferred_time)
        if pt:
            pref_hour = pt[0]
    collect_cap = MAX_SLOTS if pref_hour is None else 48

    existing = (
        client.table("appointments")
        .select("scheduled_at, duration_minutes, status")
        .eq("org_id", org_id)
        .gte("scheduled_at", now.isoformat())
        .lte("scheduled_at", window_end.isoformat())
        .in_("status", ["pending", "confirmed"])
        # An employee's PERSONAL Google busy ('employee_busy') blocks only that
        # person, not org-wide capacity — exclude it from the org slot finder. The
        # availability engine still counts it per-employee via assigned_employee_id.
        .neq("source", "employee_busy")
        .execute()
        .data
        or []
    )
    intervals = _appt_intervals(existing)
    # Max. Termine pro Tag: count existing per Berlin calendar date.
    per_day: Counter = Counter()
    for (s, _e) in intervals:
        per_day[s.astimezone(BERLIN).date()] += 1
    business_hours = normalize_business_hours(rules["business_hours"])

    # Whether Kiki may SPEAK the employee's name (default OFF). The routing below
    # runs regardless — only the surfaced name is gated.
    name_enabled = _suggest_employee_enabled(client, org_id)

    # ── Routing mode ─────────────────────────────────────────────────────────
    # With a routing signal (category/topic) we offer only slots a COMPETENT
    # person is genuinely free for, tagged with that person; otherwise we keep the
    # historical org-wide behaviour so the current agent (which sends neither)
    # never regresses.
    topic = getattr(payload, "topic", None)
    pool: list[dict] = []
    if category or topic:
        from app.services import assignment, availability

        pool = assignment.build_pool(
            client,
            org_id,
            category_name=(category["name"] if category else None),
            summary=topic,
            category_default_employee_id=(category.get("default_employee_id") if category else None),
        )

    if pool:
        ids = [e["id"] for e in pool if e.get("id")]
        busy_map = availability.load_busy_map(client, org_id, ids, now, window_end)
        workload = assignment.open_ticket_counts(client, org_id, ids)

        def _accept(dt):
            pick = assignment.pick_for_slot(
                pool, busy_map, workload, dt, dt + timedelta(minutes=dur), buffer_minutes=buffer_min
            )
            if not pick:
                return None  # nobody competent is free at this slot
            return {"id": pick["id"], "name": pick.get("display_name") if name_enabled else "Team"}
    else:
        emp = _first_employee(client, org_id)

        def _accept(dt):
            if _slot_conflicts(intervals, dt, dur, buffer_min) >= parallel:
                return None  # at capacity incl. Pufferzeit
            return {
                "id": emp["id"] if emp else None,
                "name": (emp["display_name"] if (emp and name_enabled) else "Team"),
            }

    slots = _collect_slots(
        start_date=start_date,
        days=days,
        business_hours=business_hours,
        now=now,
        earliest_dt=earliest_dt,
        earliest_clock=earliest_clock,
        max_per_day=max_per_day,
        per_day=per_day,
        step=step,
        collect_cap=collect_cap,
        accept=_accept,
    )

    # Surface slots nearest the requested time-of-day first, then truncate.
    if pref_hour is not None:
        slots.sort(key=lambda s: (s["datetime"][:10], abs(int(s["displayTime"][:2]) - pref_hour)))
    slots = slots[:MAX_SLOTS]

    if not slots:
        return {
            "success": True,
            "slots": [],
            "message": "Im gewünschten Zeitraum sind leider keine Termine frei. "
            "Bitte frag nach einem größeren Zeitfenster.",
        }
    first = slots[0]
    return {
        "success": True,
        "slots": slots,
        "message": f"Ich habe {len(slots)} freie Termine gefunden. Der früheste ist "
        f"am {first['displayDate']} um {first['displayTime']} Uhr.",
    }


# ─── bookAppointment ─────────────────────────────────────────────────────────
def _book_success(appt_id, customer_id, inquiry_id, dt, emp_name) -> dict:
    return {
        "success": True,
        "appointmentId": appt_id,
        "customerId": customer_id,
        "inquiryId": inquiry_id,
        "confirmedDatetime": dt.isoformat(),
        "displayDate": fmt_date(dt),
        "displayTime": fmt_time(dt),
        "employeeName": emp_name,
        "message": f"Termin gebucht für {fmt_date(dt)} um {fmt_time(dt)} Uhr. "
        "Du erhältst eine Bestätigung.",
    }


def book_appointment(org_id: str, payload: BookAppointmentRequest) -> dict:
    client = get_service_client()
    # Autonomy level gates whether we actually create an appointment row:
    #   L1 → inquiry only, NO appointment (the team books it manually).
    #   L2 → appointment lands as 'pending' (a reservation the team confirms).
    #   L3 → also 'pending' here; post_call._fire_level3_confirmations flips it
    #        to 'confirmed' AFTER the call so the confirmation never collides with
    #        the still-active booking call.
    level = _get_kiki_level(client, org_id)
    dt = parse_when(payload.date, payload.time)
    if dt is None:
        return {
            "success": False,
            "error": "INVALID_DATE",
            "message": "Ich konnte das Datum nicht verstehen. Bitte nenne "
            "Datum und Uhrzeit noch einmal.",
        }

    customer = get_or_create_customer(
        org_id,
        phone=payload.phone or payload.caller_number,
        name=payload.name,
        email=payload.email,
        address=payload.address,
    )
    key = slot_key(dt)
    # Category drives duration + assignment: a matched Terminkategorie supplies
    # the default duration and (if set + active) the Standard-Mitarbeiter;
    # otherwise fall back to 60 min / first active employee as before.
    category = _resolve_category(client, org_id, payload.category)
    duration_minutes = 60
    if category and category.get("duration_minutes"):
        try:
            duration_minutes = max(15, int(category["duration_minutes"]))
        except (TypeError, ValueError):
            duration_minutes = 60
    # Availability- + workload-aware assignment for THIS slot (closes the
    # long-standing ABSENCE TODO): the best AVAILABLE, least-loaded, competent
    # person — not blindly the category default / first employee. Category still
    # supplies the DURATION above; the Tätigkeitsbereich supplies WHO.
    emp = _resolve_slot_assignee(
        client,
        org_id,
        category=category,
        summary=payload.description or payload.category,
        start=dt,
        duration_minutes=duration_minutes,
    )

    day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    same_day = (
        client.table("appointments")
        .select("id, customer_id, scheduled_at, duration_minutes, status")
        .eq("org_id", org_id)
        .gte("scheduled_at", day_start.isoformat())
        .lt("scheduled_at", day_end.isoformat())
        .in_("status", ["pending", "confirmed"])
        .execute()
        .data
        or []
    )
    at_slot = [a for a in same_day if slot_key(_parse_iso(a["scheduled_at"])) == key]

    # Idempotency: same customer already holds this slot → return it.
    for a in at_slot:
        if a["customer_id"] == customer["id"]:
            return _book_success(
                a["id"], customer["id"], None, dt, emp["display_name"] if emp else "Team"
            )

    # Re-validate against the live Terminregeln (same rules as get_available_slots
    # — a stale slot offer must not slip through): parallel capacity incl. buffer,
    # plus the max-per-day cap.
    rules = _scheduling_rules(client, org_id)
    if rules["max_per_day"] and len(same_day) >= rules["max_per_day"]:
        return {
            "success": False,
            "error": "DAY_FULL",
            "message": "An diesem Tag sind keine weiteren Termine möglich. Bitte "
            "frag nach freien Terminen an einem anderen Tag.",
        }
    conflicts = _slot_conflicts(
        _appt_intervals(same_day), dt, duration_minutes, rules["buffer_minutes"]
    )
    if conflicts >= rules["parallel"]:
        return {
            "success": False,
            "error": "SLOT_TAKEN",
            "message": "Dieser Termin ist leider nicht mehr verfügbar. Bitte fragen "
            "dich erneut nach freien Terminen.",
        }

    number = gen_inquiry_number(client, org_id)
    notes = payload.description or ""
    for f in payload.additional_fields or []:
        if getattr(f, "question", None) or getattr(f, "answer", None):
            notes += f"\n{f.question}: {f.answer}"
    inquiry = (
        client.table("inquiries")
        .insert(
            {
                "org_id": org_id,
                "customer_id": customer["id"],
                "title": payload.inquiry_title or (payload.description or "Termin")[:60],
                "type": "appointment_request",
                "status": "in_progress",
                "number": number,
                "notes": notes.strip(),
            }
        )
        .execute()
        .data[0]
    )

    # ── Level 1: inquiry-only. Do NOT create an appointment row. ──
    # At autonomy level 1 the agent merely records the request; the team books
    # the actual appointment later. The inquiry above already captured the
    # request (incl. the desired slot in its notes), so we return success WITHOUT
    # an appointment — appointmentId=None signals "noted, no booking made".
    if level == 1:
        return {
            "success": True,
            "appointmentId": None,
            "customerId": customer["id"],
            "inquiryId": inquiry["id"],
            "message": "Dein Anliegen wurde notiert — das Team meldet sich bei dir.",
        }

    # ── Levels 2 & 3: create the appointment as a reservation (status='pending'). ──
    # Address on the appointment itself (so it shows on the calendar / detail card).
    # Prefer the address the agent collected this call; else fall back to the
    # customer's stored address (returning callers where the agent skipped
    # re-collecting it).
    loc_addr = payload.address
    if not loc_addr:
        crow = (
            client.table("customers").select("address")
            .eq("id", customer["id"]).limit(1).execute().data
        )
        if crow and crow[0].get("address"):
            loc_addr = format_address(crow[0]["address"])
    location = {"raw": loc_addr} if loc_addr else None

    # supabase-py has no transaction, so the inquiry (above) and the appointment
    # are two separate writes. If the appointment insert fails we must COMPENSATE
    # by deleting the inquiry we just created — otherwise the call leaves a phantom
    # "open inquiry" with no appointment behind it (silent data drift).
    try:
        appt = (
            client.table("appointments")
            .insert(
                {
                    "org_id": org_id,
                    "inquiry_id": inquiry["id"],
                    "customer_id": customer["id"],
                    "assigned_employee_id": emp["id"] if emp else None,
                    "title": payload.inquiry_title or payload.description or "Termin",
                    "scheduled_at": dt.isoformat(),
                    "duration_minutes": duration_minutes,
                    "location": location,
                    # Store the canonical category name so the Offene-Aktion card
                    # can resolve it back to the configured Terminkategorie.
                    "category": category["name"] if category else payload.category,
                    # Land as 'pending' (a reservation) so it shows in the call's
                    # "Offene Aktionen" card for a human to review/confirm. Confirming
                    # there moves it to the calendar AND fires the confirmation
                    # call+email — no automatic confirmation without a human.
                    "status": "pending",
                    "notes": notes.strip(),
                    # Correlate back to the call so the call-detail card can surface
                    # this agent-booked appointment (it lives on a separate inquiry).
                    "source_conversation_id": payload.conversation_id,
                }
            )
            .execute()
            .data[0]
        )
    except Exception:
        try:
            client.table("inquiries").delete().eq("org_id", org_id).eq(
                "id", inquiry["id"]
            ).execute()
        except Exception:  # noqa: BLE001 — best-effort cleanup; log the orphan
            logger.exception(
                "book_appointment: appointment insert failed AND inquiry rollback "
                "failed — orphaned inquiry %s (org %s)", inquiry["id"], org_id
            )
        raise
    # The confirmation call+email is fired AFTER the call ends (services/post_call.py),
    # NOT here — so it never collides with the still-active booking call. The
    # appointment carries source_conversation_id for that post-call linkage.
    return _book_success(
        appt["id"], customer["id"], inquiry["id"], dt, emp["display_name"] if emp else "Team"
    )


# ─── cancelAppointment ───────────────────────────────────────────────────────
def _upcoming_appts(client, org_id: str, customer_id: str) -> list[dict]:
    return (
        client.table("appointments")
        .select("id, scheduled_at, status")
        .eq("org_id", org_id)
        .eq("customer_id", customer_id)
        .in_("status", ["pending", "confirmed"])
        .gte("scheduled_at", now_berlin().isoformat())
        .order("scheduled_at")
        .execute()
        .data
        or []
    )


def _do_cancel(client, appt: dict, reason: str | None) -> dict:
    client.table("appointments").update(
        {"status": "cancelled", "notes": reason,
         "cancelled_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", appt["id"]).execute()
    dt = _parse_iso(appt["scheduled_at"])
    when = f"am {fmt_date(dt)} um {fmt_time(dt)} Uhr" if dt else ""
    return {
        "success": True,
        "appointmentId": appt["id"],
        "cancelledDatetime": appt["scheduled_at"],
        "message": f"Dein Termin {when} wurde storniert.".replace("  ", " "),
    }


def cancel_appointment(org_id: str, payload: CancelAppointmentRequest) -> dict:
    client = get_service_client()

    # 1) Strong identity: phone (explicit or Caller-ID) → cancel next upcoming.
    customer = _find_customer_by_phone(
        client, org_id, payload.phone_number or payload.caller_number
    )
    if customer:
        appts = _upcoming_appts(client, org_id, customer["id"])
        if not appts:
            return {
                "success": False,
                "error": "NO_APPOINTMENT_FOUND",
                "message": "Es wurde kein bevorstehender Termin gefunden.",
            }
        return _do_cancel(client, appts[0], payload.reason)

    # 2) Fallback: name + date confirmation (no phone match).
    if payload.name:
        candidates = (
            client.table("customers")
            .select("id, full_name")
            .eq("org_id", org_id)
            .ilike("full_name", f"%{payload.name}%")
            .limit(10)
            .execute()
            .data
            or []
        )
        # Gather all upcoming appts across name matches.
        appts: list[dict] = []
        for c in candidates:
            appts.extend(_upcoming_appts(client, org_id, c["id"]))

        if not appts:
            return {
                "success": False,
                "error": "NO_APPOINTMENT_FOUND",
                "message": "Zu diesem Namen wurde kein bevorstehender Termin gefunden.",
            }

        # Require a date to confirm which appointment — never guess.
        want = _parse_iso_date(payload.date)
        if want is None:
            return {
                "success": False,
                "error": "DATE_CONFIRMATION_REQUIRED",
                "message": "Zur Sicherheit nenne mir bitte das Datum des Termins, "
                "den du stornieren möchtest.",
            }
        matching = [
            a for a in appts
            if (_parse_iso(a["scheduled_at"]) and
                _parse_iso(a["scheduled_at"]).astimezone(BERLIN).date() == want)
        ]
        if len(matching) == 1:
            return _do_cancel(client, matching[0], payload.reason)
        if len(matching) == 0:
            return {
                "success": False,
                "error": "NO_APPOINTMENT_FOUND",
                "message": "An diesem Datum wurde kein Termin gefunden. Bitte prüfen "
                "nenne das Datum.",
            }
        return {
            "success": False,
            "error": "MULTIPLE_MATCHES",
            "message": "Es gibt mehrere Termine an diesem Datum. Bitte nenne "
            "zusätzlich deine Telefonnummer zur eindeutigen Zuordnung.",
        }

    return {
        "success": False,
        "error": "NO_APPOINTMENT_FOUND",
        "message": "Zu dieser Telefonnummer wurde kein Termin gefunden.",
    }


# ─── changeAppointment ───────────────────────────────────────────────────────
def _appointment_from_conversation(client, org_id: str, conversation_id: str | None) -> dict | None:
    """Deterministic reschedule targeting on OUTBOUND calls: the outbound_calls
    ledger row stamped with this conversation_id says exactly which appointment
    this call is about (referenz_typ='Termin' + referenz_id) — no phone/name/date
    guessing needed. Post-mortem conv_7401ktv…: the LLM passed a hallucinated
    phoneNumber, the lookup failed, and the reschedule request was silently lost
    although the call KNEW the appointment id the whole time."""
    if not conversation_id:
        return None
    rows = (
        client.table("outbound_calls")
        .select("referenz_typ, referenz_id")
        .eq("org_id", org_id)
        .eq("conversation_id", conversation_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    led = rows[0] if rows else None
    if not led or led.get("referenz_typ") != "Termin" or not led.get("referenz_id"):
        return None
    appt = (
        client.table("appointments")
        .select("id, scheduled_at, customer_id, status")
        .eq("org_id", org_id)
        .eq("id", led["referenz_id"])
        .in_("status", ["pending", "confirmed"])
        .limit(1)
        .execute()
        .data
        or []
    )
    return appt[0] if appt else None


def _record_unmatched_change_request(
    client, org_id: str, payload: ChangeAppointmentRequest, customer: dict | None = None
) -> dict:
    """Terminal fallback: the reschedule could not be linked to an appointment —
    NEVER drop it (the agent already promised the caller it would be passed on).
    Record a concrete appointment_change inquiry carrying every bit of caller
    context we have, so a human can match it; the agent's message stays truthful."""
    new_dt = parse_when(payload.new_date, payload.new_time)
    wunsch = (
        new_dt.isoformat()
        if new_dt
        else f"{payload.new_date or '?'} {payload.new_time or ''}".strip()
    )
    number = gen_inquiry_number(client, org_id)
    notes = (
        "NICHT ZUGEORDNET — Termin konnte nicht automatisch gefunden werden, "
        "bitte manuell zuordnen.\n"
        f"Wunschtermin neu: {wunsch}\n"
        f"Caller-ID: {payload.caller_number or '-'} | vom Agenten übermittelte Nummer: "
        f"{payload.phone_number or '-'} | Name: {payload.name or '-'}\n"
        f"Grund: {payload.reason or '-'} | Conversation: {payload.conversation_id or '-'}"
    )
    change = (
        client.table("inquiries")
        .insert(
            {
                "org_id": org_id,
                "customer_id": (customer or {}).get("id"),
                "title": "Terminänderung (manuell zuordnen)",
                "type": "appointment_change",
                "status": "open",
                "number": number,
                "notes": notes,
            }
        )
        .execute()
        .data[0]
    )
    return {
        "success": True,
        "changeRequestId": change["id"],
        "status": "FORWARDED_TO_TEAM",
        "message": "Ich habe deinen Terminänderungswunsch an das Team weitergegeben — "
        "es prüft den Termin und meldet sich zur Bestätigung bei dir.",
    }


def change_appointment(org_id: str, payload: ChangeAppointmentRequest) -> dict:
    client = get_service_client()

    # 1) Deterministic: on an outbound appointment call the ledger names the
    #    exact appointment — use it and skip the phone/name derivation entirely.
    appt = _appointment_from_conversation(client, org_id, payload.conversation_id)
    customer: dict | None = None
    if appt is not None and appt.get("customer_id"):
        cust_rows = (
            client.table("customers")
            .select("id, full_name")
            .eq("org_id", org_id)
            .eq("id", appt["customer_id"])
            .limit(1)
            .execute()
            .data
        )
        customer = cust_rows[0] if cust_rows else None

    if appt is None:
        # 2) Derivation path (inbound / no ledger): the VERIFIED Caller-ID wins
        #    over the LLM-supplied phoneNumber — a hallucinated/placeholder number
        #    must never shadow the real caller. Name is the last resort.
        customer = _find_customer_by_phone(client, org_id, payload.caller_number)
        if not customer:
            customer = _find_customer_by_phone(client, org_id, payload.phone_number)
        if not customer and payload.name:
            rows = (
                client.table("customers")
                .select("id, full_name")
                .eq("org_id", org_id)
                .ilike("full_name", f"%{payload.name}%")
                .limit(1)
                .execute()
                .data
            )
            customer = rows[0] if rows else None
        if not customer:
            # 3) Never lose the request: record it for manual matching.
            return _record_unmatched_change_request(client, org_id, payload)

        now = now_berlin()
        rows = (
            client.table("appointments")
            .select("id, scheduled_at")
            .eq("org_id", org_id)
            .eq("customer_id", customer["id"])
            .in_("status", ["pending", "confirmed"])
            .gte("scheduled_at", now.isoformat())
            .order("scheduled_at")
            .execute()
            .data
            or []
        )
        if not rows:
            # Known customer but no upcoming appointment row → still capture it.
            return _record_unmatched_change_request(client, org_id, payload, customer)
        # Pick the RIGHT appointment to move. With one upcoming appointment we
        # take it. With several we never guess: the agent must supply the date of
        # the one the customer means (mirrors the cancel flow) so we link the
        # proposal to the exact appointment — this is what keeps a reschedule
        # from drifting onto the wrong row.
        if len(rows) == 1:
            appt = rows[0]
        else:
            want = _parse_iso_date(payload.appointment_date)
            if want is None:
                return {
                    "success": False,
                    "error": "DATE_CONFIRMATION_REQUIRED",
                    "message": "Du hast mehrere bevorstehende Termine. Welchen möchtest "
                    "du verschieben? Bitte nenne mir das Datum des Termins.",
                }
            matching = [
                a for a in rows
                if (_parse_iso(a["scheduled_at"])
                    and _parse_iso(a["scheduled_at"]).astimezone(BERLIN).date() == want)
            ]
            if len(matching) == 0:
                return {
                    "success": False,
                    "error": "NO_APPOINTMENT_FOUND",
                    "message": "An diesem Datum wurde kein Termin gefunden. Bitte prüfen "
                    "nenne das Datum.",
                }
            if len(matching) > 1:
                return {
                    "success": False,
                    "error": "MULTIPLE_MATCHES",
                    "message": "Es gibt mehrere Termine an diesem Datum. Bitte nenne "
                    "zusätzlich die Uhrzeit zur eindeutigen Zuordnung.",
                }
            appt = matching[0]

    new_dt = parse_when(payload.new_date, payload.new_time)
    if new_dt is None:
        return {
            "success": False,
            "error": "INVALID_DATE",
            "message": "Ich konnte das neue Datum nicht verstehen. Bitte nenne "
            "es noch einmal.",
        }

    number = gen_inquiry_number(client, org_id)
    change = (
        client.table("inquiries")
        .insert(
            {
                "org_id": org_id,
                # Part-1 path resolves the customer from the appointment row; fall
                # back to that id if the customer fetch came up empty.
                "customer_id": (customer or {}).get("id") or appt.get("customer_id"),
                "title": "Terminänderung",
                "type": "appointment_change",
                "status": "open",
                "number": number,
                "notes": f"Wunschtermin neu: {new_dt.isoformat()}. "
                f"Ursprünglich: {appt['scheduled_at']}. Grund: {payload.reason or '-'}",
            }
        )
        .execute()
        .data[0]
    )
    # ADDITIVE (appointment epic, migration 0037): also stamp the customer's
    # requested slot onto the matched appointment so a human can approve it in one
    # click (call-detail action card → "Kunde schlägt {time} vor" →
    # POST /appointments/{id}/approve-proposal applies it + fires the confirmation
    # call+email). Purely additive: the appointment_change inquiry created above
    # and this tool's return contract are UNCHANGED. Best-effort — a stamp failure
    # must never change the agent-facing outcome.
    # The reschedule is a PROPOSAL on the existing row — no new appointment is
    # created, and NOTHING is sent to the customer here (no call, no email). The
    # admin commits it (approve-proposal → in-place move + confirmation), or the
    # timer resolves it after reschedule_expires_at if no one acts. replace_intent
    # records whether the customer abandons the old slot (→ timer may release it)
    # or keeps it as a fallback (→ never auto-cancelled).
    expires_at = now_berlin() + timedelta(
        hours=_reschedule_timeout_hours(client, org_id)
    )
    try:
        stamp_res = (
            client.table("appointments")
            .update(
                {
                    "customer_proposed_start_time": new_dt.isoformat(),
                    "customer_proposed_at": now_berlin().isoformat(),
                    "customer_proposal_source": "agent_call",
                    "reschedule_expires_at": expires_at.isoformat(),
                    "reschedule_replace_intent": bool(payload.replace_original),
                }
            )
            .eq("org_id", org_id)
            .eq("id", appt["id"])
            .execute()
        )
        if not (stamp_res.data):
            logger.warning(
                "change_appointment: customer_proposed stamp updated 0 rows for appt %s (org %s)",
                appt["id"],
                org_id,
            )
    except Exception as exc:  # pragma: no cover — never break the live change flow
        logger.warning(
            "change_appointment: customer_proposed stamp failed for appt %s (org %s): %s",
            appt["id"],
            org_id,
            exc,
        )
    return {
        "success": True,
        "changeRequestId": change["id"],
        "originalDatetime": appt["scheduled_at"],
        "requestedDatetime": new_dt.isoformat(),
        "status": "PENDING_CONFIRMATION",
        "message": f"Deine Umbuchungsanfrage für {fmt_date(new_dt)} um "
        f"{fmt_time(new_dt)} Uhr wurde aufgenommen. Du wirst zur Bestätigung "
        "kontaktiert.",
    }


# ─── ICS import ──────────────────────────────────────────────────────────────
def _unfold_ics(text: str) -> list[str]:
    """RFC 5545 line unfolding: a leading space/tab continues the previous line."""
    out: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and out:
            out[-1] += raw[1:]
        else:
            out.append(raw)
    return out


def _unescape_text(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def _parse_ics_dt(value: str, params: str) -> datetime | None:
    """Parse a DTSTART/DTEND value to a timezone-aware datetime."""
    value = value.strip()
    is_utc = value.endswith("Z")
    val = value[:-1] if is_utc else value
    try:
        if "T" in val:
            dt = datetime.strptime(val, "%Y%m%dT%H%M%S")
        else:  # VALUE=DATE (all-day) → 08:00 local
            dt = datetime.strptime(val, "%Y%m%d").replace(hour=8)
    except ValueError:
        return None
    if is_utc:
        return dt.replace(tzinfo=timezone.utc)
    return dt.replace(tzinfo=BERLIN)  # naive / TZID → treat as Berlin


def _parse_vevents(text: str) -> list[dict]:
    events: list[dict] = []
    cur: dict | None = None
    for line in _unfold_ics(text):
        if line == "BEGIN:VEVENT":
            cur = {}
            continue
        if line == "END:VEVENT":
            if cur is not None:
                events.append(cur)
            cur = None
            continue
        if cur is None or ":" not in line:
            continue
        key, value = line.split(":", 1)
        name, _, params = key.partition(";")
        name = name.upper()
        if name == "DTSTART":
            cur["start"] = _parse_ics_dt(value, params)
        elif name == "DTEND":
            cur["end"] = _parse_ics_dt(value, params)
        elif name == "SUMMARY":
            cur["summary"] = _unescape_text(value)
        elif name == "LOCATION":
            cur["location"] = _unescape_text(value)
        elif name == "DESCRIPTION":
            cur["description"] = _unescape_text(value)
    return events


def import_ics(org_id: str, content: bytes) -> dict:
    client = get_service_client()
    text = content.decode("utf-8", errors="ignore")
    events = _parse_vevents(text)

    rows: list[dict] = []
    skipped = 0
    for ev in events:
        start = ev.get("start")
        if not start:
            skipped += 1
            continue
        end = ev.get("end")
        duration = 60
        if end and end > start:
            duration = max(15, int((end - start).total_seconds() // 60))
        rows.append(
            {
                "org_id": org_id,
                "title": ev.get("summary") or "Termin (Import)",
                "scheduled_at": start.astimezone(timezone.utc).isoformat(),
                "duration_minutes": duration,
                "location": {"raw": ev["location"]} if ev.get("location") else None,
                "notes": ev.get("description"),
                "status": "confirmed",
                "category": "import",
            }
        )

    created = 0
    if rows:
        created = len(client.table("appointments").insert(rows).execute().data or [])
    return {"created": created, "skipped": skipped, "total": len(events)}
