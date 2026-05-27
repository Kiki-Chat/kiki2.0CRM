"""Super-admin org management (P0.6).

All endpoints gated by `require_super_admin` (role='super_admin'). Provides
CRUD + soft-disable/re-enable + delete (with X-Confirm-Delete header matching
the org name) over the organizations table.

The CREATE endpoint is a thin wrapper around app.services.provisioning.provision_org
— the same code path the existing POST /api/heykiki/provision uses with the
master secret. Super-admin auth replaces the master-secret check.
"""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_super_admin
from app.db.supabase_client import get_service_client
from app.schemas.provision import ProvisionRequest, ProvisionResponse
from app.services.history_import import import_agent_history
from app.services.provisioning import provision_org

router = APIRouter(prefix="/api/super-admin", tags=["super-admin"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Schemas ─────────────────────────────────────────────────────────────────
class OrgPatch(BaseModel):
    name: str | None = None
    email: str | None = None
    phone_number: str | None = None
    elevenlabs_agent_id: str | None = None
    model_config = {"extra": "ignore"}


# ─── Helpers ─────────────────────────────────────────────────────────────────
_ORG_LIST_COLS = (
    "id, heykiki_org_id, name, email, phone_number, elevenlabs_agent_id, "
    "disabled_at, created_at, updated_at"
)


def _list_orgs() -> list[dict]:
    client = get_service_client()
    rows = (
        client.table("organizations")
        .select(_ORG_LIST_COLS)
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    return rows


def _get_org(org_id: str) -> dict | None:
    client = get_service_client()
    rows = (
        client.table("organizations")
        .select("*")
        .eq("id", org_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def _patch_org(org_id: str, payload: dict) -> dict | None:
    if not payload:
        return _get_org(org_id)
    # P0.6 safety: never expose disabled_at via PATCH — must go through
    # /disable + /enable so the audit story stays clean. Same for created_at.
    for forbidden in ("disabled_at", "created_at", "id"):
        payload.pop(forbidden, None)
    payload["updated_at"] = _now()
    client = get_service_client()
    rows = (
        client.table("organizations")
        .update(payload)
        .eq("id", org_id)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def _set_disabled(org_id: str, disabled: bool) -> dict | None:
    client = get_service_client()
    rows = (
        client.table("organizations")
        .update(
            {
                "disabled_at": _now() if disabled else None,
                "updated_at": _now(),
            }
        )
        .eq("id", org_id)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def _delete_org(org_id: str) -> bool:
    """Hard delete. organizations cascades to users / customers / calls / etc.
    via ON DELETE CASCADE in 0001_init_schema.sql."""
    client = get_service_client()
    res = client.table("organizations").delete().eq("id", org_id).execute()
    return bool(res.data)


# ─── Routes ──────────────────────────────────────────────────────────────────
def _org_stats(org_ids: list[str]) -> dict[str, dict]:
    """Per-org usage counts + last activity for the standalone admin list.

    Cheap aggregate over the major tables. Each query is org_id-filtered and
    returns only the counts; no row data is read. ``last_activity`` = max of
    calls.created_at / appointments.created_at / cost_estimates.created_at
    / invoices.created_at, or None if all tables are empty for the org.
    """
    if not org_ids:
        return {}
    client = get_service_client()
    stats: dict[str, dict] = {
        oid: {
            "calls": 0,
            "kvas_sent": 0,
            "employees": 0,
            "appointments": 0,
            "last_activity": None,
        }
        for oid in org_ids
    }

    def _count_by_org(table: str, key: str, extra_eq: tuple[str, str] | None = None) -> None:
        for oid in org_ids:
            q = client.table(table).select("id", count="exact", head=True).eq("org_id", oid)
            if extra_eq:
                q = q.eq(extra_eq[0], extra_eq[1])
            try:
                res = q.execute()
                stats[oid][key] = int(getattr(res, "count", 0) or 0)
            except Exception:
                stats[oid][key] = 0

    _count_by_org("calls", "calls")
    _count_by_org("cost_estimates", "kvas_sent", extra_eq=("status", "sent"))
    _count_by_org("employees", "employees")
    _count_by_org("appointments", "appointments")

    # Last activity: max(created_at) across calls / appointments / cost_estimates / invoices.
    for oid in org_ids:
        latest: str | None = None
        for table in ("calls", "appointments", "cost_estimates", "invoices"):
            try:
                rows = (
                    client.table(table)
                    .select("created_at")
                    .eq("org_id", oid)
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                    .data
                    or []
                )
                if rows and rows[0].get("created_at"):
                    ts = rows[0]["created_at"]
                    if latest is None or ts > latest:
                        latest = ts
            except Exception:
                continue
        stats[oid]["last_activity"] = latest

    return stats


@router.get("/orgs")
async def list_orgs(_user: CurrentUser = Depends(require_super_admin)) -> dict:
    """List all organizations (super-admin only)."""
    rows = await run_in_threadpool(_list_orgs)
    return {"orgs": rows}


@router.get("/orgs-stats")
async def list_orgs_stats(_user: CurrentUser = Depends(require_super_admin)) -> dict:
    """Usage counters per org for the standalone admin org list.

    Returns ``{org_id: {calls, kvas_sent, employees, appointments, last_activity}}``.
    Separate from ``GET /orgs`` so the master-data list stays cheap and the
    counter query (which fans out across 4 tables × N orgs) can be loaded
    lazily / cached independently on the frontend.
    """
    orgs = await run_in_threadpool(_list_orgs)
    org_ids = [o["id"] for o in orgs]
    stats = await run_in_threadpool(_org_stats, org_ids)
    return {"stats": stats}


@router.get("/orgs/{org_id}")
async def get_org(
    org_id: str,
    _user: CurrentUser = Depends(require_super_admin),
) -> dict:
    org = await run_in_threadpool(_get_org, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organisation nicht gefunden.")
    return org


@router.patch("/orgs/{org_id}")
async def patch_org(
    org_id: str,
    payload: OrgPatch,
    _user: CurrentUser = Depends(require_super_admin),
) -> dict:
    body = payload.model_dump(exclude_unset=True)
    updated = await run_in_threadpool(_patch_org, org_id, body)
    if not updated:
        raise HTTPException(status_code=404, detail="Organisation nicht gefunden.")
    return updated


@router.post("/orgs/{org_id}/disable")
async def disable_org(
    org_id: str,
    _user: CurrentUser = Depends(require_super_admin),
) -> dict:
    """Soft-disable: sets disabled_at = now(). Users in this org will be blocked
    from login with 'Diese Organisation ist deaktiviert' until re-enabled."""
    updated = await run_in_threadpool(_set_disabled, org_id, True)
    if not updated:
        raise HTTPException(status_code=404, detail="Organisation nicht gefunden.")
    return updated


@router.post("/orgs/{org_id}/enable")
async def enable_org(
    org_id: str,
    _user: CurrentUser = Depends(require_super_admin),
) -> dict:
    """Re-enable a previously disabled org. Clears disabled_at."""
    updated = await run_in_threadpool(_set_disabled, org_id, False)
    if not updated:
        raise HTTPException(status_code=404, detail="Organisation nicht gefunden.")
    return updated


@router.delete("/orgs/{org_id}")
async def delete_org(
    org_id: str,
    x_confirm_delete: str | None = Header(default=None, alias="X-Confirm-Delete"),
    _user: CurrentUser = Depends(require_super_admin),
) -> dict:
    """Hard delete — irreversible. Cascades to users / customers / calls /
    inquiries / appointments / cost_estimates / invoices / etc.

    Requires X-Confirm-Delete header matching the org's `name` exactly.
    Same pattern as the org_admin /api/settings/organization DELETE."""
    org = await run_in_threadpool(_get_org, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organisation nicht gefunden.")
    expected = (org.get("name") or "").strip()
    if (x_confirm_delete or "").strip() != expected:
        raise HTTPException(
            status_code=400,
            detail="Bestätigungstext stimmt nicht mit dem Organisationsnamen überein.",
        )
    ok = await run_in_threadpool(_delete_org, org_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Löschen fehlgeschlagen.")
    return {"success": True, "deleted_org_id": org_id}


# ─── Create org (thin wrapper around provisioning) ──────────────────────────
@router.post("/orgs", response_model=ProvisionResponse)
async def create_org(
    payload: ProvisionRequest,
    background_tasks: BackgroundTasks,
    _user: CurrentUser = Depends(require_super_admin),
) -> ProvisionResponse:
    """Create a new org. Reuses app.services.provisioning.provision_org —
    the same code path as POST /api/heykiki/provision. Super-admin auth
    replaces the master-secret check here, since the caller is already a
    trusted super-admin (no shared-secret round-trip needed).

    P0.9 parity (2026-05-27 fix): mirrors /api/heykiki/provision by
    scheduling import_agent_history as a BackgroundTask so historical
    ElevenLabs conversations get backfilled into the new org's calls
    table. Without this, orgs created via the super-admin surface would
    start with empty Call Logs even when the bound agent had prior
    conversations. Idempotent via the P0.2 SELECT-first dedup.
    """
    response = await run_in_threadpool(provision_org, payload)
    background_tasks.add_task(
        import_agent_history,
        org_id=response.org_id,
        agent_id=payload.elevenlabs_agent_id,
    )
    return response


# ─── Convenience: promote/demote (for the one-shot super-admin user flow) ────
class RoleChange(BaseModel):
    role: str  # 'super_admin' | 'org_admin' | 'employee'


# ─── Manual re-trigger for the post-provision history import (P0.9) ─────────
@router.post("/orgs/{org_id}/import-history")
async def import_history(
    org_id: str,
    _user: CurrentUser = Depends(require_super_admin),
) -> dict:
    """Re-trigger the historical EL-conversation import for an existing org.
    Idempotent via the P0.2 SELECT-first dedup, so re-runs only process
    newly-appeared conversations."""
    org = await run_in_threadpool(_get_org, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organisation nicht gefunden.")
    agent_id = org.get("elevenlabs_agent_id")
    if not agent_id:
        raise HTTPException(
            status_code=400,
            detail="Diese Organisation hat keine ElevenLabs Agent ID hinterlegt.",
        )
    counters = await run_in_threadpool(import_agent_history, org_id, agent_id)
    return {"success": True, "org_id": org_id, **counters}


@router.patch("/users/{user_id}/role")
async def set_user_role(
    user_id: str | UUID,
    payload: RoleChange,
    _user: CurrentUser = Depends(require_super_admin),
) -> dict:
    """Promote/demote a user's role. Allowed roles match the existing schema.

    Enforces Amber's 'only one super_admin' constraint: rejects any attempt
    to promote a second user to super_admin. The DB-level partial unique
    index `uniq_one_super_admin` (migration 0020) is the backstop.
    """
    if payload.role not in ("super_admin", "org_admin", "employee"):
        raise HTTPException(status_code=400, detail="Unbekannte Rolle.")

    def _do() -> dict | None:
        client = get_service_client()
        if payload.role == "super_admin":
            existing = (
                client.table("users")
                .select("id")
                .eq("role", "super_admin")
                .neq("id", str(user_id))
                .limit(1)
                .execute()
                .data
                or []
            )
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Es kann nur einen Super-Admin geben. Bitte zuerst den "
                        "bestehenden Super-Admin demoten."
                    ),
                )
        rows = (
            client.table("users")
            .update({"role": payload.role})
            .eq("id", str(user_id))
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None

    updated = await run_in_threadpool(_do)
    if not updated:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden.")
    return {"id": updated["id"], "role": updated["role"]}
