"""Vorgang (case) title helpers: German long-date formatting + per-customer
uniqueness.

A customer should never have two Vorgänge with the *same* title — identical headers
are confusing at a glance (which "Heizung defekt" is this?). So a colliding title
gets a readable German date suffix ("Heizung defekt · Samstag, 27. Juni"), and a
small counter only if even that collides (same problem, same day). Different
customers may freely share a title.

The date format mirrors ``outbound_occasions`` ("Mittwoch, 20. Mai") so the whole
product speaks one date dialect, locale-free.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_BERLIN = ZoneInfo("Europe/Berlin")
_DE_WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
# 1-indexed (index 0 unused) so _DE_MONTHS[dt.month] reads naturally.
_DE_MONTHS = ["", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
              "August", "September", "Oktober", "November", "Dezember"]
_MAX_TITLE = 120


def format_de_long_date(when: datetime | str | None = None) -> str:
    """'Samstag, 27. Juni' — spelled-out weekday + day + German month, Europe/Berlin,
    no locale needed. Accepts a datetime, an ISO string, or None (= now)."""
    if isinstance(when, str):
        try:
            when = datetime.fromisoformat(when.replace("Z", "+00:00"))
        except ValueError:
            when = None
    dt = when if isinstance(when, datetime) else datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(_BERLIN)
    return f"{_DE_WEEKDAYS[dt.weekday()]}, {dt.day}. {_DE_MONTHS[dt.month]}"


def existing_case_titles(
    client, org_id: str, customer_id: str | None, exclude_id: str | None = None
) -> set[str]:
    """The set of Vorgang titles already used by this customer (for collision checks).
    Empty for a customer-less case (no scope to collide within)."""
    if not customer_id:
        return set()
    rows = (
        client.table("cases")
        .select("id, title")
        .eq("org_id", org_id)
        .eq("customer_id", customer_id)
        .execute()
        .data
        or []
    )
    return {
        (r.get("title") or "").strip()
        for r in rows
        if r.get("id") != exclude_id and (r.get("title") or "").strip()
    }


def make_unique_case_title(
    base_title: str | None, taken: set[str], when: datetime | str | None = None
) -> str:
    """A Vorgang title guaranteed not to collide with ``taken``.

    Returns ``base_title`` unchanged when it's free; otherwise appends a readable
    German date ("… · Samstag, 27. Juni"), then a small counter only if the date also
    collides. When creating several titles in one batch, add each result to ``taken``
    so siblings don't collide with each other.
    """
    base = (base_title or "Vorgang").strip()[:_MAX_TITLE] or "Vorgang"
    if base not in taken:
        return base
    dated = f"{base} · {format_de_long_date(when)}"[:_MAX_TITLE]
    if dated not in taken:
        return dated
    n = 2
    while True:
        candidate = f"{base} · {format_de_long_date(when)} ({n})"[:_MAX_TITLE]
        if candidate not in taken:
            return candidate
        n += 1
