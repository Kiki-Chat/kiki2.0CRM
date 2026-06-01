"""Appointment-epic outbound SCOPE GUARD — the safety net that keeps the build
hermetic on the shared prod DB.

While OUTBOUND_TEST_SCOPE_ONLY is ON (the default):
  * out-of-scope org → OutOfScopeError (REFUSED — the brief's required proof);
  * in-scope org → FORCED to the configured test number / test inbox, regardless
    of the customer's real destination.
When OFF (go-live) → real destinations pass through.
"""
from __future__ import annotations

import pytest

from app.core.config import settings as cfg
from app.services.outbound_scope import (
    OutOfScopeError,
    enforce_call_scope,
    enforce_email_scope,
    scope_only,
)

TEST_ORG = "c4dbf596-86fd-4484-88d9-095b2c082afb"
OTHER_ORG = "00000000-0000-0000-0000-000000000999"


@pytest.fixture
def scope_on(monkeypatch):
    monkeypatch.setattr(cfg, "outbound_test_scope_only", True)
    monkeypatch.setattr(cfg, "outbound_test_number", "+917879997839")
    monkeypatch.setattr(cfg, "outbound_test_email", "agrawalamber01@gmail.com")
    monkeypatch.setattr(cfg, "outbound_test_org_ids", TEST_ORG)


# ─── REQUIRED refusal proof: an out-of-scope send is refused ─────────────────
def test_call_out_of_scope_org_is_refused(scope_on):
    with pytest.raises(OutOfScopeError):
        enforce_call_scope(OTHER_ORG, "+4917012345678")


def test_email_out_of_scope_org_is_refused(scope_on):
    with pytest.raises(OutOfScopeError):
        enforce_email_scope(OTHER_ORG, "real.customer@example.com")


# ─── in-scope is FORCED to the test targets (never the real destination) ─────
def test_call_in_scope_is_forced_to_test_number(scope_on):
    assert enforce_call_scope(TEST_ORG, "+4917012345678") == "+917879997839"
    # even with no stored customer phone, the test number is forced (UAT-safe).
    assert enforce_call_scope(TEST_ORG, None) == "+917879997839"


def test_email_in_scope_is_forced_to_test_inbox(scope_on):
    assert enforce_email_scope(TEST_ORG, "real.customer@example.com") == "agrawalamber01@gmail.com"
    assert enforce_email_scope(TEST_ORG, None) == "agrawalamber01@gmail.com"


def test_scope_only_reports_on(scope_on):
    assert scope_only() is True


# ─── go-live (guard OFF) passes the real destination through ─────────────────
def test_guard_off_passes_real_number_through(monkeypatch):
    monkeypatch.setattr(cfg, "outbound_test_scope_only", False)
    assert enforce_call_scope(OTHER_ORG, "+4917012345678") == "+4917012345678"
    assert scope_only() is False


def test_guard_off_passes_real_email_through(monkeypatch):
    monkeypatch.setattr(cfg, "outbound_test_scope_only", False)
    assert enforce_email_scope(OTHER_ORG, "real@example.com") == "real@example.com"


def test_guard_off_still_rejects_empty_destination(monkeypatch):
    monkeypatch.setattr(cfg, "outbound_test_scope_only", False)
    with pytest.raises(OutOfScopeError):
        enforce_call_scope(OTHER_ORG, None)
    with pytest.raises(OutOfScopeError):
        enforce_email_scope(OTHER_ORG, "")


# ─── misconfig: forced target unset while scope-only ON → refuse, never leak ──
def test_missing_test_number_refuses(scope_on, monkeypatch):
    monkeypatch.setattr(cfg, "outbound_test_number", "")
    with pytest.raises(OutOfScopeError):
        enforce_call_scope(TEST_ORG, "+4917012345678")


def test_missing_test_email_refuses(scope_on, monkeypatch):
    monkeypatch.setattr(cfg, "outbound_test_email", "")
    with pytest.raises(OutOfScopeError):
        enforce_email_scope(TEST_ORG, "real@example.com")
