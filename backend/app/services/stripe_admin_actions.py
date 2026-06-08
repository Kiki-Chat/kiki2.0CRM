"""Phase 2 — super-admin billing WRITE actions. All audited via stripe_call_safely.

- approve_match: the customer-link write-back deferred from Phase 1 — writes
  heykiki_org_id into the Stripe customer's metadata (ADDITIVE) + links the org.
- reject_match: mark a proposal rejected.
- retry_payment: attempt to collect the org's open invoice.
- cancel_subscription: cancel at period end — REFUSED on legacy Connect subs
  (the stripe_call_safely Connect block raises ConnectAttributionError).
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.db.supabase_client import get_service_client
from app.services.stripe_billing import StripeBillingError, get_stripe, stripe_call_safely


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def approve_match(match_id: str, reviewer_id: str | None) -> dict:
    """Approve a dry-run match: write-back heykiki_org_id to Stripe + link the org."""
    db = get_service_client()
    rows = db.table("billing_migration_log").select("*").eq("id", match_id).limit(1).execute().data
    if not rows:
        raise StripeBillingError(f"match {match_id} not found")
    m = rows[0]
    if m.get("status") != "proposed":
        raise StripeBillingError(f"match is '{m.get('status')}', not 'proposed'")
    customer_id = m.get("stripe_customer_id")
    org_id = m.get("org_id")
    if not customer_id:
        raise StripeBillingError("match has no Stripe customer to link")

    # Cross-org guard: never link a customer already owned by a different org.
    other = (
        db.table("organizations").select("id").eq("stripe_customer_id", customer_id).neq("id", org_id).limit(1).execute().data
    )
    if other:
        raise StripeBillingError(f"customer {customer_id} is already linked to another org")

    org_rows = db.table("organizations").select("heykiki_org_id").eq("id", org_id).limit(1).execute().data
    heykiki_org_id = org_rows[0].get("heykiki_org_id") if org_rows else None

    existing_meta: dict = {}
    try:
        existing_meta = get_stripe().Customer.retrieve(customer_id).get("metadata") or {}
    except Exception:  # noqa: BLE001 — fall back to empty; merge still additive
        existing_meta = {}

    stripe_call_safely(
        op="customer.metadata_writeback",
        org_id=org_id,
        actor_id=reviewer_id,
        stripe_object=customer_id,
        metadata_existing=existing_meta,
        metadata_merge={"heykiki_org_id": heykiki_org_id, "org_id": str(org_id)},
        idempotency_payload={"match_id": match_id},
        request_payload={"customer": customer_id, "match_id": match_id},
        builder=lambda idem, meta: get_stripe().Customer.modify(customer_id, metadata=meta, idempotency_key=idem),
    )

    db.table("organizations").update(
        {"stripe_customer_id": customer_id, "billing_last_sync_at": _now()}
    ).eq("id", org_id).execute()
    db.table("billing_migration_log").update(
        {"status": "approved", "reviewed_by": str(reviewer_id) if reviewer_id else None, "reviewed_at": _now()}
    ).eq("id", match_id).execute()
    return {"status": "approved", "org_id": org_id, "stripe_customer_id": customer_id}


def reject_match(match_id: str, reviewer_id: str | None) -> dict:
    db = get_service_client()
    db.table("billing_migration_log").update(
        {"status": "rejected", "reviewed_by": str(reviewer_id) if reviewer_id else None, "reviewed_at": _now()}
    ).eq("id", match_id).eq("status", "proposed").execute()
    return {"status": "rejected", "match_id": match_id}


def retry_payment(org_id: str, actor_id: str | None) -> dict:
    db = get_service_client()
    rows = db.table("organizations").select("stripe_customer_id").eq("id", org_id).limit(1).execute().data
    customer_id = rows[0].get("stripe_customer_id") if rows else None
    if not customer_id:
        raise StripeBillingError("org has no Stripe customer")
    open_invoices = get_stripe().Invoice.list(customer=customer_id, status="open", limit=1).data
    if not open_invoices:
        return {"status": "no_open_invoice"}
    invoice_id = open_invoices[0]["id"]
    result = stripe_call_safely(
        op="invoice.pay",
        org_id=org_id,
        actor_id=actor_id,
        stripe_object=invoice_id,
        request_payload={"invoice": invoice_id},
        idempotency_payload={"invoice": invoice_id},
        builder=lambda idem, meta: get_stripe().Invoice.pay(invoice_id, idempotency_key=idem),
    )
    return {"status": result.get("status"), "invoice": invoice_id}


def cancel_subscription(org_id: str, actor_id: str | None) -> dict:
    db = get_service_client()
    rows = db.table("organizations").select("billing_subscription_id").eq("id", org_id).limit(1).execute().data
    sub_id = rows[0].get("billing_subscription_id") if rows else None
    if not sub_id:
        raise StripeBillingError("org has no active subscription")
    result = stripe_call_safely(
        op="subscription.cancel_at_period_end",
        org_id=org_id,
        actor_id=actor_id,
        subscription_id=sub_id,  # → Connect block refuses legacy ChatDash subs
        stripe_object=sub_id,
        request_payload={"subscription": sub_id, "cancel_at_period_end": True},
        builder=lambda idem, meta: get_stripe().Subscription.modify(
            sub_id, cancel_at_period_end=True, idempotency_key=idem
        ),
    )
    return {"status": "cancel_scheduled", "subscription": sub_id, "cancel_at_period_end": result.get("cancel_at_period_end")}
