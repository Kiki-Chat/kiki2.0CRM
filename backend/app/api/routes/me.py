from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, get_current_user
from app.core import cache
from app.core.config import settings
from app.db.supabase_client import get_service_client

router = APIRouter(prefix="/api", tags=["me"])


def _org_identity(org_id: str) -> dict:
    # White-label identity read on every page load (sidebar badge + footer + /api/me):
    # company name, contact email, logo, address. Available to EVERY authenticated
    # user (incl. employees), unlike the admin-only /api/settings. Cache target
    # (Item 4): changes only via PATCH /api/settings/general + the logo upload/delete
    # routes (single writers → unambiguous invalidation). org-scoped key; no-op until
    # REDIS_URL is set.
    def _load() -> dict:
        rows = (
            get_service_client()
            .table("organizations")
            .select("name, email, logo_url, address")
            .eq("id", org_id)
            .limit(1)
            .execute()
            .data
        )
        row = rows[0] if rows else {}
        return {
            "name": row.get("name"),
            "email": row.get("email"),
            "logo_url": row.get("logo_url"),
            "address": row.get("address"),
        }

    return cache.get_or_set(org_id, "org_identity", _load)


def _org_entitlements(org_id: str) -> dict:
    """The org's current plan + resolved feature keys (Phase-2 menu/route gating).
    Uncached + off the same row read so it always reflects the latest plan after an
    upgrade. plan_title=None / unknown plan ⇒ core features only."""
    from app.services.entitlements import effective_features

    rows = (
        get_service_client()
        .table("organizations")
        .select("billing_plan_title")
        .eq("id", org_id)
        .limit(1)
        .execute()
        .data
    )
    plan = (rows[0] if rows else {}).get("billing_plan_title")
    return {"plan_title": plan, "features": sorted(effective_features(plan))}


def _locked_menu_keys(org_id: str, user_id: str, role: str | None) -> list[str]:
    """Menu paths the admin has hidden for THIS employee (Phase 5). Admins,
    super-admins and technicians are never menu-locked → []. Fail-open: no rows
    (or no employee profile) → []."""
    if role in ("org_admin", "super_admin", "technician"):
        return []
    try:
        from app.services.employee_calendar import resolve_employee_id

        emp_id = resolve_employee_id(org_id, user_id)
        if not emp_id:
            return []
        rows = (
            get_service_client()
            .table("employee_menu_access")
            .select("menu_key")
            .eq("org_id", org_id)
            .eq("employee_id", emp_id)
            .execute()
            .data
            or []
        )
        return sorted(r["menu_key"] for r in rows if r.get("menu_key"))
    except Exception:  # noqa: BLE001 — menu locks are best-effort; never 500 /api/me
        return []


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    # org_* fields let the white-label UI show WHOSE CRM this is — company name +
    # contact email + logo + address surface in the sidebar badge, the footer, and
    # personal settings. Available to every authenticated user (incl. employees).
    ident = await run_in_threadpool(_org_identity, user.org_id) if user.org_id else {}
    ent = await run_in_threadpool(_org_entitlements, user.org_id) if user.org_id else {}
    locked = (
        await run_in_threadpool(_locked_menu_keys, user.org_id, user.id, user.role)
        if user.org_id
        else []
    )
    return {
        "id": user.id,
        "email": user.email,
        "org_id": user.org_id,
        "role": user.role,
        "full_name": user.full_name,
        "org_name": ident.get("name"),
        "org_email": ident.get("email"),
        "org_logo_url": ident.get("logo_url"),
        "org_address": ident.get("address"),
        # Phase-2 entitlements: which plan + which gateable features this org has.
        "plan_title": ent.get("plan_title"),
        "features": ent.get("features", []),
        # UAT/QA only — drives the dev plan-switcher button (off in prod).
        "dev_plan_switcher": settings.dev_plan_switcher,
        # Phase 5: nav paths the admin has hidden for this employee (sidebar gating).
        "locked_menu_keys": locked,
    }
