"""identifyCustomer tool logic.

Maps a caller (by Caller-ID, phone, customer number, or address/last name) to an
existing customer record. Response shapes follow hk_tools_payload_reference.md.
The ``message`` field is spoken by the agent, so it is in German (production
language). All DB calls are synchronous; the route runs this in a threadpool.
"""

import re

from app.db.supabase_client import get_service_client
from app.schemas.tools import IdentifyCustomerRequest
from app.services.common import format_address

_SELECT = "id, full_name, phone, email, customer_number, address"

# Cases use the project-style lifecycle (planning|active|completed|archived);
# inquiries use open|in_progress|completed|deleted. "Open" = anything NOT in
# these terminal/removed buckets. Kept in sync with cases.py's _CLOSED_INQ.
_CLOSED_INQ_STATUS = ("completed", "closed", "done", "resolved", "deleted")
_CLOSED_CASE_STATUS = ("completed", "archived", "closed", "deleted")
# Bounded context: enough to disambiguate "which case?" without bloating the
# tool response (the agent only needs a short list to read back).
_OPEN_CONTEXT_LIMIT = 5


def _norm_phone(value: str | None) -> str:
    """Strip non-digits. Used for forwarded-call detection where both sides
    come from the same EL/Telnyx phone system in the same format."""
    return re.sub(r"\D", "", value or "")


def _to_e164(value: str | None, default_country: str = "49") -> str | None:
    """Best-effort E.164 normalization. German default (since the customer base
    is DE tradespeople). Handles:
      - already E.164: '+4915734432281' → '+4915734432281'
      - local German: '0157 344 322 81' → '+49157344322 81' (joins to '+49157344322281')
      - international 00-prefix: '00 49 170 111 222' → '+49170111222'
      - international without +: '918920100973' → '+918920100973'
    Returns None for empty/whitespace input. Used on every customer-table read
    and write so different-format renderings of the same number collapse to a
    single canonical phone column value.
    """
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if not digits:
        return None
    if digits.startswith("00"):
        # International prefix "00" — strip and turn into "+".
        return "+" + digits[2:]
    if digits.startswith("0"):
        # Local format (German default) — drop the trunk-0, prepend country code.
        return f"+{default_country}{digits[1:]}"
    # Already in international form without "+" (e.g. "918920100973").
    return "+" + digits


def _open_context(client, org_id: str, customer_id: str) -> list[dict]:
    """Bounded, org-scoped list of the customer's OPEN matters so the agent can
    ask "which case?". Prefers OPEN inquiries (the granular request the caller is
    most likely referring to); falls back to OPEN cases (Vorgänge) when the
    customer has none. Newest first, capped at ``_OPEN_CONTEXT_LIMIT``.

    Each entry: {number, title, status}. Never raises — a context-lookup failure
    must not break identification (the agent still works, just without the hint).
    """
    try:
        inq = (
            client.table("inquiries")
            .select("number, title, status, created_at")
            .eq("org_id", org_id)
            .eq("customer_id", customer_id)
            .not_.in_("status", list(_CLOSED_INQ_STATUS))
            .order("created_at", desc=True)
            .limit(_OPEN_CONTEXT_LIMIT)
            .execute()
            .data
            or []
        )
        rows = inq
        if not rows:
            rows = (
                client.table("cases")
                .select("number, title, status, created_at")
                .eq("org_id", org_id)
                .eq("customer_id", customer_id)
                .not_.in_("status", list(_CLOSED_CASE_STATUS))
                .order("created_at", desc=True)
                .limit(_OPEN_CONTEXT_LIMIT)
                .execute()
                .data
                or []
            )
        return [
            {
                "number": r.get("number"),
                "title": r.get("title"),
                "status": r.get("status"),
            }
            for r in rows
        ]
    except Exception:  # noqa: BLE001 — context is a nice-to-have, never fatal
        return []


def _existing(row: dict, *, client=None, org_id: str | None = None) -> dict:
    name = row.get("full_name")
    result = {
        "status": "EXISTING_CUSTOMER",
        "customerId": row["id"],
        "customerNumber": row.get("customer_number"),
        "name": name,
        "address": format_address(row.get("address")),
        "email": row.get("email"),
        "phone": row.get("phone"),
        "message": f"Willkommen zurück{', ' + name if name else ''}. "
        "Wie kann ich dir helfen?",
    }
    if client is not None and org_id:
        open_items = _open_context(client, org_id, row["id"])
        if open_items:
            result["openCases"] = open_items
            # A compact German one-liner the agent can read back verbatim so it
            # never has to guess which matter the caller means.
            listed = "; ".join(
                f"{i['number'] or '—'}: {i['title']}" for i in open_items if i.get("title")
            )
            if listed:
                result["message"] = (
                    f"Willkommen zurück{', ' + name if name else ''}. Ich sehe "
                    f"{len(open_items)} offene Vorgänge: {listed}. "
                    "Worum geht es heute?"
                )
    return result


def _resolve(rows: list[dict], *, client=None, org_id: str | None = None) -> dict:
    if not rows:
        return {
            "status": "NEW_CUSTOMER",
            "customerId": None,
            "message": "Kein bestehender Eintrag gefunden.",
        }
    if len(rows) == 1:
        return _existing(rows[0], client=client, org_id=org_id)
    return {
        "status": "MULTIPLE_CANDIDATES",
        "candidates": [
            {
                "customerId": r["id"],
                "name": r.get("full_name"),
                "address": format_address(r.get("address")),
            }
            for r in rows
        ],
        "message": "Mehrere Treffer gefunden. Bitte nenne Adresse und "
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
        return _resolve(rows, client=client, org_id=org_id)

    # 2. Address / last-name confirmation flow.
    if payload.address or payload.last_name:
        q = client.table("customers").select(_SELECT).eq("org_id", org_id)
        if payload.last_name:
            q = q.ilike("full_name", f"%{payload.last_name}%")
        rows = q.limit(10).execute().data or []
        return _resolve(rows, client=client, org_id=org_id)

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
                "message": "Weitergeleiteter Anruf erkannt. Bitte nenne deine "
                "eigene Telefonnummer, damit ich dich zuordnen kann.",
            }

    caller = payload.phone_number or payload.caller_number
    if not caller:
        return {
            "status": "NEW_CUSTOMER",
            "customerId": None,
            "message": "Kein bestehender Eintrag gefunden.",
        }

    # P0.8 — normalize the caller to E.164 so different formats of the same
    # number match the canonical stored value. New customers (post-P0.8) have
    # phone stored in E.164 by get_or_create_customer; legacy rows may not match
    # until they're backfilled separately.
    #
    # CUST-014 — match BOTH phone columns. A known customer who calls from their
    # secondary number (work phone / new SIM, stored in phone2 by
    # get_or_create_customer) was previously treated as a NEW caller. Mirror
    # find_existing_customer (services/customers.py): two plain .eq() lookups —
    # one per column — rather than an or() filter, to avoid '+' encoding
    # ambiguity inside PostgREST or-filters. Dedup any row matched by both.
    caller_norm = _to_e164(caller)
    target = caller_norm or caller
    rows = (
        client.table("customers")
        .select(_SELECT)
        .eq("org_id", org_id)
        .eq("phone", target)
        .limit(10)
        .execute()
        .data
        or []
    )
    rows2 = (
        client.table("customers")
        .select(_SELECT)
        .eq("org_id", org_id)
        .eq("phone2", target)
        .limit(10)
        .execute()
        .data
        or []
    )
    seen = {r["id"] for r in rows}
    for r in rows2:
        if r["id"] not in seen:
            rows.append(r)
            seen.add(r["id"])
    return _resolve(rows, client=client, org_id=org_id)
