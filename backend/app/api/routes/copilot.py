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


def _audit(user: CurrentUser, tool_name: str, args: dict, result: Any) -> None:
    """Best-effort write audit. Fail-open (table may not exist yet in Phase 0)."""
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
            }
        ).execute()
    except Exception:  # noqa: BLE001 — audit never breaks the action
        pass


# ─── Conversation persistence (Hey-Kiki chat history) ───────────────────────
def _persist_turn(user: CurrentUser, conversation_id: str | None, message: str, result: dict) -> str | None:
    """Store the user+assistant turn; returns the conversation id. Best-effort —
    a persistence failure must never break the chat response."""
    try:
        client = get_service_client()
        cid = (conversation_id or "").strip() or None
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
        client.table("copilot_messages").insert([
            {"conversation_id": cid, "org_id": user.org_id, "role": "user", "content": message},
            {
                "conversation_id": cid, "org_id": user.org_id, "role": "assistant",
                "content": result.get("content") or "",
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
        return conversation_id


@router.post("/chat")
async def chat(payload: ChatRequest, user: CurrentUser = Depends(require_org)) -> dict:
    _require_ai()
    if not (payload.message or "").strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nachricht ist leer.")
    result = await run_in_threadpool(run_turn, user, payload.message, history=payload.history)
    cid = await run_in_threadpool(_persist_turn, user, payload.conversation_id, payload.message, result)
    return {**result, "conversation_id": cid}


@router.get("/conversations")
async def list_conversations(user: CurrentUser = Depends(require_org)) -> dict:
    def _do() -> dict:
        rows = (
            get_service_client().table("copilot_conversations")
            .select("id, title, created_at, updated_at")
            .eq("org_id", user.org_id).eq("user_id", user.id)
            .order("updated_at", desc=True).limit(30).execute().data or []
        )
        return {"conversations": rows}

    return await run_in_threadpool(_do)


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    def _do() -> dict | None:
        client = get_service_client()
        convo = (
            client.table("copilot_conversations").select("id, title")
            .eq("id", conversation_id).eq("org_id", user.org_id).eq("user_id", user.id)
            .limit(1).execute().data or []
        )
        if not convo:
            return None
        messages = (
            client.table("copilot_messages")
            .select("id, role, content, tool_calls, created_at")
            .eq("conversation_id", conversation_id)
            .order("created_at").limit(200).execute().data or []
        )
        # Frontend contract: the action payload is exposed as `actions`.
        for m in messages:
            m["actions"] = m.pop("tool_calls", None)
        return {"conversation": convo[0], "messages": messages}

    result = await run_in_threadpool(_do)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat nicht gefunden.")
    return result


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, user: CurrentUser = Depends(require_org)) -> dict:
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
    if not tool.needs_confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Diese Aktion erfordert keine Bestätigung.",
        )
    result = await run_in_threadpool(tool.run, user, payload.args or {})
    _audit(user, tool.name, payload.args or {}, result)
    return {"ok": True, "result": result}
