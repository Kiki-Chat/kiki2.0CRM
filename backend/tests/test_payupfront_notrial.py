"""Pay-upfront / no-trial assertion tests (Batch 10).

Strategy: new signups pay immediately; DEFAULT_TRIAL_DAYS and the
trial_period_days sub_data key must NOT appear anywhere in the checkout flow.

All Stripe I/O and DB calls are mocked — no network, no real keys needed.
"""

from __future__ import annotations

import inspect

import pytest

from app.services import stripe_provisioning as sp
from tests.billing_fakes import FakeDB


# ─── 1. Module-level: DEFAULT_TRIAL_DAYS constant must be gone ───────────────

def test_default_trial_days_constant_removed():
    """stripe_provisioning must NOT export DEFAULT_TRIAL_DAYS."""
    assert not hasattr(sp, "DEFAULT_TRIAL_DAYS"), (
        "DEFAULT_TRIAL_DAYS still exists in stripe_provisioning — remove it."
    )


# ─── 2. Function signature: trial_days parameter must be gone ────────────────

def test_create_checkout_session_has_no_trial_days_param():
    """create_checkout_session must not accept a trial_days keyword."""
    sig = inspect.signature(sp.create_checkout_session)
    assert "trial_days" not in sig.parameters, (
        "trial_days parameter still present in create_checkout_session signature."
    )


# ─── 3. Runtime: subscription_data must never contain trial_period_days ──────

def _run_checkout(monkeypatch, *, org_id="o1"):
    """Helper: run create_checkout_session with all external calls mocked.

    Returns (result, captured_sub_data, db_inserts).
    """
    db = FakeDB(
        canned={"organizations": [{"id": org_id, "heykiki_org_id": "kiki-test-007"}]}
    )
    monkeypatch.setattr(sp, "get_service_client", lambda: db)
    monkeypatch.setattr(
        sp, "ensure_stripe_customer", lambda org_id, actor_id=None: "cus_test"
    )
    monkeypatch.setattr(
        sp,
        "find_plan_prices",
        lambda t, i: {"base_price": "price_base", "metered_price": "price_meter"},
    )

    # Capture the subscription_data that would be sent to Stripe.
    captured_sub_data: dict = {}

    def fake_stripe_call_safely(**kwargs):
        # The builder lambda builds the actual Stripe call; we intercept
        # subscription_data by peeking at the sub_data dict that was closed over
        # in the lambda via the request_payload or by calling the builder with a
        # dummy idempotency key.
        if kwargs.get("op") == "checkout_session.create":
            # Call the builder to extract what would be passed to Stripe.
            try:
                fake_session_obj = kwargs["builder"]("idem_key_test", {})
                # builder returns whatever the fake returns — capture sub_data from
                # what was passed by inspecting kwargs["request_payload"] and the
                # inner sub_data dict built in create_checkout_session.
            except Exception:
                pass
        return {"id": "cs_test_123", "url": "https://checkout.stripe.com/test"}

    # We need to intercept sub_data directly. Patch at a lower level: replace
    # stripe_call_safely with a version that calls the builder with a sentinel
    # and captures the arguments that Session.create would have received.
    session_create_calls: list[dict] = []

    class FakeSession:
        @staticmethod
        def create(**kwargs):
            session_create_calls.append(kwargs)
            return {"id": "cs_test_123", "url": "https://checkout.stripe.com/test"}

    class FakeCheckout:
        Session = FakeSession

    class FakeStripe:
        checkout = FakeCheckout

        class Customer:
            @staticmethod
            def create(**kwargs):
                return {"id": "cus_test"}

    def fake_stripe_call_safely_v2(**kwargs):
        # Execute the builder with the fake stripe object injected.
        if kwargs.get("op") == "checkout_session.create":
            # Temporarily override get_stripe inside the builder call.
            original_get_stripe = sp.get_stripe
            sp.get_stripe = lambda: FakeStripe  # type: ignore[assignment]
            try:
                result = kwargs["builder"]("idem_key", {})
            finally:
                sp.get_stripe = original_get_stripe
            return result
        return kwargs["builder"]("idem_key", {})

    monkeypatch.setattr(sp, "stripe_call_safely", fake_stripe_call_safely_v2)

    result = sp.create_checkout_session(org_id, "Kiki Solo", "month")
    return result, session_create_calls, db


def test_no_trial_period_days_in_subscription_data(monkeypatch):
    """subscription_data passed to Stripe must NOT contain trial_period_days."""
    result, session_create_calls, db = _run_checkout(monkeypatch)

    assert result["session_id"] == "cs_test_123"
    assert len(session_create_calls) == 1, "Stripe Session.create should have been called once"

    sub_data = session_create_calls[0].get("subscription_data", {})
    assert "trial_period_days" not in sub_data, (
        f"trial_period_days={sub_data.get('trial_period_days')} found in subscription_data — "
        "pay-upfront strategy requires it to be absent."
    )


def test_no_trial_days_in_request_payload(monkeypatch):
    """request_payload logged to billing_checkout_sessions must NOT include trial_days."""
    captured_request_payloads: list[dict] = []

    db = FakeDB(
        canned={"organizations": [{"id": "o1", "heykiki_org_id": "kiki-test-007"}]}
    )
    monkeypatch.setattr(sp, "get_service_client", lambda: db)
    monkeypatch.setattr(
        sp, "ensure_stripe_customer", lambda org_id, actor_id=None: "cus_test"
    )
    monkeypatch.setattr(
        sp,
        "find_plan_prices",
        lambda t, i: {"base_price": "price_base", "metered_price": "price_meter"},
    )

    def capture_payload(**kwargs):
        captured_request_payloads.append(dict(kwargs.get("request_payload") or {}))
        return {"id": "cs_rp_test", "url": "https://checkout.stripe.com/rp"}

    monkeypatch.setattr(sp, "stripe_call_safely", capture_payload)

    sp.create_checkout_session("o1", "Kiki Team", "year")

    assert len(captured_request_payloads) == 1
    assert "trial_days" not in captured_request_payloads[0], (
        f"trial_days still in request_payload: {captured_request_payloads[0]}"
    )


def test_billing_checkout_sessions_insert_has_no_trial_days(monkeypatch):
    """The DB insert into billing_checkout_sessions must NOT write a trial_days value."""
    db = FakeDB(
        canned={"organizations": [{"id": "o1", "heykiki_org_id": "kiki-test-007"}]}
    )
    monkeypatch.setattr(sp, "get_service_client", lambda: db)
    monkeypatch.setattr(
        sp, "ensure_stripe_customer", lambda org_id, actor_id=None: "cus_test"
    )
    monkeypatch.setattr(
        sp,
        "find_plan_prices",
        lambda t, i: {"base_price": "price_base", "metered_price": "price_meter"},
    )
    monkeypatch.setattr(
        sp,
        "stripe_call_safely",
        lambda **k: {"id": "cs_db_test", "url": "https://checkout.stripe.com/db"},
    )

    sp.create_checkout_session("o1", "Kiki Premium", "month")

    checkout_inserts = db.inserts_to("billing_checkout_sessions")
    assert len(checkout_inserts) == 1, "Expected exactly one billing_checkout_sessions insert"

    row = checkout_inserts[0]
    # The column may still exist in the DB schema (we do NOT drop it) but we
    # must NOT write a value into it.
    assert row.get("trial_days") is None, (
        f"trial_days={row.get('trial_days')} was written to billing_checkout_sessions — "
        "it must be omitted (leave DB column intact, just stop writing)."
    )


# ─── 4. Schema: CheckoutRequest must not accept trial_days ───────────────────

def test_checkout_request_schema_has_no_trial_days():
    """CheckoutRequest schema must not have a trial_days field."""
    from app.schemas.billing import CheckoutRequest

    fields = CheckoutRequest.model_fields
    assert "trial_days" not in fields, (
        "trial_days field still present in CheckoutRequest schema."
    )


def test_checkout_request_rejects_trial_days_in_json():
    """CheckoutRequest must silently ignore (or Pydantic forbid) an unexpected trial_days key.

    By default Pydantic v2 ignores extra fields, so this checks we don't accidentally
    accept and forward the value.
    """
    from app.schemas.billing import CheckoutRequest

    # Pydantic v2 default: extra fields are ignored, not stored.
    req = CheckoutRequest.model_validate(
        {"plan_title": "Kiki Solo", "interval": "month", "trial_days": 30}
    )
    assert not hasattr(req, "trial_days") or getattr(req, "trial_days", "ABSENT") == "ABSENT", (
        "CheckoutRequest stored trial_days even though the field was removed."
    )
