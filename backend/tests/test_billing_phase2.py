"""Hermetic unit tests for Phase 2 — provisioning/checkout, notifications, and the
new webhook handlers (checkout.session.completed, trial_will_end, payment_failed).

7.3 additions:
  - test_month_start_utc_iso_berlin_midnight: month_start_utc_iso() correctness
  - test_quota_warning_80pct_fires_once: 80% warning inserts exactly one row
  - test_quota_warning_no_double_fire: dedup prevents second row on re-check
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services import billing_notifications as bn
from app.services import stripe_provisioning as sp
from app.services import stripe_webhook as sw
from app.services.common import month_start_utc_iso
from tests.billing_fakes import FakeDB

BERLIN = ZoneInfo("Europe/Berlin")


# ─── Provisioning + checkout ─────────────────────────────────────────────────
def test_ensure_customer_idempotent(monkeypatch):
    db = FakeDB(canned={"organizations": [{"id": "o1", "stripe_customer_id": "cus_existing"}]})
    monkeypatch.setattr(sp, "get_service_client", lambda: db)
    called = {"n": 0}
    monkeypatch.setattr(sp, "stripe_call_safely", lambda **k: called.__setitem__("n", called["n"] + 1))
    assert sp.ensure_stripe_customer("o1") == "cus_existing"
    assert called["n"] == 0  # already linked → no Stripe call


def test_ensure_customer_creates_and_links(monkeypatch):
    db = FakeDB(canned={"organizations": [{
        "id": "o1", "name": "Acme GmbH", "email": "a@b.de", "heykiki_org_id": "kiki-x",
        "address": {"line1": "Hafenweg 22", "city": "Münster", "postal_code": "48155", "country": "DE"},
    }]})
    monkeypatch.setattr(sp, "get_service_client", lambda: db)
    monkeypatch.setattr(sp, "stripe_call_safely", lambda **k: {"id": "cus_new"})
    assert sp.ensure_stripe_customer("o1") == "cus_new"
    assert any(u.get("stripe_customer_id") == "cus_new" for u in db.updates_to("organizations"))


def test_checkout_session_builds_and_records(monkeypatch):
    db = FakeDB(canned={"organizations": [{"id": "o1", "heykiki_org_id": "kiki-x"}]})
    monkeypatch.setattr(sp, "get_service_client", lambda: db)
    monkeypatch.setattr(sp, "ensure_stripe_customer", lambda org_id, actor_id=None: "cus_1")
    monkeypatch.setattr(sp, "find_plan_prices", lambda t, i: {"base_price": "price_b", "metered_price": "price_m"})
    captured = {}

    def fake_safe(**k):
        captured.update(k)
        return {"id": "cs_1", "url": "https://checkout.stripe.com/x"}

    monkeypatch.setattr(sp, "stripe_call_safely", fake_safe)
    res = sp.create_checkout_session("o1", "Kiki Solo", "month")
    assert res == {"url": "https://checkout.stripe.com/x", "session_id": "cs_1"}
    assert captured["request_payload"]["plan"] == "Kiki Solo"
    assert "trial_days" not in captured["request_payload"]
    assert any(t == "billing_checkout_sessions" for t, _ in db.inserts)


def test_checkout_no_prices_errors(monkeypatch):
    db = FakeDB(canned={"organizations": [{"id": "o1"}]})
    monkeypatch.setattr(sp, "get_service_client", lambda: db)
    monkeypatch.setattr(sp, "ensure_stripe_customer", lambda o, actor_id=None: "cus_1")
    monkeypatch.setattr(sp, "find_plan_prices", lambda t, i: {"base_price": None, "metered_price": None})
    with pytest.raises(sp.StripeBillingError):
        sp.create_checkout_session("o1", "Bogus", "month")


def test_checkout_rejects_bad_interval(monkeypatch):
    monkeypatch.setattr(sp, "get_service_client", lambda: FakeDB())
    with pytest.raises(sp.StripeBillingError):
        sp.create_checkout_session("o1", "Kiki Solo", "weekly")


# ─── Notifications ───────────────────────────────────────────────────────────
def test_record_notification_dedups(monkeypatch):
    db = FakeDB(unique={"billing_notifications": "dedup_key"})
    monkeypatch.setattr(bn, "get_service_client", lambda: db)
    a = bn.record_notification("o1", "over_quota", dedup_key="over_quota:o1:2026-06")
    b = bn.record_notification("o1", "over_quota", dedup_key="over_quota:o1:2026-06")
    assert a is not None and b is None
    assert len(db.inserts_to("billing_notifications")) == 1


def test_check_over_quota_notifies_when_over(monkeypatch):
    db = FakeDB(
        canned={
            "organizations": [{"id": "o1", "billing_quota_minutes": 20, "billing_period_start": "2026-06-01T00:00:00Z"}],
            "calls": [{"id": "c", "org_id": "o1", "duration_seconds": 1800, "created_at": "2026-06-05"}],  # 30 min
        },
        unique={"billing_notifications": "dedup_key"},
    )
    monkeypatch.setattr(bn, "get_service_client", lambda: db)
    bn.check_and_notify_over_quota("o1")
    ins = db.inserts_to("billing_notifications")
    assert ins and ins[0]["type"] == "over_quota" and ins[0]["meta"]["used"] == 30


def test_check_over_quota_silent_when_under(monkeypatch):
    db = FakeDB(canned={
        "organizations": [{"id": "o1", "billing_quota_minutes": 100, "billing_period_start": "2026-06-01T00:00:00Z"}],
        "calls": [{"id": "c", "org_id": "o1", "duration_seconds": 600, "created_at": "2026-06-05"}],  # 10 min
    })
    monkeypatch.setattr(bn, "get_service_client", lambda: db)
    bn.check_and_notify_over_quota("o1")
    assert db.inserts_to("billing_notifications") == []


def test_check_over_quota_first_warning_at_80(monkeypatch):
    db = FakeDB(
        canned={
            "organizations": [{"id": "o1", "billing_quota_minutes": 100, "billing_period_start": "2026-06-01T00:00:00Z"}],
            "calls": [{"id": "c", "org_id": "o1", "duration_seconds": 5100, "created_at": "2026-06-05"}],  # 85 min → 85 %
        },
        unique={"billing_notifications": "dedup_key"},
    )
    monkeypatch.setattr(bn, "get_service_client", lambda: db)
    bn.check_and_notify_over_quota("o1")
    ins = db.inserts_to("billing_notifications")
    assert ins and ins[0]["type"] == "quota_warning"  # first warning, not the 95 % one


def test_check_over_quota_final_warning_at_95(monkeypatch):
    db = FakeDB(
        canned={
            "organizations": [{"id": "o1", "billing_quota_minutes": 100, "billing_period_start": "2026-06-01T00:00:00Z"}],
            "calls": [{"id": "c", "org_id": "o1", "duration_seconds": 5820, "created_at": "2026-06-05"}],  # 97 min → 97 %
        },
        unique={"billing_notifications": "dedup_key"},
    )
    monkeypatch.setattr(bn, "get_service_client", lambda: db)
    bn.check_and_notify_over_quota("o1")
    ins = db.inserts_to("billing_notifications")
    assert ins and ins[0]["type"] == "quota_warning_2"  # second/final pre-overage warning


# ─── New webhook handlers ────────────────────────────────────────────────────
def _sub(status="trialing", customer="cus_1"):
    return {
        "id": "sub_1", "customer": customer, "status": status, "application": None,
        "current_period_start": 1700000000, "current_period_end": 1701000000,
        "items": {"data": [{"id": "si", "price": {
            "recurring": {"usage_type": "licensed"},
            "product": {"metadata": {"plan_title": "Kiki Solo", "included_call_minutes": "99"}},
        }}]},
    }


def test_checkout_completed_links_subscription(monkeypatch):
    db = FakeDB(canned={"organizations": [{"id": "o1", "stripe_customer_id": "cus_1"}]},
                unique={"billing_notifications": "dedup_key"})
    monkeypatch.setattr(sw, "get_service_client", lambda: db)
    monkeypatch.setattr(bn, "get_service_client", lambda: db)
    monkeypatch.setattr(sw.stripe.Subscription, "retrieve", lambda sid, **k: _sub())
    sw._handle_checkout_completed(db, {"id": "cs_1", "subscription": "sub_1", "customer": "cus_1"})
    upd = db.updates_to("organizations")
    assert upd and upd[-1]["billing_status"] == "trialing"
    assert upd[-1]["billing_plan_title"] == "Kiki Solo"
    assert upd[-1]["billing_quota_minutes"] == 99
    # Our welcome email fires once on checkout (Stripe owns receipt/invoice).
    acts = [i for i in db.inserts_to("billing_notifications") if i["type"] == "subscription_activated"]
    assert len(acts) == 1 and acts[0]["dedup_key"] == "subscription_activated:sub_1"


def test_trial_will_end_syncs_and_notifies(monkeypatch):
    db = FakeDB(canned={"organizations": [{"id": "o1", "stripe_customer_id": "cus_1"}]},
                unique={"billing_notifications": "dedup_key"})
    monkeypatch.setattr(sw, "get_service_client", lambda: db)
    monkeypatch.setattr(bn, "get_service_client", lambda: db)
    sw._handle_trial_will_end(db, _sub())
    assert any(i["type"] == "trial_will_end" for i in db.inserts_to("billing_notifications"))


def test_payment_failed_sets_past_due_and_notifies(monkeypatch):
    db = FakeDB(canned={"organizations": [{"id": "o1", "stripe_customer_id": "cus_1"}]})
    monkeypatch.setattr(sw, "get_service_client", lambda: db)
    monkeypatch.setattr(bn, "get_service_client", lambda: db)
    sw._handle_invoice_failed(db, {"customer": "cus_1"})
    assert db.updates_to("organizations")[-1]["billing_status"] == "past_due"
    assert any(i["type"] == "payment_failed" for i in db.inserts_to("billing_notifications"))


# ─── 7.3: month_start_utc_iso + 80 % quota-warning ──────────────────────────

def test_month_start_utc_iso_berlin_midnight(monkeypatch):
    """month_start_utc_iso() must return the Berlin-local first-of-month midnight
    expressed as a tz-aware UTC ISO string.

    In summer (CEST = UTC+2) 'June 1 00:00 Berlin' = 'May 31 22:00 UTC'.
    The returned string must end with '+00:00' and parse to a datetime that is
    exactly 2 hours before UTC calendar midnight on the 1st.
    """
    from datetime import timezone
    import app.services.common as _c

    fixed_berlin = datetime(2026, 6, 17, 14, 30, 0, tzinfo=BERLIN)
    monkeypatch.setattr(_c, "now_berlin", lambda: fixed_berlin)

    result = month_start_utc_iso()

    # Must be a tz-aware UTC string
    assert result.endswith("+00:00"), f"Expected UTC offset +00:00, got: {result!r}"

    from datetime import datetime as _dt, timezone as _tz
    parsed = _dt.fromisoformat(result)
    assert parsed.tzinfo is not None

    # June 1 00:00 Berlin (CEST = UTC+2) = May 31 22:00:00 UTC
    expected_utc = _dt(2026, 5, 31, 22, 0, 0, tzinfo=_tz.utc)
    assert parsed == expected_utc, (
        f"Expected {expected_utc.isoformat()!r}, got {result!r}"
    )


def test_quota_warning_80pct_fires_once(monkeypatch):
    """80% warning fires at exactly >=80% usage and inserts exactly one row.

    quota=100 min, 1 call of 4800 s = 80 min (exactly 80 %).
    Expect exactly one billing_notifications row of type 'quota_warning'.
    """
    # 4800 s / 60 = 80 min, quota = 100 → 80 % exactly → warning threshold
    db = FakeDB(
        canned={
            "organizations": [
                {
                    "id": "o1",
                    "billing_quota_minutes": 100,
                    "billing_period_start": "2026-06-01T00:00:00+00:00",
                }
            ],
            "calls": [
                {"id": "c1", "org_id": "o1", "duration_seconds": 4800, "created_at": "2026-06-10T10:00:00Z"},
            ],
        },
        unique={"billing_notifications": "dedup_key"},
    )
    monkeypatch.setattr(bn, "get_service_client", lambda: db)

    bn.check_and_notify_over_quota("o1")

    ins = db.inserts_to("billing_notifications")
    warnings = [i for i in ins if i["type"] == "quota_warning"]
    assert len(warnings) == 1, f"Expected exactly 1 quota_warning, got {len(warnings)}: {ins}"
    assert warnings[0]["meta"]["used"] == 80
    assert warnings[0]["meta"]["quota"] == 100


def test_quota_warning_no_double_fire(monkeypatch):
    """Calling check_and_notify_over_quota twice with the same period must not
    insert a second quota_warning row (dedup on dedup_key)."""
    db = FakeDB(
        canned={
            "organizations": [
                {
                    "id": "o1",
                    "billing_quota_minutes": 100,
                    "billing_period_start": "2026-06-01T00:00:00+00:00",
                }
            ],
            "calls": [
                {"id": "c1", "org_id": "o1", "duration_seconds": 4800, "created_at": "2026-06-10T10:00:00Z"},
            ],
        },
        unique={"billing_notifications": "dedup_key"},
    )
    monkeypatch.setattr(bn, "get_service_client", lambda: db)

    bn.check_and_notify_over_quota("o1")
    bn.check_and_notify_over_quota("o1")

    warnings = [i for i in db.inserts_to("billing_notifications") if i["type"] == "quota_warning"]
    assert len(warnings) == 1, (
        f"Dedup failed: expected 1 quota_warning row, got {len(warnings)}"
    )
