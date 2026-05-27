"""Wave 2 / Agent 2.1 — backend enrichment tests for the call-list endpoint
and the new inline-assign route.

The list endpoint must surface, in addition to its prior shape:
  - inquiry_id              — uuid | null
  - inquiry_status          — 'open' | 'in_progress' | 'completed' | null
  - emergency_flag          — bool (true if inquiry has emergency_flag=true OR
                                     type ∈ {Notdienst, Notfall, Emergency})
  - assigned_employee_id    — uuid | null
  - assigned_employee_initials — str (≤2 chars) | null

The inline-assign route (`PATCH /api/inquiries/{id}/assign`) must:
  - 404 when the inquiry doesn't belong to the caller's org (no info leak)
  - 422 when the employee_id references a row in a different org
  - persist `assigned_employee_id` (including the unassign null case)
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api import deps
from app.api.routes import calls as calls_route
from app.api.routes import inquiries as inquiries_route


# ─── helpers ─────────────────────────────────────────────────────────────────
def _Resp(data=None, count=None):
    return MagicMock(data=data or [], count=count)


def _build_enrich_client(
    *,
    inquiry_rows: list[dict],
    employee_rows: list[dict],
) -> MagicMock:
    """Service-client mock for the enrichment helper. Two .execute() calls:
       1) inquiries SELECT → Resp(data=inquiry_rows)
       2) employees SELECT (only when an employee_id is on any inquiry)
    """
    responses: list = [
        _Resp(data=inquiry_rows),
        _Resp(data=employee_rows),
    ]
    state = {"idx": 0}

    def _next():
        i = state["idx"]
        state["idx"] += 1
        return responses[i] if i < len(responses) else _Resp(data=[])

    chain = MagicMock()
    for op in ("select", "eq", "neq", "in_", "order", "limit", "range"):
        getattr(chain, op).return_value = chain
    chain.execute.side_effect = _next

    client = MagicMock()
    client.table.return_value = chain
    return client


# ─── _employee_initials ──────────────────────────────────────────────────────
def test_employee_initials_empty_and_none():
    assert calls_route._employee_initials(None) is None
    assert calls_route._employee_initials("") is None
    assert calls_route._employee_initials("   ") is None


def test_employee_initials_single_word_takes_first_two_chars():
    """Single-name → first two characters, uppercased."""
    assert calls_route._employee_initials("Felix") == "FE"
    # short name: 'Ed' → 'ED'
    assert calls_route._employee_initials("Ed") == "ED"


def test_employee_initials_multi_word_takes_first_and_last():
    """First initial + last initial (handles middle names cleanly)."""
    assert calls_route._employee_initials("Max Mustermann") == "MM"
    assert calls_route._employee_initials("Anna Maria Schmidt") == "AS"
    assert calls_route._employee_initials("  jan   wolfgang  müller  ") == "JM"


# ─── _enrich_calls_with_inquiries ────────────────────────────────────────────
def test_enrich_attaches_inquiry_fields_and_initials():
    """Happy path: call → inquiry → assigned employee — all 5 new fields land."""
    call_rows = [{"id": "call-1"}]
    inquiry_rows = [
        {
            "id": "inq-1",
            "call_id": "call-1",
            "status": "in_progress",
            "type": "info",
            "emergency_flag": False,
            "assigned_employee_id": "emp-1",
            "created_at": "2026-05-20T00:00:00+00:00",
        }
    ]
    employee_rows = [{"id": "emp-1", "display_name": "Max Mustermann"}]
    client = _build_enrich_client(
        inquiry_rows=inquiry_rows, employee_rows=employee_rows
    )

    out = calls_route._enrich_calls_with_inquiries(client, "org-1", call_rows)

    assert out[0]["inquiry_id"] == "inq-1"
    assert out[0]["inquiry_status"] == "in_progress"
    assert out[0]["emergency_flag"] is False
    assert out[0]["assigned_employee_id"] == "emp-1"
    assert out[0]["assigned_employee_initials"] == "MM"


def test_enrich_flips_emergency_when_category_is_notdienst():
    """Even if `emergency_flag` column is false, a `type` like 'Notdienst'
    should still surface emergency_flag=true so the badge renders correctly
    for legacy or AI-classified rows."""
    call_rows = [{"id": "call-1"}, {"id": "call-2"}]
    inquiry_rows = [
        {
            "id": "inq-1",
            "call_id": "call-1",
            "status": "open",
            "type": "Notdienst",
            "emergency_flag": False,
            "assigned_employee_id": None,
            "created_at": "2026-05-20T00:00:00+00:00",
        },
        {
            "id": "inq-2",
            "call_id": "call-2",
            "status": "open",
            "type": "info",
            "emergency_flag": True,  # flag wins independently of category
            "assigned_employee_id": None,
            "created_at": "2026-05-20T00:00:00+00:00",
        },
    ]
    client = _build_enrich_client(
        inquiry_rows=inquiry_rows, employee_rows=[]
    )

    out = calls_route._enrich_calls_with_inquiries(client, "org-1", call_rows)

    assert out[0]["emergency_flag"] is True  # via 'Notdienst' category
    assert out[1]["emergency_flag"] is True  # via emergency_flag column


def test_enrich_handles_calls_without_inquiries():
    """A call with no matching inquiry must still have all 5 fields set
    (mostly to null/false) so the frontend types don't break."""
    call_rows = [{"id": "call-orphan"}]
    client = _build_enrich_client(inquiry_rows=[], employee_rows=[])

    out = calls_route._enrich_calls_with_inquiries(client, "org-1", call_rows)

    assert out[0]["inquiry_id"] is None
    assert out[0]["inquiry_status"] is None
    assert out[0]["emergency_flag"] is False
    assert out[0]["assigned_employee_id"] is None
    assert out[0]["assigned_employee_initials"] is None


def test_enrich_picks_first_inquiry_when_multiple_exist():
    """When multiple non-deleted inquiries link to the same call, the earliest
    one wins. Order is enforced by the .order('created_at') in the SELECT;
    here we simulate the DB returning them already ordered ascending."""
    call_rows = [{"id": "call-1"}]
    inquiry_rows = [
        {
            "id": "inq-old",
            "call_id": "call-1",
            "status": "open",
            "type": "info",
            "emergency_flag": False,
            "assigned_employee_id": None,
            "created_at": "2026-05-20T00:00:00+00:00",
        },
        {
            "id": "inq-new",
            "call_id": "call-1",
            "status": "completed",
            "type": "info",
            "emergency_flag": False,
            "assigned_employee_id": None,
            "created_at": "2026-05-25T00:00:00+00:00",
        },
    ]
    client = _build_enrich_client(
        inquiry_rows=inquiry_rows, employee_rows=[]
    )

    out = calls_route._enrich_calls_with_inquiries(client, "org-1", call_rows)

    assert out[0]["inquiry_id"] == "inq-old"
    assert out[0]["inquiry_status"] == "open"


def test_enrich_handles_empty_call_list_without_db_calls():
    """Defensive: don't issue SELECTs when there are no calls to enrich."""
    client = MagicMock()
    out = calls_route._enrich_calls_with_inquiries(client, "org-1", [])
    assert out == []
    assert not client.table.called


# ─── PATCH /api/inquiries/{id}/assign ────────────────────────────────────────
def _user(org_id: str = "org-1") -> deps.CurrentUser:
    return deps.CurrentUser(
        id="user-1", email="u@example.com", org_id=org_id, role="org_admin", full_name=None
    )


def _build_assign_client(
    *,
    inquiry_exists: bool,
    employee_in_org: bool,
    updated_row: dict | None,
) -> MagicMock:
    """Stage three .execute() calls in order:
       1) inquiry lookup (exists?)
       2) employee lookup (only if employee_id passed; harmless if not)
       3) UPDATE returning the updated row
    """
    responses = [
        _Resp(data=[{"id": "inq-1"}] if inquiry_exists else []),
        _Resp(data=[{"id": "emp-1"}] if employee_in_org else []),
        _Resp(data=[updated_row] if updated_row else []),
    ]
    state = {"idx": 0}

    def _next():
        i = state["idx"]
        state["idx"] += 1
        return responses[i] if i < len(responses) else _Resp(data=[])

    chain = MagicMock()
    for op in ("select", "eq", "neq", "in_", "limit", "update", "order"):
        getattr(chain, op).return_value = chain
    chain.execute.side_effect = _next

    client = MagicMock()
    client.table.return_value = chain
    return client


def test_assign_returns_404_when_inquiry_not_in_org(monkeypatch):
    client = _build_assign_client(
        inquiry_exists=False, employee_in_org=True, updated_row=None
    )
    monkeypatch.setattr(inquiries_route, "get_service_client", lambda: client)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            inquiries_route.assign_inquiry(
                "inq-X",
                inquiries_route.InquiryAssignPayload(employee_id="emp-1"),
                _user(),
            )
        )
    assert exc.value.status_code == 404


def test_assign_returns_422_when_employee_in_other_org(monkeypatch):
    """Cross-org guard: an org_admin cannot assign their inquiry to an employee
    in a different tenant — even if they know the UUID."""
    client = _build_assign_client(
        inquiry_exists=True, employee_in_org=False, updated_row=None
    )
    monkeypatch.setattr(inquiries_route, "get_service_client", lambda: client)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            inquiries_route.assign_inquiry(
                "inq-1",
                inquiries_route.InquiryAssignPayload(employee_id="emp-other-org"),
                _user(),
            )
        )
    assert exc.value.status_code == 422


def test_assign_persists_employee_id(monkeypatch):
    """Happy path: a valid same-org employee_id lands on the inquiry row."""
    updated = {"id": "inq-1", "assigned_employee_id": "emp-1"}
    client = _build_assign_client(
        inquiry_exists=True, employee_in_org=True, updated_row=updated
    )
    monkeypatch.setattr(inquiries_route, "get_service_client", lambda: client)

    out = asyncio.run(
        inquiries_route.assign_inquiry(
            "inq-1",
            inquiries_route.InquiryAssignPayload(employee_id="emp-1"),
            _user(),
        )
    )
    assert out["assigned_employee_id"] == "emp-1"


def test_assign_with_null_unassigns(monkeypatch):
    """Sending `{employee_id: null}` clears the assignment without re-validating
    a non-existent employee (the same-org gate is skipped on null). The mock
    only stages 2 responses because the null branch never hits the employees
    table — the UPDATE follows immediately after the inquiry-existence check."""
    updated = {"id": "inq-1", "assigned_employee_id": None}
    responses = [
        _Resp(data=[{"id": "inq-1"}]),  # 1) inquiry exists
        _Resp(data=[updated]),  # 2) UPDATE result (employees lookup skipped)
    ]
    state = {"idx": 0}

    def _next():
        i = state["idx"]
        state["idx"] += 1
        return responses[i] if i < len(responses) else _Resp(data=[])

    chain = MagicMock()
    for op in ("select", "eq", "neq", "in_", "limit", "update", "order"):
        getattr(chain, op).return_value = chain
    chain.execute.side_effect = _next
    client = MagicMock()
    client.table.return_value = chain
    monkeypatch.setattr(inquiries_route, "get_service_client", lambda: client)

    out = asyncio.run(
        inquiries_route.assign_inquiry(
            "inq-1",
            inquiries_route.InquiryAssignPayload(employee_id=None),
            _user(),
        )
    )
    assert out["assigned_employee_id"] is None
    # Confirms the employees table was never queried for the null branch.
    assert state["idx"] == 2
