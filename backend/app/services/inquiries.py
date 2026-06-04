"""createInquiry + searchCustomerInquiries tools."""

from datetime import datetime

from app.db.supabase_client import get_service_client
from app.schemas.tools import CreateInquiryRequest, SearchCustomerInquiriesRequest
from app.services.common import gen_inquiry_number
from app.services.customers import get_or_create_customer
from app.services.scheduling import is_emergency_by_hours


def _parse_iso(value) -> datetime | None:
    """Lenient ISO-8601 parse (accepts a trailing 'Z'); None on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None

_STATUS_LABEL = {
    "open": "Offen",
    "in_progress": "In Bearbeitung",
    "completed": "Abgeschlossen",
    "deleted": "Gelöscht",
}


def _compose_notes(message: str | None, additional_fields) -> str:
    parts = [message or ""]
    for f in additional_fields or []:
        q = getattr(f, "question", None)
        a = getattr(f, "answer", None)
        if q or a:
            parts.append(f"{q}: {a}")
    return "\n".join(p for p in parts if p).strip()


def ensure_call_inquiry(client, org_id: str, call: dict) -> dict:
    """Get-or-create the single 'request' inquiry linked to a call.

    Every call becomes an actionable request in the Call Logs panel.
    Idempotent on call_id.
    """
    existing = (
        client.table("inquiries")
        .select("*")
        .eq("org_id", org_id)
        .eq("call_id", call["id"])
        .limit(1)
        .execute()
        .data
    )
    if existing:
        return existing[0]

    dc = call.get("data_collection") or {}
    title = call.get("summary_title") or dc.get("issue_summary") or "Anruf"
    notes = dc.get("ultimate_summary") or call.get("summary") or ""

    # Emergency tagging (user-confirmed): flag ONLY when BOTH (a) the call arrived
    # outside business hours while the org runs a Notdienst AND (b) the agent's data
    # collection actually marked it urgent. A normal after-hours call is no longer
    # auto-flagged as an emergency. The NOTDIENST badge reads emergency_flag.
    outside_hours = False
    started = _parse_iso(call.get("started_at"))
    if started is not None:
        try:
            outside_hours = is_emergency_by_hours(org_id, started)
        except Exception:
            outside_hours = False
    agent_urgent = False
    for key in ("is_emergency", "emergency", "notfall", "urgent"):
        v = dc.get(key)
        if v is True or (isinstance(v, str) and v.strip().lower() in ("true", "ja", "yes", "1")):
            agent_urgent = True
            break
    emergency = outside_hours and agent_urgent

    row = {
        "org_id": org_id,
        "call_id": call["id"],
        "customer_id": call.get("customer_id"),
        "title": title,
        "type": "info",
        "status": "open",
        "number": gen_inquiry_number(client, org_id),
        "notes": notes,
        "emergency_flag": emergency,
    }
    return client.table("inquiries").insert(row).execute().data[0]


def create_inquiry(org_id: str, payload: CreateInquiryRequest) -> dict:
    client = get_service_client()
    customer = get_or_create_customer(
        org_id,
        phone=payload.phone or payload.caller_number,
        name=payload.name,
        email=payload.email,
        address=payload.address,
    )

    number = gen_inquiry_number(client, org_id)
    notes = _compose_notes(payload.message, payload.additional_fields)
    inquiry = (
        client.table("inquiries")
        .insert(
            {
                "org_id": org_id,
                "customer_id": customer["id"],
                "title": payload.inquiry_title or (payload.message or "Anfrage")[:60],
                "type": "appointment_request",
                "status": "open",
                "number": number,
                "notes": notes,
                "emergency_flag": bool(payload.urgent),
            }
        )
        .execute()
        .data[0]
    )

    return {
        "success": True,
        "inquiryId": inquiry["id"],
        "inquiryNumber": number,
        "customerId": customer["id"],
        "message": f"Anliegen aufgenommen. Referenznummer: {number}. "
        "Jemand wird sich in Kürze bei Ihnen melden.",
    }


def search_customer_inquiries(org_id: str, payload: SearchCustomerInquiriesRequest) -> dict:
    client = get_service_client()

    # Resolve the customer: explicit id, else by caller phone.
    customer_id = payload.customer_id
    if not customer_id and payload.caller_number:
        found = (
            client.table("customers")
            .select("id")
            .eq("org_id", org_id)
            .eq("phone", payload.caller_number)
            .limit(1)
            .execute()
            .data
        )
        if found:
            customer_id = found[0]["id"]

    if not customer_id:
        return {
            "success": True,
            "inquiries": [],
            "total": 0,
            "message": "Keine Anfragen gefunden. Bitte nennen Sie weitere Angaben.",
        }

    q = (
        client.table("inquiries")
        .select("id, number, title, status, notes, created_at, updated_at")
        .eq("org_id", org_id)
        .eq("customer_id", customer_id)
        .neq("status", "deleted")
    )
    if payload.status:
        q = q.eq("status", payload.status)
    if payload.date_from:
        q = q.gte("created_at", payload.date_from)
    if payload.date_to:
        q = q.lte("created_at", payload.date_to)
    ascending = (payload.sort_order or "newest").lower() == "oldest"
    q = q.order("created_at", desc=not ascending).limit(20)
    rows = q.execute().data or []

    inquiries = [
        {
            "inquiryId": r["id"],
            "inquiryNumber": r.get("number"),
            "title": r.get("title"),
            "status": r.get("status"),
            "statusLabel": _STATUS_LABEL.get(r.get("status"), r.get("status")),
            "createdAt": r.get("created_at"),
            "lastUpdate": r.get("updated_at"),
            "note": r.get("notes"),
        }
        for r in rows
    ]

    if not inquiries:
        msg = "Ich habe keine passenden Anfragen gefunden."
    else:
        latest = inquiries[0]
        msg = (
            f"Ich habe {len(inquiries)} Anfrage(n) gefunden. Die aktuellste ist "
            f"'{latest['title']}' — Status: {latest['statusLabel']}."
        )
    return {"success": True, "inquiries": inquiries, "total": len(inquiries), "message": msg}
