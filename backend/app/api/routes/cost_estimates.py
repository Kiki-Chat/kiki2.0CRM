from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.schemas.admin import (
    CostEstimateSend,
    CostEstimateStatus,
    CostEstimateUpsert,
)
from app.services.cost_estimates import (
    build_pdf,
    compute_totals,
    fetch_customer,
    fetch_org,
    gen_number,
    valid_until_for,
)

router = APIRouter(prefix="/api/cost-estimates", tags=["cost-estimates"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ce_for_pdf(row: dict) -> dict:
    return {
        "type": row.get("type") or "kva",
        "number": row.get("number"),
        "subject": row.get("subject"),
        "is_binding": row.get("is_binding"),
        "tolerance_pct": row.get("tolerance_pct", 20),
        "valid_until": row.get("valid_until"),
        "date": row.get("created_at"),
        "positions": row.get("line_items") or [],
        "intro_text": row.get("intro_text"),
        "closing_text": row.get("closing_text"),
        "payment_terms": row.get("payment_terms"),
        "surcharge": row.get("surcharge") or 0,
        "surcharge_description": row.get("surcharge_description"),
        "total_discount_pct": row.get("total_discount_pct") or 0,
    }


# ─── List ────────────────────────────────────────────────────────────────────
def _list(org_id: str) -> list[dict]:
    client = get_service_client()
    rows = (
        client.table("cost_estimates")
        .select(
            "id, number, type, status, subject, customer_id, inquiry_id, is_binding, "
            "tolerance_pct, valid_until, subtotal, vat_amount, total, sent_at, "
            "accepted_at, rejected_at, created_at"
        )
        .eq("org_id", org_id)
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    cust_ids = {r["customer_id"] for r in rows if r.get("customer_id")}
    inq_ids = {r["inquiry_id"] for r in rows if r.get("inquiry_id")}
    customers: dict[str, dict] = {}
    if cust_ids:
        for c in (
            client.table("customers").select("id, full_name, email").eq("org_id", org_id)
            .in_("id", list(cust_ids)).execute().data or []
        ):
            customers[c["id"]] = c
    inquiries: dict[str, str] = {}
    if inq_ids:
        for i in (
            client.table("inquiries").select("id, title").eq("org_id", org_id)
            .in_("id", list(inq_ids)).execute().data or []
        ):
            inquiries[i["id"]] = i.get("title")
    for r in rows:
        c = customers.get(r.get("customer_id")) or {}
        r["customer_name"] = c.get("full_name")
        r["customer_email"] = c.get("email")
        r["inquiry_title"] = inquiries.get(r.get("inquiry_id"))
    return rows


@router.get("")
async def list_estimates(user: CurrentUser = Depends(require_org)) -> list[dict]:
    return await run_in_threadpool(_list, user.org_id)


# ─── Create ──────────────────────────────────────────────────────────────────
def _build_row(org_id: str, payload: CostEstimateUpsert, user_id: str | None) -> dict:
    positions = [p.model_dump() for p in payload.positions]
    totals = compute_totals(positions, payload.surcharge, payload.total_discount_pct)
    return {
        "org_id": org_id,
        "customer_id": payload.customer_id,
        "inquiry_id": payload.inquiry_id,
        "type": payload.type,
        "subject": payload.subject,
        "reference_number": payload.reference_number,
        "is_binding": payload.is_binding,
        "tolerance_pct": payload.tolerance_pct,
        "validity_days": payload.validity_days,
        "valid_until": valid_until_for(payload.validity_days),
        "line_items": positions,
        "intro_text": payload.intro_text,
        "closing_text": payload.closing_text,
        "payment_terms": payload.payment_terms,
        "surcharge": payload.surcharge,
        "surcharge_description": payload.surcharge_description,
        "total_discount_pct": payload.total_discount_pct,
        "subtotal": totals["net"],
        "vat_amount": totals["vat"],
        "total": totals["gross"],
        "created_by": user_id,
    }


def _create(org_id: str, user_id: str | None, payload: CostEstimateUpsert) -> dict:
    client = get_service_client()
    row = _build_row(org_id, payload, user_id)
    row["number"] = gen_number(client, org_id, payload.type)
    row["status"] = "draft"
    return client.table("cost_estimates").insert(row).execute().data[0]


@router.post("")
async def create_estimate(
    payload: CostEstimateUpsert, user: CurrentUser = Depends(require_org)
) -> dict:
    return await run_in_threadpool(_create, user.org_id, user.id, payload)


# ─── Get / Update / Delete ───────────────────────────────────────────────────
def _get(org_id: str, ce_id: str) -> dict | None:
    client = get_service_client()
    rows = (
        client.table("cost_estimates").select("*").eq("org_id", org_id)
        .eq("id", ce_id).limit(1).execute().data
    )
    if not rows:
        return None
    row = rows[0]
    if row.get("customer_id"):
        c = fetch_customer(client, org_id, row["customer_id"])
        row["customer_name"] = (c or {}).get("full_name")
    return row


@router.get("/{ce_id}")
async def get_estimate(ce_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    row = await run_in_threadpool(_get, user.org_id, ce_id)
    if not row:
        raise HTTPException(status_code=404, detail="Cost estimate not found")
    return row


def _update(org_id: str, ce_id: str, payload: CostEstimateUpsert) -> dict | None:
    client = get_service_client()
    row = _build_row(org_id, payload, None)
    row.pop("created_by", None)
    row["updated_at"] = _now()
    res = (
        client.table("cost_estimates").update(row).eq("org_id", org_id)
        .eq("id", ce_id).execute()
    )
    return res.data[0] if res.data else None


@router.patch("/{ce_id}")
async def update_estimate(
    ce_id: str, payload: CostEstimateUpsert, user: CurrentUser = Depends(require_org)
) -> dict:
    row = await run_in_threadpool(_update, user.org_id, ce_id, payload)
    if not row:
        raise HTTPException(status_code=404, detail="Cost estimate not found")
    return row


@router.delete("/{ce_id}")
async def delete_estimate(ce_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    def _delete() -> bool:
        client = get_service_client()
        res = (
            client.table("cost_estimates").delete().eq("org_id", user.org_id)
            .eq("id", ce_id).execute()
        )
        return bool(res.data)

    ok = await run_in_threadpool(_delete)
    if not ok:
        raise HTTPException(status_code=404, detail="Cost estimate not found")
    return {"success": True}


# ─── PDF ─────────────────────────────────────────────────────────────────────
def _pdf_for_row(org_id: str, ce_id: str) -> tuple[bytes, str] | None:
    client = get_service_client()
    rows = (
        client.table("cost_estimates").select("*").eq("org_id", org_id)
        .eq("id", ce_id).limit(1).execute().data
    )
    if not rows:
        return None
    row = rows[0]
    org = fetch_org(client, org_id)
    customer = fetch_customer(client, org_id, row.get("customer_id"))
    totals = {"net": row.get("subtotal") or 0, "vat": row.get("vat_amount") or 0, "gross": row.get("total") or 0}
    return build_pdf(org, customer, _ce_for_pdf(row), totals), (row.get("number") or "KVA")


@router.get("/{ce_id}/pdf")
async def estimate_pdf(
    ce_id: str, preview: bool = False, user: CurrentUser = Depends(require_org)
) -> Response:
    result = await run_in_threadpool(_pdf_for_row, user.org_id, ce_id)
    if not result:
        raise HTTPException(status_code=404, detail="Cost estimate not found")
    pdf_bytes, number = result
    disp = "inline" if preview else "attachment"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disp}; filename="{number}.pdf"'},
    )


def _preview_pdf(org_id: str, payload: CostEstimateUpsert) -> bytes:
    client = get_service_client()
    org = fetch_org(client, org_id)
    customer = fetch_customer(client, org_id, payload.customer_id)
    positions = [p.model_dump() for p in payload.positions]
    totals = compute_totals(positions, payload.surcharge, payload.total_discount_pct)
    ce = {
        "type": payload.type,
        "number": "VORSCHAU",
        "subject": payload.subject,
        "is_binding": payload.is_binding,
        "tolerance_pct": payload.tolerance_pct,
        "valid_until": valid_until_for(payload.validity_days),
        "date": _now(),
        "positions": positions,
        "intro_text": payload.intro_text,
        "closing_text": payload.closing_text,
        "payment_terms": payload.payment_terms,
        "surcharge": payload.surcharge,
        "surcharge_description": payload.surcharge_description,
        "total_discount_pct": payload.total_discount_pct,
    }
    return build_pdf(org, customer, ce, totals)


@router.post("/preview")
async def preview_pdf(
    payload: CostEstimateUpsert, user: CurrentUser = Depends(require_org)
) -> Response:
    pdf_bytes = await run_in_threadpool(_preview_pdf, user.org_id, payload)
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="vorschau.pdf"'})


# ─── Actions: send / duplicate / status ──────────────────────────────────────
@router.post("/{ce_id}/send")
async def send_estimate(
    ce_id: str, payload: CostEstimateSend, user: CurrentUser = Depends(require_org)
) -> dict:
    def _send() -> dict | None:
        client = get_service_client()
        res = (
            client.table("cost_estimates")
            .update({"status": "sent", "sent_at": _now()})
            .eq("org_id", user.org_id).eq("id", ce_id).execute()
        )
        return res.data[0] if res.data else None

    row = await run_in_threadpool(_send)
    if not row:
        raise HTTPException(status_code=404, detail="Cost estimate not found")
    # SMTP not configured in this environment → record the send and report success.
    return {"success": True, "status": "sent", "emailed": False, "to": payload.to}


@router.post("/{ce_id}/duplicate")
async def duplicate_estimate(ce_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    def _dup() -> dict | None:
        client = get_service_client()
        rows = (
            client.table("cost_estimates").select("*").eq("org_id", user.org_id)
            .eq("id", ce_id).limit(1).execute().data
        )
        if not rows:
            return None
        src = rows[0]
        for k in ("id", "number", "created_at", "updated_at", "sent_at", "accepted_at",
                  "rejected_at", "invoice_id"):
            src.pop(k, None)
        src["status"] = "draft"
        src["number"] = gen_number(client, user.org_id, src.get("type") or "kva")
        return client.table("cost_estimates").insert(src).execute().data[0]

    row = await run_in_threadpool(_dup)
    if not row:
        raise HTTPException(status_code=404, detail="Cost estimate not found")
    return row


@router.patch("/{ce_id}/status")
async def set_status(
    ce_id: str, payload: CostEstimateStatus, user: CurrentUser = Depends(require_org)
) -> dict:
    stamp = {"accepted": "accepted_at", "rejected": "rejected_at"}.get(payload.status)
    fields = {"status": payload.status}
    if stamp:
        fields[stamp] = _now()

    def _set() -> dict | None:
        client = get_service_client()
        res = (
            client.table("cost_estimates").update(fields).eq("org_id", user.org_id)
            .eq("id", ce_id).execute()
        )
        return res.data[0] if res.data else None

    row = await run_in_threadpool(_set)
    if not row:
        raise HTTPException(status_code=404, detail="Cost estimate not found")
    return row
