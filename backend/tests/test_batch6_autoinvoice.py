"""Batch 6.2 — auto-invoice wiring (INV-027).

Tests that `update_case` dispatches `maybe_create_invoice_for_project` when
a Fall is marked 'completed', does NOT dispatch for any other status, and that
a raised error inside the helper never fails the case update.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_user(org_id: str = "org-1", user_id: str = "u-1"):
    u = MagicMock()
    u.org_id = org_id
    u.id = user_id
    return u


def _fake_run():
    """A synchronous _run() replacement that returns a minimal case row."""
    return {"id": "case-1", "org_id": "org-1", "status": "completed", "number": "FL-2026-00001"}


# ──────────────────────────────────────────────────────────────────────────────
# Shared patch targets
# ──────────────────────────────────────────────────────────────────────────────

_CASES_MODULE = "app.api.routes.cases"


def _run_endpoint(payload_status: str, *, mock_invoice_fn=None, raise_in_helper=False):
    """Drive update_case(...) synchronously via asyncio.run() with patches.

    Returns (case_row, maybe_create_calls).
    """
    from app.api.routes.cases import CaseUpdateIn, update_case  # local import after patches applied

    user = _make_user()

    # Patch run_in_threadpool to execute _run synchronously (first call) and
    # capture subsequent calls for maybe_create_invoice_for_project.
    invoke_log: list[tuple] = []

    async def fake_run_in_threadpool(fn, *args, **kwargs):
        if fn.__name__ == "_run":
            # The inner _run closure — just execute it
            return fn()
        # Any other callable — record and optionally raise
        invoke_log.append((fn, args, kwargs))
        if raise_in_helper:
            raise RuntimeError("simulated helper failure")
        if mock_invoice_fn:
            return mock_invoice_fn(fn, *args, **kwargs)
        return None

    payload = CaseUpdateIn(status=payload_status)

    with (
        patch(f"{_CASES_MODULE}.run_in_threadpool", side_effect=fake_run_in_threadpool),
        patch(f"{_CASES_MODULE}.get_service_client") as mock_client,
    ):
        # Minimal supabase chain so the inner _run won't explode:
        # select("id") → .eq().eq().limit().execute().data = [{"id": "case-1"}]
        # update(...) → .eq().eq().execute().data = [full row]
        chain = MagicMock()
        chain.table.return_value = chain
        chain.select.return_value = chain
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.limit.return_value = chain
        chain.execute.return_value = MagicMock(
            data=[{"id": "case-1", "org_id": "org-1", "status": payload_status, "number": "FL-2026-00001"}]
        )
        mock_client.return_value = chain

        result = asyncio.run(update_case(case_id="case-1", payload=payload, user=user))

    return result, invoke_log


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestAutoInvoiceDispatch:
    def test_completed_dispatches_maybe_create(self):
        """status='completed' must call maybe_create_invoice_for_project."""
        result, log = _run_endpoint("completed")
        assert result["id"] == "case-1"
        # Exactly one extra run_in_threadpool call, to the invoices helper
        assert len(log) == 1
        fn, args, _kwargs = log[0]
        assert fn.__name__ == "maybe_create_invoice_for_project", (
            f"expected maybe_create_invoice_for_project, got {fn.__name__!r}"
        )
        # First positional arg = org_id
        assert args[0] == "org-1"
        # Second positional arg = the case row dict
        assert isinstance(args[1], dict)
        assert args[1]["id"] == "case-1"

    def test_active_does_not_dispatch(self):
        """status='active' must NOT call maybe_create_invoice_for_project."""
        result, log = _run_endpoint("active")
        assert result["id"] == "case-1"
        assert log == [], f"unexpected invoice dispatch calls: {log}"

    def test_planning_does_not_dispatch(self):
        """status='planning' must NOT call maybe_create_invoice_for_project."""
        result, log = _run_endpoint("planning")
        assert log == [], f"unexpected invoice dispatch calls: {log}"

    def test_archived_does_not_dispatch(self):
        """status='archived' must NOT call maybe_create_invoice_for_project."""
        result, log = _run_endpoint("archived")
        assert log == [], f"unexpected invoice dispatch calls: {log}"

    def test_helper_error_does_not_fail_case_update(self):
        """A RuntimeError raised inside maybe_create_invoice_for_project must be
        swallowed — the case update response must still be returned."""
        # raise_in_helper=True causes our fake run_in_threadpool to raise when
        # the invoice helper is called.
        result, log = _run_endpoint("completed", raise_in_helper=True)
        # The case row is still returned despite the helper blowing up
        assert result["id"] == "case-1", "case update was lost when helper raised"
        # The dispatch was attempted (one log entry before the raise)
        assert len(log) == 1
