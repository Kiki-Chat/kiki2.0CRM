"""Hermetic unit tests for the pay-up-front email+phone → org tie.

A customer who paid via the marketing site BEFORE being linked has no
stripe_customer_id on any org, so today's webhook (checkout.session.completed,
customer-id resolution only) never ties them. These tests prove the additive tie:

  - email AND phone both match an org  → auto-link (stripe_customer_id written),
    high-confidence; future webhooks then resolve by id.
  - email-only match (phone missing/mismatch) → proposal row in
    billing_migration_log for super-admin review, NO link (never activates a
    wrong org).
  - no match at all → no-op (no crash, no link, no proposal without an anchor).
  - phone normalization (0049 / +49 / spaces) collapses to one canonical value.
  - linking is idempotent (already-linked customer is left alone; a re-run does
    not write a duplicate proposal).

Covers both the webhook (stripe_webhook._handle_checkout_completed via
_try_payupfront_link) and the offline matcher's phone-aware confidence boost.
"""

import pytest

from app.services import stripe_matcher as sm
from app.services import stripe_webhook as sw
from tests.billing_fakes import FakeDB


# ─── _org_by_email_phone (the BOTH-match gate) ───────────────────────────────
def _org_db(orgs):
    return FakeDB(canned={"organizations": orgs})


def test_org_by_email_phone_both_match():
    db = _org_db([{"id": "o1", "email": "pay@dob.de", "phone_number": "+4915112345678"}])
    org = sw._org_by_email_phone(db, "pay@dob.de", "+4915112345678")
    assert org == {"id": "o1"}


def test_org_by_email_phone_is_case_insensitive_on_email():
    db = _org_db([{"id": "o1", "email": "pay@dob.de", "phone_number": "+4915112345678"}])
    # Session emails arrive in any case; org row stored lower — both normalize.
    org = sw._org_by_email_phone(db, "PAY@DOB.DE", "+4915112345678")
    assert org == {"id": "o1"}


def test_org_by_email_phone_email_match_phone_mismatch_returns_none():
    db = _org_db([{"id": "o1", "email": "pay@dob.de", "phone_number": "+4915112345678"}])
    assert sw._org_by_email_phone(db, "pay@dob.de", "+49170000000") is None


def test_org_by_email_phone_phone_match_email_mismatch_returns_none():
    db = _org_db([{"id": "o1", "email": "pay@dob.de", "phone_number": "+4915112345678"}])
    # eq("email", …) on the wrong email returns no rows → no link.
    assert sw._org_by_email_phone(db, "other@x.de", "+4915112345678") is None


def test_org_by_email_phone_missing_phone_returns_none():
    db = _org_db([{"id": "o1", "email": "pay@dob.de", "phone_number": "+4915112345678"}])
    assert sw._org_by_email_phone(db, "pay@dob.de", None) is None
    assert sw._org_by_email_phone(db, "pay@dob.de", "") is None


def test_org_by_email_phone_normalizes_both_sides():
    # Org stored E.164, session sends local "0151…" with spaces → still matches.
    db = _org_db([{"id": "o1", "email": "pay@dob.de", "phone_number": "+4915112345678"}])
    assert sw._org_by_email_phone(db, "pay@dob.de", "0151 1234 5678") == {"id": "o1"}
    # Org stored local, session sends 0049 international prefix → still matches.
    db2 = _org_db([{"id": "o2", "email": "pay@dob.de", "phone_number": "0151 12345678"}])
    assert sw._org_by_email_phone(db2, "pay@dob.de", "004915112345678") == {"id": "o2"}


# ─── _handle_checkout_completed: pay-up-front auto-link ───────────────────────
def _session(customer="cus_new", email="pay@dob.de", phone="+4915112345678", sid="cs_1"):
    return {
        "id": sid,
        "customer": customer,
        "subscription": None,  # keep the sub-sync path inert (no stripe network)
        "customer_details": {"email": email, "phone": phone},
    }


def test_checkout_both_match_auto_links(monkeypatch):
    db = FakeDB(
        canned={"organizations": [{"id": "o1", "email": "pay@dob.de", "phone_number": "+4915112345678"}]}
    )
    monkeypatch.setattr(sw, "get_service_client", lambda: db)
    note = sw._handle_checkout_completed(db, _session())

    org_updates = db.updates_to("organizations")
    assert org_updates and org_updates[0]["stripe_customer_id"] == "cus_new"
    assert "pay-up-front linked org o1" in note
    # No proposal written when we auto-linked.
    assert db.inserts_to("billing_migration_log") == []


def test_checkout_both_match_writes_match_method_when_table_present(monkeypatch):
    db = FakeDB(
        canned={
            "organizations": [{"id": "o1", "email": "pay@dob.de", "phone_number": "+4915112345678"}],
            "billing_checkout_sessions": [{"stripe_session_id": "cs_1", "status": "created"}],
        }
    )
    monkeypatch.setattr(sw, "get_service_client", lambda: db)
    sw._handle_checkout_completed(db, _session())
    cs_updates = db.updates_to("billing_checkout_sessions")
    method_update = next((u for u in cs_updates if u.get("match_method")), None)
    assert method_update is not None
    assert method_update["match_method"] == "email_phone_exact"
    assert method_update["matched_org_id"] == "o1"


def test_checkout_phone_normalization_equivalence(monkeypatch):
    # Org stored E.164; session delivers the same number as local "0151…".
    db = FakeDB(
        canned={"organizations": [{"id": "o1", "email": "pay@dob.de", "phone_number": "+4915112345678"}]}
    )
    monkeypatch.setattr(sw, "get_service_client", lambda: db)
    sw._handle_checkout_completed(db, _session(phone="0151 1234 5678"))
    org_updates = db.updates_to("organizations")
    assert org_updates and org_updates[0]["stripe_customer_id"] == "cus_new"


# ─── email-only / mismatch → proposal, never auto-link ───────────────────────
def test_checkout_email_only_writes_proposal_no_link(monkeypatch):
    # Phone on file differs → NOT a both-match → proposal, no org link.
    db = FakeDB(
        canned={"organizations": [{"id": "o1", "email": "pay@dob.de", "phone_number": "+4915199999999"}]}
    )
    monkeypatch.setattr(sw, "get_service_client", lambda: db)
    sw._handle_checkout_completed(db, _session(phone="+4915112345678"))

    # No stripe_customer_id written onto the org.
    assert db.updates_to("organizations") == []
    proposals = db.inserts_to("billing_migration_log")
    assert len(proposals) == 1
    p = proposals[0]
    assert p["match_method"] == "email_only_payupfront"
    assert p["status"] == "proposed"
    assert p["org_id"] == "o1"
    assert p["stripe_customer_id"] == "cus_new"


def test_checkout_missing_phone_writes_proposal_no_link(monkeypatch):
    db = FakeDB(
        canned={"organizations": [{"id": "o1", "email": "pay@dob.de", "phone_number": "+4915112345678"}]}
    )
    monkeypatch.setattr(sw, "get_service_client", lambda: db)
    sw._handle_checkout_completed(db, _session(phone=None))  # phone missing
    assert db.updates_to("organizations") == []
    proposals = db.inserts_to("billing_migration_log")
    assert len(proposals) == 1
    assert proposals[0]["match_method"] == "email_only_payupfront"


def test_checkout_ambiguous_email_proposal_has_null_org(monkeypatch):
    # Two orgs share the email → ambiguous → proposal with no org_id, no link.
    db = FakeDB(
        canned={
            "organizations": [
                {"id": "o1", "email": "shared@dob.de", "phone_number": "+4915111111111"},
                {"id": "o2", "email": "shared@dob.de", "phone_number": "+4915122222222"},
            ]
        }
    )
    monkeypatch.setattr(sw, "get_service_client", lambda: db)
    sw._handle_checkout_completed(db, _session(email="shared@dob.de", phone="+4915133333333"))
    assert db.updates_to("organizations") == []
    proposals = db.inserts_to("billing_migration_log")
    assert len(proposals) == 1
    assert proposals[0]["org_id"] is None
    assert proposals[0]["candidate_payload"]["ambiguous"] is True


# ─── no match at all → no-op ─────────────────────────────────────────────────
def test_checkout_no_match_is_noop(monkeypatch):
    db = FakeDB(
        canned={"organizations": [{"id": "o1", "email": "other@x.de", "phone_number": "+4915112345678"}]}
    )
    monkeypatch.setattr(sw, "get_service_client", lambda: db)
    note = sw._handle_checkout_completed(db, _session(email="nobody@nowhere.de", phone="+4915100000000"))
    assert db.updates_to("organizations") == []
    assert db.inserts_to("billing_migration_log") == []  # no email anchor → no proposal
    assert "checkout completed" in note


def test_checkout_no_email_no_proposal(monkeypatch):
    db = FakeDB(canned={"organizations": [{"id": "o1", "email": "x@y.de", "phone_number": "+4915112345678"}]})
    monkeypatch.setattr(sw, "get_service_client", lambda: db)
    sw._handle_checkout_completed(db, _session(email=None, phone="+4915112345678"))
    assert db.inserts_to("billing_migration_log") == []


# ─── idempotency ─────────────────────────────────────────────────────────────
def test_already_linked_customer_is_left_alone(monkeypatch):
    # The session's customer already resolves to an org → tie path is skipped.
    db = FakeDB(
        canned={
            "organizations": [
                {"id": "o1", "email": "pay@dob.de", "phone_number": "+4915112345678", "stripe_customer_id": "cus_new"}
            ]
        }
    )
    monkeypatch.setattr(sw, "get_service_client", lambda: db)
    sw._handle_checkout_completed(db, _session())
    # No re-link write from the pay-up-front path (org already owns the customer).
    assert db.updates_to("organizations") == []
    assert db.inserts_to("billing_migration_log") == []


def test_email_only_proposal_is_not_duplicated(monkeypatch):
    db = FakeDB(
        canned={"organizations": [{"id": "o1", "email": "pay@dob.de", "phone_number": "+4915199999999"}]}
    )
    monkeypatch.setattr(sw, "get_service_client", lambda: db)
    sw._handle_checkout_completed(db, _session(phone="+4915112345678"))
    sw._handle_checkout_completed(db, _session(phone="+4915112345678"))  # Stripe replay
    assert len(db.inserts_to("billing_migration_log")) == 1  # second run sees existing


# ─── offline matcher: phone-aware confidence boost ───────────────────────────
def _run_matcher(monkeypatch, orgs, customers):
    db = FakeDB(canned={"organizations": orgs})
    monkeypatch.setattr(sm, "get_service_client", lambda: db)
    monkeypatch.setattr(sm, "list_stripe_customers", lambda: customers)
    result = sm.propose_matches()
    return db, result


def test_matcher_email_phone_match_is_highest_confidence(monkeypatch):
    db, res = _run_matcher(
        monkeypatch,
        orgs=[{"id": "o1", "name": "Dobermann", "email": "info@dob.de", "phone_number": "+4915112345678", "stripe_customer_id": None}],
        customers=[{"id": "cus_A", "name": "Dobermann GmbH", "email": "info@dob.de", "phone": "0151 12345678"}],
    )
    row = db.inserts_to("billing_migration_log")[0]
    assert row["match_method"] == "email_phone_exact"
    assert row["match_confidence"] == 0.99
    assert row["stripe_customer_id"] == "cus_A"


def test_matcher_email_only_when_phone_differs(monkeypatch):
    db, res = _run_matcher(
        monkeypatch,
        orgs=[{"id": "o1", "name": "Dobermann", "email": "info@dob.de", "phone_number": "+4915199999999", "stripe_customer_id": None}],
        customers=[{"id": "cus_A", "name": "Dobermann GmbH", "email": "info@dob.de", "phone": "+4915112345678"}],
    )
    row = db.inserts_to("billing_migration_log")[0]
    assert row["match_method"] == "email_exact"  # phone mismatch → no boost
    assert row["match_confidence"] == 0.95


def test_normalize_phone_collapses_formats():
    assert sm.normalize_phone("0151 12345678") == sm.normalize_phone("+4915112345678")
    assert sm.normalize_phone("004915112345678") == sm.normalize_phone("+4915112345678")
    assert sm.normalize_phone(None) is None
    assert sm.normalize_phone("") is None


def test_customer_phone_falls_back_to_details():
    assert sm._customer_phone({"phone": "+4915112345678"}) == "+4915112345678"
    assert sm._customer_phone({"customer_details": {"phone": "0151 12345678"}}) == "+4915112345678"
    assert sm._customer_phone({}) is None
    assert sm._customer_phone(None) is None
