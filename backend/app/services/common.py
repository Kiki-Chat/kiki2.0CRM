"""Shared helpers for the ElevenLabs tool handlers.

Datetime parsing is best-effort over the natural-language date/time strings the
agent passes (German + English). Spoken `message` fields are German (production
language). All times are handled in Europe/Berlin.
"""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException

BERLIN = ZoneInfo("Europe/Berlin")


def validate_fk_in_org(
    client,
    *,
    table: str,
    fk_id: str | None,
    org_id: str,
    label: str,
    require_active: bool = False,
) -> None:
    """Reject a cross-tenant foreign-key pointer (FK hardening, Item 1).

    When ``fk_id`` is set, confirm a row with that id exists in ``table`` *within
    the caller's org*; raise HTTP 422 otherwise. This stops a caller from
    attaching another org's customer / project / employee / inquiry id to a row
    in their own org — a dangling cross-tenant pointer (integrity, not a leak).

    A falsy ``fk_id`` (``None`` / ``""``) is a deliberate no-op: clearing or
    omitting an optional FK is always allowed. ``require_active=True`` adds the
    ``deleted = False`` filter (only the ``employees`` table has that boolean
    soft-delete — ``inquiries`` use a ``status='deleted'`` value, not a column).

    Centralises the same-org check first shipped at ``inquiries._assign`` /
    ``projects.add_project_employee`` so every write path validates FKs the same
    way, with the same German message.
    """
    if not fk_id:
        return
    q = client.table(table).select("id").eq("org_id", org_id).eq("id", fk_id)
    if require_active:
        q = q.eq("deleted", False)
    if not (q.limit(1).execute().data or []):
        raise HTTPException(
            status_code=422,
            detail=f"{label} gehört nicht zu dieser Organisation.",
        )


def enforce_self_assignment(
    client,
    *,
    user,
    current_assignee_id: str | None,
    new_assignee_id: str | None,
) -> None:
    """Authorization: a plain employee may only manage assignments on their OWN
    work. Admins (org_admin / super_admin) may assign to anyone in the org.

    Raises 403 when a non-admin tries to (a) hand work to an employee other than
    themselves, or (b) re-/un-assign work currently owned by a different
    employee. Self-claim and dropping one's own assignment stay allowed.

    ``user`` is a CurrentUser (duck-typed: .role, .org_id, .id). The caller's own
    employee row is resolved by users.id → employees.user_id.
    """
    if getattr(user, "role", None) in ("org_admin", "super_admin"):
        return
    rows = (
        client.table("employees")
        .select("id")
        .eq("org_id", user.org_id)
        .eq("user_id", user.id)
        .eq("deleted", False)
        .limit(1)
        .execute()
        .data
    )
    my_id = rows[0]["id"] if rows else None
    if current_assignee_id and current_assignee_id != my_id:
        raise HTTPException(
            status_code=403,
            detail="Sie können nur Ihre eigenen Aufgaben verwalten.",
        )
    if new_assignee_id and new_assignee_id != my_id:
        raise HTTPException(
            status_code=403,
            detail="Sie können Aufgaben nur sich selbst zuweisen.",
        )


_WEEKDAYS = {
    "montag": 0, "monday": 0, "dienstag": 1, "tuesday": 1, "mittwoch": 2,
    "wednesday": 2, "donnerstag": 3, "thursday": 3, "freitag": 4, "friday": 4,
    "samstag": 5, "saturday": 5, "sonntag": 6, "sunday": 6,
}

_MONTHS = {
    "jan": 1, "januar": 1, "january": 1, "feb": 2, "februar": 2, "february": 2,
    "mar": 3, "mär": 3, "maerz": 3, "märz": 3, "march": 3, "apr": 4, "april": 4,
    "mai": 5, "may": 5, "jun": 6, "juni": 6, "june": 6, "jul": 7, "juli": 7,
    "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "okt": 10, "oct": 10, "oktober": 10, "october": 10, "nov": 11, "november": 11,
    "dez": 12, "dec": 12, "dezember": 12, "december": 12,
}


def now_berlin() -> datetime:
    return datetime.now(BERLIN)


def format_address(addr) -> str | None:
    if addr is None:
        return None
    if isinstance(addr, str):
        return addr or None
    if isinstance(addr, dict):
        if addr.get("raw"):
            return addr["raw"]
        street = addr.get("street")
        city = addr.get("city")
        postal = addr.get("postal_code") or addr.get("zip")
        parts = [p for p in [street, " ".join(x for x in [postal, city] if x)] if p]
        return ", ".join(parts) or None
    return None


def _to_berlin(dt: datetime) -> datetime:
    return dt.astimezone(BERLIN) if dt.tzinfo else dt.replace(tzinfo=BERLIN)


def fmt_date(dt: datetime) -> str:
    return _to_berlin(dt).strftime("%d. %b").lstrip("0")


def fmt_time(dt: datetime) -> str:
    return _to_berlin(dt).strftime("%H:%M")


def _parse_date(s: str, now: datetime) -> datetime | None:
    s = s.strip().lower()

    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        try:
            return now.replace(year=int(m[1]), month=int(m[2]), day=int(m[3]))
        except ValueError:
            return None

    m = re.match(r"(\d{1,2})\.(\d{1,2})\.?(\d{4})?", s)
    if m:
        day, month = int(m[1]), int(m[2])
        year = int(m[3]) if m[3] else now.year
        try:
            cand = now.replace(year=year, month=month, day=day)
        except ValueError:
            return None
        if not m[3] and cand.date() < now.date():
            try:
                cand = cand.replace(year=year + 1)
            except ValueError:
                return None
        return cand

    if s in ("today", "heute"):
        return now
    if s in ("tomorrow", "morgen"):
        return now + timedelta(days=1)
    if s in ("day after tomorrow", "übermorgen", "uebermorgen"):
        return now + timedelta(days=2)

    for name, idx in _WEEKDAYS.items():
        if name in s:
            delta = (idx - now.weekday()) % 7
            if delta == 0:
                delta = 7
            return now + timedelta(days=delta)

    # "27. mai" / "27 may"
    m = re.search(r"(\d{1,2})\.?\s*([a-zä]+)", s)
    if m and m[2] in _MONTHS:
        day, month = int(m[1]), _MONTHS[m[2]]
        return _from_day_month(now, day, month)
    # "mai 27" / "may 27"
    m = re.search(r"([a-zä]+)\.?\s*(\d{1,2})", s)
    if m and m[1] in _MONTHS:
        day, month = int(m[2]), _MONTHS[m[1]]
        return _from_day_month(now, day, month)

    return None


def _from_day_month(now: datetime, day: int, month: int) -> datetime | None:
    year = now.year
    try:
        cand = now.replace(year=year, month=month, day=day)
    except ValueError:
        return None
    if cand.date() < now.date():
        try:
            cand = cand.replace(year=year + 1)
        except ValueError:
            return None
    return cand


def parse_when(date_str: str | None, time_str: str | None = None) -> datetime | None:
    """Parse a natural-language date (+ optional time) into a Berlin datetime."""
    if not date_str:
        return None
    now = now_berlin()
    d = _parse_date(date_str, now)
    if d is None:
        return None

    hour, minute = 9, 0
    if time_str:
        m = re.search(r"(\d{1,2})[:.h](\d{2})", time_str)
        if m:
            hour, minute = int(m[1]), int(m[2])
        else:
            m = re.search(r"(\d{1,2})\s*(am|pm|uhr)?", time_str.lower())
            if m:
                hour = int(m[1])
                if m[2] == "pm" and hour < 12:
                    hour += 12
                minute = 0
    return d.replace(hour=hour, minute=minute, second=0, microsecond=0)


def slot_key(dt: datetime) -> str:
    """Normalised minute-precision key in Berlin time for collision checks."""
    return dt.astimezone(BERLIN).strftime("%Y-%m-%dT%H:%M")


def gen_inquiry_number(client, org_id: str) -> str:
    year = now_berlin().year
    res = (
        client.table("inquiries")
        .select("id", count="exact")
        .eq("org_id", org_id)
        .gte("created_at", f"{year}-01-01")
        .execute()
    )
    return f"ANF-{year}-{(res.count or 0) + 1:04d}"


def gen_customer_number(client, org_id: str) -> str:
    """Next customer number = max existing numeric customer_number + 1 (per org),
    starting at 101001. Unified across the AI-tool, manual-create, and CSV-import
    paths so call-created customers continue the same numeric sequence as the
    imported ones (CSV rows keep their original Kundennummer)."""
    rows = (
        client.table("customers")
        .select("customer_number")
        .eq("org_id", org_id)
        .execute()
        .data
        or []
    )
    nums = [
        int(r["customer_number"])
        for r in rows
        if r.get("customer_number") and str(r["customer_number"]).isdigit()
    ]
    return str(max(nums) + 1 if nums else 101001)
