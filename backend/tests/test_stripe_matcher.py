"""Hermetic unit tests for the dry-run customer matcher (stripe_matcher.py).

Proves: German legal-suffix normalization, email-exact + fuzzy-name matching with
confidence, re-runs don't duplicate proposals, and — critically — the matcher
NEVER writes back to Stripe (proposals land only in billing_migration_log).
"""

from app.services import stripe_matcher as sm
from tests.billing_fakes import FakeDB


def test_normalize_strips_legal_suffixes():
    assert sm.normalize_name("Dobermann Trockenbau + Maler GmbH & Co. KG") == "dobermann trockenbau maler"
    assert sm.normalize_name("M. Kloppenborg GmbH") == "m kloppenborg"
    assert sm.normalize_name(None) == ""


def _run(monkeypatch, orgs, customers):
    db = FakeDB(canned={"organizations": orgs})
    monkeypatch.setattr(sm, "get_service_client", lambda: db)
    monkeypatch.setattr(sm, "list_stripe_customers", lambda: customers)
    result = sm.propose_matches()
    return db, result


def test_email_exact_match(monkeypatch):
    db, res = _run(
        monkeypatch,
        orgs=[{"id": "o1", "name": "Dobermann GmbH", "email": "info@dob.de", "stripe_customer_id": None}],
        customers=[{"id": "cus_A", "name": "Dobermann Trockenbau GmbH & Co. KG", "email": "info@dob.de"}],
    )
    assert res["proposals_created"] == 1
    row = db.inserts_to("billing_migration_log")[0]
    assert row["match_method"] == "email_exact"
    assert row["match_confidence"] == 0.95
    assert row["stripe_customer_id"] == "cus_A"


def test_fuzzy_name_match(monkeypatch):
    db, res = _run(
        monkeypatch,
        orgs=[{"id": "o3", "name": "Renneberg Bedachung", "email": None, "stripe_customer_id": None}],
        customers=[{"id": "cus_R", "name": "Renneberg Bedachungen GmbH", "email": "r@x.de"}],
    )
    row = db.inserts_to("billing_migration_log")[0]
    assert row["match_method"] == "name_fuzzy"
    assert row["match_confidence"] >= 0.6
    assert row["stripe_customer_id"] == "cus_R"


def test_no_match_records_none(monkeypatch):
    db, res = _run(
        monkeypatch,
        orgs=[{"id": "o4", "name": "Zzz Unrelated Corp", "email": None, "stripe_customer_id": None}],
        customers=[{"id": "cus_R", "name": "Renneberg Bedachungen GmbH", "email": "r@x.de"}],
    )
    row = db.inserts_to("billing_migration_log")[0]
    assert row["match_method"] == "none"
    assert row["stripe_customer_id"] is None


def test_already_linked_org_skipped(monkeypatch):
    db, res = _run(
        monkeypatch,
        orgs=[{"id": "o2", "name": "Linked", "email": "x@y.de", "stripe_customer_id": "cus_existing"}],
        customers=[{"id": "cus_A", "name": "Linked", "email": "x@y.de"}],
    )
    assert res["proposals_created"] == 0
    assert db.inserts_to("billing_migration_log") == []


def test_rerun_does_not_duplicate(monkeypatch):
    orgs = [{"id": "o1", "name": "Dobermann GmbH", "email": "info@dob.de", "stripe_customer_id": None}]
    customers = [{"id": "cus_A", "name": "Dobermann GmbH", "email": "info@dob.de"}]
    db = FakeDB(canned={"organizations": orgs})
    monkeypatch.setattr(sm, "get_service_client", lambda: db)
    monkeypatch.setattr(sm, "list_stripe_customers", lambda: customers)

    first = sm.propose_matches()
    second = sm.propose_matches()  # re-run
    assert first["proposals_created"] == 1
    assert second["proposals_created"] == 0  # existing proposal not duplicated
    assert len(db.inserts_to("billing_migration_log")) == 1
