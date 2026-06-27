"""Kiki copilot endpoints. Mounted ONLY when settings.copilot_enabled (see main.py),
so the surface doesn't exist until the flag is switched on.

  POST /api/copilot/chat     — one assistant turn (reads execute; writes are proposed)
  POST /api/copilot/confirm  — execute a single user-confirmed write tool

Auth = require_org (any org member); per-tool roles gate sensitive operations.
Non-streaming JSON for now; SSE token streaming + conversation persistence next.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.services.ai import client as ai_client
from app.services.copilot.orchestrator import run_turn
from app.services.copilot.tools import get_tool
from app.services.ratelimit import enforce_rate_limit

router = APIRouter(prefix="/api/copilot", tags=["copilot"])


class ChatRequest(BaseModel):
    message: str
    history: list[dict] | None = None
    conversation_id: str | None = None


class ConfirmRequest(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    conversation_id: str | None = None


def _require_ai() -> None:
    if not ai_client.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="KI-Assistent ist nicht konfiguriert.",
        )


def _valid_uuid(value: str | None) -> bool:
    """PostgREST rejects non-UUID values against uuid columns with a 500-causing
    APIError — validate up front so junk ids get a clean 404 instead."""
    import uuid as _uuid

    try:
        _uuid.UUID(str(value))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def _audit(
    user: CurrentUser, tool_name: str, args: dict, result: Any,
    conversation_id: str | None = None,
) -> None:
    """Best-effort write audit. Fail-open (table may not exist yet in Phase 0).
    conversation_id links the executed write back to the chat that produced it
    (the 0042 column existed but was never populated — audit 2026-06-11)."""
    try:
        status_str = "error" if isinstance(result, dict) and result.get("error") else "ok"
        get_service_client().table("copilot_action_audit").insert(
            {
                "org_id": user.org_id,
                "user_id": user.id,
                "tool_name": tool_name,
                "args": args,
                "result_status": status_str,
                "confirmed": True,
                "conversation_id": conversation_id if _valid_uuid(conversation_id) else None,
            }
        ).execute()
    except Exception:  # noqa: BLE001 — audit never breaks the action
        pass


# ─── Conversation persistence (Hey-Kiki chat history) ───────────────────────
def _persist_turn(user: CurrentUser, conversation_id: str | None, message: str, result: dict) -> str | None:
    """Store the user+assistant turn; returns the conversation id. Best-effort —
    a persistence failure must never break the chat response.

    Hardening (audit 2026-06-11):
    - Explicit timestamps (assistant = user + 1ms): the old single-batch insert
      gave both rows an identical created_at, so reload order within a turn was
      nondeterministic (Postgres sort isn't stable) and could flip Q/A.
    - Compensation: if the messages insert fails right after a NEW conversation
      row was created, delete that empty row — it would otherwise sit in the
      history forever as an unopenable blank thread — and return the ORIGINAL
      conversation_id so the client doesn't fragment onto a dead id."""
    from datetime import datetime, timedelta, timezone

    created_new = False
    cid = None
    try:
        client = get_service_client()
        cid = (conversation_id or "").strip() or None
        if cid and not _valid_uuid(cid):
            cid = None
        if cid:
            owned = (
                client.table("copilot_conversations").select("id")
                .eq("id", cid).eq("org_id", user.org_id).eq("user_id", user.id)
                .limit(1).execute().data or []
            )
            if not owned:
                cid = None
        if not cid:
            row = (
                client.table("copilot_conversations")
                .insert({"org_id": user.org_id, "user_id": user.id, "title": message.strip()[:80]})
                .execute().data
            )
            cid = row[0]["id"]
            created_new = True
        t0 = datetime.now(timezone.utc)
        client.table("copilot_messages").insert([
            {
                "conversation_id": cid, "org_id": user.org_id, "role": "user",
                "content": message, "created_at": t0.isoformat(),
            },
            {
                "conversation_id": cid, "org_id": user.org_id, "role": "assistant",
                "content": result.get("content") or "",
                "created_at": (t0 + timedelta(milliseconds=1)).isoformat(),
                # Stored in the pre-existing tool_calls jsonb (0042 schema) —
                # holds the turn's action cards for display-only reload.
                "tool_calls": {
                    "actions": result.get("actions") or [],
                    "client_actions": result.get("client_actions") or [],
                },
            },
        ]).execute()
        client.table("copilot_conversations").update(
            {"updated_at": "now()"}
        ).eq("id", cid).execute()
        return cid
    except Exception:  # noqa: BLE001 — history is a convenience, never a blocker
        if created_new and cid:
            try:  # compensate: don't leave an empty orphan thread behind
                get_service_client().table("copilot_conversations").delete().eq(
                    "id", cid
                ).eq("org_id", user.org_id).execute()
            except Exception:  # noqa: BLE001
                pass
        return conversation_id


@router.post("/chat")
async def chat(payload: ChatRequest, user: CurrentUser = Depends(require_org)) -> dict:
    _require_ai()
    # Every turn is OpenAI spend — bound it per org (audit 2026-06-11: no rate
    # limiting anywhere). 20 turns/min is far above real chat usage.
    enforce_rate_limit("copilot_chat", user.org_id, max_calls=20, per_seconds=60)
    if not (payload.message or "").strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nachricht ist leer.")
    # Monthly AI cost cap — mirrors cases.propose (COP-023).
    from app.services.ai import usage as ai_usage  # noqa: PLC0415 — lazy import mirrors pattern

    if not ai_usage.within_cap(user.org_id):
        raise HTTPException(
            status_code=429,
            detail="Das monatliche KI-Budget Ihrer Organisation ist erreicht — "
            "der KI-Assistent ist bis zum Monatswechsel pausiert.",
        )
    result = await run_in_threadpool(run_turn, user, payload.message, history=payload.history)
    cid = await run_in_threadpool(_persist_turn, user, payload.conversation_id, payload.message, result)
    return {**result, "conversation_id": cid}


@router.get("/conversations")
async def list_conversations(
    limit: int = 30, offset: int = 0, user: CurrentUser = Depends(require_org)
) -> dict:
    """History list, newest first. Paginated (audit 2026-06-11: the hard 30-row
    cap made older chats invisible AND undeletable — the trash button only
    exists on visible rows)."""
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))

    def _do() -> dict:
        rows = (
            get_service_client().table("copilot_conversations")
            .select("id, title, created_at, updated_at")
            .eq("org_id", user.org_id).eq("user_id", user.id)
            .order("updated_at", desc=True)
            .range(offset, offset + limit)  # one extra row → has_more signal
            .execute().data or []
        )
        has_more = len(rows) > limit
        return {"conversations": rows[:limit], "has_more": has_more, "offset": offset}

    return await run_in_threadpool(_do)


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    # Non-UUID ids made PostgREST raise → 500; a junk id is just "not found".
    if not _valid_uuid(conversation_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat nicht gefunden.")

    def _do() -> dict | None:
        client = get_service_client()
        convo = (
            client.table("copilot_conversations").select("id, title")
            .eq("id", conversation_id).eq("org_id", user.org_id).eq("user_id", user.id)
            .limit(1).execute().data or []
        )
        if not convo:
            return None
        # Keep the NEWEST 200 (audit 2026-06-11: ascending+limit kept the OLDEST
        # 200 and silently dropped the recent exchange — and the model history
        # was rebuilt from that, so the AI lost the newest context too). Fetch
        # newest-first, then restore chronological order for display. `id` is
        # the tiebreaker for legacy same-timestamp turn pairs.
        messages = (
            client.table("copilot_messages")
            .select("id, role, content, tool_calls, created_at")
            .eq("conversation_id", conversation_id)
            .order("created_at", desc=True).order("id", desc=True)
            .limit(200).execute().data or []
        )
        messages.reverse()
        # Frontend contract: the action payload is exposed as `actions`.
        for m in messages:
            m["actions"] = m.pop("tool_calls", None)
        return {"conversation": convo[0], "messages": messages, "truncated": len(messages) >= 200}

    result = await run_in_threadpool(_do)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat nicht gefunden.")
    return result


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    if not _valid_uuid(conversation_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat nicht gefunden.")

    def _do() -> bool:
        res = (
            get_service_client().table("copilot_conversations").delete()
            .eq("id", conversation_id).eq("org_id", user.org_id).eq("user_id", user.id)
            .execute()
        )
        return bool(res.data)

    if not await run_in_threadpool(_do):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat nicht gefunden.")
    return {"success": True}


@router.post("/confirm")
async def confirm(payload: ConfirmRequest, user: CurrentUser = Depends(require_org)) -> dict:
    _require_ai()
    tool = get_tool(payload.tool)
    if tool is None or not tool.allowed_for(user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Aktion nicht erlaubt.")
    # Plan gating — refuse a gated tool (402) when the org's plan lacks the feature, so a
    # confirmed write can't bypass the entitlement locks either.
    from app.services.copilot.tools import FEATURE_BY_TOOL  # noqa: PLC0415
    from app.services.entitlements import FEATURE_MIN_PLAN, org_has_feature  # noqa: PLC0415

    gated = FEATURE_BY_TOOL.get(payload.tool)
    if gated and not org_has_feature(user.org_id, user.role, gated):
        raise HTTPException(
            status_code=402,
            detail={"error": "feature_locked", "feature": gated, "min_plan": FEATURE_MIN_PLAN.get(gated)},
        )
    if not tool.needs_confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Diese Aktion erfordert keine Bestätigung.",
        )
    # Monthly AI cost cap — role/validation guards run first (precedence).
    from app.services.ai import usage as ai_usage  # noqa: PLC0415 — lazy import mirrors pattern

    if not ai_usage.within_cap(user.org_id):
        raise HTTPException(
            status_code=429,
            detail="Das monatliche KI-Budget Ihrer Organisation ist erreicht — "
            "der KI-Assistent ist bis zum Monatswechsel pausiert.",
        )
    result = await run_in_threadpool(tool.run, user, payload.args or {})
    _audit(user, tool.name, payload.args or {}, result, conversation_id=payload.conversation_id)
    return {"ok": True, "result": result}
