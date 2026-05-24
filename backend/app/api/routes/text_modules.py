from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.schemas.admin import TextModuleUpsert

router = APIRouter(prefix="/api/text-modules", tags=["text-modules"])

_COLS = "id, name, category, content, sort_order, is_default, created_at"


def _list(org_id: str) -> list[dict]:
    client = get_service_client()
    return (
        client.table("text_modules")
        .select(_COLS)
        .eq("org_id", org_id)
        .order("sort_order")
        .execute()
        .data
        or []
    )


@router.get("")
async def list_modules(user: CurrentUser = Depends(require_org)) -> list[dict]:
    return await run_in_threadpool(_list, user.org_id)


def _defaults(org_id: str) -> dict:
    client = get_service_client()
    rows = (
        client.table("text_modules")
        .select("category, content, name")
        .eq("org_id", org_id)
        .eq("is_default", True)
        .order("sort_order")
        .execute()
        .data
        or []
    )
    # One default content per category (first wins).
    out: dict[str, str] = {}
    for r in rows:
        cat = (r.get("category") or "").lower()
        if cat and cat not in out:
            out[cat] = r.get("content") or ""
    return out


@router.get("/defaults")
async def module_defaults(user: CurrentUser = Depends(require_org)) -> dict:
    return await run_in_threadpool(_defaults, user.org_id)


def _create(org_id: str, payload: TextModuleUpsert) -> dict:
    client = get_service_client()
    row = payload.model_dump(exclude_unset=True)
    row["org_id"] = org_id
    row.setdefault("name", "Textbaustein")
    row.setdefault("category", "sonstiges")
    row.setdefault("content", "")
    return client.table("text_modules").insert(row).execute().data[0]


@router.post("")
async def create_module(
    payload: TextModuleUpsert, user: CurrentUser = Depends(require_org)
) -> dict:
    return await run_in_threadpool(_create, user.org_id, payload)


def _update(org_id: str, module_id: str, payload: TextModuleUpsert) -> dict | None:
    client = get_service_client()
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        rows = (
            client.table("text_modules").select(_COLS).eq("org_id", org_id)
            .eq("id", module_id).limit(1).execute().data
        )
        return rows[0] if rows else None
    res = (
        client.table("text_modules").update(fields).eq("org_id", org_id)
        .eq("id", module_id).execute()
    )
    return res.data[0] if res.data else None


@router.patch("/{module_id}")
async def update_module(
    module_id: str, payload: TextModuleUpsert, user: CurrentUser = Depends(require_org)
) -> dict:
    row = await run_in_threadpool(_update, user.org_id, module_id, payload)
    if not row:
        raise HTTPException(status_code=404, detail="Text module not found")
    return row


@router.delete("/{module_id}")
async def delete_module(module_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    def _delete() -> bool:
        client = get_service_client()
        res = (
            client.table("text_modules").delete().eq("org_id", user.org_id)
            .eq("id", module_id).execute()
        )
        return bool(res.data)

    ok = await run_in_threadpool(_delete)
    if not ok:
        raise HTTPException(status_code=404, detail="Text module not found")
    return {"success": True}
