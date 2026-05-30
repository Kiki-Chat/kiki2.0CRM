"""Post-call dedup tests (Sprint P0.2).

Three scenarios — taken from Amber's spec on the P0.2 question:

  (a) happy dedup        — same conv_id fired twice → second returns
                            status="skipped", skip_reason="already_processed".
  (b) in-flight retry    — same conv_id, first row exists but has empty
                            summary AND empty transcript (first webhook crashed
                            mid-processing) → second call IS allowed to complete
                            the work, NOT skipped.
  (c) false-positive guard — two rows with DIFFERENT conv_ids but identical
                              caller_number + started_at + duration (the exact
                              pattern of the test data Amber flagged in the
                              call list) → both kept; the dedup must only match
                              on (org_id, conversation_id), never on heuristics.

The tests mock the Supabase service-client chain and the heavy collaborators
(get_or_create_customer, ensure_call_inquiry, broadcast_new_call) so they
focus on the dedup branch + the result envelope, without an integration DB.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.post_call import _process_one


# ─── Helpers ──────────────────────────────────────────────────────────────
def _query_chain(returns: list) -> MagicMock:
    """A supabase-py-style chain that ignores filters and returns `returns` on execute()."""
    chain = MagicMock()
    for op in ("select", "eq", "neq", "limit", "order", "upsert", "insert"):
        getattr(chain, op).return_value = chain
    chain.execute.return_value = MagicMock(data=returns)
    return chain


def _build_client(table_responses: dict[str, list[list]]) -> MagicMock:
    """A supabase client where each successive .table(name) call pops the next response.

    Example: ``{"calls": [[], [{"id": "call_new"}]]}`` makes the first
    .table("calls") chain return [] on execute() and the second return [{...}].
    """
    state = {name: list(responses) for name, responses in table_responses.items()}

    def _table(name: str) -> MagicMock:
        queue = state.get(name)
        if not queue:
            return _query_chain([])
        return _query_chain(queue.pop(0))

    client = MagicMock()
    client.table.side_effect = _table
    return client


def _payload(*, conv_id: str, agent_id: str = "agent_x") -> dict:
    """A minimal valid post-call payload that exercises the full _process_one path."""
    return {
        "conversation_id": conv_id,
        "agent_id": agent_id,
        "transcript": [
            {
                "role": "agent",
                "message": "Hallo",
                "time_in_call_secs": 0,
                "tool_calls": [],
                "tool_results": [],
            }
        ],
        "analysis": {
            "transcript_summary": "Testanruf",
            "call_summary_title": "Test",
            "data_collection_results": {},
        },
        "metadata": {
            "call_duration_secs": 223,
            "start_time_unix_secs": 1748072563,  # 2026-05-24 07:52:43 UTC, same as Amber's test row
            "phone_call": {
                "direction": "inbound",
                "external_number": "918920100973",
            },
        },
    }


def _stub_collaborators(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub out the downstream effects so tests focus on the dedup branch."""
    monkeypatch.setattr(
        "app.services.customers.get_or_create_customer",
        lambda *a, **k: {"id": "cust_x"},
    )
    monkeypatch.setattr(
        "app.services.inquiries.ensure_call_inquiry",
        lambda *a, **k: {"id": "inq_x"},
    )
    monkeypatch.setattr(
        "app.services.post_call.broadcast_new_call",
        lambda *a, **k: None,
    )


# ─── (a) happy dedup ──────────────────────────────────────────────────────
def test_a_dedup_skips_when_prior_already_processed(monkeypatch):
    _stub_collaborators(monkeypatch)
    # 1st .table("organizations") → finds org_x
    # 2nd .table("calls")         → returns prior completed row with summary
    client = _build_client(
        {
            "organizations": [[{"id": "org_x"}]],
            "calls": [
                [
                    {
                        "id": "call_prior",
                        "status": "completed",
                        "summary": "Customer wanted info",
                        "transcript": [{"any": 1}],
                    }
                ]
            ],
        }
    )
    monkeypatch.setattr("app.services.post_call.get_service_client", lambda: client)

    result = _process_one(_payload(conv_id="conv_X"), "envelope")

    assert result["status"] == "skipped", result
    assert result["skipReason"] == "already_processed"
    assert result["callLogId"] == "call_prior"
    assert result["orgId"] == "org_x"


# ─── (b) in-flight retry ─────────────────────────────────────────────────
def test_b_inflight_retry_proceeds_when_prior_is_partial(monkeypatch):
    _stub_collaborators(monkeypatch)
    # Dedup SELECT finds prior with status=completed but BOTH summary and
    # transcript empty → already_done is False → must continue processing.
    # Subsequent .table("calls") is the upsert; .table("inquiries") for ensure_call_inquiry select.
    client = _build_client(
        {
            "organizations": [[{"id": "org_x"}]],
            "calls": [
                # 1st: dedup SELECT — partial prior row
                [{"id": "call_partial", "status": "completed", "summary": None, "transcript": None}],
                # 2nd: upsert — returns the (updated) row id
                [{"id": "call_partial"}],
            ],
            "inquiries": [[]],  # ensure_call_inquiry's SELECT will be stubbed via monkeypatch above anyway
        }
    )
    monkeypatch.setattr("app.services.post_call.get_service_client", lambda: client)

    result = _process_one(_payload(conv_id="conv_X"), "envelope")

    assert result["status"] == "processed", result
    assert result["skipReason"] is None
    assert result["callLogId"] == "call_partial"


# ─── (c) false-positive guard ────────────────────────────────────────────
def test_c_different_conv_ids_with_same_metadata_both_kept(monkeypatch):
    _stub_collaborators(monkeypatch)
    # New conv_id "conv_Y" — dedup SELECT returns [] (no match on this conv_id).
    # The fact that caller_number/started_at/duration match an existing row is
    # IRRELEVANT: dedup must scope strictly to (org_id, conversation_id).
    client = _build_client(
        {
            "organizations": [[{"id": "org_x"}]],
            "calls": [
                [],  # 1st: dedup SELECT — no match on conv_Y
                [{"id": "call_new"}],  # 2nd: upsert
            ],
            "inquiries": [[]],
        }
    )
    monkeypatch.setattr("app.services.post_call.get_service_client", lambda: client)

    result = _process_one(_payload(conv_id="conv_Y"), "envelope")

    assert result["status"] == "processed", result
    assert result["skipReason"] is None
    assert result["callLogId"] == "call_new"


# ─── Bonus: missing conversation_id should not trip the dedup ────────────
def test_d_missing_conversation_id_skips_dedup_and_processes(monkeypatch):
    """If conversation_id is missing (malformed payload), don't query calls — let
    the rest of _process_one handle the row (will end up with conv_id=NULL).
    Regression guard for the `if conversation_id:` gate around the dedup."""
    _stub_collaborators(monkeypatch)
    client = _build_client(
        {
            "organizations": [[{"id": "org_x"}]],
            "calls": [[{"id": "call_no_conv"}]],  # upsert response
            "inquiries": [[]],
        }
    )
    monkeypatch.setattr("app.services.post_call.get_service_client", lambda: client)

    payload = _payload(conv_id="placeholder")
    payload["conversation_id"] = None  # malformed

    result = _process_one(payload, "envelope")

    assert result["status"] == "processed", result
    assert result["skipReason"] is None


# ─── orphan fix: outbound calls must NOT spawn a new inquiry ──────────────
def test_outbound_call_does_not_spawn_inquiry(monkeypatch):
    """An OUTBOUND post-call is already linked to its case via
    outbound_calls.inquiry_id, so ensure_call_inquiry must NOT run (that was the
    bug that produced the orphan ANF-2026-0020)."""
    monkeypatch.setattr("app.services.customers.get_or_create_customer", lambda *a, **k: {"id": "cust_x"})
    monkeypatch.setattr("app.services.post_call.broadcast_new_call", lambda *a, **k: None)
    ensure = MagicMock(return_value={"id": "inq_x"})
    monkeypatch.setattr("app.services.inquiries.ensure_call_inquiry", ensure)

    client = _build_client({
        "organizations": [[{"id": "org_x"}]],
        "calls": [[], [{"id": "call_out"}]],  # dedup empty, then upsert
        "inquiries": [[]],
    })
    monkeypatch.setattr("app.services.post_call.get_service_client", lambda: client)

    payload = _payload(conv_id="conv_out")
    payload["metadata"]["phone_call"]["direction"] = "outbound"
    result = _process_one(payload, "envelope")

    assert result["status"] == "processed", result
    ensure.assert_not_called()  # orphan fix


def test_inbound_call_still_spawns_inquiry(monkeypatch):
    """Inbound path unchanged — ensure_call_inquiry still runs."""
    monkeypatch.setattr("app.services.customers.get_or_create_customer", lambda *a, **k: {"id": "cust_x"})
    monkeypatch.setattr("app.services.post_call.broadcast_new_call", lambda *a, **k: None)
    ensure = MagicMock(return_value={"id": "inq_x"})
    monkeypatch.setattr("app.services.inquiries.ensure_call_inquiry", ensure)

    client = _build_client({
        "organizations": [[{"id": "org_x"}]],
        "calls": [[], [{"id": "call_in"}]],
        "inquiries": [[]],
    })
    monkeypatch.setattr("app.services.post_call.get_service_client", lambda: client)

    result = _process_one(_payload(conv_id="conv_in"), "envelope")  # direction inbound (default)

    assert result["status"] == "processed", result
    ensure.assert_called_once()
