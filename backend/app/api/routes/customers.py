import csv
import io
import json
from collections import Counter

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.schemas.admin import CustomerUpsert
from app.services import csv_import

router = APIRouter(prefix="/api/customers", tags=["customers"])


def _next_customer_number(client, org_id: str) -> str:
    # Unified numeric scheme — see services.common.gen_customer_number.
    from app.services.common import gen_customer_number

    return gen_customer_number(client, org_id)


def _addr(value: str | None):
    return {"raw": value} if value else None

_CUSTOMER_TYPES = ["new", "regular", "supplier", "property_management"]


def _list(org_id: str, q: str | None, limit: int, offset: int, customer_type: str | None) -> dict:
    client = get_service_client()
    query = (
        client.table("customers")
        .select(
            "id, full_name, phone, email, customer_number, address, customer_type, "
            "identified_by, created_at",
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

    # Type counts for the filter badges. Uses count="exact" (the exact total is
    # returned in the Content-Range header) so it is NOT capped by PostgREST's
    # default 1000-row read limit — a plain select(...).execute() silently caps at
    # 1000 and under-reports on large orgs. NULL customer_type buckets as "new"
    # (mirrors the prior behaviour).
    def _type_count(ctype: str | None) -> int:
        qb = (
            client.table("customers")
            .select("id", count="exact")
            .eq("org_id", org_id)
            .neq("status", "deleted")
        )
        if ctype == "new":
            qb = qb.or_("customer_type.is.null,customer_type.eq.new")
        elif ctype:
            qb = qb.eq("customer_type", ctype)
        return qb.limit(1).execute().count or 0

    type_counts = {"all": _type_count(None), **{t: _type_count(t) for t in _CUSTOMER_TYPES}}

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
        .select("id, number, title, type, status, created_at, project_id")
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
        .is_("deleted_at", "null")
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


_TYPE_LABELS = {
    "new": "Neukunde",
    "regular": "Stammkunde",
    "supplier": "Lieferant",
    "property_management": "Hausverwaltung",
}
# identified_by → human label. "phone" is how callers/AI-identified customers arise.
_SOURCE_LABELS = {"phone": "Anruf / KI", "manual": "Manuell", "csv_import": "Import"}


def _export_csv(org_id: str, q: str | None, customer_type: str | None) -> str:
    """Semicolon-delimited, UTF-8-BOM CSV of every customer matching the current
    view (search + type filter). Pages past PostgREST's 1000-row cap so a 4–5k
    base exports in full."""
    client = get_service_client()

    def _page(start: int):
        query = (
            client.table("customers")
            .select(
                "customer_number, full_name, email, phone, phone2, address, "
                "customer_type, identified_by, notes, created_at"
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
        return query.order("created_at", desc=True).range(start, start + 999).execute().data or []

    rows: list[dict] = []
    start = 0
    while True:
        batch = _page(start)
        rows.extend(batch)
        if len(batch) < 1000:
            break
        start += 1000

    buf = io.StringIO()
    buf.write("﻿")  # UTF-8 BOM so Excel renders umlauts correctly
    w = csv.writer(buf, delimiter=";")
    w.writerow([
        "Kundennummer", "Name", "E-Mail", "Telefon", "Telefon 2", "Adresse",
        "Typ", "Quelle", "Notizen", "Erstellt am",
    ])
    for r in rows:
        a = r.get("address")
        address = a.get("raw") if isinstance(a, dict) else (a or "")
        w.writerow([
            r.get("customer_number") or "",
            r.get("full_name") or "",
            r.get("email") or "",
            r.get("phone") or "",
            r.get("phone2") or "",
            address or "",
            _TYPE_LABELS.get(r.get("customer_type") or "new", "Neukunde"),
            _SOURCE_LABELS.get(r.get("identified_by") or "", "Unbekannt"),
            r.get("notes") or "",
            (r.get("created_at") or "")[:10],
        ])
    return buf.getvalue()


@router.get("/export")
async def export_customers(
    q: str | None = None,
    customer_type: str | None = None,
    user: CurrentUser = Depends(require_org),
) -> Response:
    csv_text = await run_in_threadpool(_export_csv, user.org_id, q, customer_type)
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="kunden.csv"'},
    )


@router.get("/{customer_id}")
async def get_customer(
    customer_id: str, user: CurrentUser = Depends(require_org)
) -> dict:
    c = await run_in_threadpool(_detail, user.org_id, customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    return c


@router.get("/{customer_id}/timeline")
async def get_customer_timeline(
    customer_id: str, user: CurrentUser = Depends(require_org)
) -> list[dict]:
    """The customer's unified activity timeline (calls, inquiries, appointments,
    KVAs) — same event shape as the per-call Verlauf, scoped to this customer."""
    from app.api.routes.calls import build_customer_timeline

    tl = await run_in_threadpool(build_customer_timeline, user.org_id, customer_id)
    if tl is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return tl


def _create(org_id: str, payload: CustomerUpsert) -> dict:
    client = get_service_client()
    row = {
        "org_id": org_id,
        "full_name": payload.full_name,
        "email": payload.email,
        "phone": payload.phone,
        "phone2": payload.phone2,
        "address": _addr(payload.address),
        "vat_id": payload.vat_id,
        "customer_type": payload.customer_type or "new",
        "notes": payload.notes,
        "identified_by": "manual",
        "customer_number": payload.customer_number or _next_customer_number(client, org_id),
    }
    return client.table("customers").insert(row).execute().data[0]


@router.post("/import")
async def import_customers_csv(
    file: UploadFile = File(...),
    mapping: str = Form("{}"),
    user: CurrentUser = Depends(require_org),
) -> dict:
    """Bulk CSV import. ``mapping`` = JSON {target_field: csv_header}. Dedups on
    email/phone (skips duplicates, never overwrites), sets customer_type='regular'
    and keeps the CSV's customer number. Returns per-row results."""
    content = await file.read()
    try:
        m = json.loads(mapping) if mapping else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Ungültiges Mapping (kein JSON)")
    return await run_in_threadpool(csv_import.import_customers, user.org_id, content, m)


def _update(org_id: str, customer_id: str, payload: CustomerUpsert) -> dict | None:
    client = get_service_client()
    fields: dict = {}
    if payload.full_name is not None:
        fields["full_name"] = payload.full_name
    if payload.email is not None:
        fields["email"] = payload.email
    if payload.phone is not None:
        fields["phone"] = payload.phone
    if payload.phone2 is not None:
        fields["phone2"] = payload.phone2
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


class BulkDeleteRequest(BaseModel):
    ids: list[str]


@router.post("/bulk-delete")
async def bulk_delete_customers(
    payload: BulkDeleteRequest, user: CurrentUser = Depends(require_org)
) -> dict:
    """Soft-delete one or more customers (status='deleted'), scoped to the caller's
    org so a member can never delete another tenant's rows. Returns the count."""
    ids = [i for i in (payload.ids or []) if i]
    if not ids:
        return {"deleted": 0}

    def _soft_delete() -> int:
        client = get_service_client()
        res = (
            client.table("customers")
            .update({"status": "deleted"})
            .eq("org_id", user.org_id)
            .in_("id", ids)
            .execute()
        )
        return len(res.data or [])

    return {"deleted": await run_in_threadpool(_soft_delete)}
