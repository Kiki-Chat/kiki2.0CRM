"""transferCall tool.

Returns the configured forwarding number for emergency vs. staff transfers and,
when Twilio credentials are configured, ALSO redirects the live inbound call to
that number via the Twilio REST API (raw `<Dial>` redirect — the call's TwiML is
updated, which hands the caller off to the human and ends the ElevenLabs leg).

Graceful degradation: if Twilio creds or the call's `_callSid` are missing, we
still return the number + spoken message so the agent at least announces the
transfer.

⚠️ Caveat: the inbound call is held by ElevenLabs' media stream; updating its
TwiML mid-call is the standard Twilio redirect but should be verified on a live
call. The agent prompt announces the transfer BEFORE calling this tool.
"""

import logging

import httpx

from app.core.config import settings
from app.db.supabase_client import get_service_client
from app.schemas.tools import TransferCallRequest

logger = logging.getLogger(__name__)


def _twilio_redirect(call_sid: str | None, to_number: str) -> bool:
    """Redirect a LIVE Twilio call to `to_number` by updating its TwiML to
    `<Dial>`. Returns True iff Twilio accepted the update. Best-effort: never
    raises, and is a no-op when creds or call_sid are missing."""
    sid = settings.twilio_account_sid
    token = settings.twilio_auth_token
    if not (sid and token and call_sid and to_number):
        return False
    twiml = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        f"<Response><Dial>{to_number}</Dial></Response>"
    )
    try:
        resp = httpx.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls/{call_sid}.json",
            data={"Twiml": twiml},
            auth=(sid, token),
            timeout=10.0,
        )
        if resp.status_code in (200, 201):
            return True
        logger.warning(
            "twilio redirect HTTP %s for call %s: %s",
            resp.status_code, call_sid, resp.text[:200],
        )
        return False
    except Exception:  # noqa: BLE001 — never break the tool response
        logger.warning("twilio redirect failed for call %s", call_sid)
        return False


def transfer_call(org_id: str, payload: TransferCallRequest) -> dict:
    client = get_service_client()
    rows = (
        client.table("agent_configs")
        .select("emergency_number, forwarding_number, incoming_forwarding_number")
        .eq("org_id", org_id)
        .limit(1)
        .execute()
        .data
    )
    cfg = rows[0] if rows else {}

    emergency = bool(payload.emergency)
    if emergency:
        # Emergency forwarding target = the Notdienst section's emergency_number
        # (the Telefon "Notdienst-Weiterleitung" field was removed). Fall back to
        # the legacy forwarding_number for orgs that only set the old field.
        number = cfg.get("emergency_number") or cfg.get("forwarding_number")
    else:
        number = cfg.get("incoming_forwarding_number")

    if not number:
        return {
            "success": False,
            "error": "TRANSFER_UNAVAILABLE",
            "message": "Im Moment ist niemand für eine Weiterleitung erreichbar. "
            "Ich nehme gern eine Nachricht auf.",
        }

    # Raw Twilio REST: actually bridge the live call to the human.
    transferred = _twilio_redirect(payload.call_sid, number)

    if emergency:
        return {
            "success": True,
            "transferType": "EMERGENCY",
            "transferNumber": number,
            "transferred": transferred,
            "message": "Ich verbinde Sie jetzt mit unserem Notdienst. Bitte bleiben "
            "Sie in der Leitung.",
        }
    return {
        "success": True,
        "transferType": "STAFF",
        "transferNumber": number,
        "transferred": transferred,
        "message": "Ich verbinde Sie jetzt mit einem Mitarbeiter. Einen Moment bitte.",
    }
