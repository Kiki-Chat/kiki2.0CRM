"""Public (no-login) technician job-report endpoints.

The unguessable token IS the credential (same model as e-sign links): every
handler resolves the token first and serves only that one job's data, always
pinned to the link's org. Invalid/expired links → 404/410 with a German
message the form shows verbatim. No org data beyond the single job leaks.
"""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.services.ratelimit import enforce_rate_limit
from app.services.technician_jobs import (
    JobLinkError,
    add_photo,
    get_job_for_token,
    start_job,
    submit_job,
)

router = APIRouter(prefix="/api/public/jobs", tags=["public-jobs"])


def _job_error(exc: JobLinkError) -> HTTPException:
    return HTTPException(status_code=410, detail=str(exc))


def _client_ip(request: Request) -> str:
    """Best-effort client IP for per-IP throttling + submit audit. Honours the
    proxy's X-Forwarded-For (Railway sits behind one) before request.client."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# Per-IP throttles — these are unauthenticated, return customer PII (GET) and
# accept uploads (photos/submit). Keyed by IP, not org, since the caller is
# anonymous. Conservative: enough for a technician filling one form, far below
# what a scraper/abuser needs.
def _throttle(name: str, request: Request, *, max_calls: int, per_seconds: float) -> None:
    enforce_rate_limit(name, _client_ip(request), max_calls=max_calls, per_seconds=per_seconds)


@router.get("/{token}")
async def get_job(token: str, request: Request) -> dict:
    _throttle("public_job_get", request, max_calls=60, per_seconds=60)
    try:
        return await run_in_threadpool(get_job_for_token, token)
    except JobLinkError as exc:
        raise _job_error(exc)


@router.post("/{token}/start")
async def post_start(token: str, request: Request) -> dict:
    _throttle("public_job_start", request, max_calls=30, per_seconds=60)
    try:
        return await run_in_threadpool(start_job, token)
    except JobLinkError as exc:
        raise _job_error(exc)


@router.post("/{token}/photos")
async def post_photo(token: str, request: Request, file: UploadFile = File(...)) -> dict:
    _throttle("public_job_photo", request, max_calls=40, per_seconds=60)
    content = await file.read()
    try:
        return await run_in_threadpool(
            lambda: add_photo(
                token,
                filename=file.filename or "foto.jpg",
                content=content,
                mime_type=file.content_type or "",
            )
        )
    except JobLinkError as exc:
        raise _job_error(exc)


class JobReport(BaseModel):
    experience_good: bool | None = None
    extra_demands: str | None = None
    site_visit_notes: str | None = None
    job_started: bool = True
    job_finished: bool = False
    needs: list[str] = []
    description: str = ""


@router.post("/{token}/submit")
async def post_submit(token: str, request: Request, payload: JobReport) -> dict:
    _throttle("public_job_submit", request, max_calls=10, per_seconds=60)
    ip = _client_ip(request)
    ua = request.headers.get("user-agent")
    try:
        return await run_in_threadpool(
            lambda: submit_job(
                token,
                payload.model_dump(),
                submitted_ip=ip,
                submitted_user_agent=ua,
            )
        )
    except JobLinkError as exc:
        raise _job_error(exc)
