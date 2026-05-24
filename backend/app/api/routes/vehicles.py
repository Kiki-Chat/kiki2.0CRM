from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.schemas.admin import VehicleUpsert

router = APIRouter(prefix="/api/vehicles", tags=["vehicles"])

_COLS = (
    "id, name, model, license_plate, capacity_hours, assigned_employee_id, "
    "color, notes, is_active, created_at"
)


def _list(org_id: str) -> list[dict]:
    client = get_service_client()
    return (
        client.table("vehicles")
        .select(_COLS)
        .eq("org_id", org_id)
        .eq("is_active", True)
        .order("name")
        .execute()
        .data
        or []
    )


@router.get("")
async def list_vehicles(user: CurrentUser = Depends(require_org)) -> list[dict]:
    return await run_in_threadpool(_list, user.org_id)


def _create(org_id: str, payload: VehicleUpsert) -> dict:
    client = get_service_client()
    row = {
        "org_id": org_id,
        "name": payload.name or "Fahrzeug",
        "model": payload.model,
        "license_plate": payload.license_plate,
        "capacity_hours": payload.capacity_hours or 8,
        "assigned_employee_id": payload.assigned_employee_id,
        "color": payload.color,
        "notes": payload.notes,
        "is_active": payload.is_active if payload.is_active is not None else True,
    }
    return client.table("vehicles").insert(row).execute().data[0]


@router.post("")
async def create_vehicle(
    payload: VehicleUpsert, user: CurrentUser = Depends(require_org)
) -> dict:
    return await run_in_threadpool(_create, user.org_id, payload)


def _update(org_id: str, vehicle_id: str, payload: VehicleUpsert) -> dict | None:
    client = get_service_client()
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        rows = (
            client.table("vehicles").select(_COLS).eq("org_id", org_id)
            .eq("id", vehicle_id).limit(1).execute().data
        )
        return rows[0] if rows else None
    res = (
        client.table("vehicles").update(fields).eq("org_id", org_id)
        .eq("id", vehicle_id).execute()
    )
    return res.data[0] if res.data else None


@router.patch("/{vehicle_id}")
async def update_vehicle(
    vehicle_id: str, payload: VehicleUpsert, user: CurrentUser = Depends(require_org)
) -> dict:
    v = await run_in_threadpool(_update, user.org_id, vehicle_id, payload)
    if not v:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return v


def _delete(org_id: str, vehicle_id: str) -> bool:
    client = get_service_client()
    res = (
        client.table("vehicles").update({"is_active": False}).eq("org_id", org_id)
        .eq("id", vehicle_id).execute()
    )
    return bool(res.data)


@router.delete("/{vehicle_id}")
async def delete_vehicle(
    vehicle_id: str, user: CurrentUser = Depends(require_org)
) -> dict:
    ok = await run_in_threadpool(_delete, user.org_id, vehicle_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return {"success": True}
