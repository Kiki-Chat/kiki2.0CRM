import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org, require_org_admin
from app.db.supabase_client import get_service_client
from app.schemas.admin import (
    AbsenceApply,
    AbsenceCreate,
    AbsenceReview,
    EmployeeCreate,
    EmployeeUpdate,
)
from app.services import csv_import, employee_invite
from app.services.common import run_parallel, validate_fk_in_org

log = logging.getLogger(__name__)


def _org_name(client, org_id: str) -> str | None:
    rows = (
        client.table("organizations").select("name").eq("id", org_id).limit(1).execute().data
    )
    return rows[0].get("name") if rows else None


class SetPasswordRequest(BaseModel):
    password: str

router = APIRouter(prefix="/api/employees", tags=["employees"])

_OWNER_ROLES = {"org_admin", "super_admin"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _list(org_id: str, role: str | None = None) -> list[dict]:
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
    emp_ids = [e["id"] for e in employees]
    now_iso = _now().isoformat()  # absences covering "now" → presence

    # The login-users read and the absences read both depend only on the employee
    # list, not on each other → fetch them concurrently.
    def _fetch_users():
        if not user_ids:
            return []
        return (
            client.table("users").select("id, email, role, full_name")
            .in_("id", user_ids).execute().data or []
        )

    def _fetch_absences():
        if not emp_ids:
            return []
        return (
            client.table("employee_absences")
            .select("employee_id, type, starts_at, ends_at")
            .eq("org_id", org_id)
            .eq("status", "approved")  # only APPROVED absences mark someone absent
            .in_("employee_id", emp_ids)
            .lte("starts_at", now_iso)
            .gte("ends_at", now_iso)
            .execute().data or []
        )

    user_rows, absence_rows = run_parallel(_fetch_users, _fetch_absences)
    users: dict[str, dict] = {u["id"]: u for u in user_rows}
    absent_ids = set()
    absence_type: dict[str, str] = {}
    for a in absence_rows:
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
    # Non-admins may read the roster (needed for assignment dropdowns, calendars,
    # presence) but MUST NOT see colleagues' HR data. Strip the sensitive fields
    # for employees; admins get the full record.
    if role not in _OWNER_ROLES:
        sensitive = (
            "email", "has_login", "access_role", "is_org_owner",
            "vacation_days_per_year", "remaining_vacation_days", "hourly_rate",
        )
        out = [{k: v for k, v in e.items() if k not in sensitive} for e in out]
    return out


@router.get("")
async def list_employees(user: CurrentUser = Depends(require_org)) -> list[dict]:
    return await run_in_threadpool(_list, user.org_id, user.role)


def _create(org_id: str, payload: EmployeeCreate) -> dict:
    client = get_service_client()
    user_id = None
    warning = None
    # Email must be unique per org among active (non-deleted) employees. The
    # employees table has NO DB constraint and the users-table check below only
    # runs for login_access; without this, a duplicate-email employee inserts
    # cleanly. Case-insensitive exact match; soft-deleted rows are ignored so a
    # removed person can be re-added.
    if payload.email:
        target = payload.email.strip().lower()
        existing_emails = (
            client.table("employees")
            .select("email")
            .eq("org_id", org_id)
            .eq("deleted", False)
            .execute()
            .data
            or []
        )
        if any((e.get("email") or "").strip().lower() == target for e in existing_emails):
            raise HTTPException(
                status_code=409,
                detail="Ein Mitarbeiter mit dieser E-Mail-Adresse existiert bereits.",
            )
    if payload.login_access:
        if not payload.email:
            raise HTTPException(status_code=400, detail="E-Mail ist für den Login erforderlich")
        existing = (
            client.table("users").select("id").eq("email", payload.email).limit(1).execute().data
        )
        if existing:
            # Recreate-by-email (B2 / Cluster 7): the surviving auth+users login is
            # REUSED, so it must be fully RE-PROVISIONED — otherwise the deleted
            # person's name/role/sessions stick to the new hire. (a) refresh the
            # identity (name/role/org), (b) revoke the prior holder's sessions,
            # (c) reset the credential + send a fresh invite (never silently keep
            # the old password as a way in).
            user_id = existing[0]["id"]
            new_role = "org_admin" if payload.access_role == "admin" else "employee"
            try:
                client.table("users").update(
                    {"full_name": payload.display_name, "role": new_role, "org_id": org_id}
                ).eq("id", user_id).execute()
                client.auth.admin.update_user_by_id(
                    user_id, {"user_metadata": {"full_name": payload.display_name}}
                )
            except Exception:  # noqa: BLE001
                log.exception("employee recreate: profile/auth update failed (user %s)", user_id)
                warning = (
                    "Login wiederverwendet, aber das Profil konnte nicht vollständig "
                    "aktualisiert werden."
                )
            try:
                employee_invite.revoke_user_sessions(user_id)
            except Exception as exc:  # noqa: BLE001 — best-effort; never block recreate
                log.warning("recreate: session revoke failed user=%s err=%s", user_id, exc)
            try:
                link, _ = employee_invite.generate_set_password_link(
                    payload.email, new_user=False
                )
                employee_invite.send_employee_welcome(
                    org_id=org_id,
                    company_name=_org_name(client, org_id),
                    display_name=payload.display_name,
                    login_email=payload.email,
                    set_password_link=link,
                )
            except Exception:  # noqa: BLE001
                log.exception("employee recreate: invite email failed (user %s)", user_id)
                warning = ((warning + " ") if warning else "") + (
                    "Login aktualisiert, aber die Einladungs-E-Mail konnte nicht "
                    "gesendet werden."
                )
        else:
            # New login (Wave 2): generate a set-password invite link (this creates
            # the auth user; Supabase sends NO email), create the public.users row,
            # then send OUR branded welcome email carrying the link — NEVER a
            # password. Two independent try-blocks so an email failure still leaves
            # a usable login (admin can resend or set a password manually).
            link = None
            try:
                link, user_id = employee_invite.generate_set_password_link(
                    payload.email, new_user=True
                )
                client.table("users").insert(
                    {
                        "id": user_id,
                        "org_id": org_id,
                        "full_name": payload.display_name,
                        "email": payload.email,
                        "role": "org_admin" if payload.access_role == "admin" else "employee",
                    }
                ).execute()
            except Exception:  # noqa: BLE001
                # Could not create the login → don't lose the record; create the
                # employee without login. Admin can resend / set a password later.
                log.exception("employee create: login provisioning failed (email %s)", payload.email)
                user_id = None
                link = None
                warning = (
                    "Mitarbeiter angelegt, aber der Login-Zugang konnte nicht "
                    "erstellt werden. Sie können die Einladung später erneut "
                    "senden oder ein Passwort manuell setzen."
                )
            if user_id and link:
                try:
                    employee_invite.send_employee_welcome(
                        org_id=org_id,
                        company_name=_org_name(client, org_id),
                        display_name=payload.display_name,
                        login_email=payload.email,
                        set_password_link=link,
                    )
                except Exception:  # noqa: BLE001
                    log.exception("employee create: welcome email failed (email %s)", payload.email)
                    warning = (
                        "Login erstellt, aber die Willkommens-E-Mail konnte nicht "
                        "gesendet werden. Bitte die Einladung erneut senden "
                        "oder ein Passwort manuell setzen."
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
    payload: EmployeeCreate, user: CurrentUser = Depends(require_org_admin)
) -> dict:
    return await run_in_threadpool(_create, user.org_id, payload)


@router.post("/import")
async def import_employees_csv(
    file: UploadFile = File(...),
    mapping: str = Form("{}"),
    user: CurrentUser = Depends(require_org_admin),
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
    employee_id: str, payload: EmployeeUpdate, user: CurrentUser = Depends(require_org_admin)
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
    employee_id: str, user: CurrentUser = Depends(require_org_admin)
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
        .select("email, user_id, display_name, access_role")
        .eq("org_id", org_id)
        .eq("id", employee_id)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        return "not_found"
    emp = rows[0]
    email = emp.get("email")
    if not email:
        return "no_email"
    try:
        if emp.get("user_id"):
            # Existing login → recovery (set-new-password) link.
            link, _ = employee_invite.generate_set_password_link(email, new_user=False)
        else:
            # No login yet → invite link (creates the auth user); create the
            # users row and back-link it onto the employee record.
            link, new_uid = employee_invite.generate_set_password_link(email, new_user=True)
            client.table("users").insert(
                {
                    "id": new_uid,
                    "org_id": org_id,
                    "full_name": emp.get("display_name"),
                    "email": email,
                    "role": "org_admin" if emp.get("access_role") == "admin" else "employee",
                }
            ).execute()
            client.table("employees").update({"user_id": new_uid}).eq(
                "org_id", org_id
            ).eq("id", employee_id).execute()
        employee_invite.send_employee_welcome(
            org_id=org_id,
            company_name=_org_name(client, org_id),
            display_name=emp.get("display_name"),
            login_email=email,
            set_password_link=link,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("resend_invite_failed org=%s emp=%s err=%s", org_id, employee_id, exc)
        return "send_failed"
    return "ok"


@router.post("/{employee_id}/resend-invite")
async def resend_invite(
    employee_id: str, user: CurrentUser = Depends(require_org_admin)
) -> dict:
    result = await run_in_threadpool(_resend_invite, user.org_id, employee_id)
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Employee not found")
    if result == "no_email":
        raise HTTPException(status_code=400, detail="Keine E-Mail-Adresse hinterlegt")
    if result == "send_failed":
        raise HTTPException(
            status_code=502,
            detail="Einladungs-E-Mail konnte nicht gesendet werden. Bitte später erneut versuchen.",
        )
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
    employee_id: str, payload: SetPasswordRequest, user: CurrentUser = Depends(require_org_admin)
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
# Two audiences (backend is the source of truth; UI follows):
#   • Employees self-serve — apply for their OWN absence (status='pending') and
#     view their own requests. The employee_id is resolved from the caller's user,
#     NEVER taken from the request, so an employee can't file for a colleague.
#   • Org-admins manage everyone — create (pre-approved), list all, and approve /
#     reject pending requests. Admin-only (require_org_admin).
_ABSENCE_STATUSES = {"pending", "approved", "rejected"}


def _my_employee(client, org_id: str, user_id: str) -> dict | None:
    """The caller's own employee record in this org (None if they have none)."""
    rows = (
        client.table("employees")
        .select("id, display_name")
        .eq("org_id", org_id)
        .eq("user_id", user_id)
        .eq("deleted", False)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


def _attach_employee_names(client, org_id: str, absences: list[dict]) -> list[dict]:
    emp_ids = {a["employee_id"] for a in absences}
    names: dict[str, dict] = {}
    if emp_ids:
        for e in (
            client.table("employees")
            .select("id, display_name, calendar_color")
            .eq("org_id", org_id)
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


# ─── Admin: list all / pending, approve, reject ──────────────────────────────
def _list_all_absences(org_id: str, frm: str | None, to: str | None) -> list[dict]:
    client = get_service_client()
    query = client.table("employee_absences").select("*").eq("org_id", org_id)
    if to:
        query = query.lt("starts_at", to)
    if frm:
        query = query.gte("ends_at", frm)
    absences = query.order("starts_at").execute().data or []
    return _attach_employee_names(client, org_id, absences)


@router.get("/absences")
async def list_all_absences(
    frm: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    user: CurrentUser = Depends(require_org_admin),
) -> list[dict]:
    return await run_in_threadpool(_list_all_absences, user.org_id, frm, to)


def _list_pending(org_id: str) -> list[dict]:
    client = get_service_client()
    rows = (
        client.table("employee_absences")
        .select("*")
        .eq("org_id", org_id)
        .eq("status", "pending")
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    return _attach_employee_names(client, org_id, rows)


@router.get("/absences/pending")
async def list_pending_absences(user: CurrentUser = Depends(require_org_admin)) -> list[dict]:
    """Pending absence requests for the org — powers the admin Anträge tab."""
    return await run_in_threadpool(_list_pending, user.org_id)


def _review_absence(
    org_id: str, absence_id: str, status: str, reviewer_id: str, note: str | None
) -> dict | None:
    client = get_service_client()
    existing = (
        client.table("employee_absences")
        .select("id")
        .eq("org_id", org_id)
        .eq("id", absence_id)
        .limit(1)
        .execute()
        .data
    )
    if not existing:
        return None
    fields: dict = {
        "status": status,
        "reviewed_by": reviewer_id,
        "reviewed_at": _now().isoformat(),
    }
    if note is not None:
        fields["internal_note"] = note
    res = (
        client.table("employee_absences")
        .update(fields)
        .eq("org_id", org_id)
        .eq("id", absence_id)
        .execute()
    )
    return res.data[0] if res.data else None


@router.post("/absences/{absence_id}/approve")
async def approve_absence(
    absence_id: str,
    payload: AbsenceReview | None = None,
    user: CurrentUser = Depends(require_org_admin),
) -> dict:
    note = payload.note if payload else None
    row = await run_in_threadpool(
        _review_absence, user.org_id, absence_id, "approved", user.id, note
    )
    if not row:
        raise HTTPException(status_code=404, detail="Abwesenheit nicht gefunden")
    return row


@router.post("/absences/{absence_id}/reject")
async def reject_absence(
    absence_id: str,
    payload: AbsenceReview | None = None,
    user: CurrentUser = Depends(require_org_admin),
) -> dict:
    note = payload.note if payload else None
    row = await run_in_threadpool(
        _review_absence, user.org_id, absence_id, "rejected", user.id, note
    )
    if not row:
        raise HTTPException(status_code=404, detail="Abwesenheit nicht gefunden")
    return row


# ─── Employee self-service (declared BEFORE /{employee_id}/* so "me" wins) ────
def _apply_absence(org_id: str, user_id: str, payload: AbsenceApply) -> dict | str:
    client = get_service_client()
    me = _my_employee(client, org_id, user_id)
    if not me:
        return "no_employee"
    row = {
        "org_id": org_id,
        "employee_id": me["id"],  # OWN record — never from the request
        "type": payload.type,
        "starts_at": payload.starts_at,
        "ends_at": payload.ends_at,
        "all_day": payload.all_day,
        "reason": payload.reason,
        "status": "pending",  # employee requests are pending until an admin reviews
    }
    return client.table("employee_absences").insert(row).execute().data[0]


@router.post("/me/absences")
async def apply_for_absence(
    payload: AbsenceApply, user: CurrentUser = Depends(require_org)
) -> dict:
    """Employee applies for their OWN absence (lands as 'pending')."""
    res = await run_in_threadpool(_apply_absence, user.org_id, user.id, payload)
    if res == "no_employee":
        raise HTTPException(
            status_code=404,
            detail="Kein Mitarbeiterprofil für dieses Konto gefunden.",
        )
    return res


def _list_my_absences(org_id: str, user_id: str) -> list[dict] | None:
    client = get_service_client()
    me = _my_employee(client, org_id, user_id)
    if not me:
        return None
    return (
        client.table("employee_absences")
        .select("*")
        .eq("org_id", org_id)
        .eq("employee_id", me["id"])
        .order("starts_at", desc=True)
        .execute()
        .data
        or []
    )


@router.get("/me/absences")
async def list_my_absences(user: CurrentUser = Depends(require_org)) -> list[dict]:
    """The caller's own absences (all statuses)."""
    res = await run_in_threadpool(_list_my_absences, user.org_id, user.id)
    return res or []


# ─── Admin: create for any employee (pre-approved) / list one employee's ─────
def _create_absence(org_id: str, employee_id: str, payload: AbsenceCreate) -> dict:
    client = get_service_client()
    # FK hardening: can't file an absence against another org's employee.
    validate_fk_in_org(
        client, table="employees", fk_id=employee_id, org_id=org_id,
        label="Mitarbeiter", require_active=True,
    )
    row = {
        "org_id": org_id,
        "employee_id": employee_id,
        "type": payload.type,
        "starts_at": payload.starts_at,
        "ends_at": payload.ends_at,
        "all_day": payload.all_day,
        "reason": payload.reason,
        "internal_note": payload.internal_note,
        # status omitted → DB default 'approved' (an admin-created absence is
        # authoritative, no approval step needed).
    }
    return client.table("employee_absences").insert(row).execute().data[0]


@router.post("/{employee_id}/absences")
async def create_absence(
    employee_id: str, payload: AbsenceCreate, user: CurrentUser = Depends(require_org_admin)
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
    employee_id: str, user: CurrentUser = Depends(require_org_admin)
) -> list[dict]:
    return await run_in_threadpool(_list_absences, user.org_id, employee_id)
