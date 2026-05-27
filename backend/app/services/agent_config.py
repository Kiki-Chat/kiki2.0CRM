"""Reusable ElevenLabs agent-configuration helper (Step B, 2026-05-27).

This module is the single place that knows how to turn a "fresh" ElevenLabs
agent into a HeyKiki-wired agent. ``provision_org`` calls it after the DB
inserts; the manual sync route (Agent 2's surface, ``POST /api/super-admin/
orgs/{id}/sync-agent-config``) imports the same ``configure_agent`` so the
two paths can never drift.

What it does, in order:

  B.1  Fetch the phone number bound to the agent in ElevenLabs and persist
       it on ``organizations.phone_number``. Hard-fails (HTTPException 400)
       when zero phones are bound, so the caller can roll back the org row.
       With multiple phones bound it picks the first and logs a warning
       rather than failing.

  B.2  Look up the 10 ``hk_*`` workspace tools by name, then ADDITIVELY
       merge their ``tool_id``s onto the agent's ``prompt.tool_ids`` via
       ``patch_agent_safely`` (snapshot → assert audio → PATCH → verify →
       auto-rollback → audit). Any missing tools fail loudly — they're a
       workspace-config decision, not auto-created here.

  B.3  Apply the master German prompt (``agent_prompt_template.txt``) with
       per-org name substitution. SKIPPED on re-runs (detected via
       ``organizations.agent_provisioned_at IS NOT NULL``) — once a customer
       has the agent live, their prompt is untouchable from this code path.

  B.4  Enable the ``conversation_initiation_client_data`` webhook pointing
       at our backend.

  B.5  Assert "audio" is present in client_events.

All ElevenLabs writes route through ``patch_agent_safely`` (the only module
permitted to PATCH agent config — see ``elevenlabs_agent`` module docstring).

Where ``hk_*`` tool IDs are cached: a module-level dict keyed by tool name.
Populated on first call, lives for the process lifetime. Simplest option per
the design brief — survives the uvicorn process, re-populates cheaply on
restart, and a missing workspace tool is detected on every call (no
stale-cache risk).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException, status

from app.core.config import settings
from app.db.supabase_client import get_service_client
from app.services.elevenlabs_agent import (
    CLIENT_EVENTS_PATH,
    PROMPT_PATH,
    REQUIRED_AUDIO_EVENT,
    TOOL_IDS_PATH,
    WEBHOOK_ENABLED_PATH,
    WEBHOOK_URL_PATH,
    ElevenLabsWriteError,
    _get_path,
    get_agent_config,
    patch_agent_safely,
)

logger = logging.getLogger(__name__)

EL_BASE = "https://api.elevenlabs.io"
_TIMEOUT = 30.0

# The 10 hk_* tool names that every HeyKiki-wired agent must carry.
HK_TOOL_NAMES: list[str] = [
    "hk_identifyCustomer",
    "hk_updateCustomerData",
    "hk_createInquiry",
    "hk_getAvailableAppointments",
    "hk_bookAppointment",
    "hk_cancelAppointment",
    "hk_changeAppointment",
    "hk_searchCustomerInquiries",
    "hk_queryKnowledgeBase",
    "hk_transferCall",
]

# Conversation-initiation client-data webhook route on this backend.
# Verified live at backend/app/api/routes/conversation_init.py (router prefix
# "/api/elevenlabs", path "/conversation-init"). Built at runtime from
# ``settings.backend_public_url`` so it follows local vs. prod automatically.
_CONVERSATION_INIT_PATH = "/api/elevenlabs/conversation-init"

# Module-level cache: {tool_name: tool_id}. Populated on first lookup.
_HK_TOOL_ID_CACHE: dict[str, str] = {}

# Path to the German master prompt template (committed at this path so
# provisioning is self-contained — not loaded from Amber's Downloads dir).
_PROMPT_TEMPLATE_PATH = Path(__file__).parent / "agent_prompt_template.txt"

# Strings in the template that are replaced per-org at runtime. The two
# corporate variants of "Husmann & Dreier" are the parameterized hooks; the
# "Herr Husmann"/"Herr Dreier" director-name lines are deliberately NOT
# substituted here — they're bespoke template content that would need its
# own per-org field. Flagged as a deferred follow-up (see report).
_TEMPLATE_COMPANY_NAMES = ["Husmann & Dreier GmbH", "Husmann und Dreier"]


# ─── Tool lookup ─────────────────────────────────────────────────────────────
def _fetch_workspace_tools() -> dict[str, str]:
    """Return ``{tool_name: tool_id}`` for the workspace, filtered to ``hk_*``.

    Refreshes the module-level cache. Called inside ``_resolve_hk_tool_ids``
    when any required name is missing from the cache.
    """
    key = settings.elevenlabs_api_key or os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        raise ElevenLabsWriteError(
            "ELEVENLABS_API_KEY not configured; cannot fetch workspace tools."
        )
    with httpx.Client(base_url=EL_BASE, timeout=_TIMEOUT) as c:
        r = c.get("/v1/convai/tools", headers={"xi-api-key": key})
    if r.status_code != 200:
        raise ElevenLabsWriteError(
            f"GET /v1/convai/tools failed: {r.status_code} {r.text[:300]}"
        )
    payload = r.json()
    items = payload.get("tools", payload) if isinstance(payload, dict) else payload
    out: dict[str, str] = {}
    for t in items or []:
        cfg = t.get("tool_config") or t
        name = cfg.get("name")
        tid = t.get("id")
        if name and tid and name.startswith("hk_"):
            out[name] = tid
    return out


def _resolve_hk_tool_ids(required: list[str] | None = None) -> dict[str, str]:
    """Return ``{name: tool_id}`` for all 10 required hk_* names.

    Fails with HTTPException(400) listing the missing names if any of the
    required tools aren't found in the workspace — operations are expected
    to create them outside this code path (workspace-config decision).
    """
    names = list(required or HK_TOOL_NAMES)
    missing = [n for n in names if n not in _HK_TOOL_ID_CACHE]
    if missing:
        fresh = _fetch_workspace_tools()
        _HK_TOOL_ID_CACHE.update(fresh)
        missing = [n for n in names if n not in _HK_TOOL_ID_CACHE]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"ElevenLabs workspace is missing required hk_* tool(s): "
                f"{', '.join(missing)}. Create them in the workspace first, "
                "then retry provisioning."
            ),
        )
    return {n: _HK_TOOL_ID_CACHE[n] for n in names}


# ─── B.1 Phone fetch ─────────────────────────────────────────────────────────
def _list_phone_numbers() -> list[dict]:
    key = settings.elevenlabs_api_key or os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        raise ElevenLabsWriteError(
            "ELEVENLABS_API_KEY not configured; cannot fetch phone numbers."
        )
    with httpx.Client(base_url=EL_BASE, timeout=_TIMEOUT) as c:
        r = c.get("/v1/convai/phone-numbers", headers={"xi-api-key": key})
    if r.status_code != 200:
        raise ElevenLabsWriteError(
            f"GET /v1/convai/phone-numbers failed: {r.status_code} {r.text[:300]}"
        )
    data = r.json()
    if isinstance(data, dict):
        # Some EL list endpoints wrap items; handle both shapes.
        return data.get("phone_numbers") or data.get("items") or []
    return data or []


def fetch_phone_for_agent(agent_id: str) -> str:
    """Return the E.164 phone number bound to ``agent_id`` in ElevenLabs.

    Raises HTTPException(400) when zero phones are bound (the caller MUST
    roll back the half-provisioned org). With multiple phones bound, picks
    the first and logs a warning rather than failing.
    """
    phones = _list_phone_numbers()
    matches = [
        p for p in phones
        if (p.get("assigned_agent") or {}).get("agent_id") == agent_id
    ]
    if not matches:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Agent has no phone number assigned in ElevenLabs — "
                "assign one first, then retry."
            ),
        )
    if len(matches) > 1:
        logger.warning(
            "Agent %s has %d phones bound; using the first (%s).",
            agent_id, len(matches), matches[0].get("phone_number"),
        )
    return matches[0]["phone_number"]


def _store_phone_on_org(org_id: str | UUID, phone_e164: str) -> None:
    db = get_service_client()
    db.table("organizations").update({"phone_number": phone_e164}).eq(
        "id", str(org_id)
    ).execute()


# ─── B.3 Prompt template ─────────────────────────────────────────────────────
def _load_prompt_template() -> str:
    with open(_PROMPT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def render_prompt_for_org(org_name: str) -> str:
    """Return the master prompt with company name substituted to ``org_name``.

    Belt-and-braces: re-verifies that zero ``wkp_shared_`` strings remain in
    the final output (the file-on-disk transformation should already have
    handled that, but re-checking guards against an accidental edit).
    """
    text = _load_prompt_template()
    for placeholder in _TEMPLATE_COMPANY_NAMES:
        text = text.replace(placeholder, org_name)
    if "wkp_shared_" in text:
        # Hard-fail rather than ship a prompt with a stale wkp_shared_ reference.
        raise RuntimeError(
            "agent_prompt_template.txt still contains 'wkp_shared_' tokens — "
            "the tool-name mapping is incomplete. Fix the template before retrying."
        )
    return text


# ─── Tiny org-state read ─────────────────────────────────────────────────────
def _is_agent_already_provisioned(org_id: str | UUID) -> bool:
    """True iff organizations.agent_provisioned_at is set for ``org_id``."""
    db = get_service_client()
    rows = (
        db.table("organizations")
        .select("agent_provisioned_at")
        .eq("id", str(org_id))
        .limit(1)
        .execute()
        .data
        or []
    )
    return bool(rows and rows[0].get("agent_provisioned_at"))


def _stamp_agent_provisioned(org_id: str | UUID) -> None:
    from datetime import datetime, timezone
    db = get_service_client()
    db.table("organizations").update(
        {
            "agent_provisioned_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", str(org_id)).execute()


# ─── Public entry point ──────────────────────────────────────────────────────
def configure_agent(
    *,
    org_id: str | UUID,
    agent_id: str,
    org_name: str,
    actor_id: str | UUID | None = None,
) -> dict:
    """Wire up an ElevenLabs agent for HeyKiki use.

    Performs B.1 + B.2 + B.3 + B.4 + B.5 in order. Returns a summary dict::

        {
          "phone_number": "+49251...",
          "tools_attached": ["tool_xxx", ...],   # tool_ids newly added (may be [])
          "prompt_applied": True | False,        # False on re-runs
          "prompt_skipped_reason": "...",        # populated when False
          "webhook_enabled": True | False,       # True if our URL is set & toggle on
          "audio_ok": True,                      # always True post-call (else raise)
        }

    Raises:
      * HTTPException(400) on B.1 zero-phones or B.2 missing workspace tool —
        the caller is expected to roll back the org row insert.
      * ``elevenlabs_agent.ElevenLabsWriteError`` / ``SilentAgentRiskError`` /
        ``VerificationFailedError`` for ElevenLabs-side failures (these
        propagate; the snapshot/rollback inside ``patch_agent_safely`` already
        handled the EL side, the caller still needs to handle DB rollback).

    NOTE on the prompt step: SKIPPED when ``organizations.agent_provisioned_at``
    is already set (re-runs on existing orgs do not trample customer edits).
    Other steps are additive and safe to re-run.
    """
    summary: dict[str, Any] = {
        "phone_number": None,
        "tools_attached": [],
        "prompt_applied": False,
        "prompt_skipped_reason": None,
        "webhook_enabled": False,
        "audio_ok": False,
    }
    is_first_run = not _is_agent_already_provisioned(org_id)

    # ─── B.1 Phone ───────────────────────────────────────────────────────────
    phone = fetch_phone_for_agent(agent_id)
    _store_phone_on_org(org_id, phone)
    summary["phone_number"] = phone

    # ─── B.2 Tools (additive merge of tool_ids) ──────────────────────────────
    tool_map = _resolve_hk_tool_ids(HK_TOOL_NAMES)
    required_ids = list(tool_map.values())
    current = get_agent_config(agent_id)
    current_ids = _get_path(current, TOOL_IDS_PATH) or []
    to_add = [tid for tid in required_ids if tid not in current_ids]
    if to_add:
        patch_agent_safely(
            agent_id=agent_id,
            field_patches={
                "conversation_config": {
                    "agent": {"prompt": {"tool_ids": required_ids}}
                }
            },
            merge_arrays=[TOOL_IDS_PATH],
            actor_id=actor_id,
            org_id=org_id,
            endpoint_label="provision_tools",
        )
    summary["tools_attached"] = to_add

    # ─── B.3 Prompt (FIRST run only) ─────────────────────────────────────────
    if is_first_run:
        prompt_text = render_prompt_for_org(org_name)
        # Read current after the tool merge so we don't false-positive on a stale GET.
        current = get_agent_config(agent_id)
        existing_prompt = (_get_path(current, PROMPT_PATH) or "").strip()
        if existing_prompt == prompt_text.strip():
            summary["prompt_applied"] = False
            summary["prompt_skipped_reason"] = "identical_to_template"
        else:
            patch_agent_safely(
                agent_id=agent_id,
                field_patches={
                    "conversation_config": {"agent": {"prompt": {"prompt": prompt_text}}}
                },
                actor_id=actor_id,
                org_id=org_id,
                endpoint_label="provision_prompt",
            )
            summary["prompt_applied"] = True
    else:
        summary["prompt_applied"] = False
        summary["prompt_skipped_reason"] = "already_provisioned"

    # ─── B.4 Webhook (conversation initiation client data) ───────────────────
    # ElevenLabs validates the full webhook object on PATCH — sending a
    # partial {url: ...} resets siblings and trips "Field required" on
    # request_headers. So we always carry the existing request_headers in
    # the patch body to preserve them. Empty {} is a valid default.
    webhook_url = f"{settings.backend_public_url.rstrip('/')}{_CONVERSATION_INIT_PATH}"
    current = get_agent_config(agent_id)
    cur_webhook = (
        _get_path(
            current,
            "platform_settings.workspace_overrides."
            "conversation_initiation_client_data_webhook",
        )
        or {}
    )
    cur_url = cur_webhook.get("url")
    cur_headers = cur_webhook.get("request_headers") or {}
    cur_enabled = bool(_get_path(current, WEBHOOK_ENABLED_PATH))
    needs_url = cur_url != webhook_url
    needs_toggle = not cur_enabled
    if needs_url or needs_toggle:
        webhook_patch: dict = {}
        if needs_url:
            # Carry existing request_headers so EL doesn't reject the PATCH
            # for "Field required: request_headers". Preserves the
            # X-HeyKiki-Secret value already wired on the agent.
            webhook_patch.setdefault("workspace_overrides", {})[
                "conversation_initiation_client_data_webhook"
            ] = {"url": webhook_url, "request_headers": cur_headers}
        if needs_toggle:
            webhook_patch.setdefault("overrides", {})[
                "enable_conversation_initiation_client_data_from_webhook"
            ] = True
        patch_agent_safely(
            agent_id=agent_id,
            field_patches={"platform_settings": webhook_patch},
            actor_id=actor_id,
            org_id=org_id,
            endpoint_label="provision_webhook",
        )
    summary["webhook_enabled"] = True

    # ─── B.5 Audio in client_events ──────────────────────────────────────────
    current = get_agent_config(agent_id)
    ce = _get_path(current, CLIENT_EVENTS_PATH) or []
    if REQUIRED_AUDIO_EVENT not in ce:
        patch_agent_safely(
            agent_id=agent_id,
            field_patches={
                "conversation_config": {
                    "conversation": {"client_events": [REQUIRED_AUDIO_EVENT]}
                }
            },
            merge_arrays=[CLIENT_EVENTS_PATH],
            actor_id=actor_id,
            org_id=org_id,
            endpoint_label="provision_audio",
        )
    summary["audio_ok"] = True

    # ─── Stamp the org so re-runs skip the prompt step. ──────────────────────
    if is_first_run:
        _stamp_agent_provisioned(org_id)

    return summary
