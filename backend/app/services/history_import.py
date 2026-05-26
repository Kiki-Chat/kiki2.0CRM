"""Historical ElevenLabs conversation import (P0.9 Part B).

After provisioning a new org bound to an ElevenLabs agent, the agent may
already have prior conversations from before HeyKiki onboarding. This module
pulls them down so the new customer's Call Logs aren't empty on day 1.

Idempotent: re-runs hit the P0.2 SELECT-first dedup in `_process_one`, so a
manual re-trigger only processes newly-discovered conversations. Safe to
call from BackgroundTasks (no long-held connection back to the HTTP request).

Endpoints used:
  GET /v1/convai/conversations?agent_id=…&page_size=100
    → paginated list of conversation_ids for the agent
  GET /v1/convai/conversations/{conversation_id}
    → full payload (transcript + analysis + metadata) — same envelope shape
      the post-call webhook delivers, so passes directly to _process_one
"""
from __future__ import annotations

import logging
from typing import Iterator
from uuid import UUID

import httpx

from app.core.config import settings
from app.services.post_call import _process_one

log = logging.getLogger(__name__)

EL_BASE = "https://api.elevenlabs.io"
PAGE_SIZE = 100
_TIMEOUT = 30.0
_MAX_PAGES = 50  # safety guard against infinite-pagination bugs


def _headers() -> dict[str, str]:
    return {"xi-api-key": settings.elevenlabs_api_key}


def _list_conversation_ids(agent_id: str) -> Iterator[str]:
    """Paginate /v1/convai/conversations?agent_id=… and yield each conv_id."""
    with httpx.Client(base_url=EL_BASE, timeout=_TIMEOUT) as client:
        cursor: str | None = None
        page = 0
        while True:
            params: dict = {"agent_id": agent_id, "page_size": PAGE_SIZE}
            if cursor:
                params["cursor"] = cursor
            r = client.get("/v1/convai/conversations", headers=_headers(), params=params)
            if r.status_code != 200:
                log.warning(
                    "history_import: list page %d failed: %d %s",
                    page, r.status_code, r.text[:200],
                )
                return
            data = r.json() or {}
            for conv in data.get("conversations") or []:
                cid = conv.get("conversation_id")
                if cid:
                    yield cid
            cursor = data.get("next_cursor")
            has_more = bool(data.get("has_more"))
            page += 1
            if not cursor or not has_more:
                return
            if page >= _MAX_PAGES:
                log.warning(
                    "history_import: hit %d-page safety guard for agent %s",
                    _MAX_PAGES, agent_id,
                )
                return


def _fetch_conversation(conversation_id: str) -> dict | None:
    """GET full conversation envelope matching the post-call webhook shape."""
    with httpx.Client(base_url=EL_BASE, timeout=_TIMEOUT) as client:
        r = client.get(
            f"/v1/convai/conversations/{conversation_id}",
            headers=_headers(),
        )
    if r.status_code != 200:
        log.warning(
            "history_import: GET conversation %s failed: %d %s",
            conversation_id, r.status_code, r.text[:200],
        )
        return None
    return r.json()


def import_agent_history(org_id: str | UUID, agent_id: str) -> dict:
    """Import every historical EL conversation for this agent into calls.

    Returns a counters dict. Logs at INFO on completion.

    The DB writes happen via `_process_one`, which:
      - resolves the org by agent_id (already wired)
      - dedupes by elevenlabs_conversation_id (P0.2)
      - links/creates the customer, creates the inquiry, broadcasts the
        Realtime event (so the org's Call Logs page sees the import
        progressively, not all at once at the end)
    """
    if not settings.elevenlabs_api_key:
        log.warning(
            "history_import: ELEVENLABS_API_KEY not set; skipping for org=%s",
            org_id,
        )
        return {"imported": 0, "skipped": 0, "errors": 1, "reason": "no_api_key"}

    imported = 0
    skipped = 0
    errors = 0
    seen = 0

    for conv_id in _list_conversation_ids(agent_id):
        seen += 1
        try:
            data = _fetch_conversation(conv_id)
            if data is None:
                errors += 1
                continue
            result = _process_one(data, "envelope")
            status_ = result.get("status")
            if status_ == "skipped":
                skipped += 1
            elif status_ == "processed":
                imported += 1
            else:
                # Other statuses (unknown_agent, unparseable_payload) shouldn't
                # happen here — the agent_id is the one we just provisioned for
                # — but count as errors if they do.
                errors += 1
                log.warning(
                    "history_import: unexpected status %r for %s: %r",
                    status_, conv_id, result.get("skipReason"),
                )
        except Exception:  # noqa: BLE001
            log.exception("history_import: exception processing %s", conv_id)
            errors += 1

    log.info(
        "history_import done org=%s agent=%s seen=%d imported=%d skipped=%d errors=%d",
        org_id, agent_id, seen, imported, skipped, errors,
    )
    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "seen": seen,
    }
