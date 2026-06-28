"""Employee-facing calendar-connection endpoints.

A member links / inspects / disconnects THEIR OWN Google calendar for the
per-employee two-way sync. The OAuth authorize + callback are reused from
``api/routes/oauth.py`` with ``purpose='employee_calendar'`` (so the connect
button calls ``GET /api/settings/oauth/google/authorize?purpose=employee_calendar``);
these endpoints add status, disconnect, and the admin roster of who's connected.
"""
from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org, require_org_admin
from app.services import employee_calendar

router = APIRouter(prefix="/api/employee-calendar", tags=["employee-calendar"])


@router.get("/me")
async def my_calendar(user: CurrentUser = Depends(require_org)) -> dict:
    """Connection status for the calling user's OWN employee calendar."""

    def _do() -> dict:
        emp_id = employee_calendar.resolve_employee_id(user.org_id, user.id)
        if not emp_id:
            return {"has_employee": False, "connected": False}
        conn = employee_calendar.get_connection(user.org_id, emp_id)
        return {
            "has_employee": True,
            "employee_id": emp_id,
            "connected": bool(conn),
            "account_email": conn.get("account_email") if conn else None,
            "token_expires_at": conn.get("token_expires_at") if conn else None,
        }

    return await run_in_threadpool(_do)


@router.post("/disconnect")
async def disconnect_my_calendar(user: CurrentUser = Depends(require_org)) -> dict:
    """Disconnect the calling user's own calendar: best-effort revoke + delete the
    grant, then purge their mirrored busy blocks."""

    def _do() -> dict:
        emp_id = employee_calendar.resolve_employee_id(user.org_id, user.id)
        if not emp_id:
            raise HTTPException(status_code=404, detail="Kein Mitarbeiterprofil gefunden.")
        revoked = employee_calendar.revoke_and_delete(user.org_id, emp_id)
        try:  # purge this employee's imported busy blocks (per-employee sync)
            from app.services import employee_calendar_sync

            employee_calendar_sync.purge_employee_busy(user.org_id, emp_id)
        except Exception:  # noqa: BLE001 — best-effort; the grant is already gone
            pass
        return {"success": True, "revoked": revoked}

    return await run_in_threadpool(_do)


@router.get("/connections")
async def list_connected(user: CurrentUser = Depends(require_org_admin)) -> dict:
    """Admin view: which employees have linked their calendar (no token data).
    Powers the admin master-calendar 'who is synced' surface."""
    return await run_in_threadpool(employee_calendar.list_connections, user.org_id)
