"""Per-call usage reporting to Stripe (legacy usage-records API).

Invoked from the post-call ROUTE (not the shared _process_one), so historical
backfill via history_import never reaches this code → no mis-billing. Idempotent
via billing_usage_reports.call_id UNIQUE: one call = at most one report, even on
webhook retries. Soft-stop: ALL minutes are reported (no cap) — over-quota is a
UI concept, billed automatically by the metered price.

Skip (zero Stripe calls) when: the org has no Stripe customer, no metered
subscription item, or only a legacy Connect-attributed subscription (which we are
forbidden to write to). Every skip is recorded with a reason for reconciliation.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from app.db.supabase_client import get_service_client
from app.services.stripe_billing import (
    ConnectAttributionError,
    StripeBillingError,
    get_stripe,
    is_configured,
    stripe_call_safely,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_unique_violation(exc: Exception) -> bool:
    s = str(exc).lower()
    return "23505" in s or "duplicate key" in s or "already exists" in s


def select_billable(results: list[dict]) -> list[tuple[str, str]]:
    """From post-call results, the (call_id, org_id) pairs that should be billed.

    ONLY newly-finalised calls (status 'processed' with both ids) — dedup/retries
    ('skipped', 'already_processed') and unknown-agent rows are excluded. This is
    the pure core of the backfill/retry guard, unit-tested in isolation."""
    return [
        (r["callLogId"], r["orgId"])
        for r in results
        if r.get("status") == "processed" and r.get("callLogId") and r.get("orgId")
    ]


def minutes_from_seconds(seconds: int | float | None) -> int:
    """Convert call seconds → billable minutes.

    GO-LIVE DECISION (Amber, 2026-06-10): round() stays — the bill equals the
    displayed usage (settings._usage / KI-Nutzung). Do not switch to ceil()
    without also changing the display, or invoice and UI drift apart."""
    return round((seconds or 0) / 60)


def resolve_metered_subscription_item(org_id: str) -> tuple[dict | None, str | None]:
    """Find the org's writable metered subscription item.

    Returns ({subscription_id, subscription_item_id}, None) on success, or
    (None, skip_reason) where skip_reason ∈ {no_customer, no_metered_sub,
    legacy_connect_sub}.
    """
    client = get_service_client()
    rows = (
        client.table("organizations")
        .select("stripe_customer_id")
        .eq("id", org_id)
        .limit(1)
        .execute()
        .data
    )
    customer_id = rows[0].get("stripe_customer_id") if rows else None
    if not customer_id:
        return None, "no_customer"

    s = get_stripe()
    subs = s.Subscription.list(
        customer=customer_id, status="active", expand=["data.items.data.price"]
    )
    saw_connect_metered = False
    for sub in subs.get("data") or []:
        is_connect = bool(sub.get("application"))
        for item in (sub.get("items") or {}).get("data") or []:
            recurring = (item.get("price") or {}).get("recurring") or {}
            if recurring.get("usage_type") != "metered":
                continue  # the flat base price, not the overage meter
            if is_connect:
                saw_connect_metered = True
                continue  # legacy ChatDash sub — forbidden to write to
            return {"subscription_id": sub.get("id"), "subscription_item_id": item.get("id")}, None

    return None, ("legacy_connect_sub" if saw_connect_metered else "no_metered_sub")


def report_call_usage(*, call_id: str, org_id: str) -> dict:
    """Report one call's minutes to Stripe, exactly once. Safe to call repeatedly."""
    if not is_configured():
        return {"status": "skipped", "skip_reason": "not_configured", "call_id": call_id}

    client = get_service_client()

    # 1) Atomic claim — call_id UNIQUE makes a retry a no-op.
    try:
        inserted = (
            client.table("billing_usage_reports")
            .insert({"call_id": call_id, "org_id": org_id, "status": "pending"})
            .execute()
            .data
        )
    except Exception as exc:  # noqa: BLE001
        if _is_unique_violation(exc):
            return {"status": "already_reported", "call_id": call_id}
        raise
    report_id = inserted[0]["id"] if inserted else None

    def _finish(status: str, **fields) -> dict:
        client.table("billing_usage_reports").update(
            {"status": status, "updated_at": _now(), **fields}
        ).eq("id", report_id).execute()
        return {"status": status, "call_id": call_id, **fields}

    # 2) Resolve the writable metered subscription item (or skip with a reason).
    try:
        info, skip_reason = resolve_metered_subscription_item(org_id)
    except StripeBillingError as exc:
        return _finish("failed", error_message=f"resolve failed: {exc}"[:500])
    if info is None:
        return _finish("skipped", skip_reason=skip_reason)

    # 3) Duration → minutes (report ALL minutes; no quota cap).
    rows = (
        client.table("calls").select("duration_seconds").eq("id", call_id).limit(1).execute().data
    )
    minutes = minutes_from_seconds(rows[0].get("duration_seconds") if rows else 0)
    si = info["subscription_item_id"]
    client.table("billing_usage_reports").update(
        {"subscription_item_id": si, "quantity_minutes": minutes}
    ).eq("id", report_id).execute()

    if minutes <= 0:
        return _finish("skipped", skip_reason="zero_minutes", quantity_minutes=0)

    # 4) Report via the safe wrapper (Connect-blocked + idempotent on call_id).
    try:
        record = stripe_call_safely(
            op="usage.report",
            org_id=org_id,
            actor_id=None,
            subscription_id=info["subscription_id"],
            stripe_object=si,
            request_payload={"call_id": call_id, "subscription_item": si, "quantity": minutes},
            idempotency_payload={"call_id": call_id},
            builder=lambda idem, meta: get_stripe().SubscriptionItem.create_usage_record(
                si,
                quantity=minutes,
                action="increment",
                timestamp=int(time.time()),
                idempotency_key=idem,
            ),
        )
    except ConnectAttributionError:
        return _finish("skipped", skip_reason="legacy_connect_sub")
    except StripeBillingError as exc:
        return _finish("failed", error_message=str(exc)[:500])

    result = _finish("reported", stripe_usage_record_id=(record.get("id") if record else None))
    # 5) Link the call → its usage report (renders 'billed' per call in Anrufe).
    if report_id:
        client.table("calls").update({"billing_usage_report_id": report_id}).eq("id", call_id).execute()
    # 6) Soft-stop: if this call pushed the org over quota, record one alert (deduped).
    try:
        from app.services.billing_notifications import check_and_notify_over_quota
        check_and_notify_over_quota(org_id)
    except Exception:  # noqa: BLE001
        pass
    return result
