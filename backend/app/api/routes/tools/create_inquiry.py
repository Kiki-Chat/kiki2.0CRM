from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.deps import ToolOrg, resolve_tool_org
from app.schemas.tools import CreateInquiryRequest
from app.services.inquiries import create_inquiry as create_inquiry_service

router = APIRouter(prefix="/api/elevenlabs/tools", tags=["elevenlabs-tools"])


@router.post("/create-inquiry")
async def create_inquiry(
    payload: CreateInquiryRequest,
    org: ToolOrg = Depends(resolve_tool_org),
) -> dict:
    return await run_in_threadpool(create_inquiry_service, org.org_id, payload)
