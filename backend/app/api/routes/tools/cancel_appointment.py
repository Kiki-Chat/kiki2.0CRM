from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.deps import ToolOrg, resolve_tool_org
from app.schemas.tools import CancelAppointmentRequest
from app.services.appointments import cancel_appointment as cancel_service

router = APIRouter(prefix="/api/elevenlabs/tools", tags=["elevenlabs-tools"])


@router.post("/cancel-appointment")
async def cancel_appointment(
    payload: CancelAppointmentRequest,
    org: ToolOrg = Depends(resolve_tool_org),
) -> dict:
    return await run_in_threadpool(cancel_service, org.org_id, payload)
