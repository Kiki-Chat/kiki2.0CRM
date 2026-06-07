"""Stripe webhook endpoint. Public — the signature IS the authentication.

Reads the RAW request body (signature verification needs the exact bytes, so we
must NOT parse JSON first), verifies + dedups synchronously, then processes in a
background task. Returns 200 on everything except a signature/payload failure
(400), so Stripe never retries due to our own processing errors.
"""

from __future__ import annotations

import stripe
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.services.stripe_webhook import process_event, verify_and_record

router = APIRouter(prefix="/api/billing", tags=["billing-webhook"])


@router.post("/stripe-webhook")
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
    raw = await request.body()  # RAW bytes — required for signature verification
    sig = request.headers.get("stripe-signature")
    source_ip = request.client.host if request.client else None
    try:
        rec = await run_in_threadpool(verify_and_record, raw, sig, source_ip)
    except stripe.error.SignatureVerificationError as exc:  # type: ignore[attr-defined]
        raise HTTPException(status_code=400, detail="invalid signature") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid payload") from exc
    if rec.get("new"):
        background_tasks.add_task(process_event, rec["stripe_event_id"])
    return {"received": True}
