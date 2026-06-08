from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.deps import ToolOrg, resolve_tool_org
from app.schemas.tools import ConversationInitRequest
from app.services.conversation_init import conversation_init as init_service

router = APIRouter(prefix="/api/elevenlabs", tags=["elevenlabs"])


@router.post("/conversation-init")
async def conversation_init(
    payload: ConversationInitRequest,
    org: ToolOrg = Depends(resolve_tool_org),
) -> dict:
    # init_service is synchronous (two Supabase reads). Run it off the event loop
    # so a burst of inbound calls connecting at once can't serialize on one worker.
    return await run_in_threadpool(init_service, org.org_id, payload.caller_id)
