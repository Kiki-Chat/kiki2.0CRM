import asyncio
import csv
import io
import json
from collections import Counter

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.schemas.admin import CustomerUpsert
from app.services import csv_import
from app.services.common import fetch_all_rows, run_parallel
from app.services.customers import find_existing_customer
from app.services.identify import _to_e164

router = APIRouter(prefix="/api/customers", tags=["customers"])


def _next_customer_number(client, org_id: str) -> str:
    # Unified numeric scheme — see services.common.gen_customer_number.
    from app.services.common import gen_customer_number

    return gen_customer_number(client, org_id)


def _addr(value: str | None):
    return {"raw": value} if value else None

_CUSTOMER_TYPES = ["new", "regular", "supplier", "property_management"]

# Whitelisted sort columns for the customer list (guards against arbitrary order-by
# injection). customer_number is text but the numbering scheme is fixed-width 6-digit,
# so a lexical sort matches numeric order. phone is plain text (canonical E.164).
# address_text is the generated flat-address column (migration 0051) that sorts
# across both address jsonb shapes ({raw} and {street,…}).
_SORT_COLUMNS = {"created_at", "full_name", "customer_number", "phone", "address_text"}
# Public sort key → physical column (so the API stays "address" while the DB sorts
# on the generated address_text).
_SORT_ALIASES = {"address": "address_text"}


def _resolve_sort(sort_by: str | None, sort_dir: str | None) -> tuple[str, bool]:
    """(column, desc) for the order-by. Unknown column → created_at. Direction
    defaults to newest-first for dates and ascending (A→Z / 1→9) otherwise."""
    col = (sort_by or "").strip()
    col = _SORT_ALIASES.get(col, col)
    if col not in _SORT_COLUMNS:
        col = "created_at"
    if sort_dir in ("asc", "desc"):
        desc = sort_dir == "desc"
    else:
        desc = col == "created_at"
    return col, desc


async def _list(
    org_id: str,
    q: str | None,
    limit: int,
    offset: int,
    customer_type: str | None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
) -> dict:
    client = get_service_client()

    def _fetch_page():
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
        col, desc = _resolve_sort(sort_by, sort_dir)
        query = query.order(col, desc=desc, nullsfirst=False)  # blanks always last
        if col != "created_at":
            query = query.order("created_at", desc=True)  # stable tiebreaker for paging
        return query.range(offset, offset + limit - 1).execute()

    # Filter-badge totals. count="exact" reads the total from the Content-Range
    # header, so it is NOT capped by PostgREST's 1000-row read limit (selecting the
    # rows and counting in Python would silently under-count large orgs). NULL
    # customer_type buckets as "new" (mirrors the prior behaviour). These 5 counts
    # plus the page query are all independent, so they fire concurrently below —
    # ~1 round-trip wall-clock instead of 6 serial. (A single GROUP BY RPC would
    # collapse the 5 count scans to 1; available as a follow-up, pending approval.)
    def _count_type(ctype: str | None) -> int:
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

    # The shared sync client is safe across these threadpool tasks: httpx.Client is
    # thread-safe and postgrest builds a fresh request per .table() call.
    res, *counts = await asyncio.gather(
        run_in_threadpool(_fetch_page),
        run_in_threadpool(_count_type, None),
        *[run_in_threadpool(_count_type, t) for t in _CUSTOMER_TYPES],
    )
    type_counts = {"all": counts[0], **{t: counts[i + 1] for i, t in enumerate(_CUSTOMER_TYPES)}}
    customers = res.data or []

    ids = [c["id"] for c in customers]
    inq_counts: Counter = Counter()
    appt_counts: Counter = Counter()
    photo_counts: Counter = Counter()
    doc_counts: Counter = Counter()
    if ids:
        # Paged reads: these rows are COUNTED per customer, and a page of customers
        # can collectively have >1000 inquiries/appointments/documents — a plain
        # .execute() would cap at 1000 and silently undercount (e.g. show "2" calls
        # when there are 50). fetch_all_rows pages past the cap.
        def _fetch_inq():
            return fetch_all_rows(
                lambda: client.table("inquiries").select("customer_id").eq("org_id", org_id)
                .neq("status", "deleted").in_("customer_id", ids)
            )

        def _fetch_appt():
            return fetch_all_rows(
                lambda: client.table("appointments").select("customer_id").eq("org_id", org_id)
                .in_("customer_id", ids)
            )

        def _fetch_docs():
            return fetch_all_rows(
                lambda: client.table("documents").select("customer_id, is_image").eq("org_id", org_id)
                .in_("customer_id", ids)
            )

        # Enrichment counts depend on the page ids but not on each other → parallel.
        inq_rows, appt_rows, doc_rows = await asyncio.gather(
            run_in_threadpool(_fetch_inq),
            run_in_threadpool(_fetch_appt),
            run_in_threadpool(_fetch_docs),
        )
        for r in inq_rows:
            inq_counts[r["customer_id"]] += 1
        for r in appt_rows:
            appt_counts[r["customer_id"]] += 1
        for r in doc_rows:
            if r.get("is_image"):
                photo_counts[r["customer_id"]] += 1
            else:
                doc_counts[r["customer_id"]] += 1
    for c in customers:
        c["inquiry_count"] = inq_counts.get(c["id"], 0)
        c["appointment_count"] = appt_counts.get(c["id"], 0)
        c["photo_count"] = photo_counts.get(c["id"], 0)
        c["document_count"] = doc_counts.get(c["id"], 0)

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

    # Four independent enrichment reads (none depends on another) — run them
    # concurrently instead of serially. `run_parallel` uses a private thread pool,
    # so it keeps this helper sync (it's already invoked via run_in_threadpool) and
    # can't starve the request pool.
    def _inq():
        return (
            client.table("inquiries")
            .select("id, number, subject, title, type, status, created_at, updated_at, project_id, case_id, case_confidence, case_reason")
            .eq("org_id", org_id).eq("customer_id", customer_id)
            .neq("status", "deleted").order("created_at", desc=True)
            .execute().data or []
        )

    def _appt():
        return (
            client.table("appointments")
            .select("id, inquiry_id, title, scheduled_at, status, category")
            .eq("org_id", org_id).eq("customer_id", customer_id)
            .order("scheduled_at", desc=True).execute().data or []
        )

    def _calls():
        return (
            client.table("calls")
            .select("id, inquiry_id, summary_title, direction, duration_seconds, started_at")
            .eq("org_id", org_id).eq("customer_id", customer_id)
            .is_("deleted_at", "null").order("started_at", desc=True)
            .execute().data or []
        )

    def _kvas():
        return (
            client.table("cost_estimates")
            .select("id, inquiry_id, number, status, total, valid_until, created_at")
            .eq("org_id", org_id).eq("customer_id", customer_id)
            .order("created_at", desc=True).execute().data or []
        )

    customer["inquiries"], customer["appointments"], customer["calls"], customer["cost_estimates"] = (
        run_parallel(_inq, _appt, _calls, _kvas)
    )

    # Vorgang-card enrichment — per-case call count, last activity, and a count of
    # open points (pending appointments + KVAs awaiting send/answer). Computed in
    # Python from the lists already fetched above → zero extra round-trips.
    call_count: Counter = Counter()
    open_count: Counter = Counter()
    last_act: dict[str, str] = {}
    for c in customer["calls"]:
        iid = c.get("inquiry_id")
        if not iid:
            continue
        call_count[iid] += 1
        ts = c.get("started_at")
        if ts and ts > last_act.get(iid, ""):
            last_act[iid] = ts
    for a in customer["appointments"]:
        iid = a.get("inquiry_id")
        if iid and a.get("status") == "pending":
            open_count[iid] += 1
    for k in customer["cost_estimates"]:
        iid = k.get("inquiry_id")
        if iid and k.get("status") in ("draft", "sent"):
            open_count[iid] += 1
    for inq in customer["inquiries"]:
        iid = inq["id"]
        inq["call_count"] = call_count.get(iid, 0)
        inq["open_count"] = open_count.get(iid, 0)
        inq["last_activity_at"] = last_act.get(iid) or inq.get("updated_at") or inq.get("created_at")

    customer["cases"] = (
        client.table("cases").select("id, number, label, status, created_at")
        .eq("org_id", org_id).eq("customer_id", customer_id).execute().data or []
    )
    return customer


@router.get("")
async def list_customers(
    q: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    customer_type: str | None = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
    user: CurrentUser = Depends(require_org),
) -> dict:
    return await _list(user.org_id, q, limit, offset, customer_type, sort_by, sort_dir)


_TYPE_LABELS = {
    "new": "Neukunde",
    "regular": "Stammkunde",
    "supplier": "Lieferant",
    "property_management": "Hausverwaltung",
}
# identified_by → human label. "phone" is how callers/AI-identified customers arise.
_SOURCE_LABELS = {"phone": "Anruf / KI", "manual": "Manuell", "csv_import": "Import"}


def _export_csv(
    org_id: str,
    q: str | None,
    customer_type: str | None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
) -> str:
    """Semicolon-delimited, UTF-8-BOM CSV of every customer matching the current
    view (search + type filter + sort). Pages past PostgREST's 1000-row cap so a
    4–5k base exports in full."""
    client = get_service_client()
    col, desc = _resolve_sort(sort_by, sort_dir)

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
        query = query.order(col, desc=desc, nullsfirst=False)
        if col != "created_at":
            query = query.order("created_at", desc=True)
        return query.range(start, start + 999).execute().data or []

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
    sort_by: str | None = None,
    sort_dir: str | None = None,
    user: CurrentUser = Depends(require_org),
) -> Response:
    csv_text = await run_in_threadpool(
        _export_csv, user.org_id, q, customer_type, sort_by, sort_dir
    )
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

    # Dedup guard — the manual-create path used to insert unconditionally, so the
    # form (esp. a double-submit) and the API could mint two customers on one
    # mobile. Same shared rule as the AI-agent path + CSV import. A collision is a
    # 409 (per product: block, don't silently merge) naming the existing record.
    dup = find_existing_customer(
        client, org_id, phone=payload.phone, name=payload.full_name, email=payload.email
    )
    if dup is None and payload.phone2:
        dup = find_existing_customer(client, org_id, phone=payload.phone2, name=payload.full_name)
    if dup:
        num = dup.get("customer_number") or dup.get("full_name") or "vorhanden"
        raise HTTPException(
            status_code=409,
            detail=f"Es existiert bereits ein Kunde mit dieser Telefonnummer oder E-Mail (Kundennr. {num}).",
        )

    row = {
        "org_id": org_id,
        "full_name": payload.full_name,
        "email": payload.email,
        # Store canonical E.164 so the dedup guard can match this row next time
        # (a later '0157…' vs '+49157…' create would otherwise slip through).
        "phone": _to_e164(payload.phone),
        "phone2": _to_e164(payload.phone2),
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


@router.post("/import/preview")
async def import_customers_preview(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_org),
) -> dict:
    """Read-only column analysis for the import dialog: each column's detected
    content type + sample values, plus a content-aware suggested mapping (so a
    phone column is never proposed for E-Mail/Adresse). Never writes."""
    content = await file.read()
    return await run_in_threadpool(csv_import.preview_customers, content)


def _update(org_id: str, customer_id: str, payload: CustomerUpsert) -> dict | None:
    client = get_service_client()
    fields: dict = {}
    if payload.full_name is not None:
        fields["full_name"] = payload.full_name
    if payload.email is not None:
        fields["email"] = payload.email
    if payload.phone is not None:
        fields["phone"] = _to_e164(payload.phone)  # keep canonical for dedup
    if payload.phone2 is not None:
        fields["phone2"] = _to_e164(payload.phone2)
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
