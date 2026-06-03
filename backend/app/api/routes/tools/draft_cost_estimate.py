from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.deps import ToolOrg, resolve_tool_org
from app.schemas.tools import DraftCostEstimateRequest
from app.services.cost_estimates import draft_cost_estimate

router = APIRouter(prefix="/api/elevenlabs/tools", tags=["elevenlabs-tools"])


@router.post("/draft-cost-estimate")
async def draft_cost_estimate_route(
    payload: DraftCostEstimateRequest,
    org: ToolOrg = Depends(resolve_tool_org),
) -> dict:
    return await run_in_threadpool(draft_cost_estimate, org.org_id, payload)
