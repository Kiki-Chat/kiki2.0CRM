import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.services.entitlements import require_entitlement
from app.db.supabase_client import get_service_client
from app.schemas.admin import AppointmentCreate, AppointmentPatch
from app.services import calendar_sync, employee_calendar_sync
from app.services.appointment_notify import notify_appointment_outcome
from app.services.appointments import import_ics
from app.services.common import enforce_self_assignment, format_address, validate_fk_in_org
from app.services.projects import maybe_create_case_for_appointment

router = APIRouter(prefix="/api/appointments", tags=["appointments"], dependencies=[Depends(require_entitlement("calendar"))])

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_past(iso_ts: str | None) -> bool:
    """True if the ISO timestamp parses to a moment already elapsed. Unparseable
    or empty → False (don't block on a value we can't read)."""
    if not iso_ts:
        return False
    try:
        dt = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt <= datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return False


def _sync_location_to_customer(
    client, org_id: str, customer_id: str | None, location: str | None
) -> None:
    """Keep the customer's address in lock-step with an appointment's Ort —
    they are the same physical place. When a location is entered/changed on an
    appointment that has a customer, write it into the customer's `address`
    (same {"raw": …} jsonb shape) so the address shows up everywhere it's used.

    No-op without a customer or without a location, and never clears an address
    (an empty Ort leaves the customer's address untouched). Writes only when the
    value actually differs, so the common "Ort prefilled from the address"
    create/edit path stays a no-op."""
    loc = (location or "").strip()
    if not customer_id or not loc:
        return
    rows = (
        client.table("customers")
        .select("address")
        .eq("org_id", org_id)
        .eq("id", customer_id)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        return
    current = (format_address(rows[0].get("address")) or "").strip()
    if current == loc:
        return
    client.table("customers").update(
        {"address": {"raw": loc}, "updated_at": "now()"}
    ).eq("org_id", org_id).eq("id", customer_id).execute()


def _get_appointment(org_id: str, appointment_id: str) -> dict | None:
    """Tenant-scoped fetch — every action route uses this before mutating so
    cross-org IDs return 404 instead of silently no-op'ing."""
    rows = (
        get_service_client()
        .table("appointments")
        .select("*")
        .eq("org_id", org_id)
        .eq("id", appointment_id)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


def _push_appt_to_employee(org_id: str, appointment_id: str) -> None:
    """Best-effort: write a confirmed appointment into the assigned employee's own
    Google calendar (so the job shows on their phone). No-op when the employee
    hasn't connected a calendar; never raises."""
    employee_calendar_sync.push_appointment_to_employee(org_id, appointment_id)


def _sync_employee_calendar_after_patch(
    org_id: str, appointment_id: str, prev: dict | None, appt: dict
) -> None:
    """Keep the assigned employee's Google event in step after an edit: remove it
    from a previous assignee on reassignment, and re-push on reassignment / time
    change for a confirmed appointment. Best-effort."""
    try:
        prev_emp = (prev or {}).get("assigned_employee_id")
        new_emp = (appt or {}).get("assigned_employee_id")
        time_changed = (prev or {}).get("scheduled_at") != (appt or {}).get("scheduled_at")
        if prev_emp and prev_emp != new_emp:
            employee_calendar_sync.remove_appointment_from_employee(
                org_id, appointment_id, employee_id=prev_emp
            )
        if appt.get("status") == "confirmed" and new_emp and (prev_emp != new_emp or time_changed):
            employee_calendar_sync.remove_appointment_from_employee(
                org_id, appointment_id, employee_id=new_emp
            )
            employee_calendar_sync.push_appointment_to_employee(org_id, appointment_id)
    except Exception as exc:  # noqa: BLE001 — best-effort
        log.warning("employee calendar sync after patch failed appt=%s: %s", appointment_id, exc)


def _list(org_id: str, frm: str | None, to: str | None) -> list[dict]:
    client = get_service_client()
    query = (
        client.table("appointments")
        .select(
            "id, title, scheduled_at, duration_minutes, status, category, color, "
            "location, notes, customer_id, inquiry_id, assigned_employee_id, "
            "vehicle_id, tool_id, source, google_event_id, "
            # Linking for the tentative "Vorschlag" events (agent-booked pending
            # slots surface on the calendar and deep-link back to their call/Fall).
            "source_conversation_id, case_id"
        )
        .eq("org_id", org_id)
    )
    if frm:
        query = query.gte("scheduled_at", frm)
    if to:
        query = query.lt("scheduled_at", to)
    appts = query.order("scheduled_at").execute().data or []

    customer_ids = {a["customer_id"] for a in appts if a.get("customer_id")}
    employee_ids = {a["assigned_employee_id"] for a in appts if a.get("assigned_employee_id")}

    customers: dict[str, dict] = {}
    if customer_ids:
        for c in (
            client.table("customers")
            .select("id, full_name, phone, address")
            .eq("org_id", org_id)
            .in_("id", list(customer_ids))
            .execute()
            .data
            or []
        ):
            customers[c["id"]] = c
    employees: dict[str, str] = {}
    if employee_ids:
        for e in (
            client.table("employees")
            .select("id, display_name")
            .eq("org_id", org_id)
            .in_("id", list(employee_ids))
            .execute()
            .data
            or []
        ):
            employees[e["id"]] = e.get("display_name")

    # Resolve a call_id for PENDING ("Vorschlag") appointments so the calendar's
    # tentative event can deep-link to the originating call. Preferred path: the
    # linked inquiry's call_id; else the agent-booking conversation
    # (source_conversation_id -> calls.elevenlabs_conversation_id). Bounded to the
    # pending rows in the visible window so it's a cheap pair of lookups.
    pending = [a for a in appts if a.get("status") == "pending"]
    call_by_appt: dict[str, str] = {}
    if pending:
        inq_ids = [a["inquiry_id"] for a in pending if a.get("inquiry_id")]
        conv_ids = [a["source_conversation_id"] for a in pending if a.get("source_conversation_id")]
        inq_call: dict[str, str] = {}
        if inq_ids:
            for row in (
                client.table("inquiries").select("id, call_id")
                .eq("org_id", org_id).in_("id", list(set(inq_ids))).execute().data or []
            ):
                if row.get("call_id"):
                    inq_call[row["id"]] = row["call_id"]
        conv_call: dict[str, str] = {}
        if conv_ids:
            for row in (
                client.table("calls").select("id, elevenlabs_conversation_id")
                .eq("org_id", org_id).in_("elevenlabs_conversation_id", list(set(conv_ids)))
                .execute().data or []
            ):
                if row.get("elevenlabs_conversation_id"):
                    conv_call[row["elevenlabs_conversation_id"]] = row["id"]
        for a in pending:
            cid = inq_call.get(a.get("inquiry_id")) or conv_call.get(a.get("source_conversation_id"))
            if cid:
                call_by_appt[a["id"]] = cid

    for a in appts:
        cust = customers.get(a.get("customer_id"))
        a["customer_name"] = cust.get("full_name") if cust else None
        a["customer_phone"] = cust.get("phone") if cust else None
        a["customer_address"] = format_address(cust.get("address")) if cust else None
        a["employee_name"] = employees.get(a.get("assigned_employee_id"))
        a["call_id"] = call_by_appt.get(a["id"])
    return appts


@router.get("")
async def list_appointments(
    frm: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    user: CurrentUser = Depends(require_org),
) -> list[dict]:
    return await run_in_threadpool(_list, user.org_id, frm, to)


def _create(user: CurrentUser, payload: AppointmentCreate) -> dict:
    org_id = user.org_id
    client = get_service_client()
    # FK hardening: every foreign-key id in the body must belong to this org.
    validate_fk_in_org(client, table="customers", fk_id=payload.customer_id, org_id=org_id, label="Kunde")
    validate_fk_in_org(client, table="cases", fk_id=payload.case_id, org_id=org_id, label="Vorgang")
    validate_fk_in_org(client, table="inquiries", fk_id=payload.inquiry_id, org_id=org_id, label="Anfrage")
    validate_fk_in_org(
        client, table="employees", fk_id=payload.assigned_employee_id,
        org_id=org_id, label="Mitarbeiter", require_active=True,
    )
    # A plain employee may only create work assigned to themselves.
    enforce_self_assignment(
        client, user=user, current_assignee_id=None,
        new_assignee_id=payload.assigned_employee_id,
    )
    # No backdating: a freshly-created appointment must lie in the future. The
    # calendar lets you click a past day/slot, and the agent could propose a
    # stale time — both would otherwise mint an appointment already in the past.
    # (ICS import has its own path and is intentionally exempt — it carries real
    # historical events.)
    if _is_past(payload.scheduled_at):
        raise HTTPException(
            status_code=422,
            detail=(
                "Ein Termin kann nicht in der Vergangenheit liegen. "
                "Bitte Datum und Uhrzeit in der Zukunft wählen."
            ),
        )
    # Default to 'confirmed' (calendar / planning-board). The call-log create modal
    # passes 'pending' so the new appointment enters the open-action confirmation
    # stage. Only these two are accepted from the create path.
    status = payload.status if payload.status in ("pending", "confirmed") else "confirmed"
    row = {
        "org_id": org_id,
        "customer_id": payload.customer_id,
        "inquiry_id": payload.inquiry_id,
        "case_id": payload.case_id,
        "title": payload.title or "Termin",
        "scheduled_at": payload.scheduled_at,
        "duration_minutes": payload.duration_minutes,
        "location": {"raw": payload.location} if payload.location else None,
        "category": payload.category,
        "color": payload.color,
        "assigned_employee_id": payload.assigned_employee_id,
        "status": status,
        "notes": payload.notes,
    }
    created = client.table("appointments").insert(row).execute().data[0]
    # Ort → Kundenadresse: a location entered here is the customer's address.
    _sync_location_to_customer(client, org_id, payload.customer_id, payload.location)
    return created


@router.post("")
async def create_appointment(
    payload: AppointmentCreate, user: CurrentUser = Depends(require_org)
) -> dict:
    return await run_in_threadpool(_create, user, payload)


@router.post("/import-ics")
async def import_appointments_ics(
    file: UploadFile = File(...), user: CurrentUser = Depends(require_org)
) -> dict:
    content = await file.read()
    return await run_in_threadpool(import_ics, user.org_id, content)


def _patch(user: CurrentUser, appointment_id: str, payload: AppointmentPatch) -> dict | None:
    org_id = user.org_id
    client = get_service_client()
    # FK hardening: employee / vehicle / tool reassignment must stay same-org.
    validate_fk_in_org(
        client, table="employees", fk_id=payload.assigned_employee_id,
        org_id=org_id, label="Mitarbeiter", require_active=True,
    )
    validate_fk_in_org(client, table="vehicles", fk_id=payload.vehicle_id, org_id=org_id, label="Fahrzeug")
    validate_fk_in_org(client, table="tools", fk_id=payload.tool_id, org_id=org_id, label="Werkzeug")
    fields = payload.model_dump(exclude_unset=True)
    # A plain employee may not reassign an appointment to a colleague.
    if "assigned_employee_id" in fields:
        cur = (
            client.table("appointments")
            .select("assigned_employee_id")
            .eq("org_id", org_id)
            .eq("id", appointment_id)
            .limit(1)
            .execute()
            .data
        )
        enforce_self_assignment(
            client, user=user,
            current_assignee_id=cur[0].get("assigned_employee_id") if cur else None,
            new_assignee_id=fields.get("assigned_employee_id"),
        )
    if "location" in fields and isinstance(fields["location"], str):
        fields["location"] = {"raw": fields["location"]}
    # A manual time edit (calendar "Verschieben / Bearbeiten") resolves any open
    # reschedule counter-proposal: clear the customer_proposed_* markers so the
    # call card / timeline stop showing a stale "verschoben / Kundenvorschlag" tag
    # once the admin has set the new time themselves.
    if "scheduled_at" in fields:
        fields.setdefault("customer_proposed_start_time", None)
        fields.setdefault("customer_proposed_end_time", None)
        fields.setdefault("customer_proposed_at", None)
        fields.setdefault("customer_proposal_source", None)
        # Record the human reschedule so it shows in the Verlauf timeline
        # (appointment_rescheduled) — a calendar time edit was previously silent.
        fields["rescheduled_at"] = _now_iso()
    if not fields:
        rows = (
            client.table("appointments").select("*").eq("org_id", org_id)
            .eq("id", appointment_id).limit(1).execute().data
        )
        return rows[0] if rows else None
    res = (
        client.table("appointments").update(fields).eq("org_id", org_id)
        .eq("id", appointment_id).execute()
    )
    row = res.data[0] if res.data else None
    # Ort → Kundenadresse: an edited location syncs back to the customer's
    # address (same place). The location was normalised to {"raw": …} above;
    # flatten it and write it through when the appointment has a customer.
    if row and "location" in fields:
        _sync_location_to_customer(
            client, org_id, row.get("customer_id"), format_address(fields["location"])
        )
    return row


@router.patch("/{appointment_id}")
async def update_appointment(
    appointment_id: str, payload: AppointmentPatch, user: CurrentUser = Depends(require_org)
) -> dict:
    # Capture pre-edit state so we can keep the employee's Google calendar in step
    # when the assignee or the time changes (per-employee push).
    prev = await run_in_threadpool(_get_appointment, user.org_id, appointment_id)
    appt = await run_in_threadpool(_patch, user, appointment_id, payload)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    # If a human moved the time of an ALREADY-CONFIRMED appointment (calendar
    # "Verschieben/Bearbeiten"), tell the customer about the new slot — the same
    # reschedule confirmation call+email the in-call "Alternative vorschlagen" fires.
    # Best-effort, gated by the master toggle + scope guard. (Pending appointments
    # are skipped: the customer was never told a confirmed time yet.)
    changed = payload.model_dump(exclude_unset=True)
    if "scheduled_at" in changed and appt.get("status") == "confirmed":
        appt["_outbound"] = await run_in_threadpool(
            notify_appointment_outcome, user.org_id, appointment_id, "reschedule"
        )
    # If the time changed and a technician was ALREADY dispatched for this
    # appointment, send them an updated job link automatically (no-op otherwise).
    if "scheduled_at" in changed and appt.get("assigned_employee_id"):
        await run_in_threadpool(
            _maybe_resend_technician_link,
            user.org_id, appointment_id, appt.get("assigned_employee_id"),
        )
    # Keep the assigned employee's own Google calendar in step (reassign / time change).
    await run_in_threadpool(
        _sync_employee_calendar_after_patch, user.org_id, appointment_id, prev, appt
    )
    return appt


# ─── Wave 2 / Agent 2.4 — confirm / reject / propose-alternative ─────────────
# These power the OFFENE AKTIONEN appointment card on the call-detail right
# panel (see frontend/src/pages/CallLogsPage.tsx). The card renders only when
# the call's inquiry has a `status='pending'` appointment; these routes are
# the three action buttons (Bestätigen / Alternative vorschlagen / Ablehnen).
#
# Gate: every action requires the appointment to be in `pending` status. Once
# it transitions to `confirmed` / `cancelled` the card disappears, and these
# routes hard-fail 409 (state-machine violation) rather than silently no-op.
#
# Re-uses the existing status enum (pending|confirmed|cancelled|completed) —
# migration 0026 added timestamp + text columns to encode the new lifecycle
# events without widening the check constraint. See 0026 for the rationale.


class ProposeAlternativeRequest(BaseModel):
    start_time: datetime
    end_time: datetime
    note: str | None = None


class RejectAppointmentRequest(BaseModel):
    reason: str | None = None


def _confirm(org_id: str, appointment_id: str) -> dict | None:
    appt = _get_appointment(org_id, appointment_id)
    if not appt:
        return None
    # Idempotent confirm: a calendar-created appointment is already 'confirmed',
    # and a double-click or a stale open-action card can re-issue confirm. Return
    # the row unchanged (flagged so the route skips the re-notify + duplicate case
    # creation) instead of 409'ing the user. Only a genuinely un-confirmable state
    # — a cancelled/rejected/completed appointment — still hard-fails below.
    if appt.get("status") == "confirmed":
        appt["_already_confirmed"] = True
        return appt
    if appt.get("status") != "pending":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Termin kann nicht bestätigt werden — aktueller Status: "
                f"{appt.get('status')!r}. Nur ausstehende Termine sind bestätigbar."
            ),
        )
    # A confirmed appointment must have a responsible employee. Enforce here too
    # (not just in the UI) so the API can't be used to confirm an unassigned slot.
    if not appt.get("assigned_employee_id"):
        raise HTTPException(
            status_code=409,
            detail=(
                "Termin kann nicht bestätigt werden — es ist kein Mitarbeiter "
                "zugewiesen. Bitte zuerst einen Mitarbeiter zuweisen."
            ),
        )
    # …and a concrete time (tester 2026-06-11): a slot captured on a call without
    # a parseable datetime must not be confirmable — confirming fires the customer
    # call/email, which would announce an appointment with no time.
    if not appt.get("scheduled_at"):
        raise HTTPException(
            status_code=409,
            detail=(
                "Termin kann nicht bestätigt werden — es ist kein Zeitpunkt "
                "festgelegt. Bitte zuerst Datum und Uhrzeit setzen."
            ),
        )
    now = _now_iso()
    updated = (
        get_service_client()
        .table("appointments")
        .update(
            {
                "status": "confirmed",
                "confirmed_at": now,
                # Clear any stale alternative_* proposal — once confirmed we're
                # locking in the originally-proposed slot.
                "alternative_proposed_at": None,
            }
        )
        .eq("org_id", org_id)
        .eq("id", appointment_id)
        .execute()
        .data
    )
    # TODO downstream side-effects (calendar sync, customer notification email)
    # belong in their own services/handlers — kept out of v1 per scope.
    return updated[0] if updated else None


def _reject(org_id: str, appointment_id: str, reason: str | None) -> dict | None:
    appt = _get_appointment(org_id, appointment_id)
    if not appt:
        return None
    if appt.get("status") != "pending":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Termin kann nicht abgelehnt werden — aktueller Status: "
                f"{appt.get('status')!r}. Nur ausstehende Termine sind ablehnbar."
            ),
        )
    now = _now_iso()
    updated = (
        get_service_client()
        .table("appointments")
        .update(
            {
                # Re-use the existing 'cancelled' terminal status (migration 0026
                # rationale: keep the status enum stable, encode the reject vs
                # customer-cancel distinction via `rejected_at IS NOT NULL`).
                "status": "cancelled",
                "rejected_at": now,
                "rejection_reason": reason,
            }
        )
        .eq("org_id", org_id)
        .eq("id", appointment_id)
        .execute()
        .data
    )
    return updated[0] if updated else None


def _propose_alternative(
    org_id: str,
    appointment_id: str,
    payload: ProposeAlternativeRequest,
) -> dict | None:
    appt = _get_appointment(org_id, appointment_id)
    if not appt:
        return None
    if appt.get("status") != "pending":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Alternative kann nicht vorgeschlagen werden — aktueller Status: "
                f"{appt.get('status')!r}. Nur ausstehende Termine erlauben Alternativen."
            ),
        )
    now = _now_iso()
    updated = (
        get_service_client()
        .table("appointments")
        .update(
            {
                # Status stays 'pending' — the card detects the "Alternative
                # gesendet" state by reading `alternative_proposed_at`.
                "alternative_start_time": payload.start_time.isoformat(),
                "alternative_end_time": payload.end_time.isoformat(),
                "alternative_note": payload.note,
                "alternative_proposed_at": now,
            }
        )
        .eq("org_id", org_id)
        .eq("id", appointment_id)
        .execute()
        .data
    )
    return updated[0] if updated else None


@router.post("/{appointment_id}/confirm")
async def confirm_appointment(
    appointment_id: str, user: CurrentUser = Depends(require_org)
) -> dict:
    """Confirm the originally-proposed appointment slot as-is.

    Stamps `confirmed_at = now()` and flips status -> 'confirmed'. Fails 409
    if the appointment isn't currently pending (state-machine guard)."""
    appt = await run_in_threadpool(_confirm, user.org_id, appointment_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    # Already confirmed (idempotent path) — don't re-fire the customer call/email
    # or re-create the case. Just hand back the current row so the UI settles.
    if appt.get("_already_confirmed"):
        return appt
    # Back-office automation: auto-create a case (+ planning-board presence),
    # gated by agent_configs.projects_enabled/level. Best-effort, non-blocking.
    case = await run_in_threadpool(
        maybe_create_case_for_appointment, user.org_id, appt, user.id
    )
    if case:
        appt["case_id"] = case["id"]
    # Best-effort outbound side-effect (call + email) — gated by the org's master
    # Appointment-Reminders toggle, scope-guarded, non-blocking (a failure never
    # rolls back the already-committed confirmation).
    appt["_outbound"] = await run_in_threadpool(
        notify_appointment_outcome, user.org_id, appointment_id, "confirm"
    )
    # Push the confirmed job into the assigned employee's own Google calendar
    # (shows on their phone). Best-effort.
    await run_in_threadpool(_push_appt_to_employee, user.org_id, appointment_id)
    return appt


@router.post("/{appointment_id}/reject")
async def reject_appointment(
    appointment_id: str,
    payload: RejectAppointmentRequest | None = None,
    user: CurrentUser = Depends(require_org),
) -> dict:
    """Reject the proposed appointment without offering an alternative.

    Stamps `rejected_at = now()` + optional `rejection_reason`, flips status
    -> 'cancelled' (re-uses the existing terminal status). The discriminator
    between this and a customer-initiated cancel is `rejected_at IS NOT NULL`.
    Fails 409 if the appointment isn't currently pending."""
    reason = payload.reason if payload else None
    appt = await run_in_threadpool(_reject, user.org_id, appointment_id, reason)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    # Best-effort outbound side-effect — "Ablehnen" maps to the cancellation
    # occasion (call + email). Non-blocking; gated by the master toggle.
    appt["_outbound"] = await run_in_threadpool(
        notify_appointment_outcome, user.org_id, appointment_id, "cancel"
    )
    return appt


# ─── Pending-appointment lookup for the right-panel card ─────────────────────
# The OFFENE AKTIONEN card needs to know the single pending appointment that
# this call should display (if any). It's keyed by the call's inquiry — every
# call has at most one inquiry (see services/inquiries.py::ensure_call_inquiry),
# and the appointment card only ever shows the FIRST pending appointment on
# that inquiry (multiple pending appointments per inquiry is degenerate; we
# pick the earliest scheduled_at as a deterministic tiebreaker).
#
# Returns `{appointment: AppointmentPreview | null}` so the frontend can
# distinguish "no pending appointment" (200 with null) from "call not found"
# (404). Keeping it as a separate endpoint (rather than extending the call
# detail) avoids stepping on Agent 2.1's parallel changes to calls.py.


def _pending_for_call(org_id: str, call_id: str) -> dict | None:
    client = get_service_client()

    # Confirm the call exists in this tenant — otherwise 404 instead of
    # silently returning null (matches the existing 404 semantic on /api/calls/{id}).
    call_rows = (
        client.table("calls")
        .select("id, elevenlabs_conversation_id, summary")
        .eq("org_id", org_id)
        .eq("id", call_id)
        .limit(1)
        .execute()
        .data
    )
    if not call_rows:
        return {"_not_found": True}
    conv_id = call_rows[0].get("elevenlabs_conversation_id")
    call_summary = call_rows[0].get("summary")

    # The call's own inquiry (created at post-call ingest).
    inquiry_rows = (
        client.table("inquiries")
        .select("id")
        .eq("org_id", org_id)
        .eq("call_id", call_id)
        .neq("status", "deleted")
        .order("created_at")
        .limit(1)
        .execute()
        .data
    )
    inquiry_id = inquiry_rows[0]["id"] if inquiry_rows else None

    # An appointment belongs to "this call" if it's on the call's inquiry OR the
    # agent booked it during this conversation (source_conversation_id) —
    # hk_bookAppointment creates a SEPARATE inquiry, so the conversation link is
    # what surfaces an agent-booked appointment on its call.
    ors = []
    if inquiry_id:
        ors.append(f"inquiry_id.eq.{inquiry_id}")
    if conv_id:
        ors.append(f"source_conversation_id.eq.{conv_id}")
    if not ors:
        return {"appointment": None}

    appt_rows = (
        client.table("appointments")
        .select(
            "id, title, scheduled_at, duration_minutes, status, category, "
            "color, location, notes, customer_id, inquiry_id, "
            "assigned_employee_id, confirmed_at, rejected_at, rejection_reason, "
            "cancelled_at, rescheduled_at, "
            "alternative_start_time, alternative_end_time, alternative_note, "
            "alternative_proposed_at, customer_proposed_start_time, "
            "customer_proposed_end_time, customer_proposed_at, customer_proposal_source, "
            "reschedule_replace_intent"
        )
        .eq("org_id", org_id)
        .eq("status", "pending")
        .or_(",".join(ors))
        .order("scheduled_at")
        .execute()
        .data
        or []
    )
    # Only PENDING shows in the card — a request awaiting a human decision. Once
    # confirmed it leaves the card and appears on the calendar (and confirming
    # there fires the outbound call+email).
    appt = appt_rows[0] if appt_rows else None
    if appt is None:
        # Persistence: once a decision is made the appointment leaves the pending set,
        # but the card must STAY as a colour-coded status badge (Bestätigt / Storniert /
        # Verschoben — never silently vanish). Fall back to the most-recent CONFIRMED or
        # CANCELLED appointment on this call; the card reads confirmed_at / cancelled_at /
        # rejected_at to render the locked done-state (no action buttons).
        done_rows = (
            client.table("appointments")
            .select(
                "id, title, scheduled_at, duration_minutes, status, category, "
                "color, location, notes, customer_id, inquiry_id, "
                "assigned_employee_id, confirmed_at, rejected_at, rejection_reason, "
                "alternative_start_time, alternative_end_time, alternative_note, "
                "alternative_proposed_at, customer_proposed_start_time, "
                "customer_proposed_end_time, customer_proposed_at, customer_proposal_source, "
                "reschedule_replace_intent"
            )
            .eq("org_id", org_id)
            .in_("status", ["confirmed", "cancelled"])
            .or_(",".join(ors))
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        appt = done_rows[0] if done_rows else None
    if appt is not None:
        # Surface the call's summary as the (up-to-)2-line issue description.
        appt["issue_summary"] = call_summary
    return {"appointment": appt}


@router.get("/by-call/{call_id}/pending")
async def get_pending_appointment_for_call(
    call_id: str, user: CurrentUser = Depends(require_org)
) -> dict:
    """Return the single pending appointment for this call's inquiry (or null).

    Powers the OFFENE AKTIONEN card on the call-detail right panel. The
    appointment card only renders when the response has `appointment != null`."""
    result = await run_in_threadpool(_pending_for_call, user.org_id, call_id)
    if result.get("_not_found"):
        raise HTTPException(status_code=404, detail="Call not found")
    return result


@router.post("/{appointment_id}/propose-alternative")
async def propose_alternative_appointment(
    appointment_id: str,
    payload: ProposeAlternativeRequest,
    user: CurrentUser = Depends(require_org),
) -> dict:
    """Propose a different time slot back to the customer.

    Stores the alternative in `alternative_start_time`/`alternative_end_time`/
    `alternative_note`, stamps `alternative_proposed_at = now()`. Status stays
    'pending' — the appointment card flips to "Alternative gesendet" by reading
    `alternative_proposed_at`. Validates that start < end and both are in the
    future. Fails 409 if the appointment isn't currently pending."""
    if payload.start_time >= payload.end_time:
        raise HTTPException(
            status_code=422,
            detail="start_time muss vor end_time liegen.",
        )
    now = datetime.now(timezone.utc)
    if payload.start_time <= now:
        raise HTTPException(
            status_code=422,
            detail="Alternative muss in der Zukunft liegen.",
        )
    appt = await run_in_threadpool(
        _propose_alternative, user.org_id, appointment_id, payload
    )
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    # Best-effort outbound side-effect — propose-alternative maps to the
    # reschedule occasion: the call proposes the new time; if the customer
    # counters, the agent records it back as a customer proposal for approval.
    appt["_outbound"] = await run_in_threadpool(
        notify_appointment_outcome, user.org_id, appointment_id, "reschedule"
    )
    return appt


# ─── Reschedule counter-proposal: approve / decline (human-in-the-loop) ──────
# When a customer agrees to a slot on an outbound RESCHEDULE call, the agent
# records it via hk_changeAppointment, which stamps customer_proposed_* on the
# appointment (see services/appointments.change_appointment). The action card
# then shows "Kunde schlägt {time} vor". Approving applies the slot, confirms the
# appointment, and fires the final appointment_confirmation call+email; declining
# clears the proposal and leaves the appointment unchanged.
def _approve_proposal(org_id: str, appointment_id: str) -> dict | None:
    appt = _get_appointment(org_id, appointment_id)
    if not appt:
        return None
    # Status gate (bug #3): never resurrect a closed appointment. A cancelled/
    # rejected row can still carry a stale customer_proposed_* (e.g. cancelled
    # while a proposal was pending); approving it would flip it back to
    # 'confirmed' AND fire a confirmation call for an appointment the business
    # already killed. The UI also hides the button on done rows — this is the
    # server-side backstop.
    if (appt.get("status") or "") in ("cancelled", "rejected"):
        raise HTTPException(
            status_code=409,
            detail="Dieser Termin ist bereits abgeschlossen und kann nicht mehr genehmigt werden.",
        )
    new_start = appt.get("customer_proposed_start_time")
    if not new_start:
        raise HTTPException(
            status_code=409,
            detail="Kein Kundenvorschlag vorhanden, der genehmigt werden könnte.",
        )
    # Don't confirm (and call the customer about) a slot that is already in the
    # past — a stale proposal sitting unactioned past its time.
    if _is_past(new_start):
        raise HTTPException(
            status_code=409,
            detail="Der vorgeschlagene Termin liegt in der Vergangenheit und kann nicht mehr bestätigt werden.",
        )
    updated = (
        get_service_client()
        .table("appointments")
        .update(
            {
                "scheduled_at": new_start,
                "status": "confirmed",
                "confirmed_at": _now_iso(),
                # consume the proposal + clear any stale business-proposed alternative
                "customer_proposed_start_time": None,
                "customer_proposed_end_time": None,
                "customer_proposed_at": None,
                "customer_proposal_source": None,
                "alternative_proposed_at": None,
                # the reschedule is committed → the safety timer no longer applies
                "reschedule_expires_at": None,
                "reschedule_replace_intent": None,
            }
        )
        .eq("org_id", org_id)
        .eq("id", appointment_id)
        .execute()
        .data
    )
    row = updated[0] if updated else None
    # Keep Google in sync (bug #4): the slot moved, so the pushed event must move
    # too — otherwise field staff working off Google show up at the OLD time.
    # delete_google_event has no events.update primitive (push is insert-only),
    # so move = delete the old event + re-insert at the new time. Best-effort.
    if row and appt.get("google_event_id"):
        try:
            calendar_sync.delete_google_event(org_id, appt["google_event_id"])
            get_service_client().table("appointments").update(
                {"google_event_id": None}
            ).eq("org_id", org_id).eq("id", appointment_id).execute()
            calendar_sync.push_crm_event_to_google(org_id, appointment_id)
        except Exception:  # noqa: BLE001 — Google sync must not block the approval
            pass
    return row


def _decline_proposal(org_id: str, appointment_id: str) -> dict | None:
    """Decline the customer's reschedule. If the customer abandoned the old slot
    (reschedule_replace_intent), declining the MOVE means there's nothing left to
    keep → cancel the appointment (reversible) so the slot is freed and the
    customer can be told. Otherwise the original simply stays as it was."""
    appt = _get_appointment(org_id, appointment_id)
    if not appt:
        return None
    replace_intent = bool(appt.get("reschedule_replace_intent"))
    payload: dict = {
        "customer_proposed_start_time": None,
        "customer_proposed_end_time": None,
        "customer_proposed_at": None,
        "customer_proposal_source": None,
        "reschedule_expires_at": None,
        "reschedule_replace_intent": None,
    }
    if replace_intent:
        payload["status"] = "cancelled"
        payload["cancelled_at"] = _now_iso()
        # Free the slot on Google too (bug #4) — same contract as _cancel: the
        # CRM cancel proceeds regardless of the Google result.
        if appt.get("google_event_id"):
            try:
                calendar_sync.delete_google_event(org_id, appt["google_event_id"])
            except Exception:  # noqa: BLE001 — best-effort, never blocks the cancel
                pass
            payload["google_event_id"] = None
    updated = (
        get_service_client()
        .table("appointments")
        .update(payload)
        .eq("org_id", org_id)
        .eq("id", appointment_id)
        .execute()
        .data
    )
    if not updated:
        return None
    row = updated[0]
    # Signal to the route whether a cancellation notification should fire.
    row["_replace_cancelled"] = replace_intent
    return row


@router.post("/{appointment_id}/approve-proposal")
async def approve_customer_proposal(
    appointment_id: str, user: CurrentUser = Depends(require_org)
) -> dict:
    """Approve the customer's counter-proposed slot: set scheduled_at to it,
    confirm the appointment, and fire the appointment_confirmation call+email."""
    appt = await run_in_threadpool(_approve_proposal, user.org_id, appointment_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    appt["_outbound"] = await run_in_threadpool(
        notify_appointment_outcome, user.org_id, appointment_id, "confirm"
    )
    # Push the now-confirmed job (new time) into the assigned employee's own Google
    # calendar. Best-effort. _approve_proposal changed the time, so clear any prior
    # pushed event first, then push the fresh one.
    emp_id = appt.get("assigned_employee_id")
    if emp_id:
        await run_in_threadpool(
            employee_calendar_sync.remove_appointment_from_employee,
            user.org_id, appointment_id, employee_id=emp_id,
        )
    await run_in_threadpool(_push_appt_to_employee, user.org_id, appointment_id)
    return appt


@router.post("/{appointment_id}/decline-proposal")
async def decline_customer_proposal(
    appointment_id: str, user: CurrentUser = Depends(require_org)
) -> dict:
    """Decline the customer's reschedule. If the customer had abandoned the old
    slot, the appointment is cancelled (slot freed) and the customer is notified
    of the cancellation; otherwise the original stays and nothing is sent."""
    appt = await run_in_threadpool(_decline_proposal, user.org_id, appointment_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.get("_replace_cancelled"):
        appt["_outbound"] = await run_in_threadpool(
            notify_appointment_outcome, user.org_id, appointment_id, "cancel"
        )
    return appt


# ─── Technician dispatch (tokenized job link) ────────────────────────────────
class DispatchTechnicianPayload(BaseModel):
    employee_id: str


def _build_job_email(url: str, emp: dict, job: dict) -> tuple[str, str]:
    """German plain-text + HTML body for a technician job-link email."""
    a, c = job["appointment"], job["customer"]
    when = (a.get("scheduled_at") or "").replace("T", " ")[:16]
    lines = [
        f"Hallo {emp.get('display_name') or ''},".strip(),
        "",
        f"für dich wurde ein Einsatz geplant{' bei ' + c['name'] if c.get('name') else ''}:",
        f"• Termin: {a.get('title') or 'Termin'} — {when} ({a.get('duration_minutes') or 60} Min)",
    ]
    if c.get("address"):
        lines.append(f"• Adresse: {c['address']}")
    if c.get("phone"):
        lines.append(f"• Telefon: {c['phone']}")
    if a.get("notes"):
        lines.append(f"• Hinweise: {a['notes']}")
    lines += [
        "",
        "Über diesen Link startest du den Einsatz und füllst danach den kurzen Einsatzbericht aus (inkl. Fotos):",
        url,
        "",
        "Der Link gilt nur für diesen Einsatz.",
    ]
    body_text = "\n".join(lines)
    body_html = "<p>" + "<br>".join(
        line.replace(url, f'<a href="{url}">{url}</a>') for line in lines
    ) + "</p>"
    return body_text, body_html


def _send_technician_job(client, org_id: str, appointment_id: str, emp: dict) -> dict:
    """Create a fresh tokenized job link for ``emp`` on this appointment and email
    it — ``create_job_link`` revokes any prior un-submitted link for the same
    appointment. Shared by the manual dispatch AND the auto-resend on reschedule.
    Returns ``{url, email_status}``; raises ``technician_jobs.JobLinkError`` if the
    link can't be created."""
    from app.services import technician_jobs
    from app.services.email_send import send_email

    link = technician_jobs.create_job_link(
        org_id=org_id, appointment_id=appointment_id, employee_id=emp["id"]
    )
    url = technician_jobs.job_link_url(link["token"])
    job = technician_jobs.get_job_for_token(link["token"])
    a = job["appointment"]
    when = (a.get("scheduled_at") or "").replace("T", " ")[:16]
    body_text, body_html = _build_job_email(url, emp, job)
    email_status = "sent"
    try:
        send_email(
            org_id=org_id, to_email=emp["email"].strip(),
            subject=f"Neuer Einsatz: {a.get('title') or 'Termin'} — {when}",
            body_html=body_html, body_text=body_text,
        )
    except Exception:  # noqa: BLE001 — link still works; surface the failure
        email_status = "failed"
    client.table("technician_job_links").update({"email_status": email_status}).eq(
        "id", link["id"]
    ).execute()
    return {"url": url, "email_status": email_status}


def _appt_window(appt: dict):
    """(start, end) datetimes for an appointment row, or (None, None) when it has
    no parseable time. Used for the technician availability guard."""
    from datetime import datetime, timedelta

    raw = appt.get("scheduled_at")
    if not raw:
        return None, None
    try:
        start = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None, None
    return start, start + timedelta(minutes=int(appt.get("duration_minutes") or 60))


def _dispatch_technician(user: CurrentUser, appointment_id: str, employee_id: str) -> dict:
    from app.services import availability, technician_jobs

    client = get_service_client()
    emp_rows = (
        client.table("employees").select("id, display_name, email, is_technician")
        .eq("org_id", user.org_id).eq("id", employee_id).limit(1).execute().data
    )
    emp = emp_rows[0] if emp_rows else None
    # Dispatch is technician-only (AUTH-029): guard BEFORE we assign so a
    # non-technician is never even pinned to the appointment.
    if not emp or not emp.get("is_technician"):
        raise HTTPException(
            status_code=422,
            detail="Dieser Mitarbeiter ist nicht als Techniker hinterlegt.",
        )
    # Availability guard (phase 1.5): never dispatch a technician who is already on
    # another job at this slot. Exclude THIS appointment (it is about to become
    # theirs) so a re-dispatch to the same technician isn't a self-conflict.
    appt_row = _get_appointment(user.org_id, appointment_id)
    if not appt_row:
        raise HTTPException(status_code=404, detail="Appointment not found")
    start, end = _appt_window(appt_row)
    if start and not availability.is_free(
        client, user.org_id, employee_id, start, end,
        exclude_appointment_ids={appointment_id},
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"{emp.get('display_name') or 'Dieser Techniker'} ist zu diesem "
                "Zeitpunkt bereits verplant. Bitte einen verfügbaren Techniker wählen."
            ),
        )
    # Assign via the normal patch path: FK hardening + self-assignment rules.
    appt = _patch(user, appointment_id, AppointmentPatch(assigned_employee_id=employee_id))
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if not (emp.get("email") or "").strip():
        raise HTTPException(
            status_code=422,
            detail="Dieser Mitarbeiter hat keine E-Mail-Adresse hinterlegt — bitte zuerst unter Mitarbeiter ergänzen.",
        )
    try:
        res = _send_technician_job(client, user.org_id, appointment_id, emp)
    except technician_jobs.JobLinkError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "success": True,
        "link_url": res["url"],
        "email_status": res["email_status"],
        "appointment": appt,
    }


def _maybe_resend_technician_link(org_id: str, appointment_id: str, employee_id: str | None) -> None:
    """After a reschedule/edit, auto-send an UPDATED job link to the technician —
    but ONLY if one was already dispatched for this appointment (a non-revoked link
    exists). Best-effort: a resend failure must never fail the reschedule itself."""
    if not employee_id:
        return
    try:
        from app.services import technician_jobs  # noqa: F401 — JobLinkError surface

        client = get_service_client()
        rows = (
            client.table("employees").select("id, display_name, email, is_technician")
            .eq("org_id", org_id).eq("id", employee_id).limit(1).execute().data
        )
        emp = rows[0] if rows else None
        if not emp or not emp.get("is_technician") or not (emp.get("email") or "").strip():
            return
        prior = (
            client.table("technician_job_links").select("id")
            .eq("org_id", org_id).eq("appointment_id", appointment_id)
            .is_("revoked_at", "null").limit(1).execute().data
        )
        if not prior:
            return  # technician never dispatched for this appointment → nothing to resend
        _send_technician_job(client, org_id, appointment_id, emp)
    except Exception as exc:  # noqa: BLE001 — reschedule must never fail on a resend
        log.warning("technician link auto-resend failed (appt=%s): %s", appointment_id, exc)


@router.post("/{appointment_id}/dispatch-technician")
async def dispatch_technician(
    appointment_id: str,
    payload: DispatchTechnicianPayload,
    user: CurrentUser = Depends(require_org),
) -> dict:
    """Assign a technician AND send them the tokenized job link by email.
    Lives on the appointment (confirmation step) — NOT on the call log."""
    return await run_in_threadpool(_dispatch_technician, user, appointment_id, payload.employee_id)


def _available_technicians(org_id: str, appointment_id: str) -> list[dict] | None:
    """Technicians ranked for THIS appointment's slot: available first, then
    fewest open tickets, then name. Each carries ``available`` + ``open_tickets``
    so the dispatch picker can show 'verfügbar' vs 'verplant' instead of letting
    the admin pick a clashing technician (phase 1.5). ``None`` if the appointment
    is gone."""
    from app.services import assignment, availability

    client = get_service_client()
    appt = _get_appointment(org_id, appointment_id)
    if not appt:
        return None
    start, end = _appt_window(appt)
    techs = (
        client.table("employees")
        .select("id, display_name, activity_area, calendar_color")
        .eq("org_id", org_id)
        .eq("is_technician", True)
        .eq("is_active", True)
        .eq("deleted", False)
        .order("display_name")
        .execute()
        .data
        or []
    )
    ids = [t["id"] for t in techs]
    busy = (
        availability.load_busy_map(
            client, org_id, ids, start, end, exclude_appointment_ids={appointment_id}
        )
        if start
        else {}
    )
    workload = assignment.open_ticket_counts(client, org_id, ids)
    current = appt.get("assigned_employee_id")
    out = [
        {
            **t,
            "available": (True if not start else availability.slot_free(busy.get(t["id"], []), start, end)),
            "open_tickets": workload.get(t["id"], 0),
            "is_current": t["id"] == current,
        }
        for t in techs
    ]
    out.sort(key=lambda x: (not x["available"], x["open_tickets"], (x.get("display_name") or "").lower()))
    return out


@router.get("/{appointment_id}/available-technicians")
async def available_technicians(
    appointment_id: str, user: CurrentUser = Depends(require_org)
) -> list[dict]:
    """Technicians for this appointment's slot, available-first with a busy flag —
    powers the dispatch picker so an occupied technician is obvious (phase 1.5)."""
    res = await run_in_threadpool(_available_technicians, user.org_id, appointment_id)
    if res is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return res


# ─── CRM cancel / delete (propagate to Google) ───────────────────────────────
# CRM is authoritative for this direction: attempt the Google events.delete
# (best-effort) ONLY when the appointment was pushed (google_event_id set), then
# perform the CRM mutation regardless of the Google result (a failed/already-gone
# Google delete is logged, never blocks the CRM action).
def _cancel(org_id: str, appointment_id: str) -> dict | None:
    appt = _get_appointment(org_id, appointment_id)
    if not appt:
        return None
    if appt.get("google_event_id"):
        calendar_sync.delete_google_event(org_id, appt["google_event_id"])
    # Also remove it from the assigned employee's own Google calendar (push side).
    if appt.get("employee_google_event_id") and appt.get("assigned_employee_id"):
        employee_calendar_sync.remove_appointment_from_employee(
            org_id, appointment_id, employee_id=appt["assigned_employee_id"]
        )
    updated = (
        get_service_client()
        .table("appointments")
        .update({
            "status": "cancelled",
            "google_event_id": None,
            "employee_google_event_id": None,
            "cancelled_at": _now_iso(),
            # Clear any pending reschedule proposal (bug #3): a cancelled row must
            # NOT keep customer_proposed_* / the safety timer, or the approve
            # button could reappear and resurrect it.
            "customer_proposed_start_time": None,
            "customer_proposed_end_time": None,
            "customer_proposed_at": None,
            "customer_proposal_source": None,
            "reschedule_expires_at": None,
            "reschedule_replace_intent": None,
        })
        .eq("org_id", org_id)
        .eq("id", appointment_id)
        .execute()
        .data
    )
    return updated[0] if updated else None


@router.post("/{appointment_id}/cancel")
async def cancel_appointment_route(
    appointment_id: str, user: CurrentUser = Depends(require_org)
) -> dict:
    """Cancel an appointment (status='cancelled', row kept for history). If it
    was pushed to Google, delete the Google event too (best-effort) and clear the
    link. The main Kalender already hides cancelled appointments."""
    appt = await run_in_threadpool(_cancel, user.org_id, appointment_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    # Best-effort cancellation call+email (gated by the master toggle, scope-guarded).
    appt["_outbound"] = await run_in_threadpool(
        notify_appointment_outcome, user.org_id, appointment_id, "cancel"
    )
    return appt


def _delete(org_id: str, appointment_id: str) -> bool:
    appt = _get_appointment(org_id, appointment_id)
    if not appt:
        return False
    if appt.get("google_event_id"):
        calendar_sync.delete_google_event(org_id, appt["google_event_id"])
    if appt.get("employee_google_event_id") and appt.get("assigned_employee_id"):
        employee_calendar_sync.remove_appointment_from_employee(
            org_id, appointment_id, employee_id=appt["assigned_employee_id"]
        )
    get_service_client().table("appointments").delete().eq("org_id", org_id).eq(
        "id", appointment_id
    ).execute()
    return True


@router.delete("/{appointment_id}")
async def delete_appointment_route(
    appointment_id: str, user: CurrentUser = Depends(require_org)
) -> dict:
    """Hard-delete an appointment. If it was pushed to Google, delete the Google
    event first (best-effort), then remove the CRM row."""
    ok = await run_in_threadpool(_delete, user.org_id, appointment_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return {"success": True, "deleted": True}
