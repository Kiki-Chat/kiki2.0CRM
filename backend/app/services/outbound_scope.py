"""Appointment-epic outbound SCOPE GUARD (safety net for the shared prod DB).

Every outbound CALL and EMAIL added by the appointment epic routes through this
module. While ``OUTBOUND_TEST_SCOPE_ONLY`` is ON (the default), sends are FORCED
to the designated test targets and any send for an org outside the test
allow-list is REFUSED (``OutOfScopeError``) — so an unattended build can never
dial a real customer or email a real recipient on the shared production
database.

Go-live (calling/emailing real customers) = set ``OUTBOUND_TEST_SCOPE_ONLY=0``
on the backend service. The guard then becomes a pass-through. The default is ON
so a fresh deploy can never accidentally reach a real customer.
"""
from __future__ import annotations

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


class OutOfScopeError(Exception):
    """Raised when a call/email is attempted outside the allowed test scope
    while the scope guard (``OUTBOUND_TEST_SCOPE_ONLY``) is active."""


def scope_only() -> bool:
    return bool(settings.outbound_test_scope_only)


def _org_allowed(org_id: str | None) -> bool:
    return str(org_id) in settings.outbound_test_org_id_set


def enforce_call_scope(org_id: str | None, to_number: str | None) -> str:
    """Return the phone number to ACTUALLY dial.

    * Scope guard ON  → refuse out-of-scope orgs (``OutOfScopeError``), then
      FORCE the configured test number regardless of the customer's real phone.
    * Scope guard OFF → pass the real number through (go-live).
    """
    if not scope_only():
        if not to_number:
            raise OutOfScopeError("no destination number")
        return to_number
    if not _org_allowed(org_id):
        raise OutOfScopeError(
            f"outbound call refused: org {org_id!r} is outside the test scope "
            "(OUTBOUND_TEST_SCOPE_ONLY is ON)"
        )
    forced = (settings.outbound_test_number or "").strip()
    if not forced:
        raise OutOfScopeError("OUTBOUND_TEST_NUMBER is not set")
    if to_number and to_number != forced:
        logger.info("scope guard: forcing outbound call %s -> test number %s", to_number, forced)
    return forced


def enforce_email_scope(org_id: str | None, to_email: str | None) -> str:
    """Return the email address to ACTUALLY send to.

    * Scope guard ON  → refuse out-of-scope orgs (``OutOfScopeError``), then
      FORCE the configured test inbox regardless of the customer's real email.
    * Scope guard OFF → pass the real recipient through (go-live).
    """
    if not scope_only():
        if not to_email:
            raise OutOfScopeError("no recipient email")
        return to_email
    if not _org_allowed(org_id):
        raise OutOfScopeError(
            f"outbound email refused: org {org_id!r} is outside the test scope "
            "(OUTBOUND_TEST_SCOPE_ONLY is ON)"
        )
    forced = (settings.outbound_test_email or "").strip()
    if not forced:
        raise OutOfScopeError("OUTBOUND_TEST_EMAIL is not set")
    if to_email and to_email != forced:
        logger.info("scope guard: forcing outbound email %s -> test inbox %s", to_email, forced)
    return forced
