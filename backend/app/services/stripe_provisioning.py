"""Phase 2 — provision a CRM org into Stripe: customer + Checkout subscribe flow.

ensure_stripe_customer: idempotent (org.stripe_customer_id short-circuit + a stable
idempotency key). create_checkout_session: a hosted Stripe Checkout (mode=subscription)
pre-filled from the org's customer, with the base + metered line items, optional trial,
and automatic_tax (19% German VAT added ON TOP of the NET price; EU B2B reverse-charge
applies when a valid VAT-ID is collected). All writes go through stripe_call_safely.
ensure_portal_configuration: the account's billing-portal config with self-service
cancellation DISABLED (also removes the 'default configuration not created' 502).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import stripe

from app.core.config import settings
from app.db.supabase_client import get_service_client
from app.services.stripe_billing import (
    StripeBillingError,
    get_stripe,
    stripe_call_safely,
)
from app.services.stripe_catalog import find_plan_prices

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _org(db, org_id: str) -> dict:
    rows = db.table("organizations").select("*").eq("id", str(org_id)).limit(1).execute().data
    return rows[0] if rows else {}


def _org_address_to_stripe(addr: dict | None) -> dict | None:
    """Best-effort map the org's address jsonb → a Stripe address (DE keys tolerated)."""
    a = addr or {}
    line1 = a.get("line1") or a.get("street") or a.get("strasse")
    city = a.get("city") or a.get("ort") or a.get("stadt")
    postal = a.get("postal_code") or a.get("zip") or a.get("plz")
    out = {
        "line1": line1,
        "line2": a.get("line2"),
        "city": city,
        "postal_code": postal,
        "country": (a.get("country") or "DE")[:2].upper(),
    }
    out = {k: v for k, v in out.items() if v}
    return out if out.get("line1") else None  # Stripe wants at least line1


def ensure_stripe_customer(org_id: str, actor_id: str | None = None) -> str:
    """Return the org's Stripe customer id, creating + linking it if missing."""
    db = get_service_client()
    org = _org(db, org_id)
    if not org:
        raise StripeBillingError(f"org {org_id} not found")
    if org.get("stripe_customer_id"):
        return org["stripe_customer_id"]

    params: dict = {
        "name": org.get("name"),
        "email": org.get("email"),
        "preferred_locales": ["de"],
        "metadata": {
            "heykiki_org_id": org.get("heykiki_org_id"),
            "org_id": str(org_id),
        },
    }
    stripe_addr = _org_address_to_stripe(org.get("address"))
    if stripe_addr:
        params["address"] = stripe_addr

    customer = stripe_call_safely(
        op="customer.create",
        org_id=org_id,
        actor_id=actor_id,
        request_payload={k: v for k, v in params.items() if k != "metadata"},
        idempotency_payload={"org_id": str(org_id)},
        builder=lambda idem, meta: get_stripe().Customer.create(idempotency_key=idem, **params),
    )
    cid = customer["id"]
    db.table("organizations").update({"stripe_customer_id": cid, "billing_last_sync_at": _now()}).eq(
        "id", str(org_id)
    ).execute()
    return cid


def _checkout_return_base(return_origin: str | None) -> str:
    """Where Stripe sends the user after checkout. Prefer the caller's own app origin
    (so they land back on the exact app they're using and keep their session); fall back
    to the configured public URL. Only a well-formed http(s) origin is accepted, and we
    always append our own fixed path — so this can't be used as an open redirect."""
    origin = (return_origin or "").strip().rstrip("/")
    if origin.startswith("https://") or origin.startswith("http://localhost"):
        return f"{origin}/settings/abrechnung"
    return (
        settings.billing_portal_return_url
        or settings.public_app_url.rstrip("/") + "/settings/abrechnung"
    ).split("?")[0]


def create_checkout_session(
    org_id: str,
    plan_title: str,
    interval: str,
    *,
    actor_id: str | None = None,
    return_origin: str | None = None,
) -> dict:
    """Create a hosted Stripe Checkout session to subscribe the org. Returns {url, session_id}."""
    if interval not in ("month", "year"):
        raise StripeBillingError(f"invalid interval {interval!r}")
    db = get_service_client()
    # Resolve catalog prices BEFORE creating the Stripe customer. Otherwise a missing
    # catalog (e.g. LIVE mode before ensure_catalog has run) mints an orphan customer on
    # the org, flipping the Abrechnung UI into a fake 'subscribed' state on a failed
    # checkout. Fail fast here = no customer, no orphan link.
    prices = find_plan_prices(plan_title, interval)
    if not prices["base_price"] or not prices["metered_price"]:
        raise StripeBillingError(f"no catalog prices for {plan_title!r}/{interval!r}")

    customer_id = ensure_stripe_customer(org_id, actor_id)

    line_items = [
        {"price": prices["base_price"], "quantity": 1},
        {"price": prices["metered_price"]},  # metered → no quantity
    ]
    sub_data: dict = {"metadata": {"heykiki_org_id": _org(db, org_id).get("heykiki_org_id"), "org_id": str(org_id)}}

    base = _checkout_return_base(return_origin)
    success_url = f"{base}?checkout=success&session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{base}?checkout=cancel"

    session = stripe_call_safely(
        op="checkout_session.create",
        org_id=org_id,
        actor_id=actor_id,
        stripe_object=customer_id,
        request_payload={"plan": plan_title, "interval": interval},
        builder=lambda idem, meta: get_stripe().checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            line_items=line_items,
            subscription_data=sub_data,
            success_url=success_url,
            cancel_url=cancel_url,
            # Stable key for mapping this checkout back to the CRM org (handy when a
            # future public onboarding page drives checkout via webhook).
            client_reference_id=str(org_id),
            # Collect the mobile number so subscriptions can be mapped to the customer
            # going forward (stored on the Stripe customer).
            phone_number_collection={"enabled": True},
            automatic_tax={"enabled": True},
            # Only collect a card when money is actually due now. A 100%-off promo (or a
            # future trial) drops the first invoice to €0 → Stripe skips card entry; a
            # real paying signup (base price > 0) still requires the card. Address is
            # still collected (needed for the 19% VAT calc) regardless.
            payment_method_collection="if_required",
            customer_update={"address": "auto", "name": "auto"},
            # REQUIRED (not auto): German invoicing needs the full billing
            # address on file — Stripe must collect line1/PLZ/city, not just
            # infer the country for VAT. Stored on the customer → appears on
            # every invoice and drives the exact-rate tax calculation.
            billing_address_collection="required",
            tax_id_collection={"enabled": True},
            allow_promotion_codes=True,
        ),
    )

    try:
        db.table("billing_checkout_sessions").insert(
            {
                "org_id": str(org_id),
                "stripe_session_id": session["id"],
                "plan_title": plan_title,
                "interval": interval,
                "status": "created",
            }
        ).execute()
    except Exception:  # noqa: BLE001 — table may predate 0049; the session is still valid
        pass
    return {"url": session.get("url"), "session_id": session["id"]}


def change_subscription_plan(
    org_id: str, plan_title: str, *, actor_id: str | None = None
) -> dict:
    """Upgrade the org's live subscription to ``plan_title`` IN PLACE.

    Swaps the base + metered subscription items to the target plan's prices,
    keeping the current billing interval and cycle anchor, and prorates the change
    immediately. Returns the modified subscription. The caller re-syncs org state
    (POST /sync → _handle_subscription) afterwards. UPGRADE-only enforcement lives
    in the route; this fn just performs the swap. Routed through stripe_call_safely
    so the Connect-attribution block + cross-org guard + audit row all apply."""
    db = get_service_client()
    org = _org(db, org_id)
    customer_id = org.get("stripe_customer_id")
    if not customer_id:
        raise StripeBillingError(f"org {org_id} has no Stripe customer")

    s = get_stripe()
    # Prefer the stored subscription id; fall back to the customer's active sub.
    sub = None
    stored_id = org.get("billing_subscription_id")
    if stored_id:
        try:
            sub = s.Subscription.retrieve(stored_id, expand=["items.data.price"])
        except stripe.error.StripeError:  # type: ignore[attr-defined]
            sub = None
    if sub is None or sub.get("status") in (None, "canceled", "incomplete_expired"):
        subs = (
            s.Subscription.list(
                customer=customer_id, status="active", expand=["data.items.data.price"]
            ).get("data")
            or []
        )
        sub = subs[0] if subs else None
    if sub is None:
        raise StripeBillingError("no active subscription to upgrade")

    base_item = metered_item = None
    interval = "month"
    for it in (sub.get("items") or {}).get("data") or []:
        recurring = (it.get("price") or {}).get("recurring") or {}
        if recurring.get("usage_type") == "metered":
            metered_item = it
        else:
            base_item = it
            interval = recurring.get("interval") or "month"
    if not base_item:
        raise StripeBillingError("subscription has no base item to change")

    prices = find_plan_prices(plan_title, interval)
    if not prices["base_price"] or not prices["metered_price"]:
        raise StripeBillingError(f"no catalog prices for {plan_title!r}/{interval!r}")

    items = [{"id": base_item["id"], "price": prices["base_price"]}]
    if metered_item:
        items.append({"id": metered_item["id"], "price": prices["metered_price"]})

    sub_id = sub["id"]
    return stripe_call_safely(
        op="subscription.change_plan",
        org_id=org_id,
        actor_id=actor_id,
        subscription_id=sub_id,
        stripe_object=sub_id,
        request_payload={"plan": plan_title, "interval": interval},
        idempotency_payload={"plan": plan_title, "interval": interval, "sub": sub_id},
        builder=lambda idem, meta: get_stripe().Subscription.modify(
            sub_id,
            items=items,
            proration_behavior="create_prorations",
            idempotency_key=idem,
        ),
    )


# ─── Billing-portal configuration ─────────────────────────────────────────────
# Bump when the portal feature set changes (forces a fresh Configuration to be made).
_PORTAL_CONFIG_MARKER = "v1"
_portal_config_cache: dict[str, str] = {}


def ensure_portal_configuration() -> str | None:
    """Return the id of HeyKiki's billing-portal Configuration, creating it once.

    Two problems, one fix:
      • Policy (Amber): self-service cancellation is DISABLED — customers cancel only
        via email/phone. A portal Session inherits its configuration's features, and
        Stripe's *default* config ENABLES cancellation, so we must pass our own with
        ``subscription_cancel`` off.
      • The 502: ``billing_portal.Session.create`` raises *"No configuration provided
        and your default configuration has not been created"* whenever the portal was
        never saved in the Stripe Dashboard for the active mode. Passing an explicit
        configuration removes that dependency entirely — the most common root cause of
        the portal-session 502.

    Idempotent: reuses our metadata-marked configuration if one exists (cached per
    process). Returns ``None`` if creation fails, so the caller can still fall back to
    a default-config session rather than hard-failing."""
    cached = _portal_config_cache.get(_PORTAL_CONFIG_MARKER)
    if cached:
        return cached
    s = get_stripe()
    try:
        for cfg in s.billing_portal.Configuration.list(limit=100).auto_paging_iter():
            md = cfg.get("metadata") or {}
            if md.get("heykiki_portal") == _PORTAL_CONFIG_MARKER and cfg.get("active"):
                _portal_config_cache[_PORTAL_CONFIG_MARKER] = cfg["id"]
                return cfg["id"]
    except stripe.error.StripeError as exc:  # type: ignore[attr-defined]
        log.warning("portal configuration list failed: %s", exc)
    try:
        cfg = s.billing_portal.Configuration.create(
            business_profile={"headline": "HeyKiki — Abrechnung verwalten"},
            features={
                "invoice_history": {"enabled": True},
                "payment_method_update": {"enabled": True},
                "customer_update": {
                    "enabled": True,
                    # tax_id lets B2B customers add their VAT-ID → reverse-charge.
                    "allowed_updates": ["address", "email", "phone", "tax_id"],
                },
                # Amber's policy: NO self-service cancellation in the portal.
                "subscription_cancel": {"enabled": False},
            },
            metadata={"heykiki_portal": _PORTAL_CONFIG_MARKER},
        )
        _portal_config_cache[_PORTAL_CONFIG_MARKER] = cfg["id"]
        return cfg["id"]
    except stripe.error.StripeError as exc:  # type: ignore[attr-defined]
        log.warning("portal configuration create failed: %s", exc)
        return None
