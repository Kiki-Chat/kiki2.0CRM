"""ElevenLabs Conversation Initiation Webhook.

Fires when a Twilio/SIP call connects, before the agent speaks. We look up the
caller by phone in the customers table and return matching data as dynamic
variables injected into the conversation. No match → empty values, and the agent
falls back to hk_identifyCustomer.
"""

from app.db.supabase_client import get_service_client
from app.services.common import format_address


def _empty_vars() -> dict:
    return {
        "customer_found": False,
        "customer_id": "",
        "customer_name": "",
        "customer_number": "",
        "customer_address": "",
        "customer_email": "",
    }


def conversation_init(org_id: str, caller_id: str | None) -> dict:
    variables = _empty_vars()

    if caller_id:
        client = get_service_client()
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

    return {
        "type": "conversation_initiation_client_data",
        "dynamic_variables": variables,
    }
