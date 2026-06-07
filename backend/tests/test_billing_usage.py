"""Hermetic unit tests for per-call usage reporting (billing_usage.py).

Proves the money-critical guarantees: one call → at most one Stripe usage record
(idempotency via call_id), soft-stop reports ALL minutes (no cap), every skip
path makes ZERO Stripe calls, and historical backfill is structurally excluded.
"""

from pathlib import Path
from types import SimpleNamespace

from app.services import billing_usage as bu
from tests.billing_fakes import FakeDB

ORG = "o1"
CALL = "call-123"


def _db(duration=120, with_customer=True):
    return FakeDB(
        canned={
            "organizations": [
                {"id": ORG, "stripe_customer_id": "cus_1" if with_customer else None}
            ],
            "calls": [{"id": CALL, "duration_seconds": duration}],
        },
        unique={"billing_usage_reports": "call_id"},
    )


def _wire_success(monkeypatch, db, recorder):
    monkeypatch.setattr(bu, "is_configured", lambda: True)
    monkeypatch.setattr(bu, "get_service_client", lambda: db)
    monkeypatch.setattr(
        bu, "resolve_metered_subscription_item",
        lambda org_id: ({"subscription_id": "sub_1", "subscription_item_id": "si_1"}, None),
    )
    monkeypatch.setattr(bu, "stripe_call_safely", recorder)


# ─── Pure helpers ────────────────────────────────────────────────────────────
def test_minutes_from_seconds_boundaries():
    assert [bu.minutes_from_seconds(s) for s in (0, 31, 90, 120)] == [0, 1, 2, 2]


def test_select_billable_excludes_retries_and_backfill():
    results = [
        {"status": "processed", "callLogId": "a", "orgId": "o"},        # billable
        {"status": "skipped", "callLogId": "b", "orgId": "o", "skipReason": "already_processed"},
        {"status": "skipped", "callLogId": None, "orgId": "o", "skipReason": "unknown_agent"},
        {"status": "processed", "callLogId": "c", "orgId": None},        # missing org → excluded
    ]
    assert bu.select_billable(results) == [("a", "o")]


# ─── Reporting success + idempotency ─────────────────────────────────────────
def test_report_success_reports_once_and_links_call(monkeypatch):
    db = _db(duration=120)
    calls = []
    _wire_success(monkeypatch, db, lambda **kw: (calls.append(kw), {"id": "mbur_1"})[1])

    out = bu.report_call_usage(call_id=CALL, org_id=ORG)
    assert out["status"] == "reported"
    assert len(calls) == 1  # exactly one Stripe usage record
    assert calls[0]["request_payload"]["quantity"] == 2  # 120s → 2 min
    # the call row was linked to its usage report
    assert any(u.get("billing_usage_report_id") for u in db.updates_to("calls"))


def test_report_is_idempotent_per_call(monkeypatch):
    db = _db(duration=120)
    calls = []
    _wire_success(monkeypatch, db, lambda **kw: (calls.append(kw), {"id": "mbur_1"})[1])

    first = bu.report_call_usage(call_id=CALL, org_id=ORG)
    second = bu.report_call_usage(call_id=CALL, org_id=ORG)  # retry / webhook replay
    assert first["status"] == "reported"
    assert second["status"] == "already_reported"
    assert len(calls) == 1  # the second attempt made ZERO Stripe calls
    assert len(db.inserts_to("billing_usage_reports")) == 1  # one ledger row only


def test_soft_stop_reports_all_minutes_no_cap(monkeypatch):
    db = _db(duration=100000)  # ~1667 min, far over any quota
    calls = []
    _wire_success(monkeypatch, db, lambda **kw: (calls.append(kw), {"id": "mbur_1"})[1])

    out = bu.report_call_usage(call_id=CALL, org_id=ORG)
    assert out["status"] == "reported"
    assert calls[0]["request_payload"]["quantity"] == round(100000 / 60)  # no cap applied


# ─── Skip paths make ZERO Stripe calls ───────────────────────────────────────
def _wire_skip(monkeypatch, db, reason):
    monkeypatch.setattr(bu, "is_configured", lambda: True)
    monkeypatch.setattr(bu, "get_service_client", lambda: db)
    monkeypatch.setattr(bu, "resolve_metered_subscription_item", lambda org_id: (None, reason))
    called = {"n": 0}
    monkeypatch.setattr(bu, "stripe_call_safely", lambda **kw: called.__setitem__("n", called["n"] + 1))
    return called


def test_skip_no_customer(monkeypatch):
    db = _db()
    called = _wire_skip(monkeypatch, db, "no_customer")
    out = bu.report_call_usage(call_id=CALL, org_id=ORG)
    assert out["status"] == "skipped" and out["skip_reason"] == "no_customer"
    assert called["n"] == 0


def test_skip_no_metered_sub(monkeypatch):
    db = _db()
    called = _wire_skip(monkeypatch, db, "no_metered_sub")
    out = bu.report_call_usage(call_id=CALL, org_id=ORG)
    assert out["status"] == "skipped" and out["skip_reason"] == "no_metered_sub"
    assert called["n"] == 0


def test_skip_legacy_connect_sub(monkeypatch):
    db = _db()
    called = _wire_skip(monkeypatch, db, "legacy_connect_sub")
    out = bu.report_call_usage(call_id=CALL, org_id=ORG)
    assert out["status"] == "skipped" and out["skip_reason"] == "legacy_connect_sub"
    assert called["n"] == 0


def test_zero_minute_call_skipped(monkeypatch):
    db = _db(duration=20)  # 20s → 0 min
    calls = []
    _wire_success(monkeypatch, db, lambda **kw: (calls.append(kw), {"id": "x"})[1])
    out = bu.report_call_usage(call_id=CALL, org_id=ORG)
    assert out["status"] == "skipped" and out["skip_reason"] == "zero_minutes"
    assert len(calls) == 0


def test_not_configured_skips_without_row(monkeypatch):
    db = _db()
    monkeypatch.setattr(bu, "is_configured", lambda: False)
    monkeypatch.setattr(bu, "get_service_client", lambda: db)
    out = bu.report_call_usage(call_id=CALL, org_id=ORG)
    assert out["status"] == "skipped" and out["skip_reason"] == "not_configured"
    assert db.inserts_to("billing_usage_reports") == []


# ─── resolve_metered_subscription_item ───────────────────────────────────────
def _stub_subs(monkeypatch, db, subs_data):
    monkeypatch.setattr(bu, "get_service_client", lambda: db)
    fake = SimpleNamespace(Subscription=SimpleNamespace(list=lambda **k: {"data": subs_data}))
    monkeypatch.setattr(bu, "get_stripe", lambda: fake)


def test_resolve_returns_metered_item(monkeypatch):
    db = _db()
    _stub_subs(monkeypatch, db, [
        {"id": "sub_1", "application": None, "items": {"data": [
            {"id": "si_base", "price": {"recurring": {"usage_type": "licensed"}}},
            {"id": "si_meter", "price": {"recurring": {"usage_type": "metered"}}},
        ]}},
    ])
    info, reason = bu.resolve_metered_subscription_item(ORG)
    assert reason is None and info["subscription_item_id"] == "si_meter"


def test_resolve_legacy_connect_only(monkeypatch):
    db = _db()
    _stub_subs(monkeypatch, db, [
        {"id": "sub_c", "application": "ca_x", "items": {"data": [
            {"id": "si_m", "price": {"recurring": {"usage_type": "metered"}}},
        ]}},
    ])
    info, reason = bu.resolve_metered_subscription_item(ORG)
    assert info is None and reason == "legacy_connect_sub"


def test_resolve_no_metered(monkeypatch):
    db = _db()
    _stub_subs(monkeypatch, db, [
        {"id": "sub_1", "application": None, "items": {"data": [
            {"id": "si_base", "price": {"recurring": {"usage_type": "licensed"}}},
        ]}},
    ])
    info, reason = bu.resolve_metered_subscription_item(ORG)
    assert info is None and reason == "no_metered_sub"


def test_resolve_no_customer(monkeypatch):
    db = _db(with_customer=False)
    monkeypatch.setattr(bu, "get_service_client", lambda: db)
    info, reason = bu.resolve_metered_subscription_item(ORG)
    assert info is None and reason == "no_customer"


# ─── Backfill exclusion (structural) ─────────────────────────────────────────
def test_backfill_path_never_imports_usage_reporter():
    """history_import + the shared post_call service must NOT reference the reporter —
    usage is fired only from the post-call ROUTE, so backfill can't be billed."""
    base = Path(__file__).resolve().parent.parent / "app" / "services"
    for fname in ("post_call.py", "history_import.py"):
        src = (base / fname).read_text(encoding="utf-8")
        assert "report_call_usage" not in src, f"{fname} must not reference report_call_usage"
