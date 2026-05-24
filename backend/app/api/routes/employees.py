from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client

router = APIRouter(prefix="/api/employees", tags=["employees"])


def _list(org_id: str) -> list[dict]:
    client = get_service_client()
    return (
        client.table("employees")
        .select("id, display_name, role_in_company, is_active")
        .eq("org_id", org_id)
        .eq("is_active", True)
        .order("display_name")
        .execute()
        .data
        or []
    )


@router.get("")
async def list_employees(user: CurrentUser = Depends(require_org)) -> list[dict]:
    return await run_in_threadpool(_list, user.org_id)
