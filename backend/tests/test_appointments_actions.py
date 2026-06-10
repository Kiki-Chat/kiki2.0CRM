"""Wave 2 / Agent 2.4 — appointment confirm/reject/propose-alternative routes.

Covers:
 - confirm: happy path stamps confirmed_at + flips status to 'confirmed',
            409 when not pending, 404 when not in org.
 - reject:  happy path stamps rejected_at + reason, flips status to 'cancelled',
            409 when not pending.
 - propose-alternative: happy path fills alternative_* fields + keeps status
                        'pending', 422 when start>=end or in past, 409 when
                        not pending.
 - pending-for-call: returns the single pending appointment for a call's
                     inquiry, returns null when none, 404 when call missing.

Cross-tenant isolation is asserted by 404 when an appointment belongs to a
different org (the org_id filter on the SELECT means cross-org IDs never
match — _get_appointment returns None → route raises 404).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api import deps
from app.api.routes import appointments as appt_routes


@pytest.fixture(autouse=True)
def _no_outbound_side_effect(monkeypatch):
    """Neutralize the best-effort appointment outbound side-effect for these
    route tests — the call/email trigger is covered in test_appointment_notify.py.
    Without this, confirm/reject/propose-alternative/approve-proposal would invoke
    the real outbound path (a network call) after the status mutation."""
    monkeypatch.setattr(
        appt_routes, "notify_appointment_outcome", lambda *a, **k: {"fired": False}
    )


# ─── helpers ────────────────────────────────────────────────────────────────
def _org_admin_user(org_id: str = "org-1") -> deps.CurrentUser:
    return deps.CurrentUser(
        id="user-1",
        email="admin@example.com",
        org_id=org_id,
        role="org_admin",
        full_name=None,
    )


def _make_chain(rows: list[dict]) -> MagicMock:
    """Build a chainable .select().eq()...execute() mock that returns the rows."""
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.neq.return_value = chain
    chain.in_.return_value = chain
    chain.gte.return_value = chain
    chain.lt.return_value = chain
    chain.or_.return_value = chain
    chain.order.return_value = chain
    chain.limit.return_value = chain
    chain.range.return_value = chain
    chain.update.return_value = chain
    chain.insert.return_value = chain
    chain.delete.return_value = chain
    execute_result = MagicMock()
    execute_result.data = rows
    execute_result.count = len(rows)
    chain.execute.return_value = execute_result
    return chain


class _FakeClient:
    """Tracks .table() calls in sequence so we can stub a different return for
    the SELECT (existing appointment fetch) vs the UPDATE (modified row)."""

    def __init__(self, responses: list[list[dict]]):
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []  # (table, op) for assertions
        self._last_op: str | None = None

    def table(self, name: str) -> MagicMock:
        chain = MagicMock()
        for method in ("select", "eq", "neq", "in_", "gte", "lt", "or_", "order", "limit"):
            getattr(chain, method).return_value = chain

        def _record_update(payload):
            self.calls.append((name, "update"))
            self._last_update_payload = payload
            return chain

        def _record_insert(payload):
            self.calls.append((name, "insert"))
            self._last_insert_payload = payload
            return chain

        chain.update.side_effect = _record_update
        chain.insert.side_effect = _record_insert

        execute_result = MagicMock()
        # Pop the next staged response; fall back to empty list if exhausted.
        execute_result.data = self._responses.pop(0) if self._responses else []
        execute_result.count = len(execute_result.data)
        chain.execute.return_value = execute_result
        return chain


# ─── confirm ────────────────────────────────────────────────────────────────
def test_confirm_happy_path_sets_confirmed_at_and_status(monkeypatch):
    """Happy path: pending appointment in this org becomes confirmed; the
    update payload includes status='confirmed' + a confirmed_at timestamp +
    clears any stale alternative_proposed_at."""
    appt_id = "appt-1"
    org_id = "org-1"

    # First .table().select()...execute() = _get_appointment SELECT.
    # Second .table().update()...execute() = the UPDATE returning the new row.
    pending = {
        "id": appt_id,
        "org_id": org_id,
        "status": "pending",
        # A confirmable appointment must carry a responsible employee.
        "assigned_employee_id": "emp-1",
    }
    confirmed = {**pending, "status": "confirmed", "confirmed_at": "2026-05-28T10:00:00+00:00"}
    client = _FakeClient([[pending], [confirmed]])
    monkeypatch.setattr(appt_routes, "get_service_client", lambda: client)

    result = asyncio.run(
        appt_routes.confirm_appointment(appt_id, user=_org_admin_user(org_id))
    )
    assert result["status"] == "confirmed"
    assert client._last_update_payload["status"] == "confirmed"
    assert client._last_update_payload["confirmed_at"] is not None
    assert client._last_update_payload["alternative_proposed_at"] is None


def test_confirm_409_when_no_employee_assigned(monkeypatch):
    """A pending appointment with no assigned employee cannot be confirmed —
    the API rejects it with 409 so an unassigned slot never reaches 'confirmed'
    (mirrors the UI guard that forces a Mitarbeiter selection first)."""
    pending = {"id": "appt-1", "org_id": "org-1", "status": "pending", "assigned_employee_id": None}
    monkeypatch.setattr(
        appt_routes, "get_service_client", lambda: _FakeClient([[pending]])
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            appt_routes.confirm_appointment("appt-1", user=_org_admin_user("org-1"))
        )
    assert exc.value.status_code == 409
    assert "Mitarbeiter" in exc.value.detail


def test_confirm_404_when_appointment_in_other_org(monkeypatch):
    """Cross-tenant isolation: an appointment id from another org returns 404
    (the SELECT filtered by org_id returns no rows → _get_appointment None)."""
    monkeypatch.setattr(
        appt_routes, "get_service_client", lambda: _FakeClient([[]])
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            appt_routes.confirm_appointment("appt-foreign", user=_org_admin_user("org-1"))
        )
    assert exc.value.status_code == 404


def test_confirm_409_when_not_pending(monkeypatch):
    """State-machine guard: confirming a non-pending appointment is rejected
    with 409 — otherwise the action would silently re-stamp confirmed_at on
    an already-confirmed row (or worse, re-open a cancelled appointment)."""
    already = {"id": "a", "org_id": "org-1", "status": "confirmed"}
    monkeypatch.setattr(
        appt_routes, "get_service_client", lambda: _FakeClient([[already]])
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            appt_routes.confirm_appointment("a", user=_org_admin_user("org-1"))
        )
    assert exc.value.status_code == 409
    assert "confirmed" in exc.value.detail


# ─── reject ─────────────────────────────────────────────────────────────────
def test_reject_happy_path_stamps_rejected_at_and_reason(monkeypatch):
    """Happy path: pending appointment becomes 'cancelled' (re-using the
    existing terminal status) with rejected_at + rejection_reason set —
    those two fields distinguish a hard-reject from a customer-initiated
    cancel down the line."""
    pending = {"id": "a", "org_id": "org-1", "status": "pending"}
    rejected = {**pending, "status": "cancelled", "rejected_at": "2026-05-28T10:00:00+00:00"}
    client = _FakeClient([[pending], [rejected]])
    monkeypatch.setattr(appt_routes, "get_service_client", lambda: client)

    payload = appt_routes.RejectAppointmentRequest(reason="Kunde nicht erreichbar")
    result = asyncio.run(
        appt_routes.reject_appointment("a", payload, user=_org_admin_user("org-1"))
    )
    assert result["status"] == "cancelled"
    assert client._last_update_payload["status"] == "cancelled"
    assert client._last_update_payload["rejected_at"] is not None
    assert client._last_update_payload["rejection_reason"] == "Kunde nicht erreichbar"


def test_reject_without_reason_ok(monkeypatch):
    """Reason is optional — passing no body (or empty payload) still works
    and stores rejection_reason=None."""
    pending = {"id": "a", "org_id": "org-1", "status": "pending"}
    rejected = {**pending, "status": "cancelled"}
    client = _FakeClient([[pending], [rejected]])
    monkeypatch.setattr(appt_routes, "get_service_client", lambda: client)

    result = asyncio.run(
        appt_routes.reject_appointment("a", None, user=_org_admin_user("org-1"))
    )
    assert result["status"] == "cancelled"
    assert client._last_update_payload["rejection_reason"] is None


def test_reject_409_when_not_pending(monkeypatch):
    """Same state-machine guard: rejecting a confirmed appointment is 409."""
    confirmed = {"id": "a", "org_id": "org-1", "status": "confirmed"}
    monkeypatch.setattr(
        appt_routes, "get_service_client", lambda: _FakeClient([[confirmed]])
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            appt_routes.reject_appointment("a", None, user=_org_admin_user("org-1"))
        )
    assert exc.value.status_code == 409


# ─── propose-alternative ────────────────────────────────────────────────────
def test_propose_alternative_happy_path_sets_alt_fields(monkeypatch):
    """Happy path: alternative_* fields filled; status STAYS 'pending' (the
    card detects the 'Alternative gesendet' visual state by reading
    alternative_proposed_at, not by a status change)."""
    pending = {"id": "a", "org_id": "org-1", "status": "pending"}
    updated = {**pending, "alternative_proposed_at": "2026-05-28T10:00:00+00:00"}
    client = _FakeClient([[pending], [updated]])
    monkeypatch.setattr(appt_routes, "get_service_client", lambda: client)

    future_start = datetime.now(timezone.utc) + timedelta(days=1)
    future_end = future_start + timedelta(hours=1)
    payload = appt_routes.ProposeAlternativeRequest(
        start_time=future_start,
        end_time=future_end,
        note="Vorschlag: Donnerstag stattdessen",
    )
    result = asyncio.run(
        appt_routes.propose_alternative_appointment(
            "a", payload, user=_org_admin_user("org-1")
        )
    )
    # Status is NOT in the update payload (stays pending).
    assert "status" not in client._last_update_payload
    assert client._last_update_payload["alternative_proposed_at"] is not None
    assert client._last_update_payload["alternative_note"] == "Vorschlag: Donnerstag stattdessen"
    assert result.get("alternative_proposed_at") is not None


def test_propose_alternative_422_when_start_after_end():
    """Validation: start_time must be strictly before end_time."""
    future_start = datetime.now(timezone.utc) + timedelta(days=2)
    bad_end = future_start - timedelta(hours=1)  # end BEFORE start
    payload = appt_routes.ProposeAlternativeRequest(
        start_time=future_start,
        end_time=bad_end,
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            appt_routes.propose_alternative_appointment(
                "a", payload, user=_org_admin_user("org-1")
            )
        )
    assert exc.value.status_code == 422
    assert "start_time" in exc.value.detail


def test_propose_alternative_422_when_start_in_past():
    """Validation: alternative must be in the future."""
    past_start = datetime.now(timezone.utc) - timedelta(hours=1)
    past_end = past_start + timedelta(hours=1)
    payload = appt_routes.ProposeAlternativeRequest(
        start_time=past_start,
        end_time=past_end,
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            appt_routes.propose_alternative_appointment(
                "a", payload, user=_org_admin_user("org-1")
            )
        )
    assert exc.value.status_code == 422
    assert "Zukunft" in exc.value.detail


# ─── pending-for-call lookup ────────────────────────────────────────────────
def test_pending_for_call_returns_appointment_when_present(monkeypatch):
    """Happy path: call exists → inquiry exists → pending appointment exists
    → returns it in {appointment: …}."""
    call_id = "call-1"
    org_id = "org-1"
    fake_appt = {
        "id": "appt-1",
        "status": "pending",
        "scheduled_at": "2026-06-01T09:00:00+00:00",
    }
    client = _FakeClient(
        [
            [{"id": call_id}],          # calls SELECT
            [{"id": "inq-1"}],          # inquiries SELECT
            [fake_appt],                # appointments SELECT
        ]
    )
    monkeypatch.setattr(appt_routes, "get_service_client", lambda: client)
    result = asyncio.run(
        appt_routes.get_pending_appointment_for_call(
            call_id, user=_org_admin_user(org_id)
        )
    )
    assert result["appointment"]["id"] == "appt-1"


def test_pending_for_call_returns_null_when_no_inquiry(monkeypatch):
    """Call exists but no inquiry attached yet → {appointment: null}, not 404."""
    client = _FakeClient([[{"id": "call-1"}], []])  # call yes, inquiry no
    monkeypatch.setattr(appt_routes, "get_service_client", lambda: client)
    result = asyncio.run(
        appt_routes.get_pending_appointment_for_call(
            "call-1", user=_org_admin_user("org-1")
        )
    )
    assert result == {"appointment": None}


def test_pending_for_call_404_when_call_missing(monkeypatch):
    """No matching call in this org → 404 (matches /api/calls/{id} semantic)."""
    client = _FakeClient([[]])  # calls SELECT empty
    monkeypatch.setattr(appt_routes, "get_service_client", lambda: client)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            appt_routes.get_pending_appointment_for_call(
                "missing", user=_org_admin_user("org-1")
            )
        )
    assert exc.value.status_code == 404


# ─── approve / decline customer counter-proposal (reschedule loop) ───────────
def test_approve_proposal_applies_slot_and_confirms(monkeypatch):
    """Approving a customer counter-proposal sets scheduled_at to it, confirms
    the appointment, and consumes the proposal fields."""
    proposed = {
        "id": "a", "org_id": "org-1", "status": "pending",
        "customer_proposed_start_time": "2026-06-15T12:00:00+00:00",
    }
    confirmed = {**proposed, "status": "confirmed", "scheduled_at": "2026-06-15T12:00:00+00:00"}
    client = _FakeClient([[proposed], [confirmed]])
    monkeypatch.setattr(appt_routes, "get_service_client", lambda: client)

    result = asyncio.run(
        appt_routes.approve_customer_proposal("a", user=_org_admin_user("org-1"))
    )
    assert result["status"] == "confirmed"
    upd = client._last_update_payload
    assert upd["scheduled_at"] == "2026-06-15T12:00:00+00:00"
    assert upd["status"] == "confirmed" and upd["confirmed_at"] is not None
    assert upd["customer_proposed_start_time"] is None  # consumed
    assert upd["customer_proposed_at"] is None


def test_approve_proposal_409_when_no_proposal(monkeypatch):
    """Approving with nothing proposed → 409 (state-machine guard)."""
    no_prop = {"id": "a", "org_id": "org-1", "status": "pending", "customer_proposed_start_time": None}
    monkeypatch.setattr(appt_routes, "get_service_client", lambda: _FakeClient([[no_prop]]))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(appt_routes.approve_customer_proposal("a", user=_org_admin_user("org-1")))
    assert exc.value.status_code == 409


def test_approve_proposal_404_when_other_org(monkeypatch):
    monkeypatch.setattr(appt_routes, "get_service_client", lambda: _FakeClient([[]]))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(appt_routes.approve_customer_proposal("a", user=_org_admin_user("org-1")))
    assert exc.value.status_code == 404


def test_decline_proposal_clears_fields(monkeypatch):
    """Declining clears the customer_proposed_* fields and leaves the rest as-is."""
    proposed = {
        "id": "a", "org_id": "org-1", "status": "pending",
        "customer_proposed_start_time": "2026-06-15T12:00:00+00:00",
    }
    cleared = {**proposed, "customer_proposed_start_time": None}
    client = _FakeClient([[proposed], [cleared]])
    monkeypatch.setattr(appt_routes, "get_service_client", lambda: client)

    asyncio.run(appt_routes.decline_customer_proposal("a", user=_org_admin_user("org-1")))
    assert client._last_update_payload["customer_proposed_start_time"] is None
    assert client._last_update_payload["customer_proposed_at"] is None
    # keep-intent (default): the original appointment is NOT cancelled.
    assert "status" not in client._last_update_payload


def test_decline_proposal_replace_intent_cancels_original(monkeypatch):
    """When the customer abandoned the old slot (reschedule_replace_intent), declining
    the move cancels the appointment (reversible) so the held slot is freed."""
    proposed = {
        "id": "a", "org_id": "org-1", "status": "pending",
        "customer_proposed_start_time": "2026-06-15T12:00:00+00:00",
        "reschedule_replace_intent": True,
    }
    cancelled = {**proposed, "status": "cancelled"}
    client = _FakeClient([[proposed], [cancelled]])
    monkeypatch.setattr(appt_routes, "get_service_client", lambda: client)

    result = asyncio.run(
        appt_routes.decline_customer_proposal("a", user=_org_admin_user("org-1"))
    )
    assert client._last_update_payload["status"] == "cancelled"
    assert client._last_update_payload["cancelled_at"] is not None
    assert client._last_update_payload["customer_proposed_at"] is None
    # the route uses this flag to fire the cancellation notification
    assert result.get("_replace_cancelled") is True
