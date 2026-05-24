from fastapi import APIRouter, Depends
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.services.scheduling import get_scheduling, save_business_hours

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


class DayHours(BaseModel):
    open: bool = False
    start: str = "08:00"
    end: str = "17:00"
    break_start: str | None = None
    break_end: str | None = None


class BusinessHoursUpdate(BaseModel):
    business_hours: dict[str, DayHours]


@router.get("/settings")
async def get_settings(user: CurrentUser = Depends(require_org)) -> dict:
    return await run_in_threadpool(get_scheduling, user.org_id)


@router.put("/business-hours")
async def update_business_hours(
    payload: BusinessHoursUpdate, user: CurrentUser = Depends(require_org)
) -> dict:
    hours = {k: v.model_dump() for k, v in payload.business_hours.items()}
    sched = await run_in_threadpool(save_business_hours, user.org_id, hours)
    return {"business_hours": sched["business_hours"]}
