from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.schemas.admin import VehicleUpsert

router = APIRouter(prefix="/api/vehicles", tags=["vehicles"])

_COLS = (
    "id, name, model, license_plate, capacity_hours, assigned_employee_id, "
    "color, notes, is_active, created_at, vehicle_type, brand, tuev_until, "
    "insurance_until, next_maintenance, max_weight_kg, cargo_space_m3, status"
)


def _list(org_id: str) -> list[dict]:
    client = get_service_client()
    rows = (
        client.table("vehicles")
        .select(_COLS)
        .eq("org_id", org_id)
        .eq("is_active", True)
        .order("name")
        .execute()
        .data
        or []
    )
    ids = [r["id"] for r in rows]
    now_iso = datetime.now(timezone.utc).isoformat()
    today = now_iso[:10]
    last_seen: dict[str, str] = {}
    next_appt: dict[str, str] = {}
    in_use_today: set[str] = set()
    if ids:
        for a in (
            client.table("appointments")
            .select("vehicle_id, scheduled_at, status")
            .eq("org_id", org_id)
            .in_("vehicle_id", ids)
            .execute()
            .data
            or []
        ):
            vid, when, st = a.get("vehicle_id"), a.get("scheduled_at"), a.get("status")
            if not vid or not when or st == "cancelled":
                continue
            if when > last_seen.get(vid, ""):
                last_seen[vid] = when
            if when >= now_iso and (vid not in next_appt or when < next_appt[vid]):
                next_appt[vid] = when
            if when[:10] == today:
                in_use_today.add(vid)
    for r in rows:
        r["last_seen"] = last_seen.get(r["id"])
        r["next_appointment"] = next_appt.get(r["id"])
        r["in_use_today"] = r["id"] in in_use_today
        # Derived service alerts (date vs. today). An expired TÜV / insurance or an
        # overdue maintenance flags the vehicle so the UI can warn instead of
        # showing it plainly "available".
        r["tuev_expired"] = bool(r.get("tuev_until")) and str(r["tuev_until"])[:10] < today
        r["insurance_expired"] = bool(r.get("insurance_until")) and str(r["insurance_until"])[:10] < today
        r["maintenance_overdue"] = bool(r.get("next_maintenance")) and str(r["next_maintenance"])[:10] < today
        r["service_alert"] = bool(r["tuev_expired"] or r["insurance_expired"] or r["maintenance_overdue"])
    return rows


@router.get("")
async def list_vehicles(user: CurrentUser = Depends(require_org)) -> list[dict]:
    return await run_in_threadpool(_list, user.org_id)


def _create(org_id: str, payload: VehicleUpsert) -> dict:
    client = get_service_client()
    row = payload.model_dump(exclude_unset=True)
    row["org_id"] = org_id
    row.setdefault("name", "Fahrzeug")
    row.setdefault("capacity_hours", 8)
    row.setdefault("is_active", True)
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
