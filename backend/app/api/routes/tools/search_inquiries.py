from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.deps import ToolOrg, resolve_tool_org
from app.schemas.tools import SearchCustomerInquiriesRequest
from app.services.inquiries import search_customer_inquiries as search_service

router = APIRouter(prefix="/api/elevenlabs/tools", tags=["elevenlabs-tools"])


@router.post("/search-inquiries")
async def search_inquiries(
    payload: SearchCustomerInquiriesRequest,
    org: ToolOrg = Depends(resolve_tool_org),
) -> dict:
    return await run_in_threadpool(search_service, org.org_id, payload)
