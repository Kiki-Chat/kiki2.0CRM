"""ElevenLabs Conversation Initiation Webhook.

Fires when a Twilio/SIP call connects, before the agent speaks. We look up the
caller by phone in the customers table and return matching data as dynamic
variables injected into the conversation. No match → empty values, and the agent
falls back to hk_identifyCustomer.

Topic 20: if the org configured time-based welcome variants
(``agent_configs.welcome_messages``), we also return a per-call
``conversation_config_override.agent.first_message`` matching the current Berlin
time — so the greeting changes by time of day. No variant matches → no override
(the agent's stored first_message stays).
"""

import logging

from app.core.config import settings
from app.db.supabase_client import get_service_client
from app.services.common import format_address, now_berlin

logger = logging.getLogger(__name__)


def _empty_vars() -> dict:
    return {
        "customer_found": False,
        "customer_id": "",
        "customer_name": "",
        "customer_number": "",
        "customer_address": "",
        "customer_email": "",
    }


def _hhmm_to_min(value) -> int | None:
    try:
        h, m = str(value).split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _in_window(now_min: int, frm: int | None, to: int | None) -> bool:
    if frm is None or to is None or frm == to:
        return False
    if frm < to:
        return frm <= now_min < to
    return now_min >= frm or now_min < to  # window wraps midnight (e.g. 21:00–05:00)


def _pick_welcome_message(client, org_id: str) -> str | None:
    """The org's time-matched welcome variant, or None. Best-effort."""
    try:
        rows = (
            client.table("agent_configs")
            .select("welcome_messages")
            .eq("org_id", org_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        variants = (rows[0].get("welcome_messages") if rows else None) or []
        if not isinstance(variants, list) or not variants:
            return None
        now = now_berlin()
        now_min = now.hour * 60 + now.minute
        for v in variants:
            if not isinstance(v, dict):
                continue
            msg = (v.get("message") or "").strip()
            if msg and _in_window(now_min, _hhmm_to_min(v.get("from")), _hhmm_to_min(v.get("to"))):
                return msg
        return None
    except Exception:  # noqa: BLE001 — never break the webhook over a greeting
        logger.warning("welcome-variant lookup failed for org %s", org_id)
        return None


def conversation_init(org_id: str, caller_id: str | None) -> dict:
    client = get_service_client()
    variables = _empty_vars()

    if caller_id:
        rows = (
            client.table("customers")
            .select("id, full_name, phone, email, customer_number, address")
            .eq("org_id", org_id)
            .eq("phone", caller_id)
            .limit(1)
            .execute()
            .data
        )
        if rows:
            c = rows[0]
            variables = {
                "customer_found": True,
                "customer_id": c["id"],
                "customer_name": c.get("full_name") or "",
                "customer_number": c.get("customer_number") or "",
                "customer_address": format_address(c.get("address")) or "",
                "customer_email": c.get("email") or "",
            }

    # The shared agent's voicemail_detection tool references {{voicemailMessage}},
    # which only the OUTBOUND dispatch supplies — inbound left it undefined, so a
    # (mis)fire on an inbound leg would play nothing or the literal placeholder
    # (audit 2026-06-11). Always provide a sensible company-aware default here.
    try:
        org_row = (
            client.table("organizations").select("name")
            .eq("id", org_id).limit(1).execute().data or [{}]
        )[0]
        company = (org_row.get("name") or "").strip() or "uns"
    except Exception:  # noqa: BLE001
        company = "uns"
    variables["voicemailMessage"] = (
        f"Guten Tag, hier ist der Telefonassistent von {company}. Wir können deinen "
        "Anruf gerade nicht persönlich entgegennehmen. Bitte hinterlasse deinen "
        "Namen und dein Anliegen — wir melden uns schnellstmöglich zurück. Auf Wiederhören!"
    )

    result: dict = {
        "type": "conversation_initiation_client_data",
        # Tells ElevenLabs which ENVIRONMENT this call runs in, so a SHARED tool whose
        # URL host is {{system__env_api_host}} resolves to THIS backend (uat → UAT
        # host, production → prod host). One tool, attached to every agent, routed by
        # environment — no per-environment tool duplication. settings.el_environment
        # is set per deployment (EL_ENVIRONMENT=uat|production).
        "environment": settings.el_environment,
        "dynamic_variables": variables,
    }
    greeting = _pick_welcome_message(client, org_id)
    if greeting:
        result["conversation_config_override"] = {"agent": {"first_message": greeting}}
    return result
