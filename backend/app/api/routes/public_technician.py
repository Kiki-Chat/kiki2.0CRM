"""Public (no-login) technician portal — the standing link a technician opens
to see ALL their jobs (past + current), not just one dispatch.

The unguessable ``technician_portal_token`` IS the credential (same model as the
per-job link). One token → one technician → only that technician's own jobs,
always pinned to their org. Invalid/disabled → 410 with a German message.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.services.technician_jobs import JobLinkError, get_technician_portal

router = APIRouter(prefix="/api/public/technician", tags=["public-technician"])


@router.get("/{token}")
async def technician_portal(token: str) -> dict:
    try:
        return await run_in_threadpool(get_technician_portal, token)
    except JobLinkError as exc:
        raise HTTPException(status_code=410, detail=str(exc))
