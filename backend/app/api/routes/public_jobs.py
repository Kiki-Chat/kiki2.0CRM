"""Public (no-login) technician job-report endpoints.

The unguessable token IS the credential (same model as e-sign links): every
handler resolves the token first and serves only that one job's data, always
pinned to the link's org. Invalid/expired links → 404/410 with a German
message the form shows verbatim. No org data beyond the single job leaks.
"""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

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


@router.get("/{token}")
async def get_job(token: str) -> dict:
    try:
        return await run_in_threadpool(get_job_for_token, token)
    except JobLinkError as exc:
        raise _job_error(exc)


@router.post("/{token}/start")
async def post_start(token: str) -> dict:
    try:
        return await run_in_threadpool(start_job, token)
    except JobLinkError as exc:
        raise _job_error(exc)


@router.post("/{token}/photos")
async def post_photo(token: str, file: UploadFile = File(...)) -> dict:
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
async def post_submit(token: str, payload: JobReport) -> dict:
    try:
        return await run_in_threadpool(submit_job, token, payload.model_dump())
    except JobLinkError as exc:
        raise _job_error(exc)
