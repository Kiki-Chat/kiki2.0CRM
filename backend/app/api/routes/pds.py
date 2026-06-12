"""PDS integration endpoints — the CRM-native replacement for the n8n webhooks
("PDS - User Greeting Flow" / "PDS - Log Call", see services/pds.py).

Response shapes mirror the n8n Respond-to-Webhook nodes EXACTLY, so the
ElevenLabs agent tools that today point at n8n URLs can be re-pointed here with
zero behavioural change.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org, require_org_admin
from app.services import pds

router = APIRouter(prefix="/api/pds", tags=["pds"])


@router.get("/logs")
async def pds_logs(limit: int = 50, user: CurrentUser = Depends(require_org_admin)) -> list[dict]:
    """Verification feed: recent PDS interactions (request + raw response) for this
    org. Admin-only — the payloads can carry caller PII."""
    return await run_in_threadpool(pds.recent_logs, user.org_id, limit)


class GreetingIn(BaseModel):
    phoneNumber: str


@router.post("/greeting")
async def pds_greeting(payload: GreetingIn, user: CurrentUser = Depends(require_org)) -> dict:
    """Workflow 2a: caller lookup → personalised greeting (n8n contract)."""
    try:
        return await run_in_threadpool(pds.greeting_for_phone, user.org_id, payload.phoneNumber)
    except pds.PdsError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


class CreateContactIn(BaseModel):
    fullName: str
    phoneNumber: str
    city: str | None = None
    postalCode: str | None = None
    street: str | None = None


@router.post("/create-contact")
async def pds_create_contact(payload: CreateContactIn, user: CurrentUser = Depends(require_org)) -> dict:
    """Workflow 2b: create the PDS person + phone (+ address) (n8n contract)."""
    def _run():
        return pds.create_contact(
            user.org_id,
            full_name=payload.fullName,
            phone=payload.phoneNumber,
            city=payload.city,
            postal_code=payload.postalCode,
            street=payload.street,
        )

    try:
        return await run_in_threadpool(_run)
    except pds.PdsError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


class LogCallIn(BaseModel):
    call_id: str


@router.post("/log-call")
async def pds_log_call(payload: LogCallIn, user: CurrentUser = Depends(require_org)) -> dict:
    """Workflow 1 for ONE of our calls (manual push from the call log / demo)."""
    def _run():
        from app.db.supabase_client import get_service_client

        client = get_service_client()
        rows = (
            client.table("calls")
            .select("id, caller_number, duration_seconds, summary_title, summary, data_collection, started_at, created_at, pds_synced_at")
            .eq("org_id", user.org_id).eq("id", payload.call_id).limit(1).execute().data
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Anruf nicht gefunden.")
        return pds.log_call(user.org_id, rows[0])

    try:
        return await run_in_threadpool(_run)
    except pds.PdsError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
