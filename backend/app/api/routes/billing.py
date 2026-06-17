"""Tradesperson-facing billing reads (Phase 1). All require_org; org_id from the
JWT, never the request body. Pure reads go through ``stripe_read``; the only
write-ish op is creating a billing-portal session.
"""

from __future__ import annotations

import logging

import stripe
from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.core.config import settings
from app.db.supabase_client import get_service_client
from app.schemas.billing import (
    BillingInvoice,
    BillingSummary,
    CheckoutRequest,
    CheckoutResponse,
    PaymentMethod,
    PlanOption,
    PortalSessionResponse,
    UpcomingInvoice,
)
from app.services.common import month_start_utc_iso, now_berlin
from app.services.stripe_billing import (
    StripeBillingError,
    get_stripe,
    is_configured,
    stripe_call_safely,
    stripe_read,
)

router = APIRouter(prefix="/api/billing", tags=["billing"])
log = logging.getLogger(__name__)


# ─── Helpers ─────────────────────────────────────────────────────────────────
def _org(client, org_id: str) -> dict:
    rows = (
        client.table("organizations").select("*").eq("id", org_id).limit(1).execute().data
    )
    return rows[0] if rows else {}


def _used_minutes(client, org_id: str, period_start_iso: str | None) -> int:
    """Sum call minutes since the period start (Stripe billing period, else month).

    Mirrors settings._usage exactly (round(sum(duration_seconds)/60)) so the
    'minutes used' shown in Abrechnung matches the rest of the app."""
    start = period_start_iso or month_start_utc_iso()
    calls = (
        client.table("calls")
        .select("duration_seconds")
        .eq("org_id", org_id)
        .gte("created_at", start)
        .execute()
        .data
        or []
    )
    return round(sum((c.get("duration_seconds") or 0) for c in calls) / 60)


def _map_invoice(i: dict) -> BillingInvoice:
    return BillingInvoice(
        id=i.get("id"),
        number=i.get("number"),
        status=i.get("status"),
        amount_due_cents=i.get("amount_due"),
        amount_paid_cents=i.get("amount_paid"),
        currency=i.get("currency"),
        created=i.get("created"),
        period_start=i.get("period_start"),
        period_end=i.get("period_end"),
        hosted_invoice_url=i.get("hosted_invoice_url"),
        invoice_pdf=i.get("invoice_pdf"),
    )


# ─── GET /api/billing/summary ────────────────────────────────────────────────
def _summary(org_id: str) -> BillingSummary:
    client = get_service_client()
    org = _org(client, org_id)
    customer_id = org.get("stripe_customer_id")
    quota = org.get("billing_quota_minutes") or org.get("ai_minutes_quota") or 0
    period_start = org.get("billing_period_start")
    used = _used_minutes(client, org_id, period_start)
    used_percent = round(used / quota * 100) if quota else 0

    next_amount: int | None = None
    if customer_id and is_configured():
        # 'No upcoming invoice' is an EXPECTED state (unsubscribed customer) — handle
        # inline so it never floods billing_events with benign 'failed' rows.
        try:
            s = get_stripe()
            upcoming = s.Invoice.upcoming(customer=customer_id)
            next_amount = upcoming.get("amount_due")
        except stripe.error.InvalidRequestError:  # type: ignore[attr-defined]
            next_amount = None
        except stripe.error.StripeError:  # type: ignore[attr-defined]
            next_amount = None  # best-effort; summary must still render

    return BillingSummary(
        configured=bool(customer_id),
        plan_title=org.get("billing_plan_title"),
        status=org.get("billing_status"),
        period_start=period_start,
        period_end=org.get("billing_period_end"),
        quota_minutes=int(quota),
        used_minutes=int(used),
        used_percent=int(used_percent),
        over_quota=bool(quota and used > quota),
        next_invoice_amount_cents=next_amount,
    )


@router.get("/summary", response_model=BillingSummary)
async def billing_summary(user: CurrentUser = Depends(require_org)) -> BillingSummary:
    return await run_in_threadpool(_summary, user.org_id)


# ─── GET /api/billing/invoices ───────────────────────────────────────────────
def _invoices(org_id: str, limit: int) -> list[BillingInvoice]:
    client = get_service_client()
    customer_id = _org(client, org_id).get("stripe_customer_id")
    if not customer_id or not is_configured():
        return []
    result = stripe_read(
        op="invoice.list",
        org_id=org_id,
        fn=lambda: get_stripe().Invoice.list(customer=customer_id, limit=limit),
    )
    return [_map_invoice(i) for i in (result.get("data") or [])]


@router.get("/invoices", response_model=list[BillingInvoice])
async def billing_invoices(
    user: CurrentUser = Depends(require_org),
    limit: int = Query(default=12, ge=1, le=100),
) -> list[BillingInvoice]:
    return await run_in_threadpool(_invoices, user.org_id, limit)


# ─── GET /api/billing/upcoming-invoice ───────────────────────────────────────
def _upcoming(org_id: str) -> UpcomingInvoice | None:
    client = get_service_client()
    customer_id = _org(client, org_id).get("stripe_customer_id")
    if not customer_id or not is_configured():
        return None
    try:
        up = get_stripe().Invoice.upcoming(customer=customer_id)
    except stripe.error.InvalidRequestError:  # type: ignore[attr-defined]
        return None  # no upcoming invoice (unsubscribed) — expected
    except stripe.error.StripeError:  # type: ignore[attr-defined]
        return None
    return UpcomingInvoice(
        amount_due_cents=up.get("amount_due"),
        currency=up.get("currency"),
        period_start=up.get("period_start"),
        period_end=up.get("period_end"),
    )


@router.get("/upcoming-invoice", response_model=UpcomingInvoice | None)
async def billing_upcoming(user: CurrentUser = Depends(require_org)) -> UpcomingInvoice | None:
    return await run_in_threadpool(_upcoming, user.org_id)


# ─── GET /api/billing/payment-methods ────────────────────────────────────────
def _payment_methods(org_id: str) -> list[PaymentMethod]:
    client = get_service_client()
    customer_id = _org(client, org_id).get("stripe_customer_id")
    if not customer_id or not is_configured():
        return []
    result = stripe_read(
        op="payment_method.list",
        org_id=org_id,
        fn=lambda: get_stripe().PaymentMethod.list(customer=customer_id, type="card"),
    )
    out: list[PaymentMethod] = []
    for pm in result.get("data") or []:
        card = pm.get("card") or {}
        out.append(
            PaymentMethod(
                id=pm.get("id"),
                type=pm.get("type"),
                brand=card.get("brand"),
                last4=card.get("last4"),
                exp_month=card.get("exp_month"),
                exp_year=card.get("exp_year"),
            )
        )
    return out


@router.get("/payment-methods", response_model=list[PaymentMethod])
async def billing_payment_methods(
    user: CurrentUser = Depends(require_org),
) -> list[PaymentMethod]:
    return await run_in_threadpool(_payment_methods, user.org_id)


# ─── POST /api/billing/portal-session ────────────────────────────────────────
def _portal_session(org_id: str, actor_id: str) -> PortalSessionResponse:
    client = get_service_client()
    customer_id = _org(client, org_id).get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(
            status_code=400,
            detail="Für diese Organisation ist noch keine Abrechnung eingerichtet.",
        )
    return_url = settings.billing_portal_return_url or (
        settings.frontend_public_url.rstrip("/") + "/settings/abrechnung"
    )
    # Pass our own configuration (self-service cancellation disabled) — this also
    # removes Stripe's 'default configuration not created' error, the most common
    # cause of the portal-session 502.
    from app.services.stripe_provisioning import ensure_portal_configuration

    config_id = ensure_portal_configuration()

    def _build(idem, meta):
        params: dict = {"customer": customer_id, "return_url": return_url}
        if config_id:
            params["configuration"] = config_id
        return get_stripe().billing_portal.Session.create(**params)

    try:
        session = stripe_call_safely(
            op="portal_session.create",
            org_id=org_id,
            actor_id=actor_id,
            stripe_object=customer_id,
            request_payload={"customer": customer_id, "return_url": return_url, "configuration": config_id},
            builder=_build,
        )
    except StripeBillingError as exc:
        # Surface the underlying Stripe reason in the logs so a recurring 502 is
        # diagnosable (the customer still gets a clean German message).
        log.warning("billing portal session failed (org=%s, config=%s): %s", org_id, config_id, exc)
        raise HTTPException(status_code=502, detail="Stripe-Portal konnte nicht geöffnet werden.") from exc
    return PortalSessionResponse(url=session.get("url"))


@router.post("/portal-session", response_model=PortalSessionResponse)
async def billing_portal_session(
    user: CurrentUser = Depends(require_org),
) -> PortalSessionResponse:
    return await run_in_threadpool(_portal_session, user.org_id, user.id)


# ─── GET /api/billing/plans (catalog for the subscribe UI) ───────────────────
def _plans() -> list[PlanOption]:
    from app.services.stripe_catalog import ANNUAL_MONTHS, PLANS

    return [
        PlanOption(
            plan_title=title,
            included_minutes=spec["minutes"],
            monthly_cents=spec["monthly_cents"],
            annual_cents=spec["monthly_cents"] * ANNUAL_MONTHS,
            overage_cents_per_min=spec["overage_cents"],
        )
        for title, spec in PLANS.items()
    ]


@router.get("/plans", response_model=list[PlanOption])
async def billing_plans(user: CurrentUser = Depends(require_org)) -> list[PlanOption]:
    return await run_in_threadpool(_plans)


# ─── POST /api/billing/checkout-session (subscribe) ──────────────────────────
def _checkout(org_id: str, actor_id: str, body: CheckoutRequest) -> CheckoutResponse:
    from app.services.stripe_provisioning import create_checkout_session

    try:
        result = create_checkout_session(
            org_id, body.plan_title, body.interval, trial_days=body.trial_days, actor_id=actor_id
        )
    except StripeBillingError as exc:
        raise HTTPException(status_code=502, detail=f"Checkout fehlgeschlagen: {exc}") from exc
    return CheckoutResponse(url=result["url"], session_id=result["session_id"])


@router.post("/checkout-session", response_model=CheckoutResponse)
async def billing_checkout(
    body: CheckoutRequest, user: CurrentUser = Depends(require_org)
) -> CheckoutResponse:
    return await run_in_threadpool(_checkout, user.org_id, user.id, body)


# ─── POST /api/billing/sync (webhook fallback) ───────────────────────────────
_LIVE_SUB_STATES = {"active", "trialing", "past_due", "unpaid"}


def _pick_primary_subscription(subs: list) -> dict | None:
    """Pick the subscription that best represents the org's plan.

    Prefer a live one (active/trialing/past_due/unpaid) over canceled/incomplete;
    break ties by most-recently created. ``None`` for a customer with no subs."""
    if not subs:
        return None
    return max(
        subs,
        key=lambda s: (1 if s.get("status") in _LIVE_SUB_STATES else 0, int(s.get("created") or 0)),
    )


def _sync(org_id: str) -> BillingSummary:
    """Pull the org's current Stripe subscription and sync it onto ``organizations``.

    Webhook fallback: Stripe webhooks can't reach localhost (and aren't yet live),
    so after a self-serve Checkout the frontend calls this on ``?checkout=success``
    to reflect the new subscription immediately. Pure inbound read + state-sync —
    it reuses the webhook's ``_handle_subscription`` and NEVER writes to Stripe, so
    it's safe to call at any time (idempotent, no-op when nothing has changed)."""
    client = get_service_client()
    customer_id = _org(client, org_id).get("stripe_customer_id")
    if customer_id and is_configured():
        result = stripe_read(
            op="subscription.list",
            org_id=org_id,
            fn=lambda: get_stripe().Subscription.list(
                customer=customer_id, status="all", limit=10
            ),
        )
        sub = _pick_primary_subscription((result or {}).get("data") or [])
        if sub is not None:
            from app.services.stripe_webhook import _handle_subscription

            _handle_subscription(client, sub)
    return _summary(org_id)


@router.post("/sync", response_model=BillingSummary)
async def billing_sync(user: CurrentUser = Depends(require_org)) -> BillingSummary:
    return await run_in_threadpool(_sync, user.org_id)
