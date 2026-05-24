from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.schemas.admin import CustomerUpsert

router = APIRouter(prefix="/api/customers", tags=["customers"])


def _next_customer_number(client, org_id: str) -> str:
    rows = (
        client.table("customers").select("customer_number").eq("org_id", org_id).execute().data
        or []
    )
    nums = [
        int(r["customer_number"])
        for r in rows
        if r.get("customer_number") and str(r["customer_number"]).isdigit()
    ]
    return str(max(nums) + 1 if nums else 101001)


def _addr(value: str | None):
    return {"raw": value} if value else None

_CUSTOMER_TYPES = ["new", "regular", "supplier", "property_management"]


def _list(org_id: str, q: str | None, limit: int, offset: int, customer_type: str | None) -> dict:
    client = get_service_client()
    query = (
        client.table("customers")
        .select(
            "id, full_name, phone, email, customer_number, address, customer_type, created_at",
            count="exact",
        )
        .eq("org_id", org_id)
        .neq("status", "deleted")
    )
    if customer_type:
        query = query.eq("customer_type", customer_type)
    if q:
        query = query.or_(
            f"full_name.ilike.%{q}%,phone.ilike.%{q}%,email.ilike.%{q}%,"
            f"customer_number.ilike.%{q}%"
        )
    res = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    customers = res.data or []

    ids = [c["id"] for c in customers]
    inq_counts: Counter = Counter()
    appt_counts: Counter = Counter()
    photo_counts: Counter = Counter()
    doc_counts: Counter = Counter()
    if ids:
        for r in (
            client.table("inquiries").select("customer_id").eq("org_id", org_id)
            .neq("status", "deleted").in_("customer_id", ids).execute().data or []
        ):
            inq_counts[r["customer_id"]] += 1
        for r in (
            client.table("appointments").select("customer_id").eq("org_id", org_id)
            .in_("customer_id", ids).execute().data or []
        ):
            appt_counts[r["customer_id"]] += 1
        for r in (
            client.table("documents").select("customer_id, is_image").eq("org_id", org_id)
            .in_("customer_id", ids).execute().data or []
        ):
            if r.get("is_image"):
                photo_counts[r["customer_id"]] += 1
            else:
                doc_counts[r["customer_id"]] += 1
    for c in customers:
        c["inquiry_count"] = inq_counts.get(c["id"], 0)
        c["appointment_count"] = appt_counts.get(c["id"], 0)
        c["photo_count"] = photo_counts.get(c["id"], 0)
        c["document_count"] = doc_counts.get(c["id"], 0)

    # Type counts for the filter badges (across all non-deleted customers).
    all_types = (
        client.table("customers").select("customer_type").eq("org_id", org_id)
        .neq("status", "deleted").execute().data or []
    )
    tc = Counter(r.get("customer_type") or "new" for r in all_types)
    type_counts = {"all": len(all_types), **{t: tc.get(t, 0) for t in _CUSTOMER_TYPES}}

    return {"customers": customers, "total": res.count or 0, "type_counts": type_counts}


def _detail(org_id: str, customer_id: str) -> dict | None:
    client = get_service_client()
    rows = (
        client.table("customers")
        .select("*")
        .eq("org_id", org_id)
        .eq("id", customer_id)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        return None
    customer = rows[0]
    customer["inquiries"] = (
        client.table("inquiries")
        .select("id, number, title, type, status, created_at")
        .eq("org_id", org_id)
        .eq("customer_id", customer_id)
        .neq("status", "deleted")
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    customer["appointments"] = (
        client.table("appointments")
        .select("id, title, scheduled_at, status, category")
        .eq("org_id", org_id)
        .eq("customer_id", customer_id)
        .order("scheduled_at", desc=True)
        .execute()
        .data
        or []
    )
    customer["calls"] = (
        client.table("calls")
        .select("id, summary_title, direction, duration_seconds, started_at")
        .eq("org_id", org_id)
        .eq("customer_id", customer_id)
        .order("started_at", desc=True)
        .execute()
        .data
        or []
    )
    customer["cost_estimates"] = (
        client.table("cost_estimates")
        .select("id, number, status, total, valid_until, created_at")
        .eq("org_id", org_id)
        .eq("customer_id", customer_id)
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    return customer


@router.get("")
async def list_customers(
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
    customer_type: str | None = None,
    user: CurrentUser = Depends(require_org),
) -> dict:
    return await run_in_threadpool(_list, user.org_id, q, limit, offset, customer_type)


@router.get("/{customer_id}")
async def get_customer(
    customer_id: str, user: CurrentUser = Depends(require_org)
) -> dict:
    c = await run_in_threadpool(_detail, user.org_id, customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    return c


def _create(org_id: str, payload: CustomerUpsert) -> dict:
    client = get_service_client()
    row = {
        "org_id": org_id,
        "full_name": payload.full_name,
        "email": payload.email,
        "phone": payload.phone,
        "address": _addr(payload.address),
        "vat_id": payload.vat_id,
        "customer_type": payload.customer_type or "new",
        "notes": payload.notes,
        "identified_by": "manual",
        "customer_number": payload.customer_number or _next_customer_number(client, org_id),
    }
    return client.table("customers").insert(row).execute().data[0]


def _update(org_id: str, customer_id: str, payload: CustomerUpsert) -> dict | None:
    client = get_service_client()
    fields: dict = {}
    if payload.full_name is not None:
        fields["full_name"] = payload.full_name
    if payload.email is not None:
        fields["email"] = payload.email
    if payload.phone is not None:
        fields["phone"] = payload.phone
    if payload.address is not None:
        fields["address"] = _addr(payload.address)
    if payload.vat_id is not None:
        fields["vat_id"] = payload.vat_id
    if payload.customer_type is not None:
        fields["customer_type"] = payload.customer_type
    if payload.notes is not None:
        fields["notes"] = payload.notes
    if payload.customer_number is not None:
        fields["customer_number"] = payload.customer_number
    fields["updated_at"] = "now()"
    res = (
        client.table("customers")
        .update(fields)
        .eq("org_id", org_id)
        .eq("id", customer_id)
        .execute()
    )
    return res.data[0] if res.data else None


@router.post("")
async def create_customer(
    payload: CustomerUpsert, user: CurrentUser = Depends(require_org)
) -> dict:
    return await run_in_threadpool(_create, user.org_id, payload)


@router.patch("/{customer_id}")
async def update_customer(
    customer_id: str, payload: CustomerUpsert, user: CurrentUser = Depends(require_org)
) -> dict:
    c = await run_in_threadpool(_update, user.org_id, customer_id, payload)
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    return c


@router.delete("/{customer_id}")
async def delete_customer(
    customer_id: str, user: CurrentUser = Depends(require_org)
) -> dict:
    def _soft_delete() -> bool:
        client = get_service_client()
        res = (
            client.table("customers")
            .update({"status": "deleted"})
            .eq("org_id", user.org_id)
            .eq("id", customer_id)
            .execute()
        )
        return bool(res.data)

    ok = await run_in_threadpool(_soft_delete)
    if not ok:
        raise HTTPException(status_code=404, detail="Customer not found")
    return {"success": True}
