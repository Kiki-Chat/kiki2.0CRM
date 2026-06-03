"""Copilot agentic loop.

run_turn(user, history, message) → one assistant turn:
  1. system prompt (CRM-only guardrail) + prior turns + the new user message
  2. model decides; READ tool calls execute immediately (org/role-scoped)
  3. WRITE tool calls are NOT executed — they're returned as proposed actions the
     UI must confirm (then POST /api/copilot/confirm runs them)
  4. loop until a final text answer (bounded by max_steps)

Non-streaming for Phase 0/1 (fully testable via the injected fake AI client);
token streaming + conversation persistence layer on next.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.api.deps import CurrentUser
from app.core.config import settings
from app.services.ai import client as ai_client
from app.services.ai import usage
from app.services.copilot.prompt import system_prompt
from app.services.copilot.tools import get_tool, schemas_for_role

log = logging.getLogger(__name__)

_ALLOWED_HISTORY_ROLES = {"user", "assistant"}


def _clean_history(history: list[dict] | None) -> list[dict]:
    """Keep only plain user/assistant turns from client-supplied history — never
    trust client 'system'/'tool' messages (would let the UI forge tool results)."""
    out: list[dict] = []
    for m in history or []:
        if isinstance(m, dict) and m.get("role") in _ALLOWED_HISTORY_ROLES and m.get("content"):
            out.append({"role": m["role"], "content": str(m["content"])})
    return out[-20:]  # cap context


def _log_usage(user: CurrentUser, resp: Any) -> None:
    u = getattr(resp, "usage", None)
    if u is None:
        return
    usage.log_usage(
        org_id=user.org_id,
        user_id=user.id,
        feature="copilot",
        model=settings.openai_copilot_model,
        prompt_tokens=getattr(u, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(u, "completion_tokens", 0) or 0,
    )


def run_turn(
    user: CurrentUser,
    message: str,
    *,
    history: list[dict] | None = None,
    max_steps: int = 5,
) -> dict:
    """Run one copilot turn. Returns
    ``{"content": str, "actions": [proposed_write, ...]}``."""
    convo: list[dict] = [{"role": "system", "content": system_prompt(user)}]
    convo += _clean_history(history)
    convo.append({"role": "user", "content": message})

    tool_schemas = schemas_for_role(user.role)
    proposed: list[dict] = []
    client_actions: list[dict] = []
    last_text = ""

    for _ in range(max_steps):
        resp = ai_client.chat(convo, tools=tool_schemas, tool_choice="auto")
        _log_usage(user, resp)
        msg = resp.choices[0].message
        last_text = msg.content or last_text
        tool_calls = getattr(msg, "tool_calls", None)

        if not tool_calls:
            return {"content": msg.content or "", "actions": proposed, "client_actions": client_actions}

        # Echo the assistant's tool-call message back into the conversation.
        convo.append(
            {
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ],
            }
        )

        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except (TypeError, ValueError):
                args = {}
            tool = get_tool(name)

            if tool is None or not tool.allowed_for(user.role):
                result: Any = {"error": "Tool nicht verfügbar."}
            elif tool.client_side:
                # Executed by the frontend (e.g. navigation) — return as a directive.
                client_actions.append({"tool": tool.name, "args": args})
                result = {"status": "wird im Browser ausgeführt", "route": args.get("route")}
            elif tool.needs_confirm:
                # Do NOT execute writes — collect for explicit user confirmation.
                proposed.append(
                    {"tool": tool.name, "args": args, "kind": tool.kind, "description": tool.description}
                )
                result = {"status": "awaiting_confirmation",
                          "message": "Aktion vorbereitet — wartet auf Bestätigung der Person."}
            else:
                try:
                    result = tool.run(user, args)
                except Exception as exc:  # noqa: BLE001 — a tool error never crashes the turn
                    log.warning("copilot tool %s failed: %s", name, exc)
                    result = {"error": "Tool-Aufruf fehlgeschlagen."}

            convo.append(
                {"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, default=str)}
            )

    # Hit max_steps — return whatever text we have plus any proposed actions.
    return {"content": last_text, "actions": proposed, "client_actions": client_actions}
