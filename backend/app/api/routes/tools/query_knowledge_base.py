from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.deps import ToolOrg, resolve_tool_org
from app.schemas.tools import QueryKnowledgeBaseRequest
from app.services.knowledge import query_knowledge_base as query_service

router = APIRouter(prefix="/api/elevenlabs/tools", tags=["elevenlabs-tools"])


@router.post("/query-knowledge-base")
async def query_knowledge_base(
    payload: QueryKnowledgeBaseRequest,
    org: ToolOrg = Depends(resolve_tool_org),
) -> dict:
    return await run_in_threadpool(query_service, org.org_id, payload)
