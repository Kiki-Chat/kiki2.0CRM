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
from app.services import csv_import, employee_invite, technician_jobs
from app.services.common import run_parallel, validate_fk_in_org

log = logging.getLogger(__name__)


def _org_name(client, org_id: str) -> str | None:
    rows = (
        client.table("organizations").select("name").eq("id", org_id).limit(1).execute().data
    )
    return rows[0].get("name") if rows else None


def _send_technician_welcome(org_id, company, name, to_email, portal_url) -> None:
    """Best-effort: email a freshly-created technician their STANDING portal link
    (informal 'du' — a worker, not a business customer). Triggers the existing
    send_email() chain (Amber's infra); never blocks employee creation."""
    import html as _html

    try:
        from app.services.email_send import send_email

        company = company or "HeyKiki"
        greeting = f"Hallo {name}," if name else "Hallo,"
        c_esc, g_esc, url_esc = _html.escape(company), _html.escape(greeting), _html.escape(portal_url)
        body_text = (
            f"{greeting}\n\nDu wurdest als Techniker bei {company} hinzugefügt. Über deinen "
            f"persönlichen Link siehst du alle deine Einsätze (aktuelle und vergangene) — ganz "
            f"ohne Zugang:\n\n{portal_url}\n\nTipp: Speichere den Link als Lesezeichen auf deinem Handy."
        )
        body_html = (
            f"<p>{g_esc}</p><p>Du wurdest als Techniker bei <strong>{c_esc}</strong> hinzugefügt. "
            f"Über deinen persönlichen Link siehst du alle deine Einsätze (aktuelle und vergangene) "
            f'— ganz ohne Zugang:</p><p><a href="{url_esc}">{url_esc}</a></p>'
            f"<p>Tipp: Speichere den Link als Lesezeichen auf deinem Handy.</p>"
        )
        send_email(
            org_id=org_id, to_email=to_email,
            subject=f"Dein Techniker-Zugang bei {company}",
            body_html=body_html, body_text=body_text,
        )
    except Exception as exc:  # noqa: BLE001 — email must never block creation
        log.warning("technician welcome email failed (org=%s): %s", org_id, exc)


class SetPasswordRequest(BaseModel):
    password: str

router = APIRouter(prefix="/api/employees", tags=["employees"])

_OWNER_ROLES = {"org_admin", "super_admin"}

# Case statuses that count as CLOSED — everything else is an "open ticket" for the
# per-employee workload badge shown while an admin assigns a Fall.
_CLOSED_CASE = {"completed", "done", "closed", "archived", "cancelled"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _list(org_id: str, role: str | None = None) -> list[dict]:
    client = get_service_client()
    employees = (
        client.table("employees")
        .select(
            "id, user_id, display_name, email, phone, access_role, is_active, calendar_color, "
            "role_in_company, vacation_days_per_year, remaining_vacation_days, "
            "hourly_rate, activity_area, auto_assign, is_technician, technician_portal_token"
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

    def _fetch_open_tickets() -> dict[str, int]:
        # Per-employee count of OPEN Fälle they're assigned to (case_employees ⨝
        # cases), shown while an admin assigns a ticket so an overloaded colleague
        # is obvious. One membership read + one status read, counted in Python.
        if not emp_ids:
            return {}
        ce = (
            client.table("case_employees").select("case_id, employee_id")
            .in_("employee_id", emp_ids).execute().data or []
        )
        c_ids = list({r["case_id"] for r in ce if r.get("case_id")})
        open_ids: set[str] = set()
        if c_ids:
            for c in (
                client.table("cases").select("id, status")
                .eq("org_id", org_id).in_("id", c_ids).execute().data or []
            ):
                if (c.get("status") or "") not in _CLOSED_CASE:
                    open_ids.add(c["id"])
        counts: dict[str, int] = {}
        for r in ce:
            if r.get("case_id") in open_ids:
                counts[r["employee_id"]] = counts.get(r["employee_id"], 0) + 1
        return counts

    user_rows, absence_rows, ticket_counts = run_parallel(
        _fetch_users, _fetch_absences, _fetch_open_tickets
    )
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
                "phone": e.get("phone"),
                "technician_portal_url": (
                    technician_jobs.technician_portal_url(e["technician_portal_token"])
                    if e.get("technician_portal_token") else None
                ),
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
                "is_technician": e.get("is_technician", False),
                "present": e["id"] not in absent_ids,
                "absence_type": absence_type.get(e["id"]),
                "open_tickets": ticket_counts.get(e["id"], 0),
            }
        )
    # Non-admins may read the roster (needed for assignment dropdowns, calendars,
    # presence) but MUST NOT see colleagues' HR data. Strip the sensitive fields
    # for employees; admins get the full record.
    if role not in _OWNER_ROLES:
        sensitive = (
            "email", "phone", "technician_portal_url", "has_login", "access_role",
            "is_org_owner", "vacation_days_per_year", "remaining_vacation_days", "hourly_rate",
        )
        out = [{k: v for k, v in e.items() if k not in sensitive} for e in out]
    return out


@router.get("")
async def list_employees(user: CurrentUser = Depends(require_org)) -> list[dict]:
    return await run_in_threadpool(_list, user.org_id, user.role)


def _create(org_id: str, payload: EmployeeCreate, role: str | None = None) -> dict:
    client = get_service_client()
    # Seat limit (Phase 2) — block adding a Mitarbeiter beyond the plan's seat count.
    # Single chokepoint: the REST route, CSV import, and the copilot tool all reach here.
    from app.services.entitlements import org_can_add_seat, org_seat_limit  # noqa: PLC0415

    current = (
        client.table("employees").select("id", count="exact")
        .eq("org_id", org_id).eq("deleted", False).execute().count or 0
    )
    if not org_can_add_seat(org_id, role, current):
        limit = org_seat_limit(org_id)
        raise HTTPException(
            status_code=402,
            detail={
                "error": "seat_limit",
                "limit": limit,
                "message": f"Mitarbeiter-Limit erreicht ({current}/{limit}) — bitte upgrade, um weitere hinzuzufügen.",
            },
        )
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
            raise HTTPException(status_code=400, detail="E-Mail ist für den Zugang erforderlich")
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
                    "Zugang wiederverwendet, aber das Profil konnte nicht vollständig "
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
                    "Zugang aktualisiert, aber die Einladungs-E-Mail konnte nicht "
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
                    "Mitarbeiter angelegt, aber der Zugang konnte nicht "
                    "erstellt werden. Du kannst die Einladung später erneut "
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
                        "Zugang erstellt, aber die Willkommens-E-Mail konnte nicht "
                        "gesendet werden. Bitte die Einladung erneut senden "
                        "oder ein Passwort manuell setzen."
                    )

    # Lightweight technician (no CRM login) gets a STANDING portal token so they
    # can see all their jobs at /techniker/<token> (item 17). Minted here (only for
    # the no-login technician case) so the unique index can't race a later update.
    import secrets as _secrets

    portal_token = (
        _secrets.token_urlsafe(32) if (payload.is_technician and not payload.login_access) else None
    )
    row = {
        "org_id": org_id,
        "user_id": user_id,
        "display_name": payload.display_name,
        "email": payload.email,
        "phone": payload.phone,
        "access_role": payload.access_role,
        "is_active": payload.is_active,
        "calendar_color": payload.calendar_color,
        "activity_area": payload.activity_area,
        "auto_assign": payload.auto_assign,
        "is_technician": payload.is_technician,
        "technician_portal_token": portal_token,
    }
    created = client.table("employees").insert(row).execute().data[0]
    if portal_token:
        portal_url = technician_jobs.technician_portal_url(portal_token)
        created["technician_portal_url"] = portal_url
        if payload.email:
            _send_technician_welcome(
                org_id, _org_name(client, org_id), payload.display_name, payload.email, portal_url
            )
    if warning:
        created["warning"] = warning
    return created


@router.post("")
async def create_employee(
    payload: EmployeeCreate, user: CurrentUser = Depends(require_org_admin)
) -> dict:
    return await run_in_threadpool(_create, user.org_id, payload, user.role)


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
    # Seat limit (Phase 2) — block a bulk import when the org is already at its seat cap.
    from app.services.entitlements import org_can_add_seat, org_seat_limit  # noqa: PLC0415

    current = (
        get_service_client().table("employees").select("id", count="exact")
        .eq("org_id", user.org_id).eq("deleted", False).execute().count or 0
    )
    if not org_can_add_seat(user.org_id, user.role, current):
        limit = org_seat_limit(user.org_id)
        raise HTTPException(
            status_code=402,
            detail={"error": "seat_limit", "limit": limit,
                    "message": f"Mitarbeiter-Limit erreicht ({current}/{limit}) — bitte upgrade."},
        )
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


def _rotate_technician_token(org_id: str, employee_id: str) -> dict:
    """Re-mint the technician's standing portal token (AUTH-029). Old
    /techniker/<token> link dies immediately; the technician is e-mailed the new
    one via the existing welcome-email path. JobLinkError → 404 in the route."""
    return technician_jobs.rotate_portal_token(
        org_id, employee_id, notify=_send_technician_welcome
    )


@router.post("/{employee_id}/rotate-technician-token")
async def rotate_technician_token(
    employee_id: str, user: CurrentUser = Depends(require_org_admin)
) -> dict:
    """Admin-only: invalidate a technician's portal link and issue a fresh one
    (e.g. lost phone, shared link, departed technician). Returns the new portal
    URL + whether the technician was e-mailed — never the raw token."""
    try:
        return await run_in_threadpool(
            _rotate_technician_token, user.org_id, employee_id
        )
    except technician_jobs.JobLinkError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


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
            status_code=400, detail="Dieser Mitarbeiter hat keinen Zugang"
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
    # Resolve BOTH the absent employee and the chosen substitute (Vertretung) in a
    # single lookup so the overview/approval list can name who covers the absence.
    emp_ids = {a["employee_id"] for a in absences}
    emp_ids |= {a["substitute_employee_id"] for a in absences if a.get("substitute_employee_id")}
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
        sub = names.get(a.get("substitute_employee_id")) if a.get("substitute_employee_id") else None
        a["substitute_name"] = sub.get("display_name") if sub else None
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
    sub_id = (payload.substitute_employee_id or "").strip() or None
    if sub_id:
        if sub_id == me["id"]:
            return "substitute_is_self"
        # A stand-in must be an active employee of the same org.
        validate_fk_in_org(
            client, table="employees", fk_id=sub_id, org_id=org_id,
            label="Vertretung", require_active=True,
        )
    row = {
        "org_id": org_id,
        "employee_id": me["id"],  # OWN record — never from the request
        "type": payload.type,
        "starts_at": payload.starts_at,
        "ends_at": payload.ends_at,
        "all_day": payload.all_day,
        "reason": payload.reason,
        "substitute_employee_id": sub_id,
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
    if res == "substitute_is_self":
        raise HTTPException(
            status_code=400,
            detail="Die Vertretung darf nicht die antragstellende Person selbst sein.",
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
    sub_id = (payload.substitute_employee_id or "").strip() or None
    if sub_id:
        if sub_id == employee_id:
            raise HTTPException(
                status_code=400,
                detail="Die Vertretung darf nicht die abwesende Person selbst sein.",
            )
        validate_fk_in_org(
            client, table="employees", fk_id=sub_id, org_id=org_id,
            label="Vertretung", require_active=True,
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
        "substitute_employee_id": sub_id,
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
