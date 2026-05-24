"""transferCall tool.

Returns the configured forwarding number for emergency vs. staff transfers from
agent_configs. NOTE: the actual call redirect (Twilio) is wired in a later phase;
for now we return the target number + spoken message, which is what ElevenLabs
needs to perform a native transfer.
"""

from app.db.supabase_client import get_service_client
from app.schemas.tools import TransferCallRequest


def transfer_call(org_id: str, payload: TransferCallRequest) -> dict:
    client = get_service_client()
    rows = (
        client.table("agent_configs")
        .select("forwarding_number, incoming_forwarding_number")
        .eq("org_id", org_id)
        .limit(1)
        .execute()
        .data
    )
    cfg = rows[0] if rows else {}

    emergency = bool(payload.emergency)
    number = cfg.get("forwarding_number") if emergency else cfg.get("incoming_forwarding_number")

    if not number:
        return {
            "success": False,
            "error": "TRANSFER_UNAVAILABLE",
            "message": "Im Moment ist niemand für eine Weiterleitung erreichbar. "
            "Ich nehme gern eine Nachricht auf.",
        }

    if emergency:
        return {
            "success": True,
            "transferType": "EMERGENCY",
            "transferNumber": number,
            "message": "Ich verbinde Sie jetzt mit unserem Notdienst. Bitte bleiben "
            "Sie in der Leitung.",
        }
    return {
        "success": True,
        "transferType": "STAFF",
        "transferNumber": number,
        "message": "Ich verbinde Sie jetzt mit einem Mitarbeiter. Einen Moment bitte.",
    }
