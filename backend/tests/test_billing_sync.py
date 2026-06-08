"""Hermetic unit tests for the webhook-fallback sync endpoint (routes/billing.py).

Proves: _pick_primary_subscription prefers a live sub over canceled/incomplete
(newest wins ties), and _sync pulls the org's current subscription and syncs it
onto organizations via the shared webhook handler — a pure inbound read that never
writes to Stripe and is a no-op for a customerless org.
"""

from app.api.routes import billing
from tests.billing_fakes import FakeDB


def _sub(sub_id="sub_1", status="active", customer="cus_1", created=1700000000):
    return {
        "id": sub_id, "customer": customer, "status": status, "application": None,
        "created": created,
        "current_period_start": 1700000000, "current_period_end": 1701000000,
        "items": {"data": [{"id": "si", "price": {
            "recurring": {"usage_type": "licensed"},
            "product": {"metadata": {"plan_title": "Kiki Solo", "included_call_minutes": "99"}},
        }}]},
    }


# ─── _pick_primary_subscription ──────────────────────────────────────────────
def test_pick_none_when_empty():
    assert billing._pick_primary_subscription([]) is None


def test_pick_prefers_live_over_canceled():
    canceled = _sub("sub_old", status="canceled", created=2000)  # newer but dead
    active = _sub("sub_new", status="active", created=1000)
    assert billing._pick_primary_subscription([canceled, active])["id"] == "sub_new"


def test_pick_newest_among_live():
    older = _sub("sub_a", status="active", created=1000)
    newer = _sub("sub_b", status="trialing", created=5000)
    assert billing._pick_primary_subscription([older, newer])["id"] == "sub_b"


# ─── _sync ───────────────────────────────────────────────────────────────────
class _Subscriptions:
    def __init__(self, subs):
        self._subs = subs

    def list(self, **kwargs):  # mirrors stripe.Subscription.list → ListObject
        return {"data": self._subs}


class _Invoices:
    def upcoming(self, **kwargs):  # mirrors stripe.Invoice.upcoming (used by _summary)
        return {"amount_due": 1990, "currency": "eur"}


class _FakeStripe:
    def __init__(self, subs):
        self.Subscription = _Subscriptions(subs)
        self.Invoice = _Invoices()


def _wire(monkeypatch, db, subs):
    monkeypatch.setattr(billing, "get_service_client", lambda: db)
    monkeypatch.setattr(billing, "is_configured", lambda: True)
    monkeypatch.setattr(billing, "stripe_read", lambda *, op, fn, **k: fn())  # skip the config guard
    monkeypatch.setattr(billing, "get_stripe", lambda: _FakeStripe(subs))


def test_sync_pulls_and_syncs_active_subscription(monkeypatch):
    db = FakeDB(canned={"organizations": [{"id": "o1", "stripe_customer_id": "cus_1"}]})
    _wire(monkeypatch, db, [_sub(status="active")])
    summary = billing._sync("o1")
    assert summary.configured is True
    assert summary.status == "active"
    assert summary.plan_title == "Kiki Solo"
    assert summary.quota_minutes == 99
    upd = db.updates_to("organizations")
    assert upd and upd[-1]["billing_subscription_id"] == "sub_1"


def test_sync_picks_live_when_canceled_present(monkeypatch):
    db = FakeDB(canned={"organizations": [{"id": "o1", "stripe_customer_id": "cus_1"}]})
    subs = [_sub("sub_dead", status="canceled", created=9999), _sub("sub_live", status="active", created=1)]
    _wire(monkeypatch, db, subs)
    summary = billing._sync("o1")
    assert summary.status == "active"
    assert db.updates_to("organizations")[-1]["billing_subscription_id"] == "sub_live"


def test_sync_noop_without_customer(monkeypatch):
    db = FakeDB(canned={"organizations": [{"id": "o1", "stripe_customer_id": None}]})
    monkeypatch.setattr(billing, "get_service_client", lambda: db)
    monkeypatch.setattr(billing, "is_configured", lambda: True)

    def _no_stripe():  # a customerless org must never reach Stripe
        raise AssertionError("Stripe must not be called without a customer")

    monkeypatch.setattr(billing, "get_stripe", _no_stripe)
    summary = billing._sync("o1")
    assert summary.configured is False
    assert db.updates_to("organizations") == []
