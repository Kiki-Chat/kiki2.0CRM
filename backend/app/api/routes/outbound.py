"""Outbound calling endpoints (P1).

Two entrypoints:

  * ``POST /api/outbound/run-due-reminders`` — the daily sweep, fired by an
    external cron / N8N. Secret-protected (X-HeyKiki-Secret), same gate as the
    post-call webhook hop. Idempotent.
  * ``POST /api/outbound/appointments/{id}/send-reminder`` — manual single
    reminder (ad-hoc / UAT). Org-scoped via the logged-in user. Accepts an
    optional ``to_number`` override so UAT dials a designated test number
    instead of a real customer's stored phone.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org, verify_post_call_secret
from app.services import outbound_reminders
from app.services.outbound_call import OutboundCallError

router = APIRouter(prefix="/api/outbound", tags=["outbound"])


@router.post("/run-due-reminders")
async def run_due_reminders(
    dry_run: bool = False,
    only_org_id: str | None = None,
    _: None = Depends(verify_post_call_secret),
) -> dict:
    """Place reminder calls for every appointment due across all
    outbound-enabled orgs that are currently in-window. Idempotent — already
    reminded appointments are excluded by the query."""
    return await run_in_threadpool(
        outbound_reminders.run_due_reminders,
        dry_run=dry_run,
        only_org_id=only_org_id,
    )


class SendReminderBody(BaseModel):
    to_number: str | None = None  # UAT override — dial a designated test number
    dry_run: bool = False


@router.post("/appointments/{appointment_id}/send-reminder")
async def send_reminder(
    appointment_id: str,
    body: SendReminderBody,
    user: CurrentUser = Depends(require_org),
) -> dict:
    """Manual single-appointment reminder. Bypasses the time-window gate; pass
    ``to_number`` to dial a designated test number instead of the customer's
    stored phone (UAT safety)."""
    try:
        return await run_in_threadpool(
            outbound_reminders.send_reminder_for_appointment,
            org_id=user.org_id,
            appointment_id=appointment_id,
            to_number_override=body.to_number,
            dry_run=body.dry_run,
        )
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except OutboundCallError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
