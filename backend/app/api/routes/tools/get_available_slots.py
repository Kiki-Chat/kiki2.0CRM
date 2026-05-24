from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.deps import ToolOrg, resolve_tool_org
from app.schemas.tools import GetAvailableAppointmentsRequest
from app.services.appointments import get_available_slots as get_slots_service

router = APIRouter(prefix="/api/elevenlabs/tools", tags=["elevenlabs-tools"])


@router.post("/get-available-slots")
async def get_available_slots(
    payload: GetAvailableAppointmentsRequest,
    org: ToolOrg = Depends(resolve_tool_org),
) -> dict:
    return await run_in_threadpool(get_slots_service, org.org_id, payload)
