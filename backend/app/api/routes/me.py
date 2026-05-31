from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, get_current_user
from app.db.supabase_client import get_service_client

router = APIRouter(prefix="/api", tags=["me"])


def _org_name(org_id: str) -> str | None:
    rows = (
        get_service_client()
        .table("organizations")
        .select("name")
        .eq("id", org_id)
        .limit(1)
        .execute()
        .data
    )
    return rows[0].get("name") if rows else None


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    # org_name lets the (white-label) UI show WHICH company's CRM the user is in
    # — surfaced in the sidebar header + personal settings. Available to every
    # authenticated user (incl. employees), unlike the admin-only /api/settings.
    org_name = await run_in_threadpool(_org_name, user.org_id) if user.org_id else None
    return {
        "id": user.id,
        "email": user.email,
        "org_id": user.org_id,
        "role": user.role,
        "full_name": user.full_name,
        "org_name": org_name,
    }
