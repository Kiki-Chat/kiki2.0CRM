"""Hermetic unit tests for the Stripe safety layer (stripe_billing.py).

No network, no DB: _client() is replaced by a fake stripe module and
get_service_client by FakeDB. Proves the safety contract: Connect-attribution
write block, cross-org block, idempotency-key stability, additive metadata,
audit-row lifecycle (pending→succeeded/failed), no-op short-circuit, and that
pure reads are audited ONLY on error.
"""

from types import SimpleNamespace

import pytest
import stripe

from app.services import stripe_billing as sb
from tests.billing_fakes import FakeDB


def _fake_stripe(retrieve=None):
    return SimpleNamespace(Subscription=SimpleNamespace(retrieve=retrieve or (lambda sid: {})))


# ─── Pure helpers ────────────────────────────────────────────────────────────
def test_idempotency_key_stable_and_distinct():
    a = sb.idempotency_key("usage.report", "org1", {"call_id": "c1"})
    b = sb.idempotency_key("usage.report", "org1", {"call_id": "c1"})
    c = sb.idempotency_key("usage.report", "org1", {"call_id": "c2"})
    assert a == b and a != c
    assert a.startswith("usage.report:org1:")


def test_additive_metadata_preserves_unset_keys():
    merged = sb.additive_metadata({"a": "1", "keep": "x"}, {"a": "2", "b": "3", "drop": None})
    assert merged == {"a": "2", "keep": "x", "b": "3"}  # 'keep' preserved, None dropped


# ─── Connect / cross-org write blocks ────────────────────────────────────────
def test_connect_attributed_subscription_refused(monkeypatch):
    db = FakeDB(canned={"organizations": [{"id": "o1", "stripe_customer_id": "cus_1"}]})
    monkeypatch.setattr(sb, "get_service_client", lambda: db)
    monkeypatch.setattr(
        sb, "_client",
        lambda: _fake_stripe(retrieve=lambda sid: {"id": sid, "application": "ca_legacy", "customer": "cus_1"}),
    )
    called = {"n": 0}

    def builder(idem, meta):
        called["n"] += 1
        return {"id": "should_not_happen"}

    with pytest.raises(sb.ConnectAttributionError):
        sb.stripe_call_safely(
            op="usage.report", org_id="o1", actor_id=None,
            subscription_id="sub_legacy", builder=builder,
        )
    assert called["n"] == 0  # builder NEVER ran — no write to a Connect sub
    failed = [u for u in db.updates_to("billing_events") if u.get("status") == "failed"]
    assert failed and failed[-1]["error_code"] == "connect_attribution"


def test_cross_org_subscription_refused(monkeypatch):
    db = FakeDB(canned={"organizations": [{"id": "o1", "stripe_customer_id": "cus_MINE"}]})
    monkeypatch.setattr(sb, "get_service_client", lambda: db)
    monkeypatch.setattr(
        sb, "_client",
        lambda: _fake_stripe(retrieve=lambda sid: {"id": sid, "application": None, "customer": "cus_OTHER"}),
    )
    called = {"n": 0}
    with pytest.raises(sb.StripeCrossOrgError):
        sb.stripe_call_safely(
            op="usage.report", org_id="o1", actor_id=None,
            subscription_id="sub_x", builder=lambda i, m: called.__setitem__("n", called["n"] + 1),
        )
    assert called["n"] == 0


# ─── Audit lifecycle ─────────────────────────────────────────────────────────
def test_success_audits_pending_then_succeeded(monkeypatch):
    db = FakeDB(canned={"organizations": [{"id": "o1", "stripe_customer_id": "cus_1"}]})
    monkeypatch.setattr(sb, "get_service_client", lambda: db)
    monkeypatch.setattr(sb, "_client", lambda: _fake_stripe())

    out = sb.stripe_call_safely(
        op="portal_session.create", org_id="o1", actor_id="u1",
        stripe_object="cus_1", request_payload={"customer": "cus_1"},
        builder=lambda idem, meta: {"id": "bps_1", "url": "https://billing.stripe.com/x"},
    )
    assert out["url"].startswith("https://billing.stripe.com/")
    pending = db.inserts_to("billing_events")
    assert pending and pending[0]["status"] == "pending"
    assert any(u.get("status") == "succeeded" for u in db.updates_to("billing_events"))


def test_stripe_error_marks_audit_failed(monkeypatch):
    db = FakeDB(canned={"organizations": [{"id": "o1", "stripe_customer_id": "cus_1"}]})
    monkeypatch.setattr(sb, "get_service_client", lambda: db)
    monkeypatch.setattr(sb, "_client", lambda: _fake_stripe())

    def boom(idem, meta):
        raise stripe.error.StripeError("card_declined")

    with pytest.raises(sb.StripeBillingError):
        sb.stripe_call_safely(
            op="usage.report", org_id="o1", actor_id=None,
            request_payload={"x": 1}, builder=boom,
        )
    assert any(u.get("status") == "failed" for u in db.updates_to("billing_events"))


def test_metadata_noop_short_circuits(monkeypatch):
    db = FakeDB(canned={"organizations": [{"id": "o1", "stripe_customer_id": "cus_1"}]})
    monkeypatch.setattr(sb, "get_service_client", lambda: db)
    monkeypatch.setattr(sb, "_client", lambda: _fake_stripe())
    called = {"n": 0}

    out = sb.stripe_call_safely(
        op="customer.modify", org_id="o1", actor_id=None,
        metadata_existing={"heykiki_org_id": "o1"}, metadata_merge={"heykiki_org_id": "o1"},
        builder=lambda i, m: called.__setitem__("n", called["n"] + 1),
    )
    assert out is None and called["n"] == 0  # no Stripe call when metadata unchanged
    assert any(u.get("status") == "succeeded" for u in db.updates_to("billing_events"))


# ─── Reads: audited only on error ────────────────────────────────────────────
def test_stripe_read_success_not_audited(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(sb, "get_service_client", lambda: db)
    monkeypatch.setattr(sb, "_client", lambda: _fake_stripe())
    out = sb.stripe_read(op="invoice.list", fn=lambda: {"data": [1, 2]}, org_id="o1")
    assert out == {"data": [1, 2]}
    assert db.inserts_to("billing_events") == []  # success never floods the ledger


def test_stripe_read_error_is_audited(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(sb, "get_service_client", lambda: db)
    monkeypatch.setattr(sb, "_client", lambda: _fake_stripe())

    def boom():
        raise stripe.error.StripeError("rate_limited")

    with pytest.raises(sb.StripeBillingError):
        sb.stripe_read(op="invoice.list", fn=boom, org_id="o1")
    failed = db.inserts_to("billing_events")
    assert failed and failed[0]["status"] == "failed"
