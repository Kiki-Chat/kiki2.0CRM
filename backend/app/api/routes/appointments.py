from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.schemas.admin import AppointmentCreate, AppointmentPatch
from app.services.appointments import import_ics

router = APIRouter(prefix="/api/appointments", tags=["appointments"])


def _list(org_id: str, frm: str | None, to: str | None) -> list[dict]:
    client = get_service_client()
    query = (
        client.table("appointments")
        .select(
            "id, title, scheduled_at, duration_minutes, status, category, color, "
            "location, notes, customer_id, inquiry_id, assigned_employee_id, "
            "vehicle_id, tool_id"
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
    row = {
        "org_id": org_id,
        "customer_id": payload.customer_id,
        "inquiry_id": payload.inquiry_id,
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
