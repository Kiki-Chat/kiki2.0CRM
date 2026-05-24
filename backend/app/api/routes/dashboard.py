from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _count(client, table: str, org_id: str, **filters) -> int:
    q = client.table(table).select("id", count="exact").eq("org_id", org_id)
    for key, value in filters.items():
        q = q.eq(key, value)
    res = q.execute()
    return res.count or 0


@router.get("/overview")
async def overview(user: CurrentUser = Depends(require_org)) -> dict:
    client = get_service_client()
    org_id = user.org_id

    open_inquiries = _count(client, "inquiries", org_id, status="open")
    total_customers = _count(client, "customers", org_id)

    appts_res = (
        client.table("appointments")
        .select("id, title, scheduled_at, status, customer_id")
        .eq("org_id", org_id)
        .gte("scheduled_at", datetime.now(timezone.utc).isoformat())
        .order("scheduled_at")
        .limit(5)
        .execute()
    )
    upcoming = appts_res.data or []

    tasks_res = (
        client.table("inquiries")
        .select("id, title, type, status, created_at, customer_id")
        .eq("org_id", org_id)
        .eq("status", "open")
        .order("created_at", desc=True)
        .limit(5)
        .execute()
    )
    open_tasks = tasks_res.data or []

    return {
        "kpis": {
            "open_inquiries": open_inquiries,
            "total_customers": total_customers,
            "upcoming_appointments": len(upcoming),
        },
        "open_tasks": open_tasks,
        "upcoming_appointments": upcoming,
    }
