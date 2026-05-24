from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.deps import ToolOrg, resolve_tool_org
from app.schemas.tools import UpdateCustomerDataRequest
from app.services.customers import update_customer_data as update_service

router = APIRouter(prefix="/api/elevenlabs/tools", tags=["elevenlabs-tools"])


@router.post("/update-customer")
async def update_customer(
    payload: UpdateCustomerDataRequest,
    org: ToolOrg = Depends(resolve_tool_org),
) -> dict:
    return await run_in_threadpool(update_service, org.org_id, payload)
