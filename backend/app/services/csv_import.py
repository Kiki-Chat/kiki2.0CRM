"""CSV import for customers + employees (P2 / Wave 4).

Mapping-driven: the frontend supplies ``mapping = {target_field: csv_header}``;
the backend parses authoritatively (encoding + delimiter detection), applies the
mapping, normalizes phones to E.164, dedups, and batch-inserts in chunks.

Dedup is mandatory and idempotent, but SHARED-LANDLINE-SAFE: a row is a duplicate
only when its email already exists, OR its normalized phone AND name both already
exist (in the DB or earlier in the same file). Two DIFFERENT people on one phone
number — a married couple, or a property manager running several WEGs — are kept
as distinct customers; phone-alone no longer collapses them. Re-running the same
file still imports nothing new. Each row gets a result: imported / skipped_duplicate
/ error.

The email column is also validated: a value that is not a real address (German ERP
exports routinely have a phone number typed into the Mail field) is NOT stored as an
email; if it looks like a phone and no second number is set, it is salvaged into phone2.
"""
from __future__ import annotations

import csv
import io
import re
from collections import Counter

from app.db.supabase_client import get_service_client
from app.services.common import fetch_all_rows, gen_customer_number, ki_customer_seq
from app.services.identify import _to_e164

_CHUNK = 500
_PHONE_HEAD = re.compile(r"[\s+\-/().\d]*")
# A pragmatic "is this actually an email" check — local@domain.tld, no spaces.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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


def _valid_email(raw: str | None) -> str | None:
    """Return the address only if it is actually an email, else None — so a phone
    number (or other junk) typed into the source 'Mail' column is never stored as
    one."""
    if not raw:
        return None
    v = raw.strip()
    return v if _EMAIL_RE.match(v) else None


def _looks_like_phone(raw: str | None) -> bool:
    """True if the value is plausibly a phone number (only phone-ish chars, ≥5
    digits) — used to salvage a phone wrongly placed in the Mail column."""
    if not raw:
        return False
    v = raw.strip()
    return bool(re.fullmatch(r"[\d\s+\-/().]+", v)) and sum(c.isdigit() for c in v) >= 5


def classify_phone(e164: str | None) -> str:
    """Classify a NORMALIZED E.164 number → ``"mobile" | "landline" | "unknown"``.

    German mobile = ``+49`` then ``15x/16x/17x``; any other ``+49`` is a landline /
    area-code number; a non-German number is ``"unknown"`` and is treated
    landline-like for dedup (i.e. needs a name to confirm a duplicate — the safe
    default). A mobile is unique to one person, so it dedups on its own; a landline
    can be shared (a couple, a business) and must be name-confirmed.
    """
    if not e164:
        return "unknown"
    if e164.startswith("+49"):
        national = e164[3:]
        return "mobile" if national[:2] in ("15", "16", "17") else "landline"
    return "unknown"


# A street+PLZ+city address embedded in free text, anchored on a 5-digit German PLZ
# (so a plain note without an address is never matched).
_ADDR_RE = re.compile(
    r"(.+?)[,\s]+(\d{5})\s+([A-Za-zÄÖÜäöüß][\wÄÖÜäöüß .\-]+?)\s*$"
)


def extract_address(text: str | None) -> dict | None:
    """Pull a ``{street, postal_code, city}`` address out of a free-text value
    (e.g. an address mistakenly sitting in the Bemerkung/notes column). Scans each
    line and matches only a PLZ-anchored ``Street, 12345 City`` shape, so ordinary
    notes are left untouched. Returns None when no address is present."""
    if not text:
        return None
    for line in str(text).splitlines():
        m = _ADDR_RE.search(line.strip())
        if m:
            return {
                "street": m.group(1).strip(" ,;\t"),
                "postal_code": m.group(2),
                "city": m.group(3).strip(),
            }
    return None


# ─── content-type detection (intelligent mapping) ────────────────────────────
# A column's TYPE is read from its DATA, not its header — so an address is known to
# be an address by content, a phone is never put in the email/address field, and an
# odd/missing header still maps correctly.
_STREET_TOKEN = re.compile(
    r"(str\.?|straße|strasse|weg|allee|platz|ring|gasse|damm|chaussee|ufer|stieg|kamp|hof|berg)\b",
    re.I,
)
_ALPHA = re.compile(r"^[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß .,'\-/]+$")


def _value_type(v: str) -> str:
    """Best-effort content type of a single non-empty cell value. Order matters: a
    5-digit PLZ and a bare customer number are ALSO ≥5 digits, so they must be caught
    before the phone test (which accepts any 5+ digit run)."""
    v = v.strip()
    if not v:
        return "empty"
    if _valid_email(v):
        return "email"
    if re.fullmatch(r"\d{5}", v):
        return "postal_code"  # exactly 5 bare digits = German PLZ (never a phone)
    if v.isdigit() and not v.startswith("0"):
        return "number"  # bare id, e.g. a customer number (a phone starts 0/+ or is formatted)
    if _looks_like_phone(v):
        return "mobile" if classify_phone(clean_phone(v)) == "mobile" else "landline"
    if _STREET_TOKEN.search(v) or re.search(r"\d+\s*[a-z]?$", v):
        return "street"
    if _ALPHA.match(v):
        return "name_or_city"  # resolved per column by distinctness
    return "free_text"


def detect_column_type(samples: list[str]) -> dict:
    """Detect a column's dominant content type from sampled cell values. Returns
    ``{type, confidence, samples(≤3), mixed_phone}``. ``type`` ∈ email / mobile /
    landline / postal_code / customer_number / street / person_name / city /
    free_text / empty."""
    vals = [str(s).strip() for s in samples if s is not None and str(s).strip()]
    if not vals:
        return {"type": "empty", "confidence": 0.0, "samples": [], "mixed_phone": False}
    cnt = Counter(_value_type(v) for v in vals)
    distinct = len(set(vals)) / len(vals)
    top, n = cnt.most_common(1)[0]
    if top == "number":  # bare digit run: distinct → an id; repeating → not customer-relevant
        top = "customer_number" if distinct > 0.8 else "number"
    elif top == "name_or_city":  # cities repeat across rows; names are mostly distinct
        top = "person_name" if distinct >= 0.6 else "city"
    return {
        "type": top,
        "confidence": round(n / len(vals), 2),
        "samples": vals[:3],
        "mixed_phone": bool(cnt.get("mobile") and cnt.get("landline")),
    }


# Header-name hints (mirror the frontend) — used only to break ties / fill the soft
# text fields where content alone is ambiguous (name vs city vs notes).
_HEADER_HINTS = {
    "full_name": ["titel+vorname+name", "name", "vorname", "kurzname"],
    "email": ["mail", "email", "e-mail"],
    "phone": ["telefon", "phone", "tel", "festnetz"],
    "phone2": ["mobil", "mobile", "handy"],
    "street": ["strasse", "straße", "street", "str"],
    "postal_code": ["plz", "postleitzahl", "zip", "postal"],
    "city": ["ort", "stadt", "city"],
    "notes": ["bemerkung", "notiz", "notes", "comment"],
    "customer_number": ["kundennummer", "kunden-nr", "kdnr", "customer_number", "adressnummer"],
}


def _hint_score(field: str, header: str) -> int:
    """Header-name match score. Preserves hint PRIORITY order (an exact match on the
    first hint beats a match on a later one) so e.g. full_name binds to
    'Titel+Vorname+Name' before the lower-priority 'Vorname'. Exact > substring."""
    h = header.lower().strip()
    hints = _HEADER_HINTS.get(field, [])
    for i, kw in enumerate(hints):
        if h == kw:
            return 100 - i
    for i, kw in enumerate(hints):
        if len(kw) >= 4 and kw in h:
            return 50 - i
    return 0


def suggest_mapping(columns: dict) -> dict:
    """Pick ``{target_field: header}`` from per-column detected types — CONTENT first
    (so a 'Mail'-headed column that actually holds phones is NOT mapped to email),
    header-name hint as the tiebreaker. Each header maps to at most one field."""
    used: set[str] = set()
    m: dict[str, str] = {}

    def take(field: str, want_types: set[str]) -> None:
        best, best_key = None, (-1, -1.0)
        for h, info in columns.items():
            if h in used or info.get("type") not in want_types:
                continue
            key = (_hint_score(field, h), info.get("confidence", 0.0))
            if key > best_key:
                best, best_key = h, key
        if best:
            m[field] = best
            used.add(best)

    # High-precision content types first.
    take("email", {"email"})
    take("phone", {"landline"})
    take("phone2", {"mobile"})
    take("postal_code", {"postal_code"})
    take("customer_number", {"customer_number"})
    take("street", {"street"})
    take("city", {"city"})
    take("full_name", {"person_name"})
    # Fallbacks: a lone mobile can be the primary phone; a name field may read as city.
    if "phone" not in m:
        take("phone", {"mobile"})
    if "full_name" not in m:
        take("full_name", {"city", "free_text"})
    # Soft fields still unmapped → header hint only (never steal a typed column).
    for field in ("notes", "customer_number", "city", "street", "full_name", "phone2"):
        if field in m:
            continue
        for h in columns:
            if h not in used and _hint_score(field, h) >= 1:
                m[field] = h
                used.add(h)
                break
    return m


def preview_customers(content: bytes, sample_size: int = 50) -> dict:
    """Read-only: detect each column's content type from up to ``sample_size`` cells
    and propose a content-aware mapping. Powers the import dialog's live preview so a
    bad mapping is caught BEFORE anything is written."""
    headers, rows = parse_csv(content)
    columns: dict[str, dict] = {}
    for h in headers:
        samples: list[str] = []
        for r in rows:
            v = r.get(h)
            if v is not None and str(v).strip():
                samples.append(str(v).strip())
                if len(samples) >= sample_size:
                    break
        columns[h] = detect_column_type(samples)
    return {
        "headers": headers,
        "columns": columns,
        "suggested_mapping": suggest_mapping(columns),
        "row_count": len(rows),
    }


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

    # Read ALL existing customers (paged) — dedup is only idempotent if it sees
    # every prior row. A plain .execute() caps at ~1000, so on an org past 1000
    # customers a re-import of the same file would insert duplicates for rows 1001+.
    existing = fetch_all_rows(
        lambda: client.table("customers")
        .select("email, phone, phone2, full_name")
        .eq("org_id", org_id)
        .neq("status", "deleted")
    )

    # ── Dedup keys, each giving 100% assurance on its own trigger ──
    #   • email           — globally unique
    #   • mobile number   — unique to ONE person (German +49 15x/16x/17x)
    #   • landline + name — a landline is shareable (couple/business), so it is a
    #                       duplicate ONLY when the name also matches.
    seen_emails: set[str] = set()
    seen_mobiles: set[str] = set()
    seen_landline_names: dict[str, set[str]] = {}

    def _register(email_l: str | None, numbers: list[str], name_l: str) -> None:
        if email_l:
            seen_emails.add(email_l)
        for p in numbers:
            if classify_phone(p) == "mobile":
                seen_mobiles.add(p)
            else:  # landline or unknown → name-confirmed
                seen_landline_names.setdefault(p, set()).add(name_l)

    for e in existing:
        # Normalize legacy / manually-entered numbers that may not be E.164 yet, so
        # a re-import of the same file stays idempotent against older rows.
        nums = [n for n in (_to_e164(e.get("phone")), _to_e164(e.get("phone2"))) if n]
        _register(
            e["email"].lower() if e.get("email") else None,
            nums,
            (e.get("full_name") or "").strip().lower(),
        )

    # Auto-number sequence (KI-NNNNNN) for rows missing a Kundennummer. CSV rows
    # that DO carry a number keep it verbatim — it lives in its own namespace and
    # can't collide with the KI- auto numbers. gen_customer_number returns the NEXT
    # free KI- number, so seed from its sequence.
    ki_seq = ki_customer_seq(gen_customer_number(client, org_id)) or 1

    results: list[dict] = []
    corrections: list[dict] = []
    to_insert: list[dict] = []

    for i, row in enumerate(rows, start=1):
        full_name = _get(row, mapping, "full_name") or _get(row, mapping, "name")
        raw_email = _get(row, mapping, "email")
        email = _valid_email(raw_email)
        phone = clean_phone(_get(row, mapping, "phone"))
        phone2 = clean_phone(_get(row, mapping, "phone2"))

        # ── Guard: the source 'Mail' column did not actually hold an email. ──
        if raw_email and not email:
            if _looks_like_phone(raw_email):
                salvaged = clean_phone(raw_email)
                if salvaged and salvaged not in (phone, phone2):
                    slot = "phone" if not phone else ("phone2" if not phone2 else None)
                    if slot == "phone":
                        phone = salvaged
                    elif slot == "phone2":
                        phone2 = salvaged
                    if slot:
                        corrections.append({"row": i, "action": "phone_salvaged_from_email",
                                            "field_from": "email", "field_to": slot, "value": salvaged})
            else:
                corrections.append({"row": i, "action": "junk_email_dropped",
                                    "field_from": "email", "field_to": None, "value": raw_email})

        if not (full_name or email or phone or phone2):
            results.append({"row": i, "status": "error", "reason": "Kein Name/E-Mail/Telefon"})
            continue

        email_l = email.lower() if email else None
        name_l = (full_name or "").strip().lower()
        numbers = [n for n in (phone, phone2) if n]
        mobiles = [n for n in numbers if classify_phone(n) == "mobile"]
        landlines = [n for n in numbers if classify_phone(n) != "mobile"]

        dup_reason = None
        if email_l and email_l in seen_emails:
            dup_reason = "E-Mail existiert bereits"
        elif any(m in seen_mobiles for m in mobiles):
            dup_reason = "Mobilnummer existiert bereits"
        elif any(name_l in seen_landline_names.get(l, set()) for l in landlines):
            dup_reason = "Festnetz + Name existiert bereits"
        if dup_reason:
            results.append({"row": i, "status": "skipped_duplicate", "name": full_name,
                            "reason": dup_reason})
            continue

        num = _get(row, mapping, "customer_number")
        if num:
            num = str(num)  # keep the CSV's own Kundennummer verbatim
        else:
            num = f"KI-{ki_seq:06d}"
            ki_seq += 1

        street = _get(row, mapping, "street")
        plz = _get(row, mapping, "postal_code")
        city = _get(row, mapping, "city")
        address = None
        if street or plz or city:
            address = {"street": street, "postal_code": plz, "city": city}

        notes = _get(row, mapping, "notes")

        # ── Guard: an address stranded in the notes column → lift it into address. ──
        if address is None and notes:
            found = extract_address(notes)
            if found:
                address = found
                corrections.append({"row": i, "action": "address_from_notes",
                                    "field_from": "notes", "field_to": "address",
                                    "value": f"{found['street']}, {found['postal_code']} {found['city']}"})

        to_insert.append({
            "org_id": org_id,
            "full_name": full_name,
            "email": email,
            "phone": phone,
            # Second number lands in its own column; skip if identical to phone.
            "phone2": phone2 if (phone2 and phone2 != phone) else None,
            "address": address,
            "notes": notes,
            "customer_type": "regular",   # CSV import = Stammkunde, never "new"
            "identified_by": "csv_import",
            "customer_number": num,
        })
        _register(email_l, numbers, name_l)
        results.append({"row": i, "status": "imported", "name": full_name, "customer_number": num})

    inserted = 0
    for chunk in _chunks(to_insert, _CHUNK):
        inserted += len(client.table("customers").insert(chunk).execute().data or [])

    return _summary(rows, results, inserted, corrections)


# ─── employees ───────────────────────────────────────────────────────────────
def import_employees(org_id: str, content: bytes, mapping: dict) -> dict:
    client = get_service_client()
    _headers, rows = parse_csv(content)

    # Paged read (see import_customers): the dedup must see every existing employee.
    existing = fetch_all_rows(
        lambda: client.table("employees").select("email, display_name").eq("org_id", org_id)
    )
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


def _summary(
    rows: list, results: list[dict], inserted: int, corrections: list[dict] | None = None
) -> dict:
    corrections = corrections or []
    return {
        "total": len(rows),
        "imported": inserted,
        "skipped_duplicate": sum(1 for r in results if r["status"] == "skipped_duplicate"),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "corrected": len(corrections),
        "results": results,
        "corrections": corrections,
    }
