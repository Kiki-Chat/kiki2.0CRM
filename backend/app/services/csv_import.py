"""CSV import for customers + employees (P2 / Wave 4).

Mapping-driven: the frontend supplies ``mapping = {target_field: csv_header}``;
the backend parses authoritatively (encoding + delimiter detection), applies the
mapping, normalizes phones to E.164, dedups, and batch-inserts in chunks.

Dedup is mandatory and idempotent: a row whose unique key (email OR normalized
phone) already exists — in the DB or earlier in the same file — is SKIPPED, never
overwritten and never duplicated. Re-running the same file imports nothing new.
Each row gets a result: imported / skipped_duplicate / error.
"""
from __future__ import annotations

import csv
import io
import re

from app.db.supabase_client import get_service_client
from app.services.common import gen_customer_number
from app.services.identify import _to_e164

_CHUNK = 500
_PHONE_HEAD = re.compile(r"[\s+\-/().\d]*")


# ─── parsing ─────────────────────────────────────────────────────────────────
def _decode(content: bytes) -> str:
    """Decode bytes trying UTF-8 (incl. BOM) first, then German Windows/Latin
    encodings — so umlauts survive in either common export format."""
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("latin-1", errors="ignore")


def _sniff_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t").delimiter
    except csv.Error:
        return ";" if sample.count(";") > sample.count(",") else ","


def parse_csv(content: bytes) -> tuple[list[str], list[dict]]:
    text = _decode(content)
    delim = _sniff_delimiter(text[:4096])
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    headers = [h for h in (reader.fieldnames or []) if h]
    rows = [dict(r) for r in reader]
    return headers, rows


# ─── value helpers ───────────────────────────────────────────────────────────
def _get(row: dict, mapping: dict, key: str) -> str | None:
    col = mapping.get(key)
    if not col:
        return None
    val = row.get(col)
    if val is None:
        return None
    val = str(val).strip()
    if not val or val == "-":  # German ERP exports use "-" for empty cells
        return None
    return val


def clean_phone(raw: str | None) -> str | None:
    """Normalize to E.164. Trailing free-text notes (e.g. 'nicht anrufe') are
    dropped by taking only the leading phone-ish run before delegating to the
    shared _to_e164 (German default)."""
    if not raw:
        return None
    m = _PHONE_HEAD.match(raw.strip())
    head = m.group(0) if m else raw
    return _to_e164(head)


def _num(v: str | None):
    if not v:
        return None
    try:
        return float(str(v).replace(",", ".").strip())
    except ValueError:
        return None


def _hex_color(v: str | None) -> str | None:
    if not v:
        return None
    v = v.strip()
    return v if re.fullmatch(r"#?[0-9A-Fa-f]{6}", v) else None


def _chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


# ─── customers ───────────────────────────────────────────────────────────────
def import_customers(org_id: str, content: bytes, mapping: dict) -> dict:
    client = get_service_client()
    _headers, rows = parse_csv(content)

    existing = (
        client.table("customers")
        .select("email, phone")
        .eq("org_id", org_id)
        .neq("status", "deleted")
        .execute()
        .data
        or []
    )
    seen_emails = {e["email"].lower() for e in existing if e.get("email")}
    seen_phones = {e["phone"] for e in existing if e.get("phone")}

    # Continue numbering after BOTH existing rows and any explicit CSV numbers.
    max_num = int(gen_customer_number(client, org_id)) - 1

    results: list[dict] = []
    to_insert: list[dict] = []

    for i, row in enumerate(rows, start=1):
        full_name = _get(row, mapping, "full_name") or _get(row, mapping, "name")
        email = _get(row, mapping, "email")
        phone = clean_phone(_get(row, mapping, "phone"))
        phone2 = clean_phone(_get(row, mapping, "phone2"))
        if not (full_name or email or phone):
            results.append({"row": i, "status": "error", "reason": "Kein Name/E-Mail/Telefon"})
            continue

        email_l = email.lower() if email else None
        if (email_l and email_l in seen_emails) or (phone and phone in seen_phones):
            results.append(
                {"row": i, "status": "skipped_duplicate", "name": full_name,
                 "reason": "E-Mail/Telefon existiert bereits"}
            )
            continue

        num = _get(row, mapping, "customer_number")
        if num and str(num).isdigit():
            max_num = max(max_num, int(num))
        elif not num:
            max_num += 1
            num = str(max_num)

        street = _get(row, mapping, "street")
        plz = _get(row, mapping, "postal_code")
        city = _get(row, mapping, "city")
        address = None
        if street or plz or city:
            address = {"street": street, "postal_code": plz, "city": city}

        notes = _get(row, mapping, "notes")

        to_insert.append({
            "org_id": org_id,
            "full_name": full_name,
            "email": email,
            "phone": phone,
            # Second number (Mobil) lands in its own column; skip if identical to phone.
            "phone2": phone2 if (phone2 and phone2 != phone) else None,
            "address": address,
            "notes": notes,
            "customer_type": "regular",   # CSV import = Stammkunde, never "new"
            "identified_by": "csv_import",
            "customer_number": num,
        })
        if email_l:
            seen_emails.add(email_l)
        if phone:
            seen_phones.add(phone)
        results.append({"row": i, "status": "imported", "name": full_name, "customer_number": num})

    inserted = 0
    for chunk in _chunks(to_insert, _CHUNK):
        inserted += len(client.table("customers").insert(chunk).execute().data or [])

    return _summary(rows, results, inserted)


# ─── employees ───────────────────────────────────────────────────────────────
def import_employees(org_id: str, content: bytes, mapping: dict) -> dict:
    client = get_service_client()
    _headers, rows = parse_csv(content)

    existing = client.table("employees").select("email, display_name").eq("org_id", org_id).execute().data or []
    seen_emails = {e["email"].lower() for e in existing if e.get("email")}
    seen_names = {e["display_name"].lower() for e in existing if e.get("display_name")}

    results: list[dict] = []
    to_insert: list[dict] = []

    for i, row in enumerate(rows, start=1):
        name = _get(row, mapping, "display_name") or _get(row, mapping, "name")
        if not name:
            results.append({"row": i, "status": "error", "reason": "Kein Name"})
            continue
        email = _get(row, mapping, "email")
        email_l = email.lower() if email else None
        name_l = name.lower()
        if (email_l and email_l in seen_emails) or (not email_l and name_l in seen_names):
            results.append(
                {"row": i, "status": "skipped_duplicate", "name": name,
                 "reason": "E-Mail/Name existiert bereits"}
            )
            continue

        role_raw = (_get(row, mapping, "access_role") or "").lower()
        access_role = "admin" if "admin" in role_raw else "employee"

        rec = {
            "org_id": org_id,
            "display_name": name,
            "email": email,
            "access_role": access_role,
            "is_active": True,
            "activity_area": _get(row, mapping, "activity_area"),
            "auto_assign": _truthy(_get(row, mapping, "auto_assign")),
        }
        color = _hex_color(_get(row, mapping, "calendar_color"))
        if color:
            rec["calendar_color"] = color if color.startswith("#") else f"#{color}"
        rate = _num(_get(row, mapping, "hourly_rate"))
        if rate is not None:
            rec["hourly_rate"] = rate
        vac = _num(_get(row, mapping, "vacation_days_per_year"))
        if vac is not None:
            rec["vacation_days_per_year"] = int(vac)

        to_insert.append(rec)
        if email_l:
            seen_emails.add(email_l)
        seen_names.add(name_l)
        results.append({"row": i, "status": "imported", "name": name})

    inserted = 0
    for chunk in _chunks(to_insert, _CHUNK):
        inserted += len(client.table("employees").insert(chunk).execute().data or [])

    return _summary(rows, results, inserted)


def _truthy(v: str | None) -> bool:
    return bool(v) and v.strip().lower() in ("1", "true", "ja", "yes", "x", "wahr", "aktiv")


def _summary(rows: list, results: list[dict], inserted: int) -> dict:
    return {
        "total": len(rows),
        "imported": inserted,
        "skipped_duplicate": sum(1 for r in results if r["status"] == "skipped_duplicate"),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "results": results,
    }
