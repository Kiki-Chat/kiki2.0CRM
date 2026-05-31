from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.schemas.admin import AppointmentCreate, AppointmentPatch
from app.services import calendar_sync
from app.services.appointments import import_ics
from app.services.common import validate_fk_in_org

router = APIRouter(prefix="/api/appointments", tags=["appointments"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _list(org_id: str, frm: str | None, to: str | None) -> list[dict]:
    client = get_service_client()
    query = (
        client.table("appointments")
        .select(
            "id, title, scheduled_at, duration_minutes, status, category, color, "
            "location, notes, customer_id, inquiry_id, assigned_employee_id, "
            "vehicle_id, tool_id, source, google_event_id"
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

    customers: dict[str, str] = {}
    if customer_ids:
        for c in (
            client.table("customers")
            .select("id, full_name")
            .eq("org_id", org_id)
            .in_("id", list(customer_ids))
            .execute()
            .data
            or []
        ):
            customers[c["id"]] = c.get("full_name")
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

    for a in appts:
        a["customer_name"] = customers.get(a.get("customer_id"))
        a["employee_name"] = employees.get(a.get("assigned_employee_id"))
    return appts


@router.get("")
async def list_appointments(
    frm: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    user: CurrentUser = Depends(require_org),
) -> list[dict]:
    return await run_in_threadpool(_list, user.org_id, frm, to)


def _create(org_id: str, payload: AppointmentCreate) -> dict:
    client = get_service_client()
    # FK hardening: every foreign-key id in the body must belong to this org.
    validate_fk_in_org(client, table="customers", fk_id=payload.customer_id, org_id=org_id, label="Kunde")
    validate_fk_in_org(client, table="projects", fk_id=payload.project_id, org_id=org_id, label="Projekt")
    validate_fk_in_org(client, table="inquiries", fk_id=payload.inquiry_id, org_id=org_id, label="Anfrage")
    validate_fk_in_org(
        client, table="employees", fk_id=payload.assigned_employee_id,
        org_id=org_id, label="Mitarbeiter", require_active=True,
    )
    row = {
        "org_id": org_id,
        "customer_id": payload.customer_id,
        "inquiry_id": payload.inquiry_id,
        "project_id": payload.project_id,
        "title": payload.title or "Termin",
        "scheduled_at": payload.scheduled_at,
        "duration_minutes": payload.duration_minutes,
        "location": {"raw": payload.location} if payload.location else None,
        "category": payload.category,
        "color": payload.color,
        "assigned_employee_id": payload.assigned_employee_id,
        "status": "confirmed",
        "notes": payload.notes,
    }
    return client.table("appointments").insert(row).execute().data[0]


@router.post("")
async def create_appointment(
    payload: AppointmentCreate, user: CurrentUser = Depends(require_org)
) -> dict:
    return await run_in_threadpool(_create, user.org_id, payload)


@router.post("/import-ics")
async def import_appointments_ics(
    file: UploadFile = File(...), user: CurrentUser = Depends(require_org)
) -> dict:
    content = await file.read()
    return await run_in_threadpool(import_ics, user.org_id, content)


def _patch(org_id: str, appointment_id: str, payload: AppointmentPatch) -> dict | None:
    client = get_service_client()
    # FK hardening: employee / vehicle / tool reassignment must stay same-org.
    validate_fk_in_org(
        client, table="employees", fk_id=payload.assigned_employee_id,
        org_id=org_id, label="Mitarbeiter", require_active=True,
    )
    validate_fk_in_org(client, table="vehicles", fk_id=payload.vehicle_id, org_id=org_id, label="Fahrzeug")
    validate_fk_in_org(client, table="tools", fk_id=payload.tool_id, org_id=org_id, label="Werkzeug")
    fields = payload.model_dump(exclude_unset=True)
    if "location" in fields and isinstance(fields["location"], str):
        fields["location"] = {"raw": fields["location"]}
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
    return res.data[0] if res.data else None


@router.patch("/{appointment_id}")
async def update_appointment(
    appointment_id: str, payload: AppointmentPatch, user: CurrentUser = Depends(require_org)
) -> dict:
    appt = await run_in_threadpool(_patch, user.org_id, appointment_id, payload)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
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
    if appt.get("status") != "pending":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Termin kann nicht bestätigt werden — aktueller Status: "
                f"{appt.get('status')!r}. Nur ausstehende Termine sind bestätigbar."
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
        .select("id")
        .eq("org_id", org_id)
        .eq("id", call_id)
        .limit(1)
        .execute()
        .data
    )
    if not call_rows:
        return {"_not_found": True}

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
    if not inquiry_rows:
        return {"appointment": None}

    inquiry_id = inquiry_rows[0]["id"]
    appt_rows = (
        client.table("appointments")
        .select(
            "id, title, scheduled_at, duration_minutes, status, category, "
            "color, location, notes, customer_id, inquiry_id, "
            "assigned_employee_id, confirmed_at, rejected_at, rejection_reason, "
            "alternative_start_time, alternative_end_time, alternative_note, "
            "alternative_proposed_at"
        )
        .eq("org_id", org_id)
        .eq("inquiry_id", inquiry_id)
        .eq("status", "pending")
        .order("scheduled_at")
        .limit(1)
        .execute()
        .data
    )
    return {"appointment": appt_rows[0] if appt_rows else None}


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
    return appt


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
    updated = (
        get_service_client()
        .table("appointments")
        .update({"status": "cancelled", "google_event_id": None})
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
    return appt


def _delete(org_id: str, appointment_id: str) -> bool:
    appt = _get_appointment(org_id, appointment_id)
    if not appt:
        return False
    if appt.get("google_event_id"):
        calendar_sync.delete_google_event(org_id, appt["google_event_id"])
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
