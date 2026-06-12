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

# Bilingual (DE + EN) emergency markers — a content-based fallback for the call-log
# emergency flag. The agent's data_collection almost never carries an explicit
# emergency field, so without this real emergencies (incl. English-language calls)
# were never flagged. Deliberately PRECISE — strong urgency/hazard words, not generic
# plumbing terms ("Toilette"/"Leck"/"Wasser") — so a routine after-hours repair isn't
# mis-flagged. Matched as case-insensitive substrings. See ISSUES_2026-06-09.md.
_EMERGENCY_TERMS = (
    # German
    "notfall", "notdienst", "dringend", "akut", "rohrbruch", "wasserrohrbruch",
    "gasgeruch", "gasaustritt", "überschwemm", "ueberschwemm", "wasserschaden",
    "heizungsausfall", "warmwasserausfall",
    # English
    "emergency", "urgent", "burst pipe", "gas leak", "gas smell", "flooding",
    "flooded", "water damage", "no heating", "no hot water",
)


def _content_signals_emergency(call: dict) -> bool:
    """True if the call's summary/extraction text contains a strong DE/EN emergency
    marker. Language-agnostic fallback used when the agent didn't set an explicit
    emergency field in data_collection."""
    dc = call.get("data_collection") or {}
    blob = " ".join(
        str(v)
        for v in (
            call.get("summary_title"),
            call.get("summary"),
            dc.get("issue_summary"),
            dc.get("ultimate_summary"),
            dc.get("next_action"),
        )
        if v
    ).lower()
    return any(term in blob for term in _EMERGENCY_TERMS)


def _compose_notes(message: str | None, additional_fields) -> str:
    parts = [message or ""]
    for f in additional_fields or []:
        q = getattr(f, "question", None)
        a = getattr(f, "answer", None)
        if q or a:
            parts.append(f"{q}: {a}")
    return "\n".join(p for p in parts if p).strip()


def _set_call_inquiry_id(client, org_id: str, call_id: str, inquiry_id: str) -> None:
    """Stamp calls.inquiry_id (the Vorgang/case a call belongs to) when not already
    set. Only fills NULLs so a deliberate re-link is never clobbered. Best-effort —
    a failure here must never break post-call ingest."""
    try:
        (
            client.table("calls")
            .update({"inquiry_id": inquiry_id})
            .eq("org_id", org_id)
            .eq("id", call_id)
            .is_("inquiry_id", "null")
            .execute()
        )
    except Exception:  # noqa: BLE001 — linking is best-effort
        pass


def ensure_call_inquiry(client, org_id: str, call: dict) -> dict:
    """Get-or-create the single 'request' inquiry linked to an INBOUND call, and
    stamp calls.inquiry_id so the call is tied to its Vorgang (case).

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
        _set_call_inquiry_id(client, org_id, call["id"], existing[0]["id"])
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
    # The agent rarely sets an explicit emergency field, so also derive urgency from
    # the call's summary/extraction text (bilingual, language-agnostic). Without this,
    # clear emergencies — like an English "toilet emergency" outside hours — were logged
    # as non-emergency even though the agent handled them as a Notfall.
    if not agent_urgent and _content_signals_emergency(call):
        agent_urgent = True
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
    inquiry = client.table("inquiries").insert(row).execute().data[0]
    _set_call_inquiry_id(client, org_id, call["id"], inquiry["id"])
    # Projects merge (item 6): every new inquiry is auto-filed into a Projekt —
    # attach to a matching open one, else create its own. Best-effort by design.
    from app.services.projects_auto import safe_auto_assign

    safe_auto_assign(client, org_id, inquiry)
    return inquiry


# ─── Outbound case-linking (Vorgang threading) ───────────────────────────────
# referenz_typ is the German occasion label stored on the outbound_calls ledger.
def _resolve_case_from_referenz(client, org_id, referenz_typ, referenz_id):
    """Resolve the case (inquiry_id) a triggering record belongs to:
    Termin→appointment.inquiry_id, KVA→cost_estimate.inquiry_id, Vorgang→the inquiry
    itself, Rechnung→the invoice's KVA. Wartung/Rückruf have no case → None."""
    if not referenz_id or not referenz_typ:
        return None
    t = str(referenz_typ).strip().lower()
    try:
        if t == "vorgang":
            return referenz_id
        if t == "termin":
            rows = (client.table("appointments").select("inquiry_id")
                    .eq("org_id", org_id).eq("id", referenz_id).limit(1).execute().data)
            return rows[0].get("inquiry_id") if rows else None
        if t == "kva":
            rows = (client.table("cost_estimates").select("inquiry_id")
                    .eq("org_id", org_id).eq("id", referenz_id).limit(1).execute().data)
            return rows[0].get("inquiry_id") if rows else None
        if t == "rechnung":
            inv = (client.table("invoices").select("cost_estimate_id")
                   .eq("org_id", org_id).eq("id", referenz_id).limit(1).execute().data)
            ce_id = inv[0].get("cost_estimate_id") if inv else None
            if not ce_id:
                return None
            rows = (client.table("cost_estimates").select("inquiry_id")
                    .eq("org_id", org_id).eq("id", ce_id).limit(1).execute().data)
            return rows[0].get("inquiry_id") if rows else None
    except Exception:  # noqa: BLE001 — best-effort case resolution
        return None
    return None


def link_outbound_call_to_case(client, org_id: str, call: dict) -> str | None:
    """Tie an OUTBOUND call to the case that TRIGGERED it, via its outbound_calls
    ledger row (matched on the ElevenLabs conversation_id). Outbound calls don't
    spawn their own inquiry, so without this they float free of the Vorgang and the
    call-log action buttons stay dead. Prefer the ledger's stored inquiry_id, else
    derive it from (referenz_typ, referenz_id). Best-effort: returns the linked
    inquiry_id, or None."""
    conv = call.get("elevenlabs_conversation_id")
    if not conv:
        return None
    rows = (
        client.table("outbound_calls")
        .select("inquiry_id, referenz_typ, referenz_id")
        .eq("org_id", org_id)
        .eq("conversation_id", conv)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        return None
    led = rows[0]
    inquiry_id = led.get("inquiry_id") or _resolve_case_from_referenz(
        client, org_id, led.get("referenz_typ"), led.get("referenz_id")
    )
    if inquiry_id:
        _set_call_inquiry_id(client, org_id, call["id"], inquiry_id)
    return inquiry_id


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

    # Projects merge (item 6): agent-captured inquiries are auto-filed too.
    from app.services.projects_auto import safe_auto_assign

    safe_auto_assign(client, org_id, inquiry)

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
