"""Cost-estimate status PATCH stamp tests (sent_at regression).

Background — KVA-2026-00001 was found in the test org with status='sent' but
sent_at IS NULL. The AI Insights tab's `kva_followup` suggestion (see
``backend/app/api/routes/dashboard.py::_ai_insights``) only fires for KVAs
whose sent_at is non-NULL (defensive ``if sent`` guard), so any KVA whose
status transitioned to 'sent' without sent_at being stamped silently
disappears from the follow-up list.

Two code paths can transition a KVA to status='sent':
  1. ``POST /api/cost-estimates/{id}/send`` — explicitly sets sent_at=_now()
     in the same update. Correct, not exercised here.
  2. ``PATCH /api/cost-estimates/{id}/status`` with status='sent' — used to
     fall through with only ``{"status": "sent"}`` because the local stamp
     map was ``{"accepted": "accepted_at", "rejected": "rejected_at"}``. The
     schema explicitly lists 'sent' as a valid status
     (``admin.CostEstimateStatus`` docstring), so the bug was reachable
     even though no current frontend caller hits it.

The fix promotes the stamp map to module scope (mirrors ``invoices._STAMP``)
and adds ``"sent": "sent_at"``. These tests pin the four observable cases.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from app.api.deps import CurrentUser
from app.api.routes import cost_estimates as ce_routes
from app.schemas.admin import CostEstimateStatus


def _user() -> CurrentUser:
    return CurrentUser(
        id="user_x", email="user@test", org_id="org_x", role="org_admin", full_name=None
    )


def _patch_client(monkeypatch) -> MagicMock:
    """Stub get_service_client → return a chain that captures the update() args.

    Returns the chain mock so tests can assert against ``chain.update.call_args``.
    """
    chain = MagicMock()
    for op in ("table", "update", "eq"):
        getattr(chain, op).return_value = chain
    chain.execute.return_value = MagicMock(data=[{"id": "ce_x", "status": "sent"}])

    client = MagicMock()
    client.table.return_value = chain
    monkeypatch.setattr(ce_routes, "get_service_client", lambda: client)
    return chain


def _run(coro):
    return asyncio.run(coro)


def test_status_sent_stamps_sent_at(monkeypatch):
    """The bug guard: PATCH /status with 'sent' must include sent_at in the update."""
    chain = _patch_client(monkeypatch)

    _run(ce_routes.set_status("ce_x", CostEstimateStatus(status="sent"), _user()))

    (fields,), _ = chain.update.call_args
    assert fields["status"] == "sent"
    assert "sent_at" in fields and fields["sent_at"], fields


def test_status_accepted_stamps_accepted_at(monkeypatch):
    chain = _patch_client(monkeypatch)

    _run(ce_routes.set_status("ce_x", CostEstimateStatus(status="accepted"), _user()))

    (fields,), _ = chain.update.call_args
    assert fields["status"] == "accepted"
    assert "accepted_at" in fields and fields["accepted_at"], fields
    # And we don't accidentally cross-stamp sent_at.
    assert "sent_at" not in fields


def test_status_rejected_stamps_rejected_at(monkeypatch):
    chain = _patch_client(monkeypatch)

    _run(ce_routes.set_status("ce_x", CostEstimateStatus(status="rejected"), _user()))

    (fields,), _ = chain.update.call_args
    assert fields["status"] == "rejected"
    assert "rejected_at" in fields and fields["rejected_at"], fields


def test_status_draft_or_invoiced_does_not_stamp(monkeypatch):
    """`draft` and `invoiced` are valid statuses (per CostEstimateStatus
    docstring) that have no dedicated timestamp column. The endpoint must
    only set ``status`` — anything else would write to a column that may not
    exist (or, worse, accidentally stamp the wrong one)."""
    chain = _patch_client(monkeypatch)

    _run(ce_routes.set_status("ce_x", CostEstimateStatus(status="draft"), _user()))

    (fields,), _ = chain.update.call_args
    assert fields == {"status": "draft"}, fields

    _run(ce_routes.set_status("ce_x", CostEstimateStatus(status="invoiced"), _user()))

    (fields,), _ = chain.update.call_args
    assert fields == {"status": "invoiced"}, fields
