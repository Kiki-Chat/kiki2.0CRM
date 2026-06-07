from fastapi import APIRouter, BackgroundTasks, Depends, Request
from starlette.concurrency import run_in_threadpool

from app.api.deps import verify_post_call_secret
from app.core.config import settings
from app.services.post_call import process_post_call

router = APIRouter(prefix="/api/elevenlabs", tags=["elevenlabs"])


@router.post("/post-call", dependencies=[Depends(verify_post_call_secret)])
async def post_call(request: Request, background_tasks: BackgroundTasks) -> list[dict]:
    # Body shape varies (ElevenLabs envelope, flat, or an N8N item array), so we
    # read the raw JSON and let the service normalise it.
    payload = await request.json()
    results = await run_in_threadpool(process_post_call, payload)

    # Stripe usage reporting (Phase 1). Fired from the ROUTE — NOT the shared
    # process_post_call / _process_one — so historical backfill via
    # history_import.import_agent_history (which calls _process_one directly) is
    # structurally excluded and never billed. Gated by
    # STRIPE_USAGE_REPORTING_ENABLED; idempotent via billing_usage_reports.call_id.
    # Only newly-finalised calls report ('processed'); dedup/retries are 'skipped'.
    if settings.stripe_usage_reporting_enabled:
        from app.services.billing_usage import report_call_usage, select_billable

        for call_id, org_id in select_billable(results):
            background_tasks.add_task(report_call_usage, call_id=call_id, org_id=org_id)
    return results
