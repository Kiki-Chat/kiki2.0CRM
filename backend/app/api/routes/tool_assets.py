from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.schemas.admin import ToolUpsert

router = APIRouter(prefix="/api/tools", tags=["tools"])

_COLS = (
    "id, name, category, serial_number, assigned_employee_id, storage_location, "
    "notes, is_active, created_at, condition, next_maintenance, purchase_date, purchase_price"
)


def _list(org_id: str) -> list[dict]:
    client = get_service_client()
    rows = (
        client.table("tools")
        .select(_COLS)
        .eq("org_id", org_id)
        .eq("is_active", True)
        .order("name")
        .execute()
        .data
        or []
    )
    ids = [r["id"] for r in rows]
    last_seen: dict[str, str] = {}
    if ids:
        for a in (
            client.table("appointments")
            .select("tool_id, scheduled_at")
            .eq("org_id", org_id)
            .in_("tool_id", ids)
            .execute()
            .data
            or []
        ):
            tid, when = a.get("tool_id"), a.get("scheduled_at")
            if tid and when and when > last_seen.get(tid, ""):
                last_seen[tid] = when
    for r in rows:
        r["last_seen"] = last_seen.get(r["id"])
    return rows


@router.get("")
async def list_tools(user: CurrentUser = Depends(require_org)) -> list[dict]:
    return await run_in_threadpool(_list, user.org_id)


def _create(org_id: str, payload: ToolUpsert) -> dict:
    client = get_service_client()
    row = payload.model_dump(exclude_unset=True)
    row["org_id"] = org_id
    row.setdefault("name", "Werkzeug")
    row.setdefault("is_active", True)
    return client.table("tools").insert(row).execute().data[0]


@router.post("")
async def create_tool(payload: ToolUpsert, user: CurrentUser = Depends(require_org)) -> dict:
    return await run_in_threadpool(_create, user.org_id, payload)


def _update(org_id: str, tool_id: str, payload: ToolUpsert) -> dict | None:
    client = get_service_client()
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        rows = (
            client.table("tools").select(_COLS).eq("org_id", org_id)
            .eq("id", tool_id).limit(1).execute().data
        )
        return rows[0] if rows else None
    res = (
        client.table("tools").update(fields).eq("org_id", org_id)
        .eq("id", tool_id).execute()
    )
    return res.data[0] if res.data else None


@router.patch("/{tool_id}")
async def update_tool(
    tool_id: str, payload: ToolUpsert, user: CurrentUser = Depends(require_org)
) -> dict:
    t = await run_in_threadpool(_update, user.org_id, tool_id, payload)
    if not t:
        raise HTTPException(status_code=404, detail="Tool not found")
    return t


def _delete(org_id: str, tool_id: str) -> bool:
    client = get_service_client()
    res = (
        client.table("tools").update({"is_active": False}).eq("org_id", org_id)
        .eq("id", tool_id).execute()
    )
    return bool(res.data)


@router.delete("/{tool_id}")
async def delete_tool(tool_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    ok = await run_in_threadpool(_delete, user.org_id, tool_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Tool not found")
    return {"success": True}
