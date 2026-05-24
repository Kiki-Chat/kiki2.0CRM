from datetime import date as date_cls, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client

router = APIRouter(prefix="/api/planning-board", tags=["planning-board"])


def _board(org_id: str, date_str: str) -> dict:
    try:
        day = date_cls.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültiges Datum (YYYY-MM-DD)")
    start = f"{day.isoformat()}T00:00:00+00:00"
    end = f"{(day + timedelta(days=1)).isoformat()}T00:00:00+00:00"

    client = get_service_client()
    appts = (
        client.table("appointments")
        .select(
            "id, title, scheduled_at, duration_minutes, status, location, "
            "customer_id, assigned_employee_id, vehicle_id, tool_id"
        )
        .eq("org_id", org_id)
        .gte("scheduled_at", start)
        .lt("scheduled_at", end)
        .neq("status", "cancelled")
        .order("scheduled_at")
        .execute()
        .data
        or []
    )

    customer_ids = {a["customer_id"] for a in appts if a.get("customer_id")}
    employee_ids = {a["assigned_employee_id"] for a in appts if a.get("assigned_employee_id")}
    customers: dict[str, str] = {}
    if customer_ids:
        for c in (
            client.table("customers").select("id, full_name").eq("org_id", org_id)
            .in_("id", list(customer_ids)).execute().data or []
        ):
            customers[c["id"]] = c.get("full_name")
    employees: dict[str, str] = {}
    if employee_ids:
        for e in (
            client.table("employees").select("id, display_name").eq("org_id", org_id)
            .in_("id", list(employee_ids)).execute().data or []
        ):
            employees[e["id"]] = e.get("display_name")
    for a in appts:
        a["customer_name"] = customers.get(a.get("customer_id"))
        a["employee_name"] = employees.get(a.get("assigned_employee_id"))

    vehicles = (
        client.table("vehicles")
        .select("id, name, model, license_plate, capacity_hours, assigned_employee_id, color")
        .eq("org_id", org_id).eq("is_active", True).order("name").execute().data or []
    )
    tools = (
        client.table("tools")
        .select("id, name, category, assigned_employee_id, storage_location")
        .eq("org_id", org_id).eq("is_active", True).order("name").execute().data or []
    )
    return {"date": date_str, "appointments": appts, "vehicles": vehicles, "tools": tools}


@router.get("")
async def planning_board(
    date: str = Query(...), user: CurrentUser = Depends(require_org)
) -> dict:
    return await run_in_threadpool(_board, user.org_id, date)
