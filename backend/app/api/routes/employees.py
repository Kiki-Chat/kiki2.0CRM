import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.schemas.admin import AbsenceCreate, EmployeeCreate, EmployeeUpdate
from app.services import csv_import


class SetPasswordRequest(BaseModel):
    password: str

router = APIRouter(prefix="/api/employees", tags=["employees"])

_OWNER_ROLES = {"org_admin", "super_admin"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _list(org_id: str) -> list[dict]:
    client = get_service_client()
    employees = (
        client.table("employees")
        .select(
            "id, user_id, display_name, email, access_role, is_active, calendar_color, "
            "role_in_company, vacation_days_per_year, remaining_vacation_days, "
            "hourly_rate, activity_area, auto_assign"
        )
        .eq("org_id", org_id)
        .eq("deleted", False)
        .order("display_name")
        .execute()
        .data
        or []
    )

    user_ids = [e["user_id"] for e in employees if e.get("user_id")]
    users: dict[str, dict] = {}
    if user_ids:
        for u in (
            client.table("users")
            .select("id, email, role, full_name")
            .in_("id", user_ids)
            .execute()
            .data
            or []
        ):
            users[u["id"]] = u

    # Absences covering "now" → presence.
    now_iso = _now().isoformat()
    absent_ids = set()
    absence_type: dict[str, str] = {}
    emp_ids = [e["id"] for e in employees]
    if emp_ids:
        for a in (
            client.table("employee_absences")
            .select("employee_id, type, starts_at, ends_at")
            .eq("org_id", org_id)
            .in_("employee_id", emp_ids)
            .lte("starts_at", now_iso)
            .gte("ends_at", now_iso)
            .execute()
            .data
            or []
        ):
            absent_ids.add(a["employee_id"])
            absence_type[a["employee_id"]] = a["type"]

    out = []
    for e in employees:
        user = users.get(e.get("user_id")) if e.get("user_id") else None
        access_role = e.get("access_role") or (
            "admin" if user and user.get("role") in _OWNER_ROLES else "employee"
        )
        out.append(
            {
                "id": e["id"],
                "display_name": e.get("display_name"),
                "email": e.get("email") or (user.get("email") if user else None),
                "has_login": bool(e.get("user_id")),
                "access_role": access_role,
                "is_active": e.get("is_active", True),
                "is_org_owner": bool(user and user.get("role") in _OWNER_ROLES),
                "calendar_color": e.get("calendar_color"),
                "role_in_company": e.get("role_in_company"),
                "vacation_days_per_year": e.get("vacation_days_per_year") or 28,
                "remaining_vacation_days": e.get("remaining_vacation_days"),
                "hourly_rate": e.get("hourly_rate"),
                "activity_area": e.get("activity_area"),
                "auto_assign": e.get("auto_assign", False),
                "present": e["id"] not in absent_ids,
                "absence_type": absence_type.get(e["id"]),
            }
        )
    return out


@router.get("")
async def list_employees(user: CurrentUser = Depends(require_org)) -> list[dict]:
    return await run_in_threadpool(_list, user.org_id)


def _create(org_id: str, payload: EmployeeCreate) -> dict:
    client = get_service_client()
    user_id = None
    warning = None
    if payload.login_access:
        if not payload.email:
            raise HTTPException(status_code=400, detail="E-Mail ist für den Login erforderlich")
        existing = (
            client.table("users").select("id").eq("email", payload.email).limit(1).execute().data
        )
        if existing:
            user_id = existing[0]["id"]
        else:
            try:
                res = client.auth.admin.invite_user_by_email(payload.email)
                invited = getattr(res, "user", None)
                if invited is None:
                    raise ValueError("no user returned")
                user_id = invited.id
                client.table("users").insert(
                    {
                        "id": user_id,
                        "org_id": org_id,
                        "full_name": payload.display_name,
                        "email": payload.email,
                        "role": "org_admin" if payload.access_role == "admin" else "employee",
                    }
                ).execute()
            except Exception as exc:
                # Email delivery not configured (no SMTP/template) → don't lose the
                # record. Create the employee without login; admin can resend later.
                user_id = None
                warning = (
                    "Mitarbeiter angelegt, aber die Einladung konnte nicht gesendet "
                    f"werden ({exc}). Bitte den E-Mail-Versand in Supabase konfigurieren "
                    "und die Einladung anschließend erneut senden."
                )

    row = {
        "org_id": org_id,
        "user_id": user_id,
        "display_name": payload.display_name,
        "email": payload.email,
        "access_role": payload.access_role,
        "is_active": payload.is_active,
        "calendar_color": payload.calendar_color,
        "activity_area": payload.activity_area,
        "auto_assign": payload.auto_assign,
    }
    created = client.table("employees").insert(row).execute().data[0]
    if warning:
        created["warning"] = warning
    return created


@router.post("")
async def create_employee(
    payload: EmployeeCreate, user: CurrentUser = Depends(require_org)
) -> dict:
    return await run_in_threadpool(_create, user.org_id, payload)


@router.post("/import")
async def import_employees_csv(
    file: UploadFile = File(...),
    mapping: str = Form("{}"),
    user: CurrentUser = Depends(require_org),
) -> dict:
    """Bulk CSV import for employees. ``mapping`` = JSON {target_field: csv_header}.
    Dedups on email/name (skips duplicates). Does NOT send login invites — rows
    are created as records; resend invites individually afterwards."""
    content = await file.read()
    try:
        m = json.loads(mapping) if mapping else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Ungültiges Mapping (kein JSON)")
    return await run_in_threadpool(csv_import.import_employees, user.org_id, content, m)


def _update(org_id: str, employee_id: str, payload: EmployeeUpdate) -> dict | None:
    client = get_service_client()
    fields = payload.model_dump(exclude_none=True)
    if not fields:
        rows = (
            client.table("employees").select("*").eq("org_id", org_id)
            .eq("id", employee_id).limit(1).execute().data
        )
        return rows[0] if rows else None

    res = (
        client.table("employees")
        .update(fields)
        .eq("org_id", org_id)
        .eq("id", employee_id)
        .execute()
    )
    if not res.data:
        return None
    emp = res.data[0]
    # Keep linked login role in sync when access changes.
    if emp.get("user_id") and (payload.access_role is not None):
        client.table("users").update(
            {"role": "org_admin" if payload.access_role == "admin" else "employee"}
        ).eq("id", emp["user_id"]).execute()
    return emp


@router.patch("/{employee_id}")
async def update_employee(
    employee_id: str, payload: EmployeeUpdate, user: CurrentUser = Depends(require_org)
) -> dict:
    emp = await run_in_threadpool(_update, user.org_id, employee_id, payload)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return emp


def _delete(org_id: str, employee_id: str) -> str:
    client = get_service_client()
    rows = (
        client.table("employees")
        .select("id, user_id")
        .eq("org_id", org_id)
        .eq("id", employee_id)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        return "not_found"
    emp = rows[0]
    if emp.get("user_id"):
        u = client.table("users").select("role").eq("id", emp["user_id"]).limit(1).execute().data
        if u and u[0].get("role") in _OWNER_ROLES:
            return "owner"
    client.table("employees").update({"deleted": True, "is_active": False}).eq(
        "id", employee_id
    ).eq("org_id", org_id).execute()
    return "ok"


@router.delete("/{employee_id}")
async def delete_employee(
    employee_id: str, user: CurrentUser = Depends(require_org)
) -> dict:
    result = await run_in_threadpool(_delete, user.org_id, employee_id)
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Employee not found")
    if result == "owner":
        raise HTTPException(
            status_code=403, detail="Der Organisationsinhaber kann nicht gelöscht werden"
        )
    return {"success": True}


def _resend_invite(org_id: str, employee_id: str) -> str:
    client = get_service_client()
    rows = (
        client.table("employees")
        .select("email")
        .eq("org_id", org_id)
        .eq("id", employee_id)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        return "not_found"
    email = rows[0].get("email")
    if not email:
        return "no_email"
    client.auth.admin.invite_user_by_email(email)
    return "ok"


@router.post("/{employee_id}/resend-invite")
async def resend_invite(
    employee_id: str, user: CurrentUser = Depends(require_org)
) -> dict:
    result = await run_in_threadpool(_resend_invite, user.org_id, employee_id)
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Employee not found")
    if result == "no_email":
        raise HTTPException(status_code=400, detail="Keine E-Mail-Adresse hinterlegt")
    return {"success": True}


def _set_password(org_id: str, employee_id: str, password: str) -> str:
    client = get_service_client()
    rows = (
        client.table("employees")
        .select("user_id")
        .eq("org_id", org_id)
        .eq("id", employee_id)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        return "not_found"
    uid = rows[0].get("user_id")
    if not uid:
        return "no_login"
    client.auth.admin.update_user_by_id(uid, {"password": password})
    return "ok"


@router.post("/{employee_id}/set-password")
async def set_password(
    employee_id: str, payload: SetPasswordRequest, user: CurrentUser = Depends(require_org)
) -> dict:
    if len(payload.password) < 6:
        raise HTTPException(
            status_code=400, detail="Passwort muss mindestens 6 Zeichen lang sein"
        )
    result = await run_in_threadpool(
        _set_password, user.org_id, employee_id, payload.password
    )
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Employee not found")
    if result == "no_login":
        raise HTTPException(
            status_code=400, detail="Dieser Mitarbeiter hat keinen Login-Zugang"
        )
    return {"success": True}


# ─── Absences ────────────────────────────────────────────────────────────────
def _list_all_absences(org_id: str, frm: str | None, to: str | None) -> list[dict]:
    client = get_service_client()
    query = client.table("employee_absences").select("*").eq("org_id", org_id)
    if to:
        query = query.lt("starts_at", to)
    if frm:
        query = query.gte("ends_at", frm)
    absences = query.order("starts_at").execute().data or []

    emp_ids = {a["employee_id"] for a in absences}
    names: dict[str, dict] = {}
    if emp_ids:
        for e in (
            client.table("employees")
            .select("id, display_name, calendar_color")
            .in_("id", list(emp_ids))
            .execute()
            .data
            or []
        ):
            names[e["id"]] = e
    for a in absences:
        emp = names.get(a["employee_id"]) or {}
        a["employee_name"] = emp.get("display_name")
        a["calendar_color"] = emp.get("calendar_color")
    return absences


@router.get("/absences")
async def list_all_absences(
    frm: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    user: CurrentUser = Depends(require_org),
) -> list[dict]:
    return await run_in_threadpool(_list_all_absences, user.org_id, frm, to)


def _create_absence(org_id: str, employee_id: str, payload: AbsenceCreate) -> dict:
    client = get_service_client()
    row = {
        "org_id": org_id,
        "employee_id": employee_id,
        "type": payload.type,
        "starts_at": payload.starts_at,
        "ends_at": payload.ends_at,
        "all_day": payload.all_day,
        "reason": payload.reason,
        "internal_note": payload.internal_note,
    }
    return client.table("employee_absences").insert(row).execute().data[0]


@router.post("/{employee_id}/absences")
async def create_absence(
    employee_id: str, payload: AbsenceCreate, user: CurrentUser = Depends(require_org)
) -> dict:
    return await run_in_threadpool(_create_absence, user.org_id, employee_id, payload)


def _list_absences(org_id: str, employee_id: str) -> list[dict]:
    client = get_service_client()
    return (
        client.table("employee_absences")
        .select("*")
        .eq("org_id", org_id)
        .eq("employee_id", employee_id)
        .order("starts_at", desc=True)
        .execute()
        .data
        or []
    )


@router.get("/{employee_id}/absences")
async def list_absences(
    employee_id: str, user: CurrentUser = Depends(require_org)
) -> list[dict]:
    return await run_in_threadpool(_list_absences, user.org_id, employee_id)
