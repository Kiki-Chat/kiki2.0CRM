"""Shared helpers for the ElevenLabs tool handlers.

Datetime parsing is best-effort over the natural-language date/time strings the
agent passes (German + English). Spoken `message` fields are German (production
language). All times are handled in Europe/Berlin.
"""

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException

BERLIN = ZoneInfo("Europe/Berlin")


def fetch_all_rows(make_query, page: int = 1000) -> list[dict]:
    """Fetch EVERY row of a PostgREST select, paging past the silent ~1000-row cap.

    PostgREST returns at most ~1000 rows for a plain ``.execute()``. Any read whose
    *correctness* depends on seeing all rows — dedup, max-number, full counts — must
    page explicitly or it silently truncates (and, e.g., re-imports duplicate
    customers). ``make_query`` must return a FRESH query builder (all filters set,
    NO ``.range``/``.execute``) on each call, e.g.::

        fetch_all_rows(lambda: client.table("customers")
                       .select("email").eq("org_id", org_id))

    The ``page`` size must stay ≤ 1000 (PostgREST's own per-request ceiling).
    """
    rows: list[dict] = []
    offset = 0
    while True:
        chunk = make_query().range(offset, offset + page - 1).execute().data or []
        rows.extend(chunk)
        if len(chunk) < page:
            return rows
        offset += page


def run_parallel(*funcs):
    """Run independent zero-arg callables concurrently; return results in call order.

    For fanning out independent Supabase reads inside a *sync* helper (the route
    already runs that helper via ``run_in_threadpool``). It uses a PRIVATE
    ``ThreadPoolExecutor`` — NOT AnyIO's request threadpool — so it can never starve
    the pool that serves other requests. The Supabase client's underlying
    ``httpx.Client`` is safe for concurrent request execution, and each ``.table()``
    builds an independent query, so concurrent reads don't share mutable state.
    Exceptions propagate exactly as they would serially (first failure raises).
    """
    if not funcs:
        return []
    if len(funcs) == 1:
        return [funcs[0]()]
    with ThreadPoolExecutor(max_workers=min(len(funcs), 8)) as ex:
        futures = [ex.submit(f) for f in funcs]
        return [f.result() for f in futures]


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

# German clock words for natural-language times ("halb drei", "nachmittags").
_NUM_WORDS = {
    "eins": 1, "ein": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "fuenf": 5,
    "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10, "elf": 11,
    "zwölf": 12, "zwoelf": 12,
}
_DAYPART_HOURS = {
    "morgens": 8, "früh": 8, "frueh": 8, "vormittags": 10, "vormittag": 10,
    "mittags": 12, "mittag": 12, "nachmittags": 14, "nachmittag": 14,
    "abends": 18, "abend": 18, "nachts": 20,
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

    # Relative weeks: "nächste/kommende Woche", "in N Wochen" (digits or words).
    week_offset = 0
    mw = re.search(r"in\s+(\d{1,2}|einer|zwei|drei|vier|fünf|fuenf)\s+woche", s)
    if mw:
        word = mw.group(1)
        week_offset = int(word) if word.isdigit() else {
            "einer": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "fuenf": 5,
        }.get(word, 1)
    elif re.search(r"n[äa]chste[nr]?\s+woche|kommende[nr]?\s+woche", s):
        week_offset = 1

    # Weekday, respecting any week offset and the "nächste/kommende" qualifier.
    wd_idx = next((idx for name, idx in _WEEKDAYS.items() if name in s), None)
    if wd_idx is not None:
        if week_offset > 0:
            base = now + timedelta(weeks=week_offset)
            monday = base - timedelta(days=base.weekday())
            return monday + timedelta(days=wd_idx)
        delta = (wd_idx - now.weekday()) % 7
        if delta == 0 and re.search(r"n[äa]chste[nr]?|kommende[nr]?", s):
            delta = 7  # "nächsten Montag" said on a Monday = next week's
        return now + timedelta(days=delta)
    if week_offset > 0:
        return now + timedelta(weeks=week_offset)

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


def _parse_time(time_str: str) -> tuple[int, int] | None:
    """Parse a German/numeric time expression to (hour, minute), or None when it
    can't be understood. Handles 'HH:MM', 'HH.MM', 'HHhMM', 'halb drei',
    'viertel nach/vor drei', day-parts ('nachmittags'), and bare hours ('15 Uhr')."""
    t = time_str.strip().lower()
    m = re.search(r"(\d{1,2})[:.h](\d{2})", t)
    if m:
        return int(m[1]), int(m[2])
    m = re.search(r"halb\s+(\w+)", t)  # "halb drei" = 02:30
    if m and m[1] in _NUM_WORDS:
        h = _NUM_WORDS[m[1]] - 1
        return (h if h >= 0 else 11), 30
    m = re.search(r"viertel\s+nach\s+(\w+)", t)  # "viertel nach drei" = 03:15
    if m and m[1] in _NUM_WORDS:
        return _NUM_WORDS[m[1]], 15
    m = re.search(r"(?:viertel\s+vor|dreiviertel)\s+(\w+)", t)  # = 02:45
    if m and m[1] in _NUM_WORDS:
        h = _NUM_WORDS[m[1]] - 1
        return (h if h >= 0 else 11), 45
    # Longest first so "nachmittags"/"vormittags" win over the "mittags" substring.
    for word in sorted(_DAYPART_HOURS, key=len, reverse=True):
        if word in t:
            return _DAYPART_HOURS[word], 0
    m = re.search(r"(\d{1,2})\s*(am|pm|uhr)?", t)
    if m:
        h = int(m[1])
        if m[2] == "pm" and h < 12:
            h += 12
        return h, 0
    for word, n in _NUM_WORDS.items():
        if re.search(rf"\b{word}\b", t):
            return n, 0
    return None


def parse_when(date_str: str | None, time_str: str | None = None) -> datetime | None:
    """Parse a natural-language date (+ optional time) into a Berlin datetime."""
    if not date_str:
        return None
    now = now_berlin()
    d = _parse_date(date_str, now)
    if d is None:
        return None

    hour, minute = 9, 0  # neutral default when no/unparseable time is given
    if time_str:
        parsed = _parse_time(time_str)
        if parsed:
            hour, minute = parsed
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


def gen_case_number(client, org_id: str) -> str:
    """Next staff-facing case (Fall) number: ``FALL-YYYY-NNNN`` per org."""
    year = now_berlin().year
    res = (
        client.table("cases")
        .select("id", count="exact")
        .eq("org_id", org_id)
        .gte("created_at", f"{year}-01-01")
        .execute()
    )
    return f"FALL-{year}-{(res.count or 0) + 1:04d}"


CUSTOMER_NUMBER_PREFIX = "KI-"


def ki_customer_seq(value: str | None) -> int | None:
    """Return the integer sequence of a ``KI-NNNNNN`` customer number, else None.

    Used to advance the auto-number sequence while ignoring legacy/manual numbers."""
    if isinstance(value, str) and value.startswith(CUSTOMER_NUMBER_PREFIX):
        tail = value[len(CUSTOMER_NUMBER_PREFIX):]
        if tail.isdigit():
            return int(tail)
    return None


def gen_customer_number(client, org_id: str) -> str:
    """Next auto-assigned customer number, AI-tagged and per-org: ``KI-000001``.

    The ``KI-`` prefix (Kiki / KI = Künstliche Intelligenz) marks every
    system-generated number so it can NEVER collide with a Kundennummer the
    business already uses on its own — which may itself be a plain number like
    101001. Only previously auto-generated ``KI-`` numbers advance the sequence;
    legacy numeric or manually-entered numbers are left untouched and ignored here.

    Pages past the 1000-row cap: customer_number is a *text* column holding the
    original (possibly non-numeric) Kundennummer, so we read every value and take
    the max KI- sequence in Python (a >1000-customer org would otherwise re-mint)."""
    rows = fetch_all_rows(
        lambda: client.table("customers").select("customer_number").eq("org_id", org_id)
    )
    seqs = [s for r in rows if (s := ki_customer_seq(r.get("customer_number"))) is not None]
    return f"{CUSTOMER_NUMBER_PREFIX}{(max(seqs) + 1 if seqs else 1):06d}"
