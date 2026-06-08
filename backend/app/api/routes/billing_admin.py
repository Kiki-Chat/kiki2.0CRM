"""Super-admin billing dashboard (Phase 1, read-only cross-tenant).

All endpoints require_super_admin. Reads org billing_* state from the DB and
surfaces account health / migration proposals. The only write is run-matcher,
which writes proposals to billing_migration_log (never to Stripe).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_super_admin
from app.db.supabase_client import get_service_client
from app.services.stripe_admin_actions import (
    approve_match,
    cancel_subscription,
    reject_match,
    retry_payment,
)
from app.services.stripe_billing import ConnectAttributionError, StripeBillingError
from app.schemas.billing import (
    AdminBillingOverview,
    AdminOrgBilling,
    MigrationMatch,
    StripeHealth,
)
from app.services.stripe_billing import get_stripe, is_configured, stripe_read
from app.services.stripe_matcher import propose_matches

router = APIRouter(prefix="/api/super-admin/billing", tags=["super-admin-billing"])

_DELINQUENT = {"past_due", "unpaid"}


# ─── Overview ────────────────────────────────────────────────────────────────
def _estimate_mrr_and_revenue() -> tuple[int, int]:
    """Best-effort MRR + YTD revenue from Stripe (auto-paged, bounded, fail-soft)."""
    if not is_configured():
        return 0, 0
    mrr = 0
    revenue = 0
    try:
        s = get_stripe()
        count = 0
        for sub in s.Subscription.list(status="active", limit=100).auto_paging_iter():
            for item in (sub.get("items") or {}).get("data") or []:
                price = item.get("price") or {}
                recurring = price.get("recurring") or {}
                if recurring.get("usage_type") == "metered":
                    continue  # overage is variable, not part of MRR
                amount = (price.get("unit_amount") or 0) * (item.get("quantity") or 1)
                if recurring.get("interval") == "year":
                    amount = amount // 12
                mrr += amount
            count += 1
            if count >= 1000:  # safety bound
                break
    except Exception:  # noqa: BLE001 — best-effort estimate
        pass
    try:
        s = get_stripe()
        now = datetime.now(timezone.utc)
        jan1 = int(datetime(now.year, 1, 1, tzinfo=timezone.utc).timestamp())
        count = 0
        for inv in s.Invoice.list(
            status="paid", created={"gte": jan1}, limit=100
        ).auto_paging_iter():
            revenue += inv.get("amount_paid") or 0
            count += 1
            if count >= 5000:  # safety bound
                break
    except Exception:  # noqa: BLE001
        pass
    return mrr, revenue


def _overview() -> AdminBillingOverview:
    client = get_service_client()
    orgs = (
        client.table("organizations")
        .select("id, billing_status, stripe_customer_id")
        .execute()
        .data
        or []
    )
    by_status: dict[str, int] = {}
    delinquent = 0
    unlinked = 0
    for o in orgs:
        st = o.get("billing_status") or "none"
        by_status[st] = by_status.get(st, 0) + 1
        if st in _DELINQUENT:
            delinquent += 1
        if not o.get("stripe_customer_id"):
            unlinked += 1
    mrr, revenue = _estimate_mrr_and_revenue()
    return AdminBillingOverview(
        total_orgs=len(orgs),
        by_status=by_status,
        delinquent_count=delinquent,
        unlinked_orgs=unlinked,
        mrr_estimate_cents=mrr,
        revenue_ytd_cents=revenue,
    )


@router.get("/overview", response_model=AdminBillingOverview)
async def overview(user: CurrentUser = Depends(require_super_admin)) -> AdminBillingOverview:
    return await run_in_threadpool(_overview)


# ─── Org list + detail ───────────────────────────────────────────────────────
def _map_org(r: dict) -> AdminOrgBilling:
    return AdminOrgBilling(
        org_id=r.get("id"),
        org_name=r.get("name"),
        stripe_customer_id=r.get("stripe_customer_id"),
        billing_status=r.get("billing_status"),
        billing_plan_title=r.get("billing_plan_title"),
        billing_subscription_id=r.get("billing_subscription_id"),
        is_legacy=bool(r.get("billing_subscription_application")),
        quota_minutes=r.get("billing_quota_minutes"),
        period_start=r.get("billing_period_start"),
        period_end=r.get("billing_period_end"),
        last_sync_at=r.get("billing_last_sync_at"),
    )


_ORG_COLS = (
    "id, name, stripe_customer_id, billing_status, billing_plan_title, "
    "billing_subscription_id, billing_subscription_application, billing_quota_minutes, "
    "billing_period_start, billing_period_end, billing_last_sync_at"
)


def _orgs(status: str | None, search: str | None, limit: int, offset: int) -> list[AdminOrgBilling]:
    client = get_service_client()
    q = client.table("organizations").select(_ORG_COLS)
    if status:
        q = q.eq("billing_status", status)
    if search:
        q = q.ilike("name", f"%{search}%")
    rows = q.order("name").range(offset, offset + limit - 1).execute().data or []
    return [_map_org(r) for r in rows]


@router.get("/orgs", response_model=list[AdminOrgBilling])
async def orgs(
    user: CurrentUser = Depends(require_super_admin),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[AdminOrgBilling]:
    return await run_in_threadpool(_orgs, status, search, limit, offset)


def _org_detail(org_id: str) -> dict:
    client = get_service_client()
    rows = client.table("organizations").select(_ORG_COLS).eq("id", org_id).limit(1).execute().data
    org = _map_org(rows[0]) if rows else None
    events = (
        client.table("billing_events")
        .select("id, created_at, event_type, stripe_object, status, error_code, error_message")
        .eq("org_id", org_id)
        .order("created_at", desc=True)
        .limit(20)
        .execute()
        .data
        or []
    )
    usage = (
        client.table("billing_usage_reports")
        .select("id, created_at, call_id, quantity_minutes, status, skip_reason")
        .eq("org_id", org_id)
        .order("created_at", desc=True)
        .limit(20)
        .execute()
        .data
        or []
    )
    return {"org": org.model_dump() if org else None, "events": events, "usage_reports": usage}


@router.get("/orgs/{org_id}")
async def org_detail(
    org_id: str, user: CurrentUser = Depends(require_super_admin)
) -> dict:
    return await run_in_threadpool(_org_detail, org_id)


# ─── Stripe account health ───────────────────────────────────────────────────
def _stripe_health() -> StripeHealth:
    if not is_configured():
        return StripeHealth(configured=False)
    acct = stripe_read(op="account.retrieve", fn=lambda: get_stripe().Account.retrieve())
    req = acct.get("requirements") or {}
    return StripeHealth(
        configured=True,
        charges_enabled=acct.get("charges_enabled"),
        payouts_enabled=acct.get("payouts_enabled"),
        default_currency=acct.get("default_currency"),
        requirements_past_due=req.get("past_due") or [],
        requirements_currently_due=req.get("currently_due") or [],
        requirements_eventually_due=req.get("eventually_due") or [],
        disabled_reason=req.get("disabled_reason"),
    )


@router.get("/stripe-health", response_model=StripeHealth)
async def stripe_health(user: CurrentUser = Depends(require_super_admin)) -> StripeHealth:
    return await run_in_threadpool(_stripe_health)


# ─── Migration matches (dry-run review queue) ────────────────────────────────
def _matches(status_filter: str | None) -> list[MigrationMatch]:
    client = get_service_client()
    q = client.table("billing_migration_log").select("*").order("match_confidence", desc=True)
    if status_filter:
        q = q.eq("status", status_filter)
    rows = q.limit(500).execute().data or []
    org_ids = list({r["org_id"] for r in rows})
    names: dict[str, str] = {}
    if org_ids:
        orgs_rows = (
            client.table("organizations").select("id, name").in_("id", org_ids).execute().data or []
        )
        names = {o["id"]: o.get("name") for o in orgs_rows}
    return [
        MigrationMatch(
            id=r["id"],
            org_id=r["org_id"],
            org_name=names.get(r["org_id"]),
            stripe_customer_id=r.get("stripe_customer_id"),
            match_method=r.get("match_method"),
            match_confidence=r.get("match_confidence"),
            candidate=r.get("candidate_payload"),
            status=r.get("status"),
            created_at=r.get("created_at"),
        )
        for r in rows
    ]


@router.get("/migration-matches", response_model=list[MigrationMatch])
async def migration_matches(
    user: CurrentUser = Depends(require_super_admin),
    status: str | None = Query(default="proposed"),
) -> list[MigrationMatch]:
    return await run_in_threadpool(_matches, status)


@router.post("/run-matcher")
async def run_matcher(user: CurrentUser = Depends(require_super_admin)) -> dict:
    return await run_in_threadpool(propose_matches)


# ─── Write actions (Phase 2) ─────────────────────────────────────────────────
def _guard(fn, *args):
    try:
        return fn(*args)
    except ConnectAttributionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except StripeBillingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/matches/{match_id}/approve")
async def approve_match_ep(
    match_id: str, user: CurrentUser = Depends(require_super_admin)
) -> dict:
    """Approve a dry-run match → write heykiki_org_id to Stripe + link the org."""
    return await run_in_threadpool(_guard, approve_match, match_id, user.id)


@router.post("/matches/{match_id}/reject")
async def reject_match_ep(
    match_id: str, user: CurrentUser = Depends(require_super_admin)
) -> dict:
    return await run_in_threadpool(_guard, reject_match, match_id, user.id)


@router.post("/orgs/{org_id}/retry-payment")
async def retry_payment_ep(
    org_id: str, user: CurrentUser = Depends(require_super_admin)
) -> dict:
    return await run_in_threadpool(_guard, retry_payment, org_id, user.id)


@router.post("/orgs/{org_id}/cancel-subscription")
async def cancel_subscription_ep(
    org_id: str, user: CurrentUser = Depends(require_super_admin)
) -> dict:
    """Cancel at period end. Refused (409) on legacy Connect-attributed subs."""
    return await run_in_threadpool(_guard, cancel_subscription, org_id, user.id)
