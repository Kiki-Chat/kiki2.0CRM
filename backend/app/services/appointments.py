"""Appointment tools: get_available_slots, book, cancel, change."""

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


def _scheduling(client, org_id: str) -> dict:
    rows = (
        client.table("agent_configs")
        .select("scheduling")
        .eq("org_id", org_id)
        .limit(1)
        .execute()
        .data
    )
    return (rows[0].get("scheduling") if rows and rows[0].get("scheduling") else {}) or {}


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


# ─── getAvailableAppointments ────────────────────────────────────────────────
def get_available_slots(org_id: str, payload: GetAvailableAppointmentsRequest) -> dict:
    client = get_service_client()
    sched = _scheduling(client, org_id)
    lead_days = int(sched.get("lead_days", 1) or 1)
    parallel = int(sched.get("parallel_slots", 1) or 1)
    days = min(int(payload.days or 7), 14)
    dur = int(payload.duration_minutes or 60)
    step = max(1, round(dur / 60))

    now = now_berlin()
    earliest = (now + timedelta(days=lead_days)).date()
    # Honor the caller's requested date: anchor the search window there (never
    # before the lead time) so a "next Tuesday" request returns Tuesday's slots
    # instead of always the generic earliest ones.
    pref_date = _parse_iso_date(payload.preferred_date)
    if pref_date:
        start_date = max(pref_date, earliest)
        days = min(days, 5)
        window_end = datetime.combine(start_date, datetime.min.time(), tzinfo=BERLIN) + timedelta(days=days + 1)
    else:
        start_date = earliest
        window_end = now + timedelta(days=lead_days + days + 1)
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
        .select("scheduled_at, status")
        .eq("org_id", org_id)
        .gte("scheduled_at", now.isoformat())
        .lte("scheduled_at", window_end.isoformat())
        .in_("status", ["pending", "confirmed"])
        .execute()
        .data
        or []
    )
    busy: Counter = Counter()
    for a in existing:
        dt = _parse_iso(a.get("scheduled_at"))
        if dt:
            busy[slot_key(dt)] += 1

    business_hours = normalize_business_hours(sched.get("business_hours"))
    emp = _first_employee(client, org_id)
    slots: list[dict] = []
    for offset in range(days):
        day = start_date + timedelta(days=offset)
        bh = business_hours[WEEKDAY_KEYS[day.weekday()]]
        if not bh.get("open"):  # closed day (weekend / holiday config)
            continue
        open_hour = _hour(bh["start"], 8)
        close_hour = _hour(bh["end"], 17)
        brk_start = _hour(bh["break_start"], -1) if bh.get("break_start") else -1
        brk_end = _hour(bh["break_end"], -1) if bh.get("break_end") else -1
        for hour in range(open_hour, close_hour, step):
            if brk_start <= hour < brk_end:  # lunch break
                continue
            dt = datetime(day.year, day.month, day.day, hour, 0, tzinfo=BERLIN)
            if dt <= now or busy.get(slot_key(dt), 0) >= parallel:
                continue
            slots.append(
                {
                    "datetime": dt.isoformat(),
                    "displayDate": fmt_date(dt),
                    "displayTime": fmt_time(dt),
                    "employeeId": emp["id"] if emp else None,
                    "employeeName": emp["display_name"] if emp else "Team",
                }
            )
            if len(slots) >= collect_cap:
                break
        if len(slots) >= collect_cap:
            break

    # Surface slots nearest the requested time-of-day first, then truncate.
    if pref_hour is not None:
        slots.sort(key=lambda s: (s["datetime"][:10], abs(int(s["displayTime"][:2]) - pref_hour)))
    slots = slots[:MAX_SLOTS]

    if not slots:
        return {
            "success": True,
            "slots": [],
            "message": "Im gewünschten Zeitraum sind leider keine Termine frei. "
            "Bitte fragen Sie nach einem größeren Zeitfenster.",
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
        "Sie erhalten eine Bestätigung.",
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
            "message": "Ich konnte das Datum nicht verstehen. Bitte nennen Sie "
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
    emp = _first_employee(client, org_id)

    day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    same_day = (
        client.table("appointments")
        .select("id, customer_id, scheduled_at, status")
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

    parallel = int(_scheduling(client, org_id).get("parallel_slots", 1) or 1)
    if len(at_slot) >= parallel:
        return {
            "success": False,
            "error": "SLOT_TAKEN",
            "message": "Dieser Termin ist leider nicht mehr verfügbar. Bitte fragen "
            "Sie erneut nach freien Terminen.",
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
            "message": "Ihr Anliegen wurde notiert — das Team meldet sich bei Ihnen.",
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
                "duration_minutes": 60,
                "location": location,
                "category": payload.category,
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
        {"status": "cancelled", "notes": reason}
    ).eq("id", appt["id"]).execute()
    dt = _parse_iso(appt["scheduled_at"])
    when = f"am {fmt_date(dt)} um {fmt_time(dt)} Uhr" if dt else ""
    return {
        "success": True,
        "appointmentId": appt["id"],
        "cancelledDatetime": appt["scheduled_at"],
        "message": f"Ihr Termin {when} wurde storniert.".replace("  ", " "),
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
                "message": "Zur Sicherheit nennen Sie mir bitte das Datum des Termins, "
                "den Sie stornieren möchten.",
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
                "Sie das Datum.",
            }
        return {
            "success": False,
            "error": "MULTIPLE_MATCHES",
            "message": "Es gibt mehrere Termine an diesem Datum. Bitte nennen Sie "
            "zusätzlich Ihre Telefonnummer zur eindeutigen Zuordnung.",
        }

    return {
        "success": False,
        "error": "NO_APPOINTMENT_FOUND",
        "message": "Zu dieser Telefonnummer wurde kein Termin gefunden.",
    }


# ─── changeAppointment ───────────────────────────────────────────────────────
def change_appointment(org_id: str, payload: ChangeAppointmentRequest) -> dict:
    client = get_service_client()
    customer = _find_customer_by_phone(
        client, org_id, payload.phone_number or payload.caller_number
    )
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
        return {
            "success": False,
            "error": "NO_APPOINTMENT_FOUND",
            "message": "Zu Ihren Angaben wurde kein Termin gefunden.",
        }

    now = now_berlin()
    rows = (
        client.table("appointments")
        .select("id, scheduled_at")
        .eq("org_id", org_id)
        .eq("customer_id", customer["id"])
        .in_("status", ["pending", "confirmed"])
        .gte("scheduled_at", now.isoformat())
        .order("scheduled_at")
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return {
            "success": False,
            "error": "NO_APPOINTMENT_FOUND",
            "message": "Es wurde kein bevorstehender Termin gefunden.",
        }
    appt = rows[0]

    new_dt = parse_when(payload.new_date, payload.new_time)
    if new_dt is None:
        return {
            "success": False,
            "error": "INVALID_DATE",
            "message": "Ich konnte das neue Datum nicht verstehen. Bitte nennen Sie "
            "es noch einmal.",
        }

    number = gen_inquiry_number(client, org_id)
    change = (
        client.table("inquiries")
        .insert(
            {
                "org_id": org_id,
                "customer_id": customer["id"],
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
    try:
        client.table("appointments").update(
            {
                "customer_proposed_start_time": new_dt.isoformat(),
                "customer_proposed_at": now_berlin().isoformat(),
                "customer_proposal_source": "agent_call",
            }
        ).eq("org_id", org_id).eq("id", appt["id"]).execute()
    except Exception:  # pragma: no cover — never break the live change flow
        pass
    return {
        "success": True,
        "changeRequestId": change["id"],
        "originalDatetime": appt["scheduled_at"],
        "requestedDatetime": new_dt.isoformat(),
        "status": "PENDING_CONFIRMATION",
        "message": f"Ihre Umbuchungsanfrage für {fmt_date(new_dt)} um "
        f"{fmt_time(new_dt)} Uhr wurde aufgenommen. Sie werden zur Bestätigung "
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
