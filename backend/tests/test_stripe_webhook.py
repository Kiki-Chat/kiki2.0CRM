"""Hermetic unit tests for the Stripe webhook ingest (stripe_webhook.py).

Proves: signature verification gates ingest (bad sig → security event + raise),
the stripe_event_id UNIQUE dedup makes replays no-ops, event→state mapping is
correct (invoice.payment_failed → past_due), processing is idempotent, and
unknown event types are recorded as 'ignored' (never crash).
"""

import pytest
import stripe

from app.services import stripe_webhook as sw
from tests.billing_fakes import FakeDB


def _event(eid="evt_1", etype="invoice.payment_failed", customer="cus_1"):
    return {
        "id": eid,
        "type": etype,
        "livemode": False,
        "data": {"object": {"customer": customer}},
    }


# ─── verify_and_record ───────────────────────────────────────────────────────
def test_valid_event_recorded_as_new(monkeypatch):
    db = FakeDB(unique={"billing_webhook_events": "stripe_event_id"})
    monkeypatch.setattr(sw, "get_service_client", lambda: db)
    monkeypatch.setattr(sw.stripe.Webhook, "construct_event", lambda body, sig, secret: _event())

    rec = sw.verify_and_record(b"{}", "sig", "1.2.3.4")
    assert rec["new"] is True and rec["stripe_event_id"] == "evt_1"
    assert len(db.inserts_to("billing_webhook_events")) == 1


def test_duplicate_event_is_not_reprocessed(monkeypatch):
    db = FakeDB(unique={"billing_webhook_events": "stripe_event_id"})
    monkeypatch.setattr(sw, "get_service_client", lambda: db)
    monkeypatch.setattr(sw.stripe.Webhook, "construct_event", lambda body, sig, secret: _event())

    first = sw.verify_and_record(b"{}", "sig")
    second = sw.verify_and_record(b"{}", "sig")  # Stripe retries the same evt id
    assert first["new"] is True and second["new"] is False
    assert len(db.inserts_to("billing_webhook_events")) == 1  # inserted once only


def test_bad_signature_logs_security_event_and_raises(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(sw, "get_service_client", lambda: db)

    def boom(body, sig, secret):
        raise stripe.error.SignatureVerificationError("bad sig", "t=1,v1=deadbeef")

    monkeypatch.setattr(sw.stripe.Webhook, "construct_event", boom)
    with pytest.raises(stripe.error.SignatureVerificationError):
        sw.verify_and_record(b"forged", "sig", "9.9.9.9")
    assert len(db.inserts_to("billing_security_events")) == 1


# ─── process_event ───────────────────────────────────────────────────────────
def _proc_db(etype="invoice.payment_failed"):
    return FakeDB(
        canned={
            "billing_webhook_events": [
                {
                    "stripe_event_id": "evt_1",
                    "event_type": etype,
                    "processing_status": "received",
                    "payload": _event(etype=etype),
                }
            ],
            "organizations": [{"id": "o1", "stripe_customer_id": "cus_1"}],
        }
    )


def test_payment_failed_sets_past_due(monkeypatch):
    db = _proc_db("invoice.payment_failed")
    monkeypatch.setattr(sw, "get_service_client", lambda: db)
    sw.process_event("evt_1")
    org_updates = db.updates_to("organizations")
    assert org_updates and org_updates[-1]["billing_status"] == "past_due"
    wh = db.updates_to("billing_webhook_events")
    assert wh and wh[-1]["processing_status"] == "processed"


def test_processing_is_idempotent(monkeypatch):
    db = _proc_db("invoice.payment_failed")
    monkeypatch.setattr(sw, "get_service_client", lambda: db)
    sw.process_event("evt_1")
    sw.process_event("evt_1")  # second run must short-circuit (already processed)
    assert len(db.updates_to("organizations")) == 1


def test_unknown_event_type_ignored(monkeypatch):
    db = _proc_db("payment_intent.created")  # no handler
    monkeypatch.setattr(sw, "get_service_client", lambda: db)
    sw.process_event("evt_1")
    assert db.updates_to("organizations") == []
    wh = db.updates_to("billing_webhook_events")
    assert wh and wh[-1]["processing_status"] == "ignored"


def test_sub_period_reads_from_items_when_top_level_absent():
    # 2025-03-31.basil webhook payloads drop current_period_* from the sub
    # object and carry them only on items.data[0].
    sub = {"id": "sub_1", "items": {"data": [{"current_period_start": 111, "current_period_end": 222}]}}
    assert sw._sub_period(sub) == (111, 222)


def test_sub_period_prefers_top_level_when_present():
    sub = {"current_period_start": 5, "current_period_end": 9, "items": {"data": [{"current_period_start": 111}]}}
    assert sw._sub_period(sub) == (5, 9)
