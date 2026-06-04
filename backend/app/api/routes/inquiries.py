from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from pydantic import BaseModel

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.schemas.admin import InquiryUpdate
from app.services.common import enforce_self_assignment, gen_inquiry_number, validate_fk_in_org

router = APIRouter(prefix="/api/inquiries", tags=["inquiries"])

_ALLOWED_STATUS = {"open", "in_progress", "completed", "deleted"}


class InquiryCreate(BaseModel):
    customer_id: str | None = None
    title: str | None = None
    type: str | None = None
    notes: str | None = None
    project_id: str | None = None


def _create(org_id: str, payload: InquiryCreate) -> dict:
    client = get_service_client()
    # FK hardening: a customer_id / project_id from the body must belong to this org.
    validate_fk_in_org(client, table="customers", fk_id=payload.customer_id, org_id=org_id, label="Kunde")
    validate_fk_in_org(client, table="projects", fk_id=payload.project_id, org_id=org_id, label="Projekt")
    row = {
        "org_id": org_id,
        "customer_id": payload.customer_id,
        "project_id": payload.project_id,
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


def _update(user: CurrentUser, inquiry_id: str, payload: InquiryUpdate) -> dict | None:
    org_id = user.org_id
    client = get_service_client()
    # FK hardening: project_id / assigned_employee_id from the body must be same-org.
    # (The dedicated /assign route already validates the employee; the generic
    # PATCH path did not — close that gap here.)
    validate_fk_in_org(client, table="projects", fk_id=payload.project_id, org_id=org_id, label="Projekt")
    validate_fk_in_org(
        client, table="employees", fk_id=payload.assigned_employee_id,
        org_id=org_id, label="Mitarbeiter", require_active=True,
    )
    # A plain employee may not reassign work to a colleague via the generic PATCH.
    if payload.assigned_employee_id is not None:
        cur = (
            client.table("inquiries")
            .select("assigned_employee_id")
            .eq("org_id", org_id)
            .eq("id", inquiry_id)
            .limit(1)
            .execute()
            .data
        )
        enforce_self_assignment(
            client,
            user=user,
            current_assignee_id=cur[0].get("assigned_employee_id") if cur else None,
            new_assignee_id=payload.assigned_employee_id or None,
        )
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
    if payload.project_id is not None:
        fields["project_id"] = payload.project_id or None
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
    row = await run_in_threadpool(_update, user, inquiry_id, payload)
    if not row:
        raise HTTPException(status_code=404, detail="Inquiry not found")
    return row


# Wave 2 / Agent 2.1 — inline assign-employee dropdown on the call/inquiry
# list-card. Distinct route from the generic PATCH so the frontend can fire
# a focused mutation (and so test coverage doesn't conflate concerns).
class InquiryAssignPayload(BaseModel):
    employee_id: str | None = None


def _assign(user: CurrentUser, inquiry_id: str, employee_id: str | None) -> dict | None:
    """Assign (or unassign) an employee to an inquiry, validating that the
    employee belongs to the caller's org. Returns the updated row or None
    when the inquiry doesn't exist in this org."""
    org_id = user.org_id
    client = get_service_client()

    # Verify the inquiry belongs to the caller's org BEFORE writing — otherwise
    # the org_id filter on the UPDATE silently makes a wrong inquiry_id a no-op
    # and the frontend can't tell apart "permission denied" from "you assigned
    # nobody". 404 is more honest.
    existing = (
        client.table("inquiries")
        .select("id, assigned_employee_id")
        .eq("org_id", org_id)
        .eq("id", inquiry_id)
        .limit(1)
        .execute()
        .data
    )
    if not existing:
        return None

    # A plain employee may only (un)assign their OWN inquiries, and only to
    # themselves — admins may assign to anyone in the org.
    enforce_self_assignment(
        client,
        user=user,
        current_assignee_id=existing[0].get("assigned_employee_id"),
        new_assignee_id=employee_id,
    )

    if employee_id:
        # Same-org check: a malicious org_admin can't reassign an inquiry to an
        # employee in another tenant.
        emp_rows = (
            client.table("employees")
            .select("id")
            .eq("org_id", org_id)
            .eq("id", employee_id)
            .eq("deleted", False)
            .limit(1)
            .execute()
            .data
        )
        if not emp_rows:
            raise HTTPException(
                status_code=422,
                detail="Mitarbeiter gehört nicht zu dieser Organisation.",
            )

    res = (
        client.table("inquiries")
        .update(
            {
                "assigned_employee_id": employee_id,
                "updated_at": "now()",
            }
        )
        .eq("org_id", org_id)
        .eq("id", inquiry_id)
        .execute()
    )
    return res.data[0] if res.data else None


@router.patch("/{inquiry_id}/assign")
async def assign_inquiry(
    inquiry_id: str,
    payload: InquiryAssignPayload,
    user: CurrentUser = Depends(require_org),
) -> dict:
    """Assign / unassign an employee on an inquiry. POST `{employee_id: null}`
    to clear the assignment. Validates same-org employee ownership."""
    row = await run_in_threadpool(_assign, user, inquiry_id, payload.employee_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Inquiry not found")
    return row
