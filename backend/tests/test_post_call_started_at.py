"""started_at fallback cascade tests (Sprint P0.3).

Covers the four resolution paths in _process_one:
  1. metadata.start_time_unix_secs (the happy path — ~all real EL payloads)
  2. metadata.start_time (alternate naming sometimes seen on retries)
  3. phone_call.start_time_unix_secs (legacy/alt placement)
  4. fallback to now() — better than NULL for ordering & "Eingehend · X · Y" render
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from app.services.post_call import _process_one

# A fixed unix timestamp used across the cascade tests.
_FIXED_TS = 1748072563  # 2025-05-24T07:42:43+00:00


def _expected_iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _query_chain(returns: list) -> MagicMock:
    chain = MagicMock()
    for op in ("select", "eq", "neq", "limit", "order", "upsert", "insert"):
        getattr(chain, op).return_value = chain
    chain.execute.return_value = MagicMock(data=returns)
    return chain


def _build_client() -> tuple[MagicMock, dict]:
    """Returns (client, captured_upsert_dict). Captures the dict passed to upsert
    so the test can assert started_at on the persisted row."""
    captured: dict = {}

    def _calls_chain() -> MagicMock:
        chain = MagicMock()
        for op in ("select", "eq", "neq", "limit", "order"):
            getattr(chain, op).return_value = chain
        chain.execute.return_value = MagicMock(data=[])  # no prior row (no dedup hit)

        def _upsert(row, **_kw):
            captured.update(row)
            return _query_chain([{"id": "call_new"}])

        chain.upsert.side_effect = _upsert
        return chain

    state = {"calls_calls": 0}

    def _table(name):
        if name == "organizations":
            return _query_chain([{"id": "org_x"}])
        if name == "calls":
            state["calls_calls"] += 1
            if state["calls_calls"] == 1:
                # Dedup SELECT — return empty
                chain = _query_chain([])
                return chain
            return _calls_chain()
        if name == "inquiries":
            return _query_chain([])
        return _query_chain([])

    client = MagicMock()
    client.table.side_effect = _table
    return client, captured


def _stub_collaborators(monkeypatch: pytest.MonkeyPatch) -> None:
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


def _base_payload(metadata: dict) -> dict:
    return {
        "conversation_id": "conv_XYZ",
        "agent_id": "agent_x",
        "transcript": [
            {"role": "agent", "message": "Hi", "time_in_call_secs": 0,
             "tool_calls": [], "tool_results": []}
        ],
        "analysis": {
            "transcript_summary": "test", "call_summary_title": "Test",
            "data_collection_results": {},
        },
        "metadata": metadata,
    }


# Path 1 — happy: metadata.start_time_unix_secs present
def test_started_at_uses_metadata_unix_secs(monkeypatch):
    _stub_collaborators(monkeypatch)
    client, captured = _build_client()
    monkeypatch.setattr("app.services.post_call.get_service_client", lambda: client)

    result = _process_one(
        _base_payload({
            "call_duration_secs": 60,
            "start_time_unix_secs": _FIXED_TS,
            "phone_call": {"direction": "inbound", "external_number": "+49170111222"},
        }),
        "envelope",
    )

    assert result["status"] == "processed"
    assert captured["started_at"] == _expected_iso(_FIXED_TS)


# Path 2 — alt naming: metadata.start_time (still unix-secs numeric)
def test_started_at_falls_back_to_metadata_start_time(monkeypatch):
    _stub_collaborators(monkeypatch)
    client, captured = _build_client()
    monkeypatch.setattr("app.services.post_call.get_service_client", lambda: client)

    result = _process_one(
        _base_payload({
            "call_duration_secs": 60,
            # start_time_unix_secs ABSENT
            "start_time": _FIXED_TS,
            "phone_call": {"direction": "inbound", "external_number": "+49170111222"},
        }),
        "envelope",
    )

    assert result["status"] == "processed"
    assert captured["started_at"] == _expected_iso(_FIXED_TS)


# Path 3 — phone_call.start_time_unix_secs (legacy placement)
def test_started_at_falls_back_to_phone_call(monkeypatch):
    _stub_collaborators(monkeypatch)
    client, captured = _build_client()
    monkeypatch.setattr("app.services.post_call.get_service_client", lambda: client)

    result = _process_one(
        _base_payload({
            "call_duration_secs": 60,
            "phone_call": {
                "direction": "inbound",
                "external_number": "+49170111222",
                "start_time_unix_secs": _FIXED_TS,
            },
        }),
        "envelope",
    )

    assert result["status"] == "processed"
    assert captured["started_at"] == _expected_iso(_FIXED_TS)


# Path 4 — nothing usable: must fall back to now(), never NULL
def test_started_at_falls_back_to_now_when_metadata_empty(monkeypatch):
    _stub_collaborators(monkeypatch)
    client, captured = _build_client()
    monkeypatch.setattr("app.services.post_call.get_service_client", lambda: client)

    before = datetime.now(timezone.utc)
    result = _process_one(
        _base_payload({
            "call_duration_secs": 60,
            "phone_call": {"direction": "inbound", "external_number": "+49170111222"},
            # no start_time_unix_secs / start_time / phone_call.start_time_unix_secs
        }),
        "envelope",
    )
    after = datetime.now(timezone.utc)

    assert result["status"] == "processed"
    assert captured["started_at"] is not None
    parsed = datetime.fromisoformat(captured["started_at"])
    # within the test window — confirms we used now(), not NULL
    assert before - timedelta(seconds=1) <= parsed <= after + timedelta(seconds=1)


# Bonus: malformed (non-numeric string) should still fall back to now()
def test_started_at_falls_back_to_now_when_value_is_malformed(monkeypatch):
    _stub_collaborators(monkeypatch)
    client, captured = _build_client()
    monkeypatch.setattr("app.services.post_call.get_service_client", lambda: client)

    result = _process_one(
        _base_payload({
            "call_duration_secs": 60,
            "start_time_unix_secs": "not-a-number",
            "phone_call": {"direction": "inbound", "external_number": "+49170111222"},
        }),
        "envelope",
    )

    assert result["status"] == "processed"
    assert captured["started_at"] is not None
    # confirm it's a parseable ISO timestamp (so it's not the malformed string)
    datetime.fromisoformat(captured["started_at"])
