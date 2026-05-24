from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.schemas.admin import AppointmentCreate

router = APIRouter(prefix="/api/appointments", tags=["appointments"])


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
