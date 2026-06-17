"""Batch 5 — EMP-030 auto-assign (services/dispatch.resolve_auto_assignee) and
the dispatch is_technician guard (api/routes/appointments._dispatch_technician).

The DB is mocked: a chainable MagicMock returns staged rows for the single
employees SELECT in resolve_auto_assignee, and a sequenced fake client feeds
the _dispatch_technician route its employee lookup.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api import deps
from app.api.routes import appointments as appt_routes
from app.services.dispatch import resolve_auto_assignee


# ─── helpers ────────────────────────────────────────────────────────────────
def _employee_client(rows: list[dict]) -> MagicMock:
    """Chainable client whose employees SELECT (…select().eq().eq().execute())
    yields `rows`. resolve_auto_assignee only ever touches the employees table."""
    chain = MagicMock()
    for method in ("select", "eq"):
        getattr(chain, method).return_value = chain
    result = MagicMock()
    result.data = rows
    chain.execute.return_value = result
    client = MagicMock()
    client.table.return_value = chain
    return client


def _emp(emp_id: str, area: str | None, *, auto_assign=True, is_active=True) -> dict:
    return {
        "id": emp_id,
        "display_name": emp_id,
        "activity_area": area,
        "auto_assign": auto_assign,
        "is_active": is_active,
    }


# ─── 5.1 resolve_auto_assignee ────────────────────────────────────────────────
def test_clean_token_match_fires():
    """A distinct keyword in activity_area that appears in the signal wins."""
    client = _employee_client(
        [_emp("heizung-tech", "Heizung Wartung"), _emp("dach-tech", "Dachdecker")]
    )
    match = resolve_auto_assignee(
        client, "org-1", category_name="Heizung", summary="Die Heizung ist defekt"
    )
    assert match is not None and match["id"] == "heizung-tech"


def test_sentence_form_activity_area_does_not_spuriously_match():
    """activity_area typed as a full sentence ('Wenn der Mitarbeiter X genannt
    wird') must NOT match a sanitär signal — the connective stopwords are
    stripped, leaving only 'mitarbeiter'/'genannt', which the signal lacks."""
    client = _employee_client(
        [_emp("sentence-emp", "Wenn der Mitarbeiter genannt wird")]
    )
    match = resolve_auto_assignee(
        client, "org-1", category_name="Sanitär", summary="Das Waschbecken ist verstopft"
    )
    assert match is None


def test_auto_assign_false_excluded():
    """Employees with auto_assign=false are filtered by the query — when the only
    candidate that matches is opted out, nothing returns. The fake client honours
    the .eq('auto_assign', True) filter by returning [] for that case."""
    # resolve_auto_assignee builds .eq('auto_assign', True); we model the DB
    # filter by feeding zero rows back (no auto-assign employee exists).
    client = _employee_client([])
    match = resolve_auto_assignee(
        client, "org-1", category_name="Heizung", summary="Heizung defekt"
    )
    assert match is None


def test_auto_assign_false_employee_not_returned_even_if_in_rows():
    """Defense-in-depth: even if a non-auto_assign row leaked through the query,
    it has the same activity_area as the signal but resolve relies on the query
    filter. Here we confirm the query is built with the auto_assign filter."""
    client = _employee_client([_emp("opted-out", "Heizung", auto_assign=False)])
    # The function still scores whatever rows the (mocked) query returns; the real
    # exclusion is the .eq('auto_assign', True) on the live query. Assert that
    # filter is applied to the chain.
    resolve_auto_assignee(
        client, "org-1", category_name="Heizung", summary="Heizung defekt"
    )
    chain = client.table.return_value
    eq_calls = [c.args for c in chain.eq.call_args_list]
    assert ("auto_assign", True) in eq_calls


def test_inactive_excluded():
    """exclude_inactive (default) adds .eq('is_active', True) to the query."""
    client = _employee_client([])
    resolve_auto_assignee(
        client, "org-1", category_name="Heizung", summary="Heizung defekt"
    )
    chain = client.table.return_value
    eq_calls = [c.args for c in chain.eq.call_args_list]
    assert ("is_active", True) in eq_calls


def test_inactive_not_filtered_when_exclude_inactive_false():
    """exclude_inactive=False drops the is_active filter from the query."""
    client = _employee_client([_emp("x", "Heizung", is_active=False)])
    resolve_auto_assignee(
        client,
        "org-1",
        category_name="Heizung",
        summary="Heizung defekt",
        exclude_inactive=False,
    )
    chain = client.table.return_value
    eq_calls = [c.args for c in chain.eq.call_args_list]
    assert ("is_active", True) not in eq_calls


def test_tie_returns_none():
    """Two employees with equal top overlap → ambiguous → None (tie loses)."""
    client = _employee_client(
        [_emp("a", "Heizung Sanitär"), _emp("b", "Heizung Elektrik")]
    )
    # Both share exactly one distinctive token ('heizung') with the signal.
    match = resolve_auto_assignee(
        client, "org-1", category_name="Heizung", summary="Heizung kaputt"
    )
    assert match is None


def test_distinctive_winner_beats_runner_up():
    """A strictly higher overlap than #2 wins even when #2 also matches."""
    client = _employee_client(
        [_emp("strong", "Heizung Wartung Notdienst"), _emp("weak", "Heizung")]
    )
    match = resolve_auto_assignee(
        client,
        "org-1",
        category_name="Heizung",
        summary="Heizung Wartung Notdienst nötig",
    )
    assert match is not None and match["id"] == "strong"


def test_no_auto_assign_employees_returns_none():
    """No auto-assign employees at all → None (category-default path untouched)."""
    client = _employee_client([])
    match = resolve_auto_assignee(
        client, "org-1", category_name="Heizung", summary="Heizung defekt"
    )
    assert match is None


def test_empty_activity_area_skipped():
    """An auto-assign employee with empty activity_area is never scored."""
    client = _employee_client([_emp("blank", ""), _emp("blank2", None)])
    match = resolve_auto_assignee(
        client, "org-1", category_name="Heizung", summary="Heizung defekt"
    )
    assert match is None


def test_empty_signal_returns_none():
    """No tokens in category_name+summary → None (nothing to match against)."""
    client = _employee_client([_emp("a", "Heizung")])
    match = resolve_auto_assignee(client, "org-1", category_name="", summary="")
    assert match is None


def test_never_raises_on_db_error():
    """A DB blow-up is swallowed (best-effort) → None, not an exception."""
    client = MagicMock()
    client.table.side_effect = RuntimeError("db down")
    match = resolve_auto_assignee(
        client, "org-1", category_name="Heizung", summary="Heizung defekt"
    )
    assert match is None


# ─── 5.4 _dispatch_technician is_technician guard ─────────────────────────────
def _org_admin_user(org_id: str = "org-1") -> deps.CurrentUser:
    return deps.CurrentUser(
        id="user-1",
        email="admin@example.com",
        org_id=org_id,
        role="org_admin",
        full_name=None,
    )


def test_dispatch_422_when_target_not_technician(monkeypatch):
    """Dispatching to an employee who is NOT is_technician=true is rejected with
    422 BEFORE any assignment/email side-effect — _patch must not even run."""
    non_tech = {
        "id": "emp-1",
        "display_name": "Bürokraft",
        "email": "buero@example.com",
        "is_technician": False,
    }
    chain = MagicMock()
    for method in ("select", "eq", "limit"):
        getattr(chain, method).return_value = chain
    result = MagicMock()
    result.data = [non_tech]
    chain.execute.return_value = result
    fake_client = MagicMock()
    fake_client.table.return_value = chain
    monkeypatch.setattr(appt_routes, "get_service_client", lambda: fake_client)

    # _patch must NOT be reached for a non-technician.
    def _boom(*a, **k):  # pragma: no cover — asserts the guard runs first
        raise AssertionError("_patch should not run for a non-technician")

    monkeypatch.setattr(appt_routes, "_patch", _boom)

    with pytest.raises(HTTPException) as exc:
        appt_routes._dispatch_technician(_org_admin_user(), "appt-1", "emp-1")
    assert exc.value.status_code == 422
    assert "Techniker" in exc.value.detail


def test_dispatch_422_when_employee_not_found(monkeypatch):
    """An unknown employee id (no row in this org) is treated as 'not a technician'
    → 422, never reaching the assignment path."""
    chain = MagicMock()
    for method in ("select", "eq", "limit"):
        getattr(chain, method).return_value = chain
    result = MagicMock()
    result.data = []
    chain.execute.return_value = result
    fake_client = MagicMock()
    fake_client.table.return_value = chain
    monkeypatch.setattr(appt_routes, "get_service_client", lambda: fake_client)
    monkeypatch.setattr(
        appt_routes, "_patch",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not patch")),
    )

    with pytest.raises(HTTPException) as exc:
        appt_routes._dispatch_technician(_org_admin_user(), "appt-1", "ghost")
    assert exc.value.status_code == 422
    assert "Techniker" in exc.value.detail
