"""Tiny in-process sliding-window rate limiter for LLM-spend endpoints.

Audit 2026-06-11: the backend had NO rate limiting anywhere; any authenticated
org user could loop the copilot/chat, cases/propose, or rule-generate endpoints
into unmetered OpenAI spend. This guards exactly those (per-org, per-endpoint).

Deliberately dependency-free and in-memory: the backend runs as a single
process on Railway, so a process-local window is sufficient. If the backend is
ever scaled horizontally, replace with a shared store (Redis is already in the
project) — the call sites won't change.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException

_lock = threading.Lock()
_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def enforce_rate_limit(
    name: str, org_id: str | None, *, max_calls: int, per_seconds: float
) -> None:
    """Raise 429 when (name, org) exceeded max_calls within the sliding window.

    Counts the current call on success. org_id None (shouldn't happen behind
    require_org) falls back to a shared bucket rather than no limit.
    """
    key = (name, org_id or "_global")
    now = time.monotonic()
    with _lock:
        q = _hits[key]
        while q and now - q[0] > per_seconds:
            q.popleft()
        if len(q) >= max_calls:
            raise HTTPException(
                status_code=429,
                detail="Zu viele Anfragen — bitte warten Sie einen Moment und "
                "versuchen Sie es erneut.",
            )
        q.append(now)


def reset() -> None:
    """Test hook: clear all windows."""
    with _lock:
        _hits.clear()
