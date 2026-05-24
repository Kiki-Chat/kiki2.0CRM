from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.deps import ToolOrg, resolve_tool_org
from app.schemas.tools import TransferCallRequest
from app.services.transfer import transfer_call as transfer_service

router = APIRouter(prefix="/api/elevenlabs/tools", tags=["elevenlabs-tools"])


@router.post("/transfer-call")
async def transfer_call(
    payload: TransferCallRequest,
    org: ToolOrg = Depends(resolve_tool_org),
) -> dict:
    return await run_in_threadpool(transfer_service, org.org_id, payload)
