"""On-demand Google Sheets sync endpoints (master-secret). DB is the source of truth.

IMPORT seeds the canonical DB from the legacy sheet; MIRROR rewrites the read-only
sheet from the DB for non-tech staff. Mounted only when SHEETS_SYNC_ENABLED. Intended
to be called from a small cron/script (e.g. mirror nightly) or manually after a backfill.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.deps import verify_master_secret

router = APIRouter(
    prefix="/api/sheets", tags=["sheets-sync"], dependencies=[Depends(verify_master_secret)]
)


@router.post("/import/twilio-pool")
async def import_twilio_pool_route() -> dict:
    from app.services.sheets_sync import import_twilio_pool

    return await run_in_threadpool(import_twilio_pool)


@router.post("/mirror/twilio-pool")
async def mirror_twilio_pool_route() -> dict:
    from app.services.sheets_sync import mirror_twilio_pool

    return await run_in_threadpool(mirror_twilio_pool)


@router.post("/mirror/final-clients")
async def mirror_final_clients_route() -> dict:
    from app.services.sheets_sync import mirror_final_clients

    return await run_in_threadpool(mirror_final_clients)
