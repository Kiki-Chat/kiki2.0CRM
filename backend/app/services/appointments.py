"""Appointment tools: get_available_slots, book, cancel, change."""

from collections import Counter
from datetime import datetime, timedelta

from app.db.supabase_client import get_service_client
from app.schemas.tools import (
    BookAppointmentRequest,
    CancelAppointmentRequest,
    ChangeAppointmentRequest,
    GetAvailableAppointmentsRequest,
)
from app.services.common import (
    BERLIN,
    fmt_date,
    fmt_time,
    gen_inquiry_number,
    now_berlin,
    parse_when,
    slot_key,
)
from app.services.customers import get_or_create_customer

BUSINESS_START_HOUR = 8
BUSINESS_END_HOUR = 17
MAX_SLOTS = 6


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
    start_date = (now + timedelta(days=lead_days)).date()
    window_end = now + timedelta(days=lead_days + days + 1)

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

    emp = _first_employee(client, org_id)
    slots: list[dict] = []
    for offset in range(days):
        day = start_date + timedelta(days=offset)
        if day.weekday() >= 5:  # skip Sat/Sun
            continue
        for hour in range(BUSINESS_START_HOUR, BUSINESS_END_HOUR, step):
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
            if len(slots) >= MAX_SLOTS:
                break
        if len(slots) >= MAX_SLOTS:
            break

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
                "category": payload.category,
                "status": "confirmed",
                "notes": notes.strip(),
            }
        )
        .execute()
        .data[0]
    )
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
