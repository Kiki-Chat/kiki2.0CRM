"""Technician portal API — Track A, Phase 4.

A field technician logs in (``users.role='technician'``) and sees a toned-down
portal. Every endpoint is SELF-SCOPED to the caller's own employee record — a
technician can only ever read their OWN jobs (the route resolves the employee
from the JWT, never from a client-supplied id).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.services.employee_calendar import resolve_employee_id

router = APIRouter(prefix="/api/technician", tags=["technician"])


def _fmt_addr(location, customer: dict | None) -> str | None:
    if isinstance(location, dict) and location.get("raw"):
        return location["raw"]
    if isinstance(location, str) and location.strip():
        return location
    if customer:
        if customer.get("address_text"):
            return customer["address_text"]
        addr = customer.get("address")
        if isinstance(addr, dict):
            joined = ", ".join(p for p in [addr.get("street"), addr.get("zip"), addr.get("city")] if p)
            return joined or None
    return None


def _my_profile_and_jobs(org_id: str, user_id: str) -> dict:
    client = get_service_client()
    emp_id = resolve_employee_id(org_id, user_id)
    if not emp_id:
        return {"employee_id": None, "display_name": None, "jobs": []}
    emp_rows = (
        client.table("employees").select("id, display_name")
        .eq("org_id", org_id).eq("id", emp_id).limit(1).execute().data
        or []
    )
    display_name = emp_rows[0].get("display_name") if emp_rows else None
    # The technician's own visits = appointments assigned to them (on confirm the
    # two-stage flow mirrors the technician onto assigned_employee_id).
    appts = (
        client.table("appointments")
        .select("id, title, scheduled_at, duration_minutes, status, location, customer_id, category")
        .eq("org_id", org_id)
        .eq("assigned_employee_id", emp_id)
        .neq("status", "cancelled")
        .order("scheduled_at", desc=False)
        .execute()
        .data
        or []
    )
    cust_ids = list({a["customer_id"] for a in appts if a.get("customer_id")})
    customers: dict[str, dict] = {}
    if cust_ids:
        for c in (
            client.table("customers")
            .select("id, full_name, phone, address, address_text")
            .eq("org_id", org_id).in_("id", cust_ids).execute().data
            or []
        ):
            customers[c["id"]] = c
    jobs = []
    for a in appts:
        c = customers.get(a.get("customer_id"))
        jobs.append({
            "appointment_id": a["id"],
            "title": a.get("title"),
            "scheduled_at": a.get("scheduled_at"),
            "duration_minutes": a.get("duration_minutes"),
            "status": a.get("status"),
            "category": a.get("category"),
            "customer_name": (c or {}).get("full_name"),
            "customer_phone": (c or {}).get("phone"),
            "customer_address": _fmt_addr(a.get("location"), c),
        })
    return {"employee_id": emp_id, "display_name": display_name, "jobs": jobs}


@router.get("/me/jobs")
async def my_jobs(user: CurrentUser = Depends(require_org)) -> dict:
    """The caller technician's own assigned visits (newest scheduled first)."""
    return await run_in_threadpool(_my_profile_and_jobs, user.org_id, user.id)
