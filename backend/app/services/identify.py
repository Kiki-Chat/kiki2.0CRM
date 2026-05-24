"""identifyCustomer tool logic.

Maps a caller (by Caller-ID, phone, customer number, or address/last name) to an
existing customer record. Response shapes follow hk_tools_payload_reference.md.
The ``message`` field is spoken by the agent, so it is in German (production
language). All DB calls are synchronous; the route runs this in a threadpool.
"""

import re

from app.db.supabase_client import get_service_client
from app.schemas.tools import IdentifyCustomerRequest

_SELECT = "id, full_name, phone, email, customer_number, address"


def _norm_phone(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _format_address(addr) -> str | None:
    if not isinstance(addr, dict):
        return addr if isinstance(addr, str) else None
    street = addr.get("street")
    city = addr.get("city")
    postal = addr.get("postal_code") or addr.get("zip")
    parts = [p for p in [street, " ".join(x for x in [postal, city] if x)] if p]
    return ", ".join(parts) or None


def _existing(row: dict) -> dict:
    name = row.get("full_name")
    return {
        "status": "EXISTING_CUSTOMER",
        "customerId": row["id"],
        "customerNumber": row.get("customer_number"),
        "name": name,
        "address": _format_address(row.get("address")),
        "email": row.get("email"),
        "phone": row.get("phone"),
        "message": f"Willkommen zurück{', ' + name if name else ''}. "
        "Wie kann ich Ihnen helfen?",
    }


def _resolve(rows: list[dict]) -> dict:
    if not rows:
        return {
            "status": "NEW_CUSTOMER",
            "customerId": None,
            "message": "Kein bestehender Eintrag gefunden.",
        }
    if len(rows) == 1:
        return _existing(rows[0])
    return {
        "status": "MULTIPLE_CANDIDATES",
        "candidates": [
            {
                "customerId": r["id"],
                "name": r.get("full_name"),
                "address": _format_address(r.get("address")),
            }
            for r in rows
        ],
        "message": "Mehrere Treffer gefunden. Bitte nennen Sie Adresse und "
        "Nachnamen zur Bestätigung.",
    }


def identify_customer(org_id: str, payload: IdentifyCustomerRequest) -> dict:
    client = get_service_client()

    # 1. Explicit customer number wins.
    if payload.customer_number:
        rows = (
            client.table("customers")
            .select(_SELECT)
            .eq("org_id", org_id)
            .eq("customer_number", payload.customer_number)
            .limit(10)
            .execute()
            .data
            or []
        )
        return _resolve(rows)

    # 2. Address / last-name confirmation flow.
    if payload.address or payload.last_name:
        q = client.table("customers").select(_SELECT).eq("org_id", org_id)
        if payload.last_name:
            q = q.ilike("full_name", f"%{payload.last_name}%")
        rows = q.limit(10).execute().data or []
        return _resolve(rows)

    # 3. Phone path (explicit phoneNumber, else Caller-ID).
    # Detect a forwarded call: Caller-ID equals the org's own number and the
    # caller hasn't supplied their own number yet.
    if not payload.phone_number and payload.caller_number:
        org = (
            client.table("organizations")
            .select("phone_number")
            .eq("id", org_id)
            .limit(1)
            .execute()
            .data
        )
        org_phone = org[0]["phone_number"] if org else None
        if org_phone and _norm_phone(org_phone) == _norm_phone(payload.caller_number):
            return {
                "status": "FORWARDED_CALL",
                "message": "Weitergeleiteter Anruf erkannt. Bitte nennen Sie Ihre "
                "eigene Telefonnummer, damit ich Sie zuordnen kann.",
            }

    caller = payload.phone_number or payload.caller_number
    if not caller:
        return {
            "status": "NEW_CUSTOMER",
            "customerId": None,
            "message": "Kein bestehender Eintrag gefunden.",
        }

    rows = (
        client.table("customers")
        .select(_SELECT)
        .eq("org_id", org_id)
        .eq("phone", caller)
        .limit(10)
        .execute()
        .data
        or []
    )
    return _resolve(rows)
