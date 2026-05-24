from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from pydantic import BaseModel

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.schemas.admin import InquiryUpdate
from app.services.common import gen_inquiry_number

router = APIRouter(prefix="/api/inquiries", tags=["inquiries"])

_ALLOWED_STATUS = {"open", "in_progress", "completed", "deleted"}


class InquiryCreate(BaseModel):
    customer_id: str | None = None
    title: str | None = None
    type: str | None = None
    notes: str | None = None


def _create(org_id: str, payload: InquiryCreate) -> dict:
    client = get_service_client()
    row = {
        "org_id": org_id,
        "customer_id": payload.customer_id,
        "title": payload.title or "Neue Anfrage",
        "type": payload.type or "info",
        "status": "open",
        "notes": payload.notes,
        "number": gen_inquiry_number(client, org_id),
    }
    return client.table("inquiries").insert(row).execute().data[0]


@router.post("")
async def create_inquiry(
    payload: InquiryCreate, user: CurrentUser = Depends(require_org)
) -> dict:
    return await run_in_threadpool(_create, user.org_id, payload)


def _update(org_id: str, inquiry_id: str, payload: InquiryUpdate) -> dict | None:
    client = get_service_client()
    fields: dict = {}
    if payload.status is not None:
        if payload.status not in _ALLOWED_STATUS:
            raise HTTPException(status_code=422, detail="Invalid status")
        fields["status"] = payload.status
    if payload.title is not None:
        fields["title"] = payload.title
    if payload.type is not None:
        fields["type"] = payload.type
    if payload.notes is not None:
        fields["notes"] = payload.notes
    if payload.assigned_employee_id is not None:
        fields["assigned_employee_id"] = payload.assigned_employee_id or None
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    fields["updated_at"] = "now()"

    res = (
        client.table("inquiries")
        .update(fields)
        .eq("org_id", org_id)
        .eq("id", inquiry_id)
        .execute()
    )
    return res.data[0] if res.data else None


@router.patch("/{inquiry_id}")
async def update_inquiry(
    inquiry_id: str,
    payload: InquiryUpdate,
    user: CurrentUser = Depends(require_org),
) -> dict:
    row = await run_in_threadpool(_update, user.org_id, inquiry_id, payload)
    if not row:
        raise HTTPException(status_code=404, detail="Inquiry not found")
    return row
