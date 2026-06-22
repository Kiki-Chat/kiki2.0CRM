"""Public (no-login) technician portal — the standing link a technician opens
to see ALL their jobs (past + current), not just one dispatch.

The unguessable ``technician_portal_token`` IS the credential (same model as the
per-job link). One token → one technician → only that technician's own jobs,
always pinned to their org. Invalid/disabled → 410 with a German message.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from app.services.ratelimit import enforce_rate_limit
from app.services.technician_jobs import JobLinkError, get_technician_portal

router = APIRouter(prefix="/api/public/technician", tags=["public-technician"])


def _client_ip(request: Request) -> str:
    """Best-effort client IP for per-IP throttling. Honours the proxy's
    X-Forwarded-For (Railway sits behind one) before request.client."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.get("/{token}")
async def technician_portal(token: str, request: Request) -> dict:
    # Unauthenticated + returns the technician's whole job list (customer names
    # + addresses = PII). Per-IP throttle since the caller is anonymous.
    enforce_rate_limit(
        "public_technician_portal", _client_ip(request), max_calls=60, per_seconds=60
    )
    try:
        return await run_in_threadpool(get_technician_portal, token)
    except JobLinkError as exc:
        raise HTTPException(status_code=410, detail=str(exc))
