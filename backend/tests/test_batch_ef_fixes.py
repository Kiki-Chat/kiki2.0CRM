"""Batch E (cost/rate guards) + Batch F (phantom-capture detector) — 2026-06-12.

E1: /cases/propose enforces the monthly AI cap (429), like the offline runners.
E2: in-process sliding-window rate limiter on the LLM-spend endpoints.
F1b: post-call detector flags calls where the agent CLAIMED capture but no
     write tool ran (data_collection.phantom_capture).
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.api import deps
from app.services import ratelimit
from app.services.post_call import _phantom_capture


def _org_user(org_id="org-1") -> deps.CurrentUser:
    return deps.CurrentUser(
        id="u1", email="a@b.de", org_id=org_id, role="org_admin", full_name=None
    )


# ─── E2: rate limiter ─────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _fresh_windows():
    ratelimit.reset()
    yield
    ratelimit.reset()


def test_rate_limit_allows_under_and_blocks_over():
    for _ in range(3):
        ratelimit.enforce_rate_limit("t", "org-1", max_calls=3, per_seconds=60)
    with pytest.raises(HTTPException) as exc:
        ratelimit.enforce_rate_limit("t", "org-1", max_calls=3, per_seconds=60)
    assert exc.value.status_code == 429


def test_rate_limit_isolated_per_org_and_endpoint():
    for _ in range(3):
        ratelimit.enforce_rate_limit("t", "org-1", max_calls=3, per_seconds=60)
    # other org and other endpoint are untouched
    ratelimit.enforce_rate_limit("t", "org-2", max_calls=3, per_seconds=60)
    ratelimit.enforce_rate_limit("other", "org-1", max_calls=3, per_seconds=60)


def test_rate_limit_window_slides(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: t[0])
    ratelimit.enforce_rate_limit("t", "o", max_calls=1, per_seconds=10)
    with pytest.raises(HTTPException):
        ratelimit.enforce_rate_limit("t", "o", max_calls=1, per_seconds=10)
    t[0] += 11  # past the window → allowed again
    ratelimit.enforce_rate_limit("t", "o", max_calls=1, per_seconds=10)


# ─── E1: cases/propose cap gate ───────────────────────────────────────────────
def test_cases_propose_429_when_over_cap(monkeypatch):
    from app.api.routes import cases as cases_routes
    from app.services.ai import usage as ai_usage

    monkeypatch.setattr(ai_usage, "within_cap", lambda org: False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(cases_routes.propose_cases("cust-1", user=_org_user()))
    assert exc.value.status_code == 429
    assert "KI-Budget" in exc.value.detail


# ─── F1b: phantom-capture detector ────────────────────────────────────────────
def _turn(role, msg, tools=()):
    return {"role": role, "message": msg, "tool_calls": list(tools), "tool_results": []}


def test_phantom_flagged_when_claim_without_write_tool():
    # The real failure pattern (corpus call #19 "Broken device report").
    t = [
        _turn("user", "Mein Gerät ist kaputt."),
        _turn("agent", "Einen Moment, ich nehme Ihr Anliegen direkt auf — die "
                       "Kollegen schauen kurz nach und melden sich zeitnah.",
              tools=["hk_identifyCustomer"]),
        _turn("agent", "Danke. Wir haben Ihr Anliegen aufgenommen und melden uns "
                       "schnellstmöglich bei Ihnen zurück. Auf Wiederhören."),
    ]
    assert _phantom_capture(t) is True


def test_no_flag_when_inquiry_was_created():
    t = [
        _turn("agent", "Ich nehme Ihr Anliegen auf.", tools=["hk_createInquiry"]),
        _turn("agent", "Wir haben Ihr Anliegen aufgenommen. Auf Wiederhören."),
    ]
    assert _phantom_capture(t) is False


def test_no_flag_when_booking_captured_the_concern():
    t = [
        _turn("agent", "Ich reserviere den Termin.", tools=["hk_bookAppointment"]),
        _turn("agent", "Wir haben Ihr Anliegen aufgenommen. Auf Wiederhören."),
    ]
    assert _phantom_capture(t) is False


def test_no_flag_without_any_capture_claim():
    # Wrong number / pure question: neutral goodbye, nothing claimed.
    t = [
        _turn("user", "Falsch verbunden, Entschuldigung."),
        _turn("agent", "Kein Problem. Danke für Ihren Anruf. Auf Wiederhören.",
              tools=["hk_identifyCustomer"]),
    ]
    assert _phantom_capture(t) is False


def test_transfer_counts_as_handled():
    t = [
        _turn("agent", "Ich leite Sie sofort an den Notdienst weiter.",
              tools=["transfer_to_number"]),
    ]
    assert _phantom_capture(t) is False
