"""Stripe webhook ingest: verify → dedup → persist → background-process.

Retry-safety comes from billing_webhook_events.stripe_event_id UNIQUE: Stripe
retries the same evt_… id, the second insert is a no-op, so a handler never runs
twice. Processing failures are recorded (processing_status='failed') and the route
still returns 200 — a Phase-2 sweep can reprocess failed rows. Only a signature
failure returns non-200 (the route raises 400), because a forged event should not
be retried.

Phase-1 handlers are pure inbound state-syncs onto organizations.billing_* — they
NEVER write back to Stripe. An event for a customer we have not linked yet is a
no-op (Phase-1 expected, since linking is dry-run only).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import stripe

from app.core.config import settings
from app.db.supabase_client import get_service_client
from app.services.stripe_billing import StripeConfigError, _client, _to_jsonable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ts(unix: Any) -> str | None:
    if not unix:
        return None
    try:
        return datetime.fromtimestamp(int(unix), tz=timezone.utc).isoformat()
    except (ValueError, OSError, TypeError):
        return None


def _is_unique_violation(exc: Exception) -> bool:
    s = str(exc).lower()
    return "23505" in s or "duplicate key" in s or "already exists" in s


# ─── Inbound verification + dedup ────────────────────────────────────────────
def _record_security_event(db, source_ip: str | None, error_message: str, raw_body: Any) -> None:
    try:
        excerpt = (
            raw_body[:500].decode("utf-8", "replace")
            if isinstance(raw_body, (bytes, bytearray))
            else str(raw_body)[:500]
        )
        db.table("billing_security_events").insert(
            {
                "event_type": "webhook_signature_failure",
                "source_ip": source_ip,
                "error_message": str(error_message)[:2000],
                "raw_excerpt": excerpt,
            }
        ).execute()
    except Exception:  # noqa: BLE001 — security logging must never mask the 400
        pass


def verify_and_record(raw_body: bytes, sig_header: str | None, source_ip: str | None = None) -> dict:
    """Verify the Stripe signature on the RAW body, then persist (deduped).

    Raises stripe.error.SignatureVerificationError / ValueError on a bad request
    (the route turns these into a 400). Returns {new, stripe_event_id, event_type}.
    """
    db = get_service_client()
    try:
        event = stripe.Webhook.construct_event(raw_body, sig_header, settings.stripe_webhook_secret)
    except (stripe.error.SignatureVerificationError, ValueError) as exc:  # type: ignore[attr-defined]
        _record_security_event(db, source_ip, str(exc), raw_body)
        raise

    event_id = event.get("id")
    event_type = event.get("type")

    existing = (
        db.table("billing_webhook_events")
        .select("id")
        .eq("stripe_event_id", event_id)
        .limit(1)
        .execute()
        .data
    )
    if existing:
        return {"new": False, "stripe_event_id": event_id, "event_type": event_type}

    try:
        db.table("billing_webhook_events").insert(
            {
                "stripe_event_id": event_id,
                "event_type": event_type,
                "livemode": event.get("livemode"),
                "processing_status": "received",
                "payload": _to_jsonable(event),
            }
        ).execute()
    except Exception as exc:  # noqa: BLE001 — concurrent insert ⇒ duplicate
        if _is_unique_violation(exc):
            return {"new": False, "stripe_event_id": event_id, "event_type": event_type}
        raise
    return {"new": True, "stripe_event_id": event_id, "event_type": event_type}


# ─── State-sync helpers ──────────────────────────────────────────────────────
def _org_by_customer(db, customer_id: str | None) -> dict | None:
    if not customer_id:
        return None
    rows = (
        db.table("organizations")
        .select("id")
        .eq("stripe_customer_id", customer_id)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


def _derive_plan(sub: dict) -> tuple[str | None, int | None]:
    """plan_title + included minutes from the base (non-metered) item's product metadata."""
    items = (sub.get("items") or {}).get("data") or []
    for it in items:
        price = it.get("price") or {}
        recurring = price.get("recurring") or {}
        if recurring.get("usage_type") == "metered":
            continue  # the overage price, not the plan
        product = price.get("product")
        meta: dict = {}
        if isinstance(product, dict):  # expanded
            meta = product.get("metadata") or {}
        elif product:
            try:
                meta = (stripe.Product.retrieve(product).get("metadata")) or {}
            except Exception:  # noqa: BLE001 — best-effort; status still syncs
                meta = {}
        title = meta.get("plan_title")
        raw_minutes = meta.get("included_call_minutes")
        minutes: int | None = None
        if raw_minutes not in (None, ""):
            try:
                minutes = int(float(raw_minutes))
            except (ValueError, TypeError):
                minutes = None
        return title, minutes
    return None, None


def _sub_period(sub: dict) -> tuple[int | None, int | None]:
    """Current period (start, end) as unix ts. The 2025-03-31.basil API moved
    current_period_* OFF the subscription object ONTO its items — webhook
    payloads now only carry them on items.data[0]. Read top-level first (older
    versions / SDK back-fill), fall back to the first item."""
    start = sub.get("current_period_start")
    end = sub.get("current_period_end")
    if start is None or end is None:
        items = (sub.get("items") or {}).get("data") or []
        if items:
            start = start if start is not None else items[0].get("current_period_start")
            end = end if end is not None else items[0].get("current_period_end")
    return start, end


def _handle_subscription(db, sub: dict) -> str:
    org = _org_by_customer(db, sub.get("customer"))
    if not org:
        return f"no linked org for customer {sub.get('customer')}"
    p_start, p_end = _sub_period(sub)
    update = {
        "billing_subscription_id": sub.get("id"),
        "billing_status": sub.get("status"),
        "billing_subscription_application": sub.get("application"),
        "billing_period_start": _ts(p_start),
        "billing_period_end": _ts(p_end),
        "billing_last_sync_at": _now(),
    }
    title, minutes = _derive_plan(sub)
    if title is not None:
        update["billing_plan_title"] = title
    if minutes is not None:
        update["billing_quota_minutes"] = minutes
    db.table("organizations").update(update).eq("id", org["id"]).execute()
    return f"synced org {org['id']} status={sub.get('status')} plan={title}"


def _handle_subscription_deleted(db, sub: dict) -> str:
    org = _org_by_customer(db, sub.get("customer"))
    if not org:
        return f"no linked org for customer {sub.get('customer')}"
    db.table("organizations").update(
        {"billing_status": "canceled", "billing_last_sync_at": _now()}
    ).eq("id", org["id"]).execute()
    return f"canceled org {org['id']}"


def _handle_invoice_paid(db, inv: dict) -> str:
    org = _org_by_customer(db, inv.get("customer"))
    if not org:
        return f"no linked org for customer {inv.get('customer')}"
    db.table("organizations").update(
        {"billing_status": "active", "billing_last_sync_at": _now()}
    ).eq("id", org["id"]).execute()
    return f"invoice paid org {org['id']}"


def _handle_invoice_failed(db, inv: dict) -> str:
    org = _org_by_customer(db, inv.get("customer"))
    if not org:
        return f"no linked org for customer {inv.get('customer')}"
    db.table("organizations").update(
        {"billing_status": "past_due", "billing_last_sync_at": _now()}
    ).eq("id", org["id"]).execute()
    try:
        from app.services.billing_notifications import notify_payment_failed
        notify_payment_failed(org["id"])
    except Exception:  # noqa: BLE001
        pass
    return f"invoice payment failed org {org['id']} → past_due"


def _handle_trial_will_end(db, sub: dict) -> str:
    """Trial about to end → sync status + record a notification for the org."""
    note = _handle_subscription(db, sub)
    org = _org_by_customer(db, sub.get("customer"))
    if org:
        try:
            from app.services.billing_notifications import notify_trial_will_end
            notify_trial_will_end(org["id"])
        except Exception:  # noqa: BLE001
            pass
    return f"trial will end → {note}"


def _handle_checkout_completed(db, session: dict) -> str:
    """A subscribe Checkout finished → link the new subscription to the org."""
    sub_id = session.get("subscription")
    note = "no subscription on session"
    if sub_id:
        try:
            sub = stripe.Subscription.retrieve(sub_id, expand=["items.data.price"])
            note = _handle_subscription(db, sub)
        except Exception as exc:  # noqa: BLE001
            note = f"sub sync failed: {exc}"
    try:
        db.table("billing_checkout_sessions").update(
            {"status": "completed", "completed_at": _now()}
        ).eq("stripe_session_id", session.get("id")).execute()
    except Exception:  # noqa: BLE001 — table may predate 0049; never block sub linking
        pass
    return f"checkout completed → {note}"


# event.type → handler(db, event_data_object) -> note
_HANDLERS: dict[str, Callable[[Any, dict], str]] = {
    "customer.subscription.created": _handle_subscription,
    "customer.subscription.updated": _handle_subscription,
    "customer.subscription.trial_will_end": _handle_trial_will_end,
    "customer.subscription.paused": _handle_subscription,
    "customer.subscription.resumed": _handle_subscription,
    "customer.subscription.deleted": _handle_subscription_deleted,
    "invoice.paid": _handle_invoice_paid,
    "invoice.payment_succeeded": _handle_invoice_paid,
    "invoice.payment_failed": _handle_invoice_failed,
    "checkout.session.completed": _handle_checkout_completed,
}


def process_event(stripe_event_id: str) -> None:
    """Load a persisted webhook row, dispatch by type, record the outcome. Never raises."""
    db = get_service_client()
    rows = (
        db.table("billing_webhook_events")
        .select("*")
        .eq("stripe_event_id", stripe_event_id)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        return
    row = rows[0]
    if row.get("processing_status") == "processed":
        return

    # Best-effort: set the API key so handlers can retrieve products. Webhook
    # verification only needs the webhook secret, so a missing API key is tolerated.
    try:
        _client()
    except StripeConfigError:
        pass

    payload = row.get("payload") or {}
    event_type = row.get("event_type")
    obj = (payload.get("data") or {}).get("object") or {}
    handler = _HANDLERS.get(event_type)
    try:
        if handler is None:
            status, note = "ignored", f"no handler for {event_type}"
        else:
            note = handler(db, obj)
            status = "processed"
    except Exception as exc:  # noqa: BLE001 — record + move on; route already 200'd
        status, note = "failed", f"{type(exc).__name__}: {exc}"

    db.table("billing_webhook_events").update(
        {
            "processing_status": status,
            "processed_at": _now(),
            "processing_notes": (note or "")[:2000],
        }
    ).eq("stripe_event_id", stripe_event_id).execute()
