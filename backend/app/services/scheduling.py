"""Business-hours storage + helpers, shared by the calendar settings route and
the get_available_slots tool so slot suggestions respect the configured hours."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.db.supabase_client import get_service_client

# Business hours are stored without a timezone; this is a German-market product,
# so evaluate "is it open now" in Europe/Berlin.
_BERLIN = ZoneInfo("Europe/Berlin")

# Monday-first; index matches datetime.weekday().
WEEKDAY_KEYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def default_business_hours() -> dict:
    """Standard tradesperson week: Mon–Fri 08:00–17:00, weekend closed."""
    out: dict = {}
    for i, key in enumerate(WEEKDAY_KEYS):
        out[key] = {
            "open": i < 5,
            "start": "08:00",
            "end": "17:00",
            "break_start": None,
            "break_end": None,
        }
    return out


def _norm_time(value, fallback: str | None) -> str | None:
    if not value:
        return fallback
    s = str(value).strip()
    # Accept "8", "8:0", "08:00" → "HH:MM".
    if ":" in s:
        h, m = s.split(":", 1)
    else:
        h, m = s, "0"
    try:
        return f"{int(h):02d}:{int(m):02d}"
    except ValueError:
        return fallback


def normalize_business_hours(raw: dict | None) -> dict:
    """Merge stored hours over defaults, coercing types and time formats."""
    base = default_business_hours()
    if not isinstance(raw, dict):
        return base
    for key in WEEKDAY_KEYS:
        day = raw.get(key)
        if not isinstance(day, dict):
            continue
        d = base[key]
        if "open" in day:
            d["open"] = bool(day["open"])
        d["start"] = _norm_time(day.get("start"), d["start"])
        d["end"] = _norm_time(day.get("end"), d["end"])
        d["break_start"] = _norm_time(day.get("break_start"), None)
        d["break_end"] = _norm_time(day.get("break_end"), None)
        if not (d["break_start"] and d["break_end"]):
            d["break_start"] = d["break_end"] = None
    return base


def get_scheduling(org_id: str) -> dict:
    client = get_service_client()
    rows = (
        client.table("agent_configs")
        .select("scheduling")
        .eq("org_id", org_id)
        .limit(1)
        .execute()
        .data
    )
    sched = (rows[0].get("scheduling") if rows and rows[0].get("scheduling") else {}) or {}
    sched["business_hours"] = normalize_business_hours(sched.get("business_hours"))
    return sched


def save_business_hours(org_id: str, business_hours: dict) -> dict:
    """Upsert agent_configs.scheduling.business_hours for the org."""
    client = get_service_client()
    rows = (
        client.table("agent_configs")
        .select("scheduling")
        .eq("org_id", org_id)
        .limit(1)
        .execute()
        .data
    )
    sched = (rows[0].get("scheduling") if rows and rows[0].get("scheduling") else {}) or {}
    sched["business_hours"] = normalize_business_hours(business_hours)
    if rows:
        client.table("agent_configs").update({"scheduling": sched}).eq(
            "org_id", org_id
        ).execute()
    else:
        client.table("agent_configs").insert(
            {"org_id": org_id, "scheduling": sched}
        ).execute()
    return sched


def _within_hours(hours: dict, when: datetime) -> bool:
    """Is `when` inside the given business-hours map? Evaluated in Europe/Berlin;
    a naive datetime is treated as UTC."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    local = when.astimezone(_BERLIN)
    day = hours.get(WEEKDAY_KEYS[local.weekday()]) or {}
    if not day.get("open"):
        return False
    cur = local.strftime("%H:%M")
    if not (str(day.get("start") or "08:00") <= cur < str(day.get("end") or "17:00")):
        return False
    bs, be = day.get("break_start"), day.get("break_end")
    if bs and be and bs <= cur < be:  # inside a configured break = closed
        return False
    return True


def is_within_business_hours(org_id: str, when: datetime) -> bool:
    """True if `when` falls inside the org's configured business hours."""
    return _within_hours(get_scheduling(org_id)["business_hours"], when)


def is_emergency_by_hours(org_id: str, when: datetime) -> bool:
    """The deterministic 'after-hours call = Notdienst' rule: True when the org
    runs an emergency service (emergency_enabled) AND `when` is OUTSIDE business
    hours. One query fetches both the flag and the hours."""
    client = get_service_client()
    rows = (
        client.table("agent_configs")
        .select("emergency_enabled, scheduling")
        .eq("org_id", org_id)
        .limit(1)
        .execute()
        .data
    )
    cfg = rows[0] if rows else {}
    if not cfg.get("emergency_enabled"):
        return False
    hours = normalize_business_hours((cfg.get("scheduling") or {}).get("business_hours"))
    return not _within_hours(hours, when)
