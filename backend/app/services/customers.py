"""Customer helpers + updateCustomerData tool."""

from app.db.supabase_client import get_service_client
from app.schemas.tools import UpdateCustomerDataRequest
from app.services.common import gen_customer_number
from app.services.csv_import import classify_phone
from app.services.identify import _to_e164

# Superset of every field a caller of get_or_create_customer expects, plus phone2
# (so the dedup lookup can match a number stored in either phone column).
_DEDUP_SELECT = "id, full_name, phone, phone2, email, customer_number, address, identified_by"


def find_existing_customer(
    client,
    org_id: str,
    *,
    phone: str | None = None,
    name: str | None = None,
    email: str | None = None,
) -> dict | None:
    """Return an existing customer the given identity would duplicate, else None.

    ONE dedup rule, shared by every insert path (manual-create API + AI agent),
    mirroring the CSV importer (csv_import.py) so all three paths agree:
      - email match → duplicate.
      - a MOBILE number (DE 15x/16x/17x) matching phone OR phone2 → duplicate
        (a mobile belongs to one person, so it dedups on its own).
      - a LANDLINE / unknown number → duplicate only if the NAME also matches
        (a shared landline — couple, business — must be name-confirmed).
      - no phone → dedup on exact name (so retries don't duplicate).
    Relies on stored phone/phone2 being canonical E.164 (every insert path now
    normalizes before writing); legacy non-canonical rows may not match until
    backfilled.
    """

    def _q():
        return (
            client.table("customers")
            .select(_DEDUP_SELECT)
            .eq("org_id", org_id)
            .neq("status", "deleted")
        )

    if email:
        # Case-insensitive: emails are stored verbatim across paths, so try the
        # given casing and a lowercased form (mirrors the CSV importer, which
        # dedups on email.lower()).
        for cand in dict.fromkeys([email.strip(), email.strip().lower()]):
            rows = _q().eq("email", cand).limit(1).execute().data
            if rows:
                return rows[0]

    phone_norm = _to_e164(phone)
    if phone_norm:
        # Match the canonical number against BOTH phone columns — two plain eq
        # lookups (avoids any '+' encoding ambiguity inside an or() filter).
        rows = (_q().eq("phone", phone_norm).limit(10).execute().data or []) + (
            _q().eq("phone2", phone_norm).limit(10).execute().data or []
        )
        if classify_phone(phone_norm) == "mobile":
            # A mobile is unique to one person → dedup on the number alone.
            if rows:
                return rows[0]
        elif rows:
            # Landline / unknown — a shared landline (couple, business) is only a
            # duplicate when the NAME also matches. But WITHOUT a name (common on
            # the call path: a landline Caller-ID with no captured name), fall
            # back to phone-exact so a repeat caller is not duplicated on every
            # call — preserving the pre-helper behaviour of the call/agent path.
            if name:
                nl = name.strip().casefold()
                match = next(
                    (r for r in rows if (r.get("full_name") or "").strip().casefold() == nl),
                    None,
                )
                if match:
                    return match
            else:
                return rows[0]
    elif name:
        rows = _q().eq("full_name", name).limit(1).execute().data
        if rows:
            return rows[0]
    return None


def get_or_create_customer(
    org_id: str,
    *,
    phone: str | None = None,
    name: str | None = None,
    email: str | None = None,
    address: str | None = None,
) -> dict:
    """Find a customer (shared dedup) within the org, or create a new one.

    P0.8 — normalize phone to E.164 on BOTH the lookup and the insert, so
    different-format renderings of the same number collapse to a single
    customer row. The lookup now goes through find_existing_customer, so the
    call/agent path matches the SAME way the manual-create API and CSV import
    do (mobile on phone OR phone2; landline+name; email) instead of the old
    phone-exact-only match that ignored phone2.
    """
    client = get_service_client()
    existing = find_existing_customer(client, org_id, phone=phone, name=name, email=email)
    if existing:
        return existing

    phone_norm = _to_e164(phone)

    # Tester 2026-06-11: a KNOWN customer giving a DIFFERENT number on a call
    # (new SIM, work phone, calling for themselves from elsewhere) must not become
    # a duplicate row with the same name. If exactly ONE same-name customer exists
    # in the org, attach the new number as the SECONDARY mobile (phone2 — simply
    # overwritten when they give yet another) and reuse that row. Ambiguous names
    # (0 or 2+ matches) fall through to create, as before — we never guess-merge.
    if phone_norm and name and name.strip():
        same_name = (
            client.table("customers")
            .select("id, full_name, phone, phone2, email, customer_number")
            .eq("org_id", org_id)
            .neq("status", "deleted")
            .ilike("full_name", name.strip())  # no wildcards → exact, case-insensitive
            .limit(2)
            .execute()
            .data
            or []
        )
        if len(same_name) == 1:
            cust = same_name[0]
            if phone_norm not in (cust.get("phone"), cust.get("phone2")):
                client.table("customers").update(
                    {"phone2": phone_norm, "updated_at": "now()"}
                ).eq("org_id", org_id).eq("id", cust["id"]).execute()
                cust["phone2"] = phone_norm
            return cust

    payload = {
        "org_id": org_id,
        "full_name": name,
        "phone": phone_norm,  # always store the canonical E.164 form
        "email": email,
        "customer_number": gen_customer_number(client, org_id),
        "identified_by": "phone" if phone_norm else "manual",
    }
    if address:
        payload["address"] = {"raw": address}
    created = client.table("customers").insert(payload).execute().data
    return created[0]


def update_customer_data(org_id: str, payload: UpdateCustomerDataRequest) -> dict:
    client = get_service_client()
    if not payload.customer_id:
        return {"success": False, "message": "customerId fehlt."}

    fields: dict = {}
    if payload.name:
        fields["full_name"] = payload.name
    if payload.email:
        fields["email"] = payload.email
    if payload.phone:
        # Store canonical E.164 so the dedup lookup can match this number later.
        fields["phone"] = _to_e164(payload.phone) or payload.phone
    if payload.address:
        fields["address"] = {"raw": payload.address}

    if not fields:
        return {"success": False, "updatedFields": [], "message": "Keine Daten zum Aktualisieren."}

    fields["updated_at"] = "now()"
    res = (
        client.table("customers")
        .update(fields)
        .eq("org_id", org_id)
        .eq("id", payload.customer_id)
        .execute()
    )
    if not res.data:
        return {"success": False, "message": "Kunde nicht gefunden."}

    # Report using the request field names that were actually set.
    reported = []
    if payload.name:
        reported.append("name")
    if payload.email:
        reported.append("email")
    if payload.phone:
        reported.append("phone")
    if payload.address:
        reported.append("address")
    return {
        "success": True,
        "updatedFields": reported,
        "message": "Kundendaten erfolgreich aktualisiert.",
    }
