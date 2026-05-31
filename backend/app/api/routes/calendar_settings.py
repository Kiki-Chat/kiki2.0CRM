from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.services import calendar_sync
from app.services.oauth_tokens import OAuthTokenError, calendar_provider
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


# ─── Google Calendar read-sync (Phase 2: on-demand) ──────────────────────────
@router.post("/sync")
async def sync_calendar(user: CurrentUser = Depends(require_org)) -> dict:
    """On-demand calendar → CRM read sync for the calling org.

    Resolves the provider serving the CALENDAR purpose (per-purpose linkage) and
    pulls its events into ``appointments`` as read-only blocked time
    (``source='google_import'``). NEVER writes to the external calendar. Today
    only the Google reader is implemented.
    """
    cal_provider = await run_in_threadpool(calendar_provider, user.org_id)
    if cal_provider is None:
        raise HTTPException(status_code=409, detail="Kein Kalender verbunden.")
    if cal_provider != "google":
        raise HTTPException(
            status_code=501,
            detail=f"Kalender-Sync für '{cal_provider}' ist noch nicht verfügbar (nur Google).",
        )
    try:
        return await run_in_threadpool(calendar_sync.pull_google_events, user.org_id)
    except OAuthTokenError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Google-Kalender ist nicht verbunden — bitte erneut verbinden. ({exc})",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Kalender-Sync fehlgeschlagen: {exc}")


@router.get("/sync-status")
async def sync_status(user: CurrentUser = Depends(require_org)) -> dict:
    """Last-sync time + count of mirrored Google events for the org (so the UI
    can show that a *connection* is actually *syncing* — connection ≠ sync)."""
    def _do() -> dict:
        rows = (
            get_service_client()
            .table("appointments")
            .select("last_synced_at")
            .eq("org_id", user.org_id)
            .eq("source", calendar_sync.SOURCE_GOOGLE)
            .neq("status", "cancelled")
            .order("last_synced_at", desc=True)
            .execute()
            .data
            or []
        )
        return {
            "last_synced_at": rows[0]["last_synced_at"] if rows else None,
            "event_count": len(rows),
        }

    return await run_in_threadpool(_do)
