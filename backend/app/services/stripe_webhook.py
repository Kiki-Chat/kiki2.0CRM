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
from app.services.identify import _to_e164
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


def _org_by_email_phone(db, email: str | None, phone: str | None) -> dict | None:
    """High-confidence email+phone → org lookup for the pay-up-front tie.

    Returns an org ONLY when BOTH organizations.email matches (case-insensitive)
    AND organizations.phone_number matches the E.164-normalized phone. A match on
    email alone (or phone alone) returns None — the caller treats that as a
    proposal for super-admin review, NEVER an auto-link, so a wrong org can never
    be activated. Org emails are stored as-entered (mixed case possible), so the
    server-side filter is a case-insensitive ilike; the Python re-check on the
    lower-cased / E.164-normalized values is the authoritative gate (and keeps the
    test fake — where ilike is a no-op — correct).
    """
    norm_email = (email or "").strip().lower()
    norm_phone = _to_e164(phone)
    if not norm_email or not norm_phone:
        return None
    rows = (
        db.table("organizations")
        .select("id, email, phone_number")
        .ilike("email", norm_email)
        .limit(20)
        .execute()
        .data
        or []
    )
    for row in rows:
        if (row.get("email") or "").strip().lower() != norm_email:
            continue
        if _to_e164(row.get("phone_number")) == norm_phone:
            return {"id": row["id"]}
    return None


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


def _session_email_phone(session: dict) -> tuple[str | None, str | None]:
    """Pull the payer's email + phone from a Checkout session. Prefers Stripe's
    collected customer_details; falls back to our own metadata (email_hint /
    phone_hint) if the marketing site forwarded them on the session."""
    details = session.get("customer_details") or {}
    meta = session.get("metadata") or {}
    email = details.get("email") or meta.get("email") or meta.get("email_hint")
    phone = details.get("phone") or meta.get("phone") or meta.get("phone_hint")
    return email, phone


def _try_payupfront_link(db, session: dict) -> str | None:
    """Tie a marketing-site payer (paid BEFORE being linked) to an org.

    Only called when the session's stripe_customer_id resolves to NO org. On a
    high-confidence BOTH-match (email AND phone), store stripe_customer_id on that
    org so future webhooks resolve directly, record the match method, and return
    the org_id so the caller proceeds with the normal subscription sync. On an
    email-only / ambiguous / no match, write a proposal to billing_migration_log
    for super-admin review (never auto-link a wrong org) and return None.
    """
    customer_id = session.get("customer")
    if not customer_id:
        return None  # nothing to link a future webhook to
    email, phone = _session_email_phone(session)

    org = _org_by_email_phone(db, email, phone)
    if org:
        # High-confidence: link the customer so future events resolve by id.
        db.table("organizations").update(
            {"stripe_customer_id": customer_id, "billing_last_sync_at": _now()}
        ).eq("id", org["id"]).execute()
        # Record HOW we linked it (additive; column/table may predate this change).
        try:
            db.table("billing_checkout_sessions").update(
                {"match_method": "email_phone_exact", "matched_org_id": str(org["id"])}
            ).eq("stripe_session_id", session.get("id")).execute()
        except Exception:  # noqa: BLE001 — column may not exist; never block linking
            pass
        return org["id"]

    # Not a BOTH-match → do NOT auto-link. Record a proposal for review only when
    # we have at least an email to anchor it (mirrors the matcher's proposal shape).
    norm_email = (email or "").strip().lower()
    if not norm_email:
        return None
    try:
        rows = (
            db.table("organizations")
            .select("id, email")
            .ilike("email", norm_email)
            .limit(20)
            .execute()
            .data
            or []
        )
        candidates = [r for r in rows if (r.get("email") or "").strip().lower() == norm_email]
        if not candidates:
            return None  # no email anchor either → silent no-op
        proposal_org = candidates[0]["id"] if len(candidates) == 1 else None
        existing = (
            db.table("billing_migration_log")
            .select("id")
            .eq("stripe_customer_id", customer_id)
            .limit(1)
            .execute()
            .data
        )
        if existing:
            return None  # already proposed for this customer — don't duplicate
        db.table("billing_migration_log").insert(
            {
                "org_id": proposal_org,
                "stripe_customer_id": customer_id,
                "match_method": "email_only_payupfront",
                "match_confidence": 0.5,
                "candidate_payload": {
                    "source": "checkout.session.completed",
                    "session_id": session.get("id"),
                    "email": email,
                    "phone": phone,
                    "ambiguous": len(candidates) > 1,
                },
                "status": "proposed",
            }
        ).execute()
    except Exception:  # noqa: BLE001 — proposal logging must never break the webhook
        pass
    return None


def _handle_checkout_completed(db, session: dict) -> str:
    """A subscribe Checkout finished → link the new subscription to the org."""
    # Paid-onboarding funnel branch (ONBOARDING_ENABLED): a session bound to an
    # onboarding_leads token has NO org yet → create the tenant in-house (EL agent +
    # Twilio number + provision_org + welcome email). onboard_from_session returns the
    # org_id when it handled the session, None when it's not a funnel lead (fall through
    # to the existing org-link path). A failure RAISES → process_event records the event
    # 'failed' and the onboarding_events ledger captures the stage for /retry.
    if settings.onboarding_enabled:
        from app.services.onboarding_provision import onboard_from_session

        onboarded_org = onboard_from_session(session)
        if onboarded_org:
            try:
                db.table("billing_checkout_sessions").update(
                    {"status": "completed", "completed_at": _now()}
                ).eq("stripe_session_id", session.get("id")).execute()
            except Exception:  # noqa: BLE001 — table may predate 0049; never block onboarding
                pass
            return f"onboarding provisioned org {onboarded_org}"

    sub_id = session.get("subscription")
    note = "no subscription on session"

    # Pay-up-front tie: a marketing-site customer may have paid BEFORE being linked,
    # so the session's customer isn't on any org yet. If so, try a high-confidence
    # email+phone link FIRST (writes stripe_customer_id), so the subscription sync
    # below — which resolves the org by stripe_customer_id — then succeeds.
    if session.get("customer") and not _org_by_customer(db, session.get("customer")):
        try:
            linked = _try_payupfront_link(db, session)
            if linked:
                note = f"pay-up-front linked org {linked}"
        except Exception:  # noqa: BLE001 — linking must never break checkout handling
            pass

    if sub_id:
        try:
            sub = stripe.Subscription.retrieve(sub_id, expand=["items.data.price"])
            note = _handle_subscription(db, sub)
            # OUR welcome email (Brevo) — Stripe owns the receipt + invoice email.
            # Best-effort + deduped per subscription, so it never blocks linking.
            try:
                from app.services.billing_notifications import notify_subscription_activated

                org = _org_by_customer(db, sub.get("customer"))
                title, _ = _derive_plan(sub)
                if org:
                    notify_subscription_activated(org["id"], title, sub_id)
            except Exception:  # noqa: BLE001
                pass
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
