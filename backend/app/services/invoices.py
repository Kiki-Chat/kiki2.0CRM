"""Invoice (Rechnung) helpers: numbering, date math, and back-office auto-draft.

Totals and the PDF renderer are shared with the cost-estimate module
(`app/services/cost_estimates.py`); `build_pdf` renders a RECHNUNG when the
document dict carries `type="invoice"`.
"""

import logging
from datetime import date, timedelta

from app.db.supabase_client import get_service_client
from app.services.common import now_berlin

logger = logging.getLogger(__name__)


def gen_invoice_number(client, org_id: str) -> str:
    year = now_berlin().year
    res = (
        client.table("invoices")
        .select("id", count="exact")
        .eq("org_id", org_id)
        .gte("created_at", f"{year}-01-01")
        .execute()
    )
    return f"RE-{year}-{(res.count or 0) + 1:05d}"


def add_days(iso_date: str | None, days) -> str | None:
    """Add `days` to an ISO date string (used to derive the due date)."""
    if not iso_date:
        return None
    try:
        d = date.fromisoformat(str(iso_date)[:10])
    except ValueError:
        return None
    return (d + timedelta(days=int(days or 0))).isoformat()


def today_iso() -> str:
    return now_berlin().date().isoformat()


def maybe_create_invoice_for_project(
    org_id: str, case: dict, user_id: str | None = None, client=None
) -> dict | None:
    """Back-office automation (topic 19): when a **Fall (case)** is marked
    'completed', auto-draft an invoice from the case's ACCEPTED KVA, gated by
    agent_configs.invoices_enabled + invoices_level.

    Case↔Project split (migration 0073): KVAs and invoices anchor on
    ``case_id`` now (the renamed former ``project_id`` column → ``cases`` table),
    so the lookup keys on the case id. The public name is kept for callers; the
    ``case`` row carries the project-style schema (id / number / customer_id).

    off / level 1 → nothing. Levels 2 and 3 → a 'draft' invoice (one per case).
    NOTE: the actual e-mail SEND (the L3 "auto-send" step) is intentionally NOT
    done here — it rides the separate Brevo/e-mail-send chain. Best-effort: never
    raises (a failure must not roll back the case update)."""
    try:
        case_id = case.get("id")
        if not case_id:
            return None
        client = client or get_service_client()
        cfg = (
            client.table("agent_configs")
            .select("invoices_enabled, invoices_level")
            .eq("org_id", org_id)
            .limit(1)
            .execute()
            .data
        )
        row = cfg[0] if cfg else {}
        if not row.get("invoices_enabled"):
            return None
        try:
            level = int(row.get("invoices_level") or 2)
        except (TypeError, ValueError):
            level = 2
        if level <= 1:
            return None
        # One auto-invoice per case.
        existing = (
            client.table("invoices")
            .select("id")
            .eq("org_id", org_id)
            .eq("case_id", case_id)
            .limit(1)
            .execute()
            .data
        )
        if existing:
            return None
        # Source = the case's ACCEPTED KVA (only invoice an agreed quote).
        kvas = (
            client.table("cost_estimates")
            .select("id, customer_id, line_items, subtotal, vat_amount, total")
            .eq("org_id", org_id)
            .eq("case_id", case_id)
            .eq("type", "kva")
            .eq("status", "accepted")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        kva = kvas[0] if kvas else None
        if not kva:
            return None  # nothing agreed to invoice
        inv_date = today_iso()
        inv = {
            "org_id": org_id,
            "customer_id": kva.get("customer_id") or case.get("customer_id"),
            "cost_estimate_id": kva["id"],
            "case_id": case_id,
            "subject": f"Rechnung zu Vorgang {case.get('number') or ''}".strip(),
            "invoice_date": inv_date,
            "payment_terms_days": 14,
            "due_date": add_days(inv_date, 14),
            "line_items": kva.get("line_items") or [],
            "subtotal": kva.get("subtotal"),
            "vat_amount": kva.get("vat_amount"),
            "total": kva.get("total"),
            "number": gen_invoice_number(client, org_id),
            "status": "draft",
            "created_by": user_id,
        }
        created = client.table("invoices").insert(inv).execute().data
        invoice = created[0] if created else None
        if invoice:
            # Mirror the manual KVA→invoice link.
            (
                client.table("cost_estimates")
                .update({"status": "invoiced", "invoice_id": invoice["id"]})
                .eq("org_id", org_id)
                .eq("id", kva["id"])
                .execute()
            )
        return invoice
    except Exception:  # noqa: BLE001 — never break the case update
        logger.exception("invoice auto-draft failed for case %s", case.get("id"))
        return None
