from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.deps import ToolOrg, resolve_tool_org
from app.schemas.tools import IdentifyCustomerRequest
from app.services.identify import identify_customer as identify_customer_service

router = APIRouter(prefix="/api/elevenlabs/tools", tags=["elevenlabs-tools"])


@router.post("/identify-customer")
async def identify_customer(
    payload: IdentifyCustomerRequest,
    org: ToolOrg = Depends(resolve_tool_org),
) -> dict:
    return await run_in_threadpool(identify_customer_service, org.org_id, payload)
