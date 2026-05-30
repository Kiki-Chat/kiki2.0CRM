"""Place outbound calls via ElevenLabs' native Twilio integration (P1).

ElevenLabs is the controller for outbound: a single authenticated POST places
the call on the Twilio number already linked to the agent. There is NO separate
Twilio dial / TwiML / media-stream layer — that integration is auto-configured
on the ElevenLabs side when the number is imported and linked.

    POST /v1/convai/twilio/outbound-call
    → 200 {"success": true, "conversation_id": "...", "callSid": "..."}
"""
from __future__ import annotations

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

EL_BASE = "https://api.elevenlabs.io"
_OUTBOUND_PATH = "/v1/convai/twilio/outbound-call"
_TIMEOUT = 30.0


class OutboundCallError(Exception):
    """Raised when ElevenLabs fails to place the outbound call."""


def place_outbound_call(
    *,
    agent_id: str,
    agent_phone_number_id: str,
    to_number: str,
    dynamic_variables: dict | None = None,
    conversation_config_override: dict | None = None,
    call_recording_enabled: bool = True,
) -> dict:
    """Place a single outbound call via the org's linked Twilio number.

    Returns the ElevenLabs JSON body (``{"success", "conversation_id",
    "callSid"}``). Raises ``OutboundCallError`` on any non-200 / success=false.

    ``dynamic_variables`` carry the structured ID/occasion layer (outboundCallId,
    anlassTyp, kundeId, referenzId, voicemailMessage, …). ``conversation_config_override``
    is the Path A per-call override — ``{"agent": {"first_message", "language",
    "prompt": {"prompt"}}}`` — that swaps in the occasion-specific, server-rendered
    German opener + system prompt WITHOUT touching the stored agent config. Both
    ride inside the same ``conversation_initiation_client_data`` object, which the
    Twilio outbound-call endpoint accepts (verified against the API reference). The
    agent's Security → Overrides must whitelist prompt + first_message + language
    (verified enabled on the safe agent).
    """
    if not agent_id:
        raise OutboundCallError("missing agent_id")
    if not agent_phone_number_id:
        raise OutboundCallError(
            "missing agent_phone_number_id — run sync-agent-config to capture "
            "the org's ElevenLabs phone_number_id"
        )
    if not to_number:
        raise OutboundCallError("missing to_number")

    body: dict = {
        "agent_id": agent_id,
        "agent_phone_number_id": agent_phone_number_id,
        "to_number": to_number,
        "call_recording_enabled": call_recording_enabled,
    }
    cicd: dict = {}
    if dynamic_variables:
        cicd["dynamic_variables"] = dynamic_variables
    if conversation_config_override:
        cicd["conversation_config_override"] = conversation_config_override
    if cicd:
        body["conversation_initiation_client_data"] = cicd

    with httpx.Client(base_url=EL_BASE, timeout=_TIMEOUT) as c:
        r = c.post(
            _OUTBOUND_PATH,
            headers={
                "xi-api-key": settings.elevenlabs_api_key,
                "Content-Type": "application/json",
            },
            json=body,
        )
    if r.status_code != 200:
        raise OutboundCallError(
            f"outbound-call failed: {r.status_code} {r.text[:300]}"
        )
    data = r.json()
    if data.get("success") is False:
        raise OutboundCallError(f"outbound-call returned success=false: {data}")
    logger.info(
        "outbound call placed agent=%s to=%s conversation_id=%s",
        agent_id, to_number, data.get("conversation_id"),
    )
    return data
