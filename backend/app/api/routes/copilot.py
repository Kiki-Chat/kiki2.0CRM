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


@router.post("/chat")
async def chat(payload: ChatRequest, user: CurrentUser = Depends(require_org)) -> dict:
    _require_ai()
    if not (payload.message or "").strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nachricht ist leer.")
    return await run_in_threadpool(run_turn, user, payload.message, history=payload.history)


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
