"""Historical ElevenLabs conversation import (P0.9 Part B).

After provisioning a new org bound to an ElevenLabs agent, the agent may
already have prior conversations from before HeyKiki onboarding. This module
pulls them down so the new customer's Call Logs aren't empty on day 1.

Built to survive LARGE back-catalogues (agents with hundreds of calls):
  * runs ONLY as a BackgroundTask — never in the request path, so account
    creation returns immediately and a slow import can't time the request out;
  * retries with backoff on rate-limit / timeout (a 600-call burst gets
    throttled by ElevenLabs otherwise);
  * already-imported conversations are skipped WITHOUT re-fetching (a bulk
    preload of existing ids), so a re-trigger resumes cheaply instead of
    re-pulling the whole history;
  * the whole run is defensive — one bad conversation, or a transient outage
    mid-stream, never aborts the batch or escapes the background task;
  * a per-run safety cap bounds a single pass; re-trigger to continue.

Idempotent: re-runs hit the P0.2 SELECT-first dedup in `_process_one` (and now
the pre-fetch existing-id skip), so a re-trigger only processes newly-discovered
conversations.

Endpoints used:
  GET /v1/convai/conversations?agent_id=…&page_size=100  → paginated conv ids
  GET /v1/convai/conversations/{conversation_id}         → full payload
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Iterator
from uuid import UUID

import httpx

from app.core.config import settings
from app.db.supabase_client import get_service_client
from app.services.post_call import _process_one

log = logging.getLogger(__name__)

EL_BASE = "https://api.elevenlabs.io"
PAGE_SIZE = 100
_TIMEOUT = 30.0
_MAX_PAGES = 80           # safety guard against infinite pagination (≈8000 convs)
_MAX_NEW_PER_RUN = 1000   # cap NEW imports in one background pass; re-trigger to continue
_RETRIES = 3              # attempts per request before giving up
_BACKOFF_BASE = 1.0       # seconds; doubles each retry (1s, 2s, …)
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _headers() -> dict[str, str]:
    return {"xi-api-key": settings.elevenlabs_api_key}


def _get_with_retry(
    client: httpx.Client, url: str, params: dict | None = None
) -> httpx.Response | None:
    """GET with small exponential backoff on rate-limit / 5xx / network error.
    Returns the Response (success OR a non-retryable failure), or None when every
    attempt raised a network/timeout error. The caller treats None / non-200 as
    'skip this one' — never as a crash."""
    resp: httpx.Response | None = None
    for attempt in range(_RETRIES):
        try:
            resp = client.get(url, headers=_headers(), params=params)
        except httpx.HTTPError as exc:  # timeout / connection reset / etc.
            log.warning("history_import: %s network error (try %d/%d): %s",
                        url, attempt + 1, _RETRIES, exc)
            resp = None
        else:
            if resp.status_code == 200 or resp.status_code not in _RETRYABLE_STATUS:
                return resp  # success, or a permanent failure (e.g. 404) — done
        if attempt < _RETRIES - 1:
            time.sleep(_BACKOFF_BASE * (2 ** attempt))
    return resp


def _list_conversation_ids(agent_id: str) -> Iterator[str]:
    """Paginate /v1/convai/conversations?agent_id=… and yield each conv_id."""
    with httpx.Client(base_url=EL_BASE, timeout=_TIMEOUT) as client:
        cursor: str | None = None
        page = 0
        while True:
            params: dict = {"agent_id": agent_id, "page_size": PAGE_SIZE}
            if cursor:
                params["cursor"] = cursor
            r = _get_with_retry(client, "/v1/convai/conversations", params=params)
            if r is None or r.status_code != 200:
                log.warning("history_import: list page %d failed: %s %s", page,
                            getattr(r, "status_code", "network-error"),
                            (r.text[:200] if r is not None else ""))
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
                log.warning("history_import: hit %d-page safety guard for agent %s",
                            _MAX_PAGES, agent_id)
                return


def _fetch_conversation(conversation_id: str) -> dict | None:
    """GET full conversation envelope matching the post-call webhook shape."""
    with httpx.Client(base_url=EL_BASE, timeout=_TIMEOUT) as client:
        r = _get_with_retry(client, f"/v1/convai/conversations/{conversation_id}")
    if r is None or r.status_code != 200:
        log.warning("history_import: GET conversation %s failed: %s", conversation_id,
                    getattr(r, "status_code", "network-error"))
        return None
    return r.json()


def _existing_conversation_ids(org_id: str | UUID) -> set[str]:
    """EL conversation ids already imported for this org — so a re-run skips them
    WITHOUT re-fetching from ElevenLabs (cheap, resumable after an interrupted
    pass). Best-effort: a read failure just means we fall back to the post-fetch
    dedup in _process_one (correct, only slower)."""
    try:
        rows = (
            get_service_client()
            .table("calls")
            .select("elevenlabs_conversation_id")
            .eq("org_id", str(org_id))
            .execute()
            .data
            or []
        )
        return {r["elevenlabs_conversation_id"] for r in rows if r.get("elevenlabs_conversation_id")}
    except Exception:  # noqa: BLE001
        log.exception("history_import: existing-id preload failed for org=%s", org_id)
        return set()


def import_agent_history(
    org_id: str | UUID, agent_id: str, max_new: int | None = _MAX_NEW_PER_RUN
) -> dict:
    """Import historical EL conversations into ``calls`` for ``org_id``.

    Returns ``{imported, skipped, errors, seen, more}`` — ``more=True`` means the
    per-run cap was hit and a re-trigger will continue. Run ONLY as a
    BackgroundTask (it can take minutes for a large agent). Resilient + resumable:
    safe to re-trigger; the existing-id skip + P0.2 dedup make it idempotent.
    """
    if not settings.elevenlabs_api_key:
        log.warning("history_import: ELEVENLABS_API_KEY not set; skipping org=%s", org_id)
        return {"imported": 0, "skipped": 0, "errors": 1, "seen": 0, "more": False,
                "reason": "no_api_key"}

    existing = _existing_conversation_ids(org_id)
    imported = skipped = errors = seen = 0
    more = False

    try:
        for conv_id in _list_conversation_ids(agent_id):
            seen += 1
            if conv_id in existing:
                skipped += 1            # already imported → no fetch, no re-process
                continue
            if max_new is not None and imported >= max_new:
                more = True             # hit the per-run cap; re-trigger to continue
                log.warning("history_import: per-run cap %d reached for org=%s — "
                            "re-trigger to continue", max_new, org_id)
                break
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
                    existing.add(conv_id)
                else:
                    errors += 1
                    log.warning("history_import: unexpected status %r for %s: %r",
                                status_, conv_id, result.get("skipReason"))
            except Exception:  # noqa: BLE001 — one bad conv never aborts the batch
                log.exception("history_import: exception processing %s", conv_id)
                errors += 1
    except Exception:  # noqa: BLE001 — listing/iteration failure must not escape the task
        log.exception("history_import: run aborted early for org=%s agent=%s", org_id, agent_id)

    log.info("history_import done org=%s agent=%s seen=%d imported=%d skipped=%d errors=%d more=%s",
             org_id, agent_id, seen, imported, skipped, errors, more)
    return {"imported": imported, "skipped": skipped, "errors": errors, "seen": seen, "more": more}


# ─── Auto-continuing wrapper + progress state ────────────────────────────────
_MAX_PASSES = 20  # auto-continue bound: 20 × _MAX_NEW_PER_RUN ≈ 20k convs per run


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_import_state(org_id: str | UUID, state: dict) -> None:
    """Best-effort: persist import progress on ``organizations.history_import_state``
    so the super-admin Migration view can show running / complete / N-of-M. A write
    failure is logged, never raised (it must not break the import)."""
    try:
        get_service_client().table("organizations").update(
            {"history_import_state": state}
        ).eq("id", str(org_id)).execute()
    except Exception:  # noqa: BLE001
        log.exception("history_import: failed to persist import state for org=%s", org_id)


def import_agent_history_until_done(org_id: str | UUID, agent_id: str) -> dict:
    """Import the FULL back-catalogue, auto-continuing past the per-run cap.

    Calls ``import_agent_history`` in a loop until a pass reports ``more=False``
    (or the ``_MAX_PASSES`` guard), so a large agent finishes in one BackgroundTask
    without a manual re-trigger. Each pass skips already-imported conversations, so
    successive passes only do new work; the run is idempotent + resumable on
    re-trigger if interrupted. Records progress on the org throughout.

    ``imported`` is summed across passes (total NEW this run); ``seen`` is the last
    pass's full list size (≈ the agent's total conversations, the "M" of N-of-M).
    """
    started = _now_iso()
    _set_import_state(org_id, {"status": "running", "started_at": started,
                              "imported": 0, "seen": 0, "errors": 0, "more": True, "passes": 0})

    imported_total = errors_total = seen_last = 0
    more = True
    passes = 0
    for passes in range(1, _MAX_PASSES + 1):
        result = import_agent_history(org_id, agent_id)
        imported_total += int(result.get("imported", 0) or 0)
        errors_total += int(result.get("errors", 0) or 0)
        seen_last = int(result.get("seen", 0) or 0)
        more = bool(result.get("more"))
        _set_import_state(org_id, {"status": "running", "started_at": started,
                                  "imported": imported_total, "seen": seen_last,
                                  "errors": errors_total, "more": more, "passes": passes})
        if not more:
            break

    status_ = "incomplete" if more else "complete"
    final = {"status": status_, "started_at": started, "finished_at": _now_iso(),
             "imported": imported_total, "seen": seen_last, "errors": errors_total,
             "more": more, "passes": passes}
    _set_import_state(org_id, final)
    log.info("history_import_until_done org=%s status=%s imported=%d seen=%d passes=%d",
             org_id, status_, imported_total, seen_last, passes)
    return final
