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
    if payload.subject is not None:
        fields["subject"] = payload.subject
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


# ─── Vorgang (case) thread + Link/Merge ──────────────────────────────────────
def _related_cases(org_id: str, inquiry_id: str) -> list[dict]:
    """Cases linked to this one via case_links (either direction)."""
    client = get_service_client()
    links = (
        client.table("case_links")
        .select("case_id, related_case_id, relation")
        .eq("org_id", org_id)
        .or_(f"case_id.eq.{inquiry_id},related_case_id.eq.{inquiry_id}")
        .execute().data or []
    )
    rel_by_id: dict[str, str] = {}
    for link in links:
        other = link["related_case_id"] if link["case_id"] == inquiry_id else link["case_id"]
        rel_by_id[other] = link.get("relation") or "related"
    if not rel_by_id:
        return []
    rows = (
        client.table("inquiries").select("id, number, subject, title, status")
        .eq("org_id", org_id).in_("id", list(rel_by_id.keys()))
        .execute().data or []
    )
    return [{"relation": rel_by_id.get(r["id"], "related"), "case": r} for r in rows]


@router.get("/{inquiry_id}/thread")
async def get_inquiry_thread(
    inquiry_id: str, user: CurrentUser = Depends(require_org)
) -> dict:
    """The full Vorgang (case) thread: header + one chronological timeline of every
    call (in/out), appointment, KVA and status change on this case, the raw record
    lists, and any linked/duplicate cases."""
    from app.api.routes.calls import build_case_thread

    bundle = await run_in_threadpool(build_case_thread, user.org_id, inquiry_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Vorgang not found")
    bundle["related"] = await run_in_threadpool(_related_cases, user.org_id, inquiry_id)
    return bundle


class CaseLinkPayload(BaseModel):
    related_case_id: str
    relation: str = "related"  # 'related' | 'duplicate'


def _link_case(org_id: str, inquiry_id: str, payload: "CaseLinkPayload") -> dict:
    if payload.related_case_id == inquiry_id:
        raise HTTPException(status_code=422, detail="Ein Vorgang kann nicht mit sich selbst verknüpft werden.")
    if payload.relation not in ("related", "duplicate"):
        raise HTTPException(status_code=422, detail="Ungültige Relation")
    client = get_service_client()
    validate_fk_in_org(client, table="inquiries", fk_id=inquiry_id, org_id=org_id, label="Vorgang")
    validate_fk_in_org(client, table="inquiries", fk_id=payload.related_case_id, org_id=org_id, label="Vorgang")
    # Normalise the pair order so (a,b) and (b,a) collapse to one row (unique index).
    a, b = sorted([inquiry_id, payload.related_case_id])
    try:
        client.table("case_links").insert(
            {"org_id": org_id, "case_id": a, "related_case_id": b, "relation": payload.relation}
        ).execute()
    except Exception:  # noqa: BLE001 — already linked → make it idempotent
        client.table("case_links").update({"relation": payload.relation}).eq(
            "org_id", org_id
        ).eq("case_id", a).eq("related_case_id", b).execute()
    return {"success": True}


@router.post("/{inquiry_id}/link")
async def link_case(
    inquiry_id: str, payload: CaseLinkPayload, user: CurrentUser = Depends(require_org)
) -> dict:
    """Link this Vorgang to another (relation 'related' or 'duplicate') — keeps both
    cases separate but cross-referenced (industry-standard Link)."""
    return await run_in_threadpool(_link_case, user.org_id, inquiry_id, payload)


class CaseMergePayload(BaseModel):
    into_case_id: str  # the surviving (parent) case


def _merge_case(org_id: str, child_id: str, parent_id: str) -> dict:
    if child_id == parent_id:
        raise HTTPException(status_code=422, detail="Ein Vorgang kann nicht mit sich selbst zusammengeführt werden.")
    client = get_service_client()
    validate_fk_in_org(client, table="inquiries", fk_id=child_id, org_id=org_id, label="Vorgang")
    validate_fk_in_org(client, table="inquiries", fk_id=parent_id, org_id=org_id, label="Vorgang")
    # Move the child's activities onto the surviving case (reversible — just FKs).
    for table in ("calls", "appointments", "cost_estimates"):
        client.table(table).update({"inquiry_id": parent_id}).eq("org_id", org_id).eq(
            "inquiry_id", child_id
        ).execute()
    # Mark the child a duplicate of the parent and close it — reachable via the link,
    # NOT deleted (history stays intact).
    client.table("inquiries").update({"status": "completed", "updated_at": "now()"}).eq(
        "org_id", org_id
    ).eq("id", child_id).execute()
    a, b = sorted([child_id, parent_id])
    try:
        client.table("case_links").insert(
            {"org_id": org_id, "case_id": a, "related_case_id": b, "relation": "duplicate"}
        ).execute()
    except Exception:  # noqa: BLE001 — already linked
        client.table("case_links").update({"relation": "duplicate"}).eq("org_id", org_id).eq(
            "case_id", a
        ).eq("related_case_id", b).execute()
    return {"success": True, "into_case_id": parent_id}


@router.post("/{inquiry_id}/merge")
async def merge_case(
    inquiry_id: str, payload: CaseMergePayload, user: CurrentUser = Depends(require_org)
) -> dict:
    """Merge this Vorgang INTO another: moves its calls/appointments/KVAs onto the
    target case, marks this one a closed duplicate, and links them. Reversible."""
    return await run_in_threadpool(_merge_case, user.org_id, inquiry_id, payload.into_case_id)
