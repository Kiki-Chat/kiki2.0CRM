"""Pydantic response models for the billing module (Phase 1, read-only)."""

from __future__ import annotations

from pydantic import BaseModel


# ─── Tradesperson-facing ─────────────────────────────────────────────────────
class BillingSummary(BaseModel):
    configured: bool                       # True once the org has a Stripe customer
    plan_title: str | None = None
    status: str | None = None              # active|trialing|past_due|unpaid|canceled|…
    period_start: str | None = None
    period_end: str | None = None
    quota_minutes: int = 0                 # included minutes for the plan
    used_minutes: int = 0
    used_percent: int = 0
    over_quota: bool = False               # soft stop: overage is billed, agent stays online
    # Extra-usage (overage) breakdown — minutes beyond quota_minutes bill at the
    # plan's metered tier (overage_cents_per_min). projected_overage_cents is the
    # running extra charge for the current period (minutes_over × tariff, NET).
    overage_cents_per_min: int | None = None
    minutes_over: int = 0
    projected_overage_cents: int | None = None
    next_invoice_amount_cents: int | None = None
    currency: str = "eur"


class BillingInvoice(BaseModel):
    id: str
    number: str | None = None
    status: str | None = None
    amount_due_cents: int | None = None
    amount_paid_cents: int | None = None
    currency: str | None = None
    created: int | None = None
    period_start: int | None = None
    period_end: int | None = None
    hosted_invoice_url: str | None = None
    invoice_pdf: str | None = None


class UpcomingInvoice(BaseModel):
    amount_due_cents: int | None = None
    currency: str | None = None
    period_start: int | None = None
    period_end: int | None = None


class PaymentMethod(BaseModel):
    id: str
    type: str | None = None
    brand: str | None = None
    last4: str | None = None
    exp_month: int | None = None
    exp_year: int | None = None


class PortalSessionResponse(BaseModel):
    url: str


class CheckoutRequest(BaseModel):
    plan_title: str
    interval: str = "month"
    # The app origin the user is on (window.location.origin). The post-checkout
    # redirect returns here so the user lands back on the SAME app, logged in —
    # instead of a baked PUBLIC_URL that may differ and bounce them to /login.
    return_origin: str | None = None


class CheckoutResponse(BaseModel):
    url: str
    session_id: str


class ChangePlanRequest(BaseModel):
    plan_title: str                        # target plan; must be a strict upgrade


class PlanOption(BaseModel):
    plan_title: str
    included_minutes: int
    monthly_cents: int
    annual_cents: int
    overage_cents_per_min: int


# ─── Super-admin ─────────────────────────────────────────────────────────────
class AdminBillingOverview(BaseModel):
    total_orgs: int
    by_status: dict[str, int]
    delinquent_count: int
    unlinked_orgs: int
    mrr_estimate_cents: int
    revenue_ytd_cents: int
    currency: str = "eur"


class AdminOrgBilling(BaseModel):
    org_id: str
    org_name: str | None = None
    stripe_customer_id: str | None = None
    billing_status: str | None = None
    billing_plan_title: str | None = None
    billing_subscription_id: str | None = None
    is_legacy: bool = False                 # Connect-attributed sub ⇒ read-only in CRM
    quota_minutes: int | None = None
    period_start: str | None = None
    period_end: str | None = None
    last_sync_at: str | None = None


class StripeHealth(BaseModel):
    configured: bool = False
    charges_enabled: bool | None = None
    payouts_enabled: bool | None = None
    default_currency: str | None = None
    requirements_past_due: list[str] = []
    requirements_currently_due: list[str] = []
    requirements_eventually_due: list[str] = []
    disabled_reason: str | None = None


class MigrationMatch(BaseModel):
    id: str
    org_id: str
    org_name: str | None = None
    stripe_customer_id: str | None = None
    match_method: str | None = None
    match_confidence: float | None = None
    candidate: dict | None = None
    status: str
    created_at: str | None = None
