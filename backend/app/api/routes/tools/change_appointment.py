from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.deps import ToolOrg, resolve_tool_org
from app.schemas.tools import ChangeAppointmentRequest
from app.services.appointments import change_appointment as change_service

router = APIRouter(prefix="/api/elevenlabs/tools", tags=["elevenlabs-tools"])


@router.post("/change-appointment")
async def change_appointment(
    payload: ChangeAppointmentRequest,
    org: ToolOrg = Depends(resolve_tool_org),
) -> dict:
    return await run_in_threadpool(change_service, org.org_id, payload)
