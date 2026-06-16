from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org, require_org_admin
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
from app.services import email_templates
from app.services.common import run_parallel, validate_fk_in_org
from app.services.email_send import Attachment, send_email

router = APIRouter(prefix="/api/cost-estimates", tags=["cost-estimates"])

# Status → timestamp column for the generic PATCH /status endpoint. Mirrors
# invoices._STAMP. The dedicated POST /send route stamps sent_at directly, but
# a status-transition to "sent" through this endpoint must also fill it, or
# the AI Insights `kva_followup` suggestion (dashboard._ai_insights) silently
# never fires for that KVA because it gates on a non-NULL sent_at.
_STAMP = {"sent": "sent_at", "accepted": "accepted_at", "rejected": "rejected_at"}


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

    # The customer and inquiry enrichment reads are independent → run concurrently.
    def _fetch_customers():
        if not cust_ids:
            return []
        return (
            client.table("customers").select("id, full_name, email").eq("org_id", org_id)
            .in_("id", list(cust_ids)).execute().data or []
        )

    def _fetch_inquiries():
        if not inq_ids:
            return []
        return (
            client.table("inquiries").select("id, title").eq("org_id", org_id)
            .in_("id", list(inq_ids)).execute().data or []
        )

    cust_rows, inq_rows = run_parallel(_fetch_customers, _fetch_inquiries)
    customers: dict[str, dict] = {c["id"]: c for c in cust_rows}
    inquiries: dict[str, str] = {i["id"]: i.get("title") for i in inq_rows}
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
        "case_id": payload.case_id,
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


def _validate_fks(client, org_id: str, payload: CostEstimateUpsert) -> None:
    """Reject cross-tenant customer/inquiry/case ids (service-role bypasses RLS).
    payload.case_id is the grouping pointer → the `cases` table (FL-)."""
    validate_fk_in_org(client, table="customers", fk_id=payload.customer_id, org_id=org_id, label="Kunde")
    validate_fk_in_org(client, table="inquiries", fk_id=payload.inquiry_id, org_id=org_id, label="Anfrage")
    validate_fk_in_org(client, table="cases", fk_id=payload.case_id, org_id=org_id, label="Fall")


def _create(org_id: str, user_id: str | None, payload: CostEstimateUpsert) -> dict:
    client = get_service_client()
    _validate_fks(client, org_id, payload)
    row = _build_row(org_id, payload, user_id)
    # Case grouping: a KVA for an inquiry belongs to that inquiry's
    # Fall (case) — inherit it when the form didn't set one explicitly.
    if row.get("inquiry_id") and not row.get("case_id"):
        inq = (
            client.table("inquiries").select("case_id")
            .eq("org_id", org_id).eq("id", row["inquiry_id"]).limit(1).execute().data
        )
        if inq and inq[0].get("case_id"):
            row["case_id"] = inq[0]["case_id"]
    row["number"] = gen_number(client, org_id, payload.type)
    row["status"] = "draft"
    return client.table("cost_estimates").insert(row).execute().data[0]


@router.post("")
async def create_estimate(
    payload: CostEstimateUpsert, user: CurrentUser = Depends(require_org_admin)
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
    _validate_fks(client, org_id, payload)
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
    ce_id: str, payload: CostEstimateUpsert, user: CurrentUser = Depends(require_org_admin)
) -> dict:
    row = await run_in_threadpool(_update, user.org_id, ce_id, payload)
    if not row:
        raise HTTPException(status_code=404, detail="Cost estimate not found")
    return row


@router.delete("/{ce_id}")
async def delete_estimate(ce_id: str, user: CurrentUser = Depends(require_org_admin)) -> dict:
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
    payload: CostEstimateUpsert, user: CurrentUser = Depends(require_org_admin)
) -> Response:
    pdf_bytes = await run_in_threadpool(_preview_pdf, user.org_id, payload)
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="vorschau.pdf"'})


# ─── Actions: send / duplicate / status ──────────────────────────────────────
def _build_kva_email(
    *,
    ce_row: dict,
    org: dict,
    customer: dict | None,
    email_config: dict | None,
    payload: CostEstimateSend,
) -> tuple[str, str]:
    """Render subject + HTML body for the KVA / Angebot / AB email.

    Customer-stored templates (``kva_email_subject`` / ``kva_email_body``)
    win, then the request payload's ``subject`` / ``message``, then a sane
    German default. Variables ``{number}`` / ``{customer_name}`` /
    ``{org_name}`` are substituted in templates.
    """
    doc_type = ce_row.get("type") or "kva"
    type_label = {
        "kva": "Kostenvoranschlag",
        "offer": "Angebot",
        "order_confirmation": "Auftragsbestätigung",
    }.get(doc_type, "Kostenvoranschlag")
    number = ce_row.get("number") or "—"
    org_name = org.get("name") or "HeyKiki"
    cust_name = (customer or {}).get("full_name") or ""

    tpl_subject = (email_config or {}).get("kva_email_subject")
    tpl_body = (email_config or {}).get("kva_email_body")

    subject = (
        payload.subject
        or (email_templates.substitute(
            tpl_subject, number=number, customer_name=cust_name, org_name=org_name,
            firmenname=org_name, kundename=cust_name, rechnungsnummer=number, kvanummer=number,
        ) if tpl_subject else None)
        or f"{type_label} {number} von {org_name}"
    )
    if payload.message:
        body_text = payload.message
    elif tpl_body:
        body_text = email_templates.substitute(
            tpl_body, number=number, customer_name=cust_name, org_name=org_name,
            firmenname=org_name, kundename=cust_name, rechnungsnummer=number, kvanummer=number,
        )
    else:
        greeting = f"Sehr geehrte/r {cust_name}," if cust_name else "Guten Tag,"
        body_text = (
            f"{greeting}\n\n"
            f"anbei senden wir Ihnen den {type_label} {number}.\n\n"
            f"Bei Rückfragen stehen wir Ihnen gerne zur Verfügung.\n\n"
            f"Mit freundlichen Grüßen\n{org_name}"
        )
    body_html = email_templates.render_message_email(
        company_name=org_name, message_text=body_text,
        contact_email=org.get("email"), address=email_templates.addr_line(org.get("address")),
    )
    return subject, body_html


@router.post("/{ce_id}/send")
async def send_estimate(
    ce_id: str, payload: CostEstimateSend, user: CurrentUser = Depends(require_org_admin)
) -> dict:
    def _load() -> dict | None:
        client = get_service_client()
        rows = (
            client.table("cost_estimates").select("*")
            .eq("org_id", user.org_id).eq("id", ce_id).limit(1).execute().data
        )
        return rows[0] if rows else None

    row = await run_in_threadpool(_load)
    if not row:
        raise HTTPException(status_code=404, detail="Cost estimate not found")

    # Determine the recipient: payload override → customer.email → 400.
    def _resolve_to() -> tuple[str | None, dict | None, dict, dict | None]:
        client = get_service_client()
        org = fetch_org(client, user.org_id)
        customer = fetch_customer(client, user.org_id, row.get("customer_id"))
        ec = (
            client.table("email_configs").select("*")
            .eq("org_id", user.org_id).limit(1).execute().data or [None]
        )[0]
        return ((customer or {}).get("email") if not payload.to else payload.to), customer, org, ec

    to_email, customer, org, email_config = await run_in_threadpool(_resolve_to)
    if not to_email:
        raise HTTPException(
            status_code=400,
            detail="Keine Empfänger-E-Mail vorhanden — bitte beim Kunden hinterlegen oder im Sende-Dialog angeben.",
        )

    # Render the PDF, then build + send.
    def _render_pdf() -> bytes:
        client = get_service_client()
        org_local = fetch_org(client, user.org_id)
        cust_local = fetch_customer(client, user.org_id, row.get("customer_id"))
        ce = _ce_for_pdf(row)
        totals = compute_totals(
            ce.get("positions") or [], ce.get("surcharge") or 0,
            ce.get("total_discount_pct") or 0,
        )
        return build_pdf(org_local, cust_local, ce, totals)

    pdf_bytes = await run_in_threadpool(_render_pdf)
    subject, body_html = _build_kva_email(
        ce_row=row, org=org, customer=customer,
        email_config=email_config, payload=payload,
    )
    filename = f"{(row.get('type') or 'kva').upper()}-{row.get('number') or 'entwurf'}.pdf"
    cc = [(org.get("email") or "").strip()] if payload.copy_to_me and org.get("email") else []

    try:
        result = await run_in_threadpool(
            send_email,
            org_id=user.org_id,
            to_email=to_email,
            subject=subject,
            body_html=body_html,
            attachments=[Attachment(filename=filename, content=pdf_bytes)],
            cc=cc,
            reply_to=(org.get("email") or None),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"E-Mail-Versand fehlgeschlagen: {exc}")

    # Only stamp status after a successful send so failed-send retries stay
    # in 'draft' instead of being misleadingly marked 'sent'.
    def _stamp() -> dict | None:
        client = get_service_client()
        res = (
            client.table("cost_estimates")
            .update({"status": "sent", "sent_at": _now()})
            .eq("org_id", user.org_id).eq("id", ce_id).execute()
        )
        return res.data[0] if res.data else None

    await run_in_threadpool(_stamp)
    return {
        "success": True,
        "status": "sent",
        "emailed": True,
        "to": to_email,
        "provider_used": result.provider_used,
        "fallback_chain": result.fallback_chain,
    }


@router.post("/{ce_id}/duplicate")
async def duplicate_estimate(ce_id: str, user: CurrentUser = Depends(require_org_admin)) -> dict:
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
    ce_id: str, payload: CostEstimateStatus, user: CurrentUser = Depends(require_org_admin)
) -> dict:
    fields = {"status": payload.status}
    stamp = _STAMP.get(payload.status)
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
