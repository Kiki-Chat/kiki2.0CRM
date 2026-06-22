from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.deps import ToolOrg, resolve_tool_org
from app.schemas.tools import SendCostEstimateRequest
from app.services.cost_estimates import send_cost_estimate

router = APIRouter(prefix="/api/elevenlabs/tools", tags=["elevenlabs-tools"])


@router.post("/send-cost-estimate")
async def send_cost_estimate_route(
    payload: SendCostEstimateRequest,
    org: ToolOrg = Depends(resolve_tool_org),
) -> dict:
    """hk_sendKVA — email an existing Kostenvoranschlag to the customer (L3 only)."""
    return await run_in_threadpool(send_cost_estimate, org.org_id, payload)
