import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.core.config import settings
from app.db.supabase_client import get_service_client

router = APIRouter(prefix="/api/calls", tags=["calls"])

_LIST_SELECT = (
    "id, elevenlabs_conversation_id, caller_number, summary_title, direction, "
    "duration_seconds, started_at, status, data_collection, customer_id, "
    "customers(full_name)"
)


def _list(org_id: str, limit: int, offset: int, customer_id: str | None) -> dict:
    client = get_service_client()
    query = (
        client.table("calls")
        .select(_LIST_SELECT, count="exact")
        .eq("org_id", org_id)
    )
    if customer_id:
        query = query.eq("customer_id", customer_id)
    res = (
        query.order("started_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return {"calls": res.data or [], "total": res.count or 0}


def _detail(org_id: str, call_id: str) -> dict | None:
    client = get_service_client()
    rows = (
        client.table("calls")
        .select("*, customers(full_name, phone, email, customer_number)")
        .eq("org_id", org_id)
        .eq("id", call_id)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


@router.get("")
async def list_calls(
    limit: int = 50,
    offset: int = 0,
    customer_id: str | None = None,
    user: CurrentUser = Depends(require_org),
) -> dict:
    return await run_in_threadpool(_list, user.org_id, limit, offset, customer_id)


@router.get("/{call_id}")
async def get_call(call_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    call = await run_in_threadpool(_detail, user.org_id, call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    return call


def _ensure_inquiry(org_id: str, call_id: str) -> dict | None:
    from app.services.inquiries import ensure_call_inquiry

    call = _detail(org_id, call_id)
    if not call:
        return None
    return ensure_call_inquiry(get_service_client(), org_id, call)


@router.post("/{call_id}/inquiry")
async def ensure_call_inquiry_route(
    call_id: str, user: CurrentUser = Depends(require_org)
) -> dict:
    inquiry = await run_in_threadpool(_ensure_inquiry, user.org_id, call_id)
    if inquiry is None:
        raise HTTPException(status_code=404, detail="Call not found")
    return inquiry


@router.get("/{call_id}/audio")
async def get_call_audio(call_id: str, user: CurrentUser = Depends(require_org)):
    """Fetch the recording on demand from ElevenLabs by conversation_id."""
    call = await run_in_threadpool(_detail, user.org_id, call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    conversation_id = call.get("elevenlabs_conversation_id")
    if not conversation_id:
        raise HTTPException(status_code=404, detail="No conversation id for this call")
    if not settings.elevenlabs_api_key:
        raise HTTPException(status_code=503, detail="ElevenLabs API key not configured")

    url = f"https://api.elevenlabs.io/v1/convai/conversations/{conversation_id}/audio"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers={"xi-api-key": settings.elevenlabs_api_key})
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502, detail=f"Audio unavailable ({resp.status_code})"
        )
    return Response(content=resp.content, media_type="audio/mpeg")
