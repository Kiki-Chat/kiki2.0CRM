"""Hermetic tests for super-admin billing write actions (stripe_admin_actions.py)."""

from types import SimpleNamespace

import pytest

from app.services import stripe_admin_actions as saa
from tests.billing_fakes import FakeDB


def _fake_stripe(meta=None):
    return SimpleNamespace(Customer=SimpleNamespace(retrieve=lambda cid: {"metadata": meta or {}}))


def test_approve_match_writes_back_and_links(monkeypatch):
    db = FakeDB(canned={
        "billing_migration_log": [{"id": "m1", "status": "proposed", "stripe_customer_id": "cus_1", "org_id": "o1"}],
        "organizations": [{"id": "o1", "heykiki_org_id": "kiki-x"}],
    })
    monkeypatch.setattr(saa, "get_service_client", lambda: db)
    monkeypatch.setattr(saa, "get_stripe", lambda: _fake_stripe({"existing": "keep"}))
    captured = {}
    monkeypatch.setattr(saa, "stripe_call_safely", lambda **k: (captured.update(k), {"id": "cus_1"})[1])

    res = saa.approve_match("m1", "admin1")
    assert res["status"] == "approved" and res["stripe_customer_id"] == "cus_1"
    # additive write-back: new key added, existing preserved (merge done by the wrapper)
    assert captured["metadata_merge"]["heykiki_org_id"] == "kiki-x"
    assert captured["metadata_existing"] == {"existing": "keep"}
    assert any(u.get("stripe_customer_id") == "cus_1" for u in db.updates_to("organizations"))
    assert any(u.get("status") == "approved" for u in db.updates_to("billing_migration_log"))


def test_approve_match_blocks_cross_org(monkeypatch):
    db = FakeDB(canned={
        "billing_migration_log": [{"id": "m1", "status": "proposed", "stripe_customer_id": "cus_1", "org_id": "o1"}],
        "organizations": [{"id": "o1", "heykiki_org_id": "kiki-x"}, {"id": "o2", "stripe_customer_id": "cus_1"}],
    })
    monkeypatch.setattr(saa, "get_service_client", lambda: db)
    with pytest.raises(saa.StripeBillingError):
        saa.approve_match("m1", "admin1")


def test_approve_non_proposed_errors(monkeypatch):
    db = FakeDB(canned={"billing_migration_log": [{"id": "m1", "status": "approved", "stripe_customer_id": "cus_1", "org_id": "o1"}]})
    monkeypatch.setattr(saa, "get_service_client", lambda: db)
    with pytest.raises(saa.StripeBillingError):
        saa.approve_match("m1", "admin1")


def test_reject_match(monkeypatch):
    db = FakeDB(canned={"billing_migration_log": [{"id": "m1", "status": "proposed", "org_id": "o1"}]})
    monkeypatch.setattr(saa, "get_service_client", lambda: db)
    assert saa.reject_match("m1", "admin1")["status"] == "rejected"
    assert any(u.get("status") == "rejected" for u in db.updates_to("billing_migration_log"))


def test_cancel_subscription_targets_sub(monkeypatch):
    db = FakeDB(canned={"organizations": [{"id": "o1", "billing_subscription_id": "sub_1"}]})
    monkeypatch.setattr(saa, "get_service_client", lambda: db)
    captured = {}
    monkeypatch.setattr(saa, "stripe_call_safely", lambda **k: (captured.update(k), {"cancel_at_period_end": True})[1])
    res = saa.cancel_subscription("o1", "admin1")
    assert res["cancel_at_period_end"] is True
    # passes subscription_id → the wrapper's Connect block guards legacy subs
    assert captured["subscription_id"] == "sub_1"


def test_cancel_no_sub_errors(monkeypatch):
    db = FakeDB(canned={"organizations": [{"id": "o1", "billing_subscription_id": None}]})
    monkeypatch.setattr(saa, "get_service_client", lambda: db)
    with pytest.raises(saa.StripeBillingError):
        saa.cancel_subscription("o1", "admin1")


def test_retry_payment_pays_open_invoice(monkeypatch):
    db = FakeDB(canned={"organizations": [{"id": "o1", "stripe_customer_id": "cus_1"}]})
    monkeypatch.setattr(saa, "get_service_client", lambda: db)
    monkeypatch.setattr(saa, "get_stripe", lambda: SimpleNamespace(
        Invoice=SimpleNamespace(list=lambda **k: SimpleNamespace(data=[{"id": "in_1"}]))
    ))
    monkeypatch.setattr(saa, "stripe_call_safely", lambda **k: {"status": "paid"})
    res = saa.retry_payment("o1", "admin1")
    assert res["status"] == "paid" and res["invoice"] == "in_1"


def test_retry_payment_no_open_invoice(monkeypatch):
    db = FakeDB(canned={"organizations": [{"id": "o1", "stripe_customer_id": "cus_1"}]})
    monkeypatch.setattr(saa, "get_service_client", lambda: db)
    monkeypatch.setattr(saa, "get_stripe", lambda: SimpleNamespace(
        Invoice=SimpleNamespace(list=lambda **k: SimpleNamespace(data=[]))
    ))
    assert saa.retry_payment("o1", "admin1")["status"] == "no_open_invoice"
