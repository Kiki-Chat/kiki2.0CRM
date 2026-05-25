from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.schemas.admin import InvoiceSend, InvoiceStatus, InvoiceUpsert
from app.services.cost_estimates import build_pdf, compute_totals, fetch_customer, fetch_org
from app.services.invoices import add_days, gen_invoice_number, today_iso

router = APIRouter(prefix="/api/invoices", tags=["invoices"])

# Statuses that may be persisted. "overdue" is derived from due_date, never stored.
STORABLE_STATUSES = {"draft", "sent", "paid", "cancelled"}
_STAMP = {"paid": "paid_at", "cancelled": "cancelled_at", "sent": "sent_at"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _invoice_for_pdf(row: dict) -> dict:
    return {
        "type": "invoice",
        "number": row.get("number"),
        "subject": row.get("subject"),
        "invoice_date": row.get("invoice_date") or row.get("created_at"),
        "performance_date": row.get("performance_date"),
        "due_date": row.get("due_date"),
        "date": row.get("invoice_date") or row.get("created_at"),
        "positions": row.get("line_items") or [],
        "intro_text": row.get("intro_text"),
        "closing_text": row.get("closing_text"),
        "payment_terms": row.get("payment_terms_text"),
        "surcharge": row.get("surcharge") or 0,
        "surcharge_description": row.get("surcharge_description"),
        "total_discount_pct": row.get("total_discount_pct") or 0,
    }


def _build_row(org_id: str, payload: InvoiceUpsert, user_id: str | None) -> dict:
    positions = [p.model_dump() for p in payload.positions]
    totals = compute_totals(positions, payload.surcharge, payload.total_discount_pct)
    inv_date = payload.invoice_date or today_iso()
    return {
        "org_id": org_id,
        "customer_id": payload.customer_id,
        "cost_estimate_id": payload.kva_id,
        "project_id": payload.project_id,
        "subject": payload.subject,
        "reference_number": payload.reference_number,
        "invoice_date": inv_date,
        "performance_date": payload.performance_date,
        "payment_terms_days": payload.payment_terms_days,
        "due_date": add_days(inv_date, payload.payment_terms_days),
        "discount_pct": payload.discount_pct,
        "discount_days": payload.discount_days,
        "line_items": positions,
        "intro_text": payload.intro_text,
        "closing_text": payload.closing_text,
        "payment_terms_text": payload.payment_terms_text,
        "surcharge": payload.surcharge,
        "surcharge_description": payload.surcharge_description,
        "total_discount_pct": payload.total_discount_pct,
        "subtotal": totals["net"],
        "vat_amount": totals["vat"],
        "total": totals["gross"],
        "created_by": user_id,
    }


# ─── List ────────────────────────────────────────────────────────────────────
def _list(org_id: str) -> list[dict]:
    client = get_service_client()
    rows = (
        client.table("invoices")
        .select(
            "id, number, status, subject, customer_id, cost_estimate_id, reference_number, "
            "invoice_date, performance_date, due_date, subtotal, vat_amount, total, "
            "sent_at, paid_at, cancelled_at, created_at"
        )
        .eq("org_id", org_id)
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    cust_ids = {r["customer_id"] for r in rows if r.get("customer_id")}
    customers: dict[str, dict] = {}
    if cust_ids:
        for c in (
            client.table("customers").select("id, full_name, email").eq("org_id", org_id)
            .in_("id", list(cust_ids)).execute().data or []
        ):
            customers[c["id"]] = c
    today = today_iso()
    for r in rows:
        c = customers.get(r.get("customer_id")) or {}
        r["customer_name"] = c.get("full_name")
        r["customer_email"] = c.get("email")
        # Derive "overdue" for sent invoices past their due date (not stored).
        if r.get("status") == "sent" and r.get("due_date") and str(r["due_date"]) < today:
            r["status"] = "overdue"
    return rows


@router.get("")
async def list_invoices(user: CurrentUser = Depends(require_org)) -> list[dict]:
    return await run_in_threadpool(_list, user.org_id)


# ─── Create ──────────────────────────────────────────────────────────────────
def _create(org_id: str, user_id: str | None, payload: InvoiceUpsert) -> dict:
    client = get_service_client()
    row = _build_row(org_id, payload, user_id)
    row["number"] = gen_invoice_number(client, org_id)
    row["status"] = "draft"
    created = client.table("invoices").insert(row).execute().data[0]
    # Converting a KVA: mark the source estimate invoiced and link it both ways.
    if payload.kva_id:
        client.table("cost_estimates").update(
            {"status": "invoiced", "invoice_id": created["id"]}
        ).eq("org_id", org_id).eq("id", payload.kva_id).execute()
    return created


@router.post("")
async def create_invoice(
    payload: InvoiceUpsert, user: CurrentUser = Depends(require_org)
) -> dict:
    return await run_in_threadpool(_create, user.org_id, user.id, payload)


# ─── Get / Update / Delete ───────────────────────────────────────────────────
def _get(org_id: str, inv_id: str) -> dict | None:
    client = get_service_client()
    rows = (
        client.table("invoices").select("*").eq("org_id", org_id)
        .eq("id", inv_id).limit(1).execute().data
    )
    if not rows:
        return None
    row = rows[0]
    if row.get("customer_id"):
        c = fetch_customer(client, org_id, row["customer_id"])
        row["customer_name"] = (c or {}).get("full_name")
        row["customer_email"] = (c or {}).get("email")
    row["kva_id"] = row.get("cost_estimate_id")  # frontend-facing alias
    return row


@router.get("/{inv_id}")
async def get_invoice(inv_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    row = await run_in_threadpool(_get, user.org_id, inv_id)
    if not row:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return row


def _update(org_id: str, inv_id: str, payload: InvoiceUpsert) -> dict | None:
    client = get_service_client()
    row = _build_row(org_id, payload, None)
    row.pop("created_by", None)
    row["updated_at"] = _now()
    res = (
        client.table("invoices").update(row).eq("org_id", org_id)
        .eq("id", inv_id).execute()
    )
    return res.data[0] if res.data else None


@router.patch("/{inv_id}")
async def update_invoice(
    inv_id: str, payload: InvoiceUpsert, user: CurrentUser = Depends(require_org)
) -> dict:
    row = await run_in_threadpool(_update, user.org_id, inv_id, payload)
    if not row:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return row


@router.delete("/{inv_id}")
async def delete_invoice(inv_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    def _delete() -> str:
        client = get_service_client()
        rows = (
            client.table("invoices").select("status").eq("org_id", user.org_id)
            .eq("id", inv_id).limit(1).execute().data
        )
        if not rows:
            return "missing"
        if rows[0]["status"] != "draft":
            return "not_draft"
        client.table("invoices").delete().eq("org_id", user.org_id).eq("id", inv_id).execute()
        return "ok"

    res = await run_in_threadpool(_delete)
    if res == "missing":
        raise HTTPException(status_code=404, detail="Invoice not found")
    if res == "not_draft":
        raise HTTPException(status_code=400, detail="Nur Entwürfe können gelöscht werden.")
    return {"success": True}


# ─── PDF ─────────────────────────────────────────────────────────────────────
def _pdf_for_row(org_id: str, inv_id: str) -> tuple[bytes, str] | None:
    client = get_service_client()
    rows = (
        client.table("invoices").select("*").eq("org_id", org_id)
        .eq("id", inv_id).limit(1).execute().data
    )
    if not rows:
        return None
    row = rows[0]
    org = fetch_org(client, org_id)
    customer = fetch_customer(client, org_id, row.get("customer_id"))
    totals = {
        "net": row.get("subtotal") or 0,
        "vat": row.get("vat_amount") or 0,
        "gross": row.get("total") or 0,
    }
    return build_pdf(org, customer, _invoice_for_pdf(row), totals), (row.get("number") or "RE")


@router.get("/{inv_id}/pdf")
async def invoice_pdf(
    inv_id: str, preview: bool = False, user: CurrentUser = Depends(require_org)
) -> Response:
    result = await run_in_threadpool(_pdf_for_row, user.org_id, inv_id)
    if not result:
        raise HTTPException(status_code=404, detail="Invoice not found")
    pdf_bytes, number = result
    disp = "inline" if preview else "attachment"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disp}; filename="{number}.pdf"'},
    )


def _preview_pdf(org_id: str, payload: InvoiceUpsert) -> bytes:
    client = get_service_client()
    org = fetch_org(client, org_id)
    customer = fetch_customer(client, org_id, payload.customer_id)
    positions = [p.model_dump() for p in payload.positions]
    totals = compute_totals(positions, payload.surcharge, payload.total_discount_pct)
    inv_date = payload.invoice_date or today_iso()
    ce = {
        "type": "invoice",
        "number": "VORSCHAU",
        "subject": payload.subject,
        "invoice_date": inv_date,
        "performance_date": payload.performance_date,
        "due_date": add_days(inv_date, payload.payment_terms_days),
        "date": inv_date,
        "positions": positions,
        "intro_text": payload.intro_text,
        "closing_text": payload.closing_text,
        "payment_terms": payload.payment_terms_text,
        "surcharge": payload.surcharge,
        "surcharge_description": payload.surcharge_description,
        "total_discount_pct": payload.total_discount_pct,
    }
    return build_pdf(org, customer, ce, totals)


@router.post("/preview")
async def preview_pdf(
    payload: InvoiceUpsert, user: CurrentUser = Depends(require_org)
) -> Response:
    pdf_bytes = await run_in_threadpool(_preview_pdf, user.org_id, payload)
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="vorschau.pdf"'})


# ─── Actions: send / duplicate / status ──────────────────────────────────────
@router.post("/{inv_id}/send")
async def send_invoice(
    inv_id: str, payload: InvoiceSend, user: CurrentUser = Depends(require_org)
) -> dict:
    def _send() -> dict | None:
        client = get_service_client()
        res = (
            client.table("invoices")
            .update({"status": "sent", "sent_at": _now()})
            .eq("org_id", user.org_id).eq("id", inv_id).execute()
        )
        return res.data[0] if res.data else None

    row = await run_in_threadpool(_send)
    if not row:
        raise HTTPException(status_code=404, detail="Invoice not found")
    # SMTP not configured in this environment → record the send and report success.
    return {"success": True, "status": "sent", "emailed": False, "to": payload.to}


@router.post("/{inv_id}/duplicate")
async def duplicate_invoice(inv_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    def _dup() -> dict | None:
        client = get_service_client()
        rows = (
            client.table("invoices").select("*").eq("org_id", user.org_id)
            .eq("id", inv_id).limit(1).execute().data
        )
        if not rows:
            return None
        src = rows[0]
        for k in ("id", "number", "created_at", "updated_at", "sent_at", "paid_at",
                  "cancelled_at", "cost_estimate_id"):
            src.pop(k, None)
        src["status"] = "draft"
        src["invoice_date"] = today_iso()
        src["due_date"] = add_days(src["invoice_date"], src.get("payment_terms_days"))
        src["number"] = gen_invoice_number(client, user.org_id)
        return client.table("invoices").insert(src).execute().data[0]

    row = await run_in_threadpool(_dup)
    if not row:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return row


@router.patch("/{inv_id}/status")
async def set_status(
    inv_id: str, payload: InvoiceStatus, user: CurrentUser = Depends(require_org)
) -> dict:
    if payload.status not in STORABLE_STATUSES:
        raise HTTPException(status_code=400, detail=f"Ungültiger Status: {payload.status}")
    fields = {"status": payload.status}
    stamp = _STAMP.get(payload.status)
    if stamp:
        fields[stamp] = _now()

    def _set() -> dict | None:
        client = get_service_client()
        res = (
            client.table("invoices").update(fields).eq("org_id", user.org_id)
            .eq("id", inv_id).execute()
        )
        return res.data[0] if res.data else None

    row = await run_in_threadpool(_set)
    if not row:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return row
