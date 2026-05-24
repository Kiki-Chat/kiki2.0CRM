from fastapi import APIRouter, Depends

from app.api.deps import ToolOrg, resolve_tool_org
from app.schemas.tools import ConversationInitRequest
from app.services.conversation_init import conversation_init as init_service

router = APIRouter(prefix="/api/elevenlabs", tags=["elevenlabs"])


@router.post("/conversation-init")
async def conversation_init(
    payload: ConversationInitRequest,
    org: ToolOrg = Depends(resolve_tool_org),
) -> dict:
    return init_service(org.org_id, payload.caller_id)
