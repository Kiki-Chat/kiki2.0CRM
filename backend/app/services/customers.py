"""Customer helpers + updateCustomerData tool."""

from app.db.supabase_client import get_service_client
from app.schemas.tools import UpdateCustomerDataRequest
from app.services.common import gen_customer_number

_SELECT = "id, full_name, phone, email, customer_number, address, identified_by"


def get_or_create_customer(
    org_id: str,
    *,
    phone: str | None = None,
    name: str | None = None,
    email: str | None = None,
    address: str | None = None,
) -> dict:
    """Find a customer by phone within the org, or create a new one."""
    client = get_service_client()
    if phone:
        found = (
            client.table("customers")
            .select(_SELECT)
            .eq("org_id", org_id)
            .eq("phone", phone)
            .limit(1)
            .execute()
            .data
        )
        if found:
            return found[0]
    elif name:
        # No phone to match on — dedupe by exact name so retries don't duplicate.
        found = (
            client.table("customers")
            .select(_SELECT)
            .eq("org_id", org_id)
            .eq("full_name", name)
            .limit(1)
            .execute()
            .data
        )
        if found:
            return found[0]

    payload = {
        "org_id": org_id,
        "full_name": name,
        "phone": phone,
        "email": email,
        "customer_number": gen_customer_number(client, org_id),
        "identified_by": "phone" if phone else "manual",
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
        fields["phone"] = payload.phone
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
