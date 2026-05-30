"""Outbound calling endpoints (Path A — occasion-driven).

Two entrypoints:

  * ``POST /api/outbound/run-due-reminders`` — the scheduled sweep, fired by an
    external cron / N8N. Secret-protected (X-HeyKiki-Secret). Dispatches every
    DUE + ENABLED occasion (appointment_reminder, kva_followup, …) across all
    outbound-enabled orgs in-window. Idempotent via the ``outbound_calls``
    ledger. Optional ``occasions=a,b`` scopes the sweep.
  * ``POST /api/outbound/send`` — manual single-record trigger (ad-hoc / UAT).
    Org-scoped via the logged-in user. Pass ``occasion`` + ``record_id``; an
    optional ``to_number`` override dials a designated TEST number instead of a
    real customer's stored phone (and makes the dispatch repeatable).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org, verify_post_call_secret
from app.services import outbound_dispatch
from app.services.outbound_call import OutboundCallError

router = APIRouter(prefix="/api/outbound", tags=["outbound"])


@router.post("/run-due-reminders")
async def run_due_reminders(
    dry_run: bool = False,
    only_org_id: str | None = None,
    occasions: str | None = None,
    _: None = Depends(verify_post_call_secret),
) -> dict:
    """Dispatch every due + enabled outbound occasion across all outbound-enabled
    orgs currently in-window. Idempotent — already-dispatched records are
    excluded by the ledger. ``occasions`` (comma-separated) scopes the sweep."""
    occ = [o.strip() for o in occasions.split(",") if o.strip()] if occasions else None
    return await run_in_threadpool(
        outbound_dispatch.run_due_outbound,
        dry_run=dry_run,
        only_org_id=only_org_id,
        occasions=occ,
    )


class SendOutboundBody(BaseModel):
    occasion: str               # 'appointment_reminder' | 'kva_followup'
    record_id: str              # appointment id / cost_estimate id
    to_number: str | None = None  # UAT override — dial a designated test number
    dry_run: bool = False


@router.post("/send")
async def send_outbound(
    body: SendOutboundBody,
    user: CurrentUser = Depends(require_org),
) -> dict:
    """Manual single-record outbound dispatch. Bypasses the time-window gate;
    pass ``to_number`` to dial a designated test number instead of the
    customer's stored phone (UAT safety)."""
    try:
        return await run_in_threadpool(
            outbound_dispatch.send_single_outbound,
            org_id=user.org_id,
            occasion=body.occasion,
            record_id=body.record_id,
            to_number_override=body.to_number,
            dry_run=body.dry_run,
        )
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except OutboundCallError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
