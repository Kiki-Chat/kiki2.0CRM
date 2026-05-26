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

from fastapi import APIRouter, Depends, Header, HTTPException
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
@router.get("/orgs")
async def list_orgs(_user: CurrentUser = Depends(require_super_admin)) -> dict:
    """List all organizations (super-admin only)."""
    rows = await run_in_threadpool(_list_orgs)
    return {"orgs": rows}


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
    _user: CurrentUser = Depends(require_super_admin),
) -> ProvisionResponse:
    """Create a new org. Reuses app.services.provisioning.provision_org —
    the same code path as POST /api/heykiki/provision. Super-admin auth
    replaces the master-secret check here, since the caller is already a
    trusted super-admin (no shared-secret round-trip needed)."""
    return await run_in_threadpool(provision_org, payload)


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
    """Promote/demote a user's role. Allowed roles match the existing schema."""
    if payload.role not in ("super_admin", "org_admin", "employee"):
        raise HTTPException(status_code=400, detail="Unbekannte Rolle.")

    def _do() -> dict | None:
        client = get_service_client()
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
