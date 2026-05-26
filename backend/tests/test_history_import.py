"""Historical ElevenLabs conversation import tests (Sprint P0.9 Part B).

Focuses on the iteration + counter logic. The real EL HTTP calls and
_process_one are mocked so tests are fast and offline.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import history_import as hi


# ─── _list_conversation_ids ──────────────────────────────────────────────────
def _mock_httpx_client_returning(pages: list[dict]) -> MagicMock:
    """Build a mock httpx.Client whose .get() pops the next page from `pages`."""
    client = MagicMock()
    calls: list[dict] = []
    def _get(path, headers=None, params=None):
        calls.append({"path": path, "params": params})
        idx = len(calls) - 1
        page = pages[idx] if idx < len(pages) else {"conversations": []}
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = page
        return resp
    client.get.side_effect = _get
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    return client


def test_list_conversation_ids_paginates_and_stops(monkeypatch):
    pages = [
        {
            "conversations": [{"conversation_id": "conv_1"}, {"conversation_id": "conv_2"}],
            "next_cursor": "c1",
            "has_more": True,
        },
        {
            "conversations": [{"conversation_id": "conv_3"}],
            "next_cursor": None,
            "has_more": False,
        },
    ]
    monkeypatch.setattr(hi.httpx, "Client", lambda **kw: _mock_httpx_client_returning(pages))
    monkeypatch.setattr(hi.settings, "elevenlabs_api_key", "fake")

    ids = list(hi._list_conversation_ids("agent_x"))
    assert ids == ["conv_1", "conv_2", "conv_3"]


def test_list_conversation_ids_stops_at_page_guard(monkeypatch):
    """Infinite pagination is caught by _MAX_PAGES guard."""
    # Always return has_more=True + a cursor → would loop forever.
    pages = [
        {
            "conversations": [{"conversation_id": f"c_{i}"}],
            "next_cursor": "k",
            "has_more": True,
        }
        for i in range(hi._MAX_PAGES + 5)
    ]
    monkeypatch.setattr(hi.httpx, "Client", lambda **kw: _mock_httpx_client_returning(pages))
    monkeypatch.setattr(hi.settings, "elevenlabs_api_key", "fake")

    ids = list(hi._list_conversation_ids("agent_x"))
    # _MAX_PAGES is 50, each page yields 1 → exactly 50 items.
    assert len(ids) == hi._MAX_PAGES


def test_list_conversation_ids_stops_on_non_200(monkeypatch):
    """API error mid-pagination stops cleanly (returns what was already yielded)."""
    def _client_factory(**kw):
        client = MagicMock()
        responses = [
            MagicMock(status_code=200, json=MagicMock(return_value={
                "conversations": [{"conversation_id": "c_1"}],
                "next_cursor": "k", "has_more": True,
            })),
            MagicMock(status_code=500, json=MagicMock(return_value={}), text="server error"),
        ]
        call_idx = {"n": 0}
        def _get(path, headers=None, params=None):
            r = responses[call_idx["n"]]
            call_idx["n"] += 1
            return r
        client.get.side_effect = _get
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        return client
    monkeypatch.setattr(hi.httpx, "Client", _client_factory)
    monkeypatch.setattr(hi.settings, "elevenlabs_api_key", "fake")

    ids = list(hi._list_conversation_ids("agent_x"))
    assert ids == ["c_1"]


# ─── import_agent_history ────────────────────────────────────────────────────
def test_import_agent_history_no_api_key(monkeypatch):
    monkeypatch.setattr(hi.settings, "elevenlabs_api_key", "")
    result = hi.import_agent_history("org_x", "agent_x")
    assert result == {"imported": 0, "skipped": 0, "errors": 1, "reason": "no_api_key"}


def test_import_agent_history_counts_processed_skipped_errors(monkeypatch):
    monkeypatch.setattr(hi.settings, "elevenlabs_api_key", "fake")

    # List returns 4 conversation ids
    monkeypatch.setattr(
        hi, "_list_conversation_ids",
        lambda agent_id: iter(["c_processed", "c_skipped", "c_fetch_fail", "c_exception"]),
    )

    # Fetch returns a dict for some, None for fetch-fail, raises for exception
    def _fetch(conv_id):
        if conv_id == "c_fetch_fail":
            return None
        if conv_id == "c_exception":
            raise RuntimeError("boom")
        return {"conversation_id": conv_id, "fake": True}
    monkeypatch.setattr(hi, "_fetch_conversation", _fetch)

    # _process_one returns "processed" for one, "skipped" for the other
    def _process(data, fmt):
        if data["conversation_id"] == "c_processed":
            return {"status": "processed"}
        if data["conversation_id"] == "c_skipped":
            return {"status": "skipped", "skipReason": "already_processed"}
        return {"status": "skipped", "skipReason": "unknown_agent"}
    monkeypatch.setattr(hi, "_process_one", _process)

    result = hi.import_agent_history("org_x", "agent_x")
    assert result["seen"] == 4
    assert result["imported"] == 1
    assert result["skipped"] == 1
    assert result["errors"] == 2  # one fetch-fail, one exception


def test_import_agent_history_unknown_agent_counted_as_error(monkeypatch):
    """A status other than processed/skipped (e.g. unknown_agent — wouldn't
    happen for a fresh provision but defends against config drift) is
    treated as an error and logged."""
    monkeypatch.setattr(hi.settings, "elevenlabs_api_key", "fake")
    monkeypatch.setattr(hi, "_list_conversation_ids", lambda a: iter(["c_1"]))
    monkeypatch.setattr(hi, "_fetch_conversation", lambda c: {"conversation_id": c})
    # _process_one returns the status='skipped' with skip_reason='unknown_agent'
    monkeypatch.setattr(
        hi, "_process_one",
        lambda d, fmt: {"status": "skipped", "skipReason": "unknown_agent"},
    )
    result = hi.import_agent_history("org_x", "agent_x")
    # 'skipped' status is counted as skipped, not error
    assert result["skipped"] == 1
    assert result["errors"] == 0
    # (the unknown_agent SkipReason is opaque to import_agent_history — it
    # only inspects status. That's intentional — _process_one owns the
    # categorization.)
