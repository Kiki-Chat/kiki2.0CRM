"""Google Calendar → CRM read sync (calendar Phase 1).

``pull_google_events(org_id)`` reads the org's Google **primary** calendar for a
forward window and mirrors the events into ``appointments`` as
``source='google_import'`` — read-only "blocked time", so the CRM and the AI
slot finder (``get_available_slots``, which counts confirmed appointments) see
the owner's real Google commitments.

Strictly ONE-DIRECTIONAL (READ): this module NEVER writes to Google.

Idempotency is done in code (select-existing → insert-new / update-existing),
keyed on ``(org_id, google_event_id)``. The DB has a *partial* unique index on
those columns as an integrity guard; we deliberately do NOT use PostgREST
upsert/ON CONFLICT (a partial index can't be inferred as a conflict arbiter).
Full-window reconcile: events that vanished from Google since the last sync are
flipped to ``status='cancelled'`` so they stop blocking slots (handles deletions
without a syncToken; incremental syncToken is a later optimization).

Access token via ``oauth_tokens.get_valid_access_token(org_id, 'google')``
(auto-refresh). Requires a google ``oauth_connection`` whose consent included the
calendar scope (granted at connect).

External calls are at module scope so tests can monkeypatch them (no network).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.db.supabase_client import get_service_client
from app.services.common import BERLIN
from app.services.oauth_tokens import calendar_provider, get_valid_access_token

log = logging.getLogger(__name__)

_TIMEOUT = 30.0
_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
SOURCE_GOOGLE = "google_import"
_DEFAULT_WINDOW_DAYS = 60
_PAGE_SIZE = 250


# ─── Public API ──────────────────────────────────────────────────────────────
def pull_google_events(
    org_id: str, *, window_days: int = _DEFAULT_WINDOW_DAYS, now: datetime | None = None
) -> dict:
    """Sync the org's Google primary-calendar events for ``[now, now+window_days]``
    into ``appointments`` (source='google_import'). Returns a summary dict.

    Raises ``oauth_tokens.OAuthTokenError`` when the org has no usable google
    connection (the caller maps that to a 409 telling the user to (re)connect).
    """
    now_dt = now or datetime.now(timezone.utc)
    time_min = now_dt.isoformat()
    time_max = (now_dt + timedelta(days=window_days)).isoformat()

    access_token = get_valid_access_token(org_id, "google")
    events = _fetch_events(access_token, time_min, time_max)
    rows, seen_ids = _to_rows(org_id, events, now_dt)

    client = get_service_client()
    # Echo-loop guard (PULL side): never re-import an event WE pushed to Google.
    # Such events are owned by a source='crm' appointment that already holds their
    # google_event_id; importing them as google_import would both duplicate the
    # appointment and collide with the unique (org_id, google_event_id) index.
    pushed_ids = _crm_owned_event_ids(client, org_id)
    if pushed_ids:
        rows = [r for r in rows if r["google_event_id"] not in pushed_ids]
    existing = _existing_google_rows(client, org_id, time_min, time_max)  # gid -> {id,status}
    created, updated = _apply_rows(client, org_id, rows, existing)
    cancelled = _reconcile_deletions(client, org_id, existing, seen_ids, now_dt)

    log.info(
        "calendar_sync org=%s fetched=%d created=%d updated=%d cancelled=%d window_days=%d",
        org_id, len(events), created, updated, cancelled, window_days,
    )
    return {
        "success": True,
        "fetched": len(events),
        "created": created,
        "updated": updated,
        "cancelled": cancelled,
        "synced_at": now_dt.isoformat(),
        "window_days": window_days,
    }


def purge_imported_events(org_id: str) -> int:
    """Delete all sync-imported (``source='google_import'``) events for the org.

    Called when the CALENDAR provider is disconnected, so stale imported
    blocked-time doesn't survive and pollute a later-linked provider's view.
    Scoped strictly to ``source='google_import'`` — the user's own native
    appointments (``source='crm'``) and ICS imports (``source='ics'``) are
    NEVER touched."""
    rows = (
        get_service_client()
        .table("appointments")
        .delete()
        .eq("org_id", org_id)
        .eq("source", SOURCE_GOOGLE)
        .execute()
        .data
        or []
    )
    log.info("calendar_sync org=%s purged_imported=%d", org_id, len(rows))
    return len(rows)


# ─── Google fetch (READ-ONLY) ────────────────────────────────────────────────
def _fetch_events(access_token: str, time_min: str, time_max: str) -> list[dict]:
    """GET primary-calendar events in ``[time_min, time_max]``, recurrences
    expanded (``singleEvents=true``). Paginates fully. READ-ONLY GET — never
    mutates Google. Raises on non-200."""
    out: list[dict] = []
    page_token: str | None = None
    headers = {"Authorization": f"Bearer {access_token}"}
    with httpx.Client(timeout=_TIMEOUT) as client:
        while True:
            params: dict = {
                "timeMin": time_min,
                "timeMax": time_max,
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": _PAGE_SIZE,
            }
            if page_token:
                params["pageToken"] = page_token
            r = client.get(_EVENTS_URL, params=params, headers=headers)
            if r.status_code != 200:
                raise RuntimeError(f"google calendar list {r.status_code}: {r.text[:300]}")
            data = r.json() or {}
            out.extend(data.get("items") or [])
            page_token = data.get("nextPageToken")
            if not page_token:
                break
    return out


# ─── Mapping (pure) ──────────────────────────────────────────────────────────
def _to_rows(
    org_id: str, events: list[dict], now_dt: datetime
) -> tuple[list[dict], set[str]]:
    """Map Google events → appointment rows. Pure (no I/O). Returns
    ``(rows, seen_event_ids)``. Cancelled events are skipped (reconcile handles
    them); both timed and all-day events produce a row."""
    rows: list[dict] = []
    seen: set[str] = set()
    for ev in events:
        gid = ev.get("id")
        if not gid or ev.get("status") == "cancelled":
            continue
        start = _event_dt(ev.get("start"))
        if not start:
            continue
        seen.add(gid)
        end = _event_dt(ev.get("end"))
        duration = 60
        if end and end > start:
            duration = max(15, int((end - start).total_seconds() // 60))
        rows.append(
            {
                "org_id": org_id,
                "google_event_id": gid,
                "source": SOURCE_GOOGLE,
                "title": ev.get("summary") or "(Google-Termin)",
                "scheduled_at": start.astimezone(timezone.utc).isoformat(),
                "duration_minutes": duration,
                "location": {"raw": ev["location"]} if ev.get("location") else None,
                "notes": ev.get("description"),
                "status": "confirmed",  # counts as blocked time in get_available_slots
                "category": "google",
                "external_updated_at": ev.get("updated"),
                "last_synced_at": now_dt.isoformat(),
            }
        )
    return rows, seen


def _event_dt(node: dict | None) -> datetime | None:
    """Parse a Google start/end node: ``{'dateTime': ISO}`` (timed) or
    ``{'date': 'YYYY-MM-DD'}`` (all-day → 00:00 Berlin). tz-aware or None."""
    if not node:
        return None
    dt = node.get("dateTime")
    if dt:
        try:
            return datetime.fromisoformat(str(dt).replace("Z", "+00:00"))
        except ValueError:
            return None
    date = node.get("date")
    if date:
        try:
            return datetime.strptime(str(date), "%Y-%m-%d").replace(tzinfo=BERLIN)
        except ValueError:
            return None
    return None


# ─── DB apply (insert-or-update; no upsert, partial index stays the guard) ───
def _existing_google_rows(client, org_id: str, time_min: str, time_max: str) -> dict[str, dict]:
    """Map ``google_event_id -> {id, status}`` for this org's google_import rows
    in the window (used to split insert vs update and to reconcile deletions)."""
    rows = (
        client.table("appointments")
        .select("id, google_event_id, status")
        .eq("org_id", org_id)
        .eq("source", SOURCE_GOOGLE)
        .gte("scheduled_at", time_min)
        .lte("scheduled_at", time_max)
        .execute()
        .data
        or []
    )
    return {r["google_event_id"]: r for r in rows if r.get("google_event_id")}


def _apply_rows(client, org_id: str, rows: list[dict], existing: dict[str, dict]) -> tuple[int, int]:
    """Insert new google events; update those already mirrored (also un-cancels a
    re-appeared event, since the row sets status='confirmed')."""
    created = updated = 0
    to_insert: list[dict] = []
    for row in rows:
        gid = row["google_event_id"]
        if gid in existing:
            patch = {k: v for k, v in row.items() if k not in ("org_id", "google_event_id")}
            client.table("appointments").update(patch).eq("org_id", org_id).eq(
                "google_event_id", gid
            ).execute()
            updated += 1
        else:
            to_insert.append(row)
    if to_insert:
        created = len(client.table("appointments").insert(to_insert).execute().data or [])
    return created, updated


def _reconcile_deletions(
    client, org_id: str, existing: dict[str, dict], seen_ids: set[str], now_dt: datetime
) -> int:
    """Flip previously-synced google_import rows no longer present in Google to
    ``status='cancelled'`` so they stop blocking slots."""
    stale = [
        gid
        for gid, r in existing.items()
        if gid not in seen_ids and r.get("status") != "cancelled"
    ]
    cancelled = 0
    for gid in stale:
        cancelled += len(
            client.table("appointments")
            .update({"status": "cancelled", "last_synced_at": now_dt.isoformat()})
            .eq("org_id", org_id)
            .eq("google_event_id", gid)
            .execute()
            .data
            or []
        )
    return cancelled


# ─── Echo-loop guard helper (pull side) ──────────────────────────────────────
def _crm_owned_event_ids(client, org_id: str) -> set[str]:
    """``google_event_id``s held by source='crm' appointments — i.e. events WE
    pushed to Google. The pull skips these (see pull_google_events)."""
    rows = (
        client.table("appointments")
        .select("google_event_id")
        .eq("org_id", org_id)
        .eq("source", "crm")
        .execute()
        .data
        or []
    )
    return {r["google_event_id"] for r in rows if r.get("google_event_id")}


# ─── Calendar write-back (Phase 4): per-event, approval-gated push ───────────
class CalendarWriteError(Exception):
    """A push-to-Google failure carrying an HTTP status for the route to surface."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def push_crm_event_to_google(org_id: str, appointment_id: str) -> dict:
    """Push ONE CRM-native appointment to the org's Google calendar
    (``events.insert``) and store the returned ``google_event_id`` on the row.

    ECHO-LOOP GUARD (push side): ONLY ``source='crm'`` appointments are pushable.
    A ``source='google_import'`` event came FROM Google — pushing it back would
    loop — so it is rejected here (and the UI shows no push affordance for it).
    One-directional: this only ever INSERTS; it never reads back or deletes.
    Idempotent: an appointment that already has a ``google_event_id`` is not
    re-inserted.
    """
    client = get_service_client()
    appt = (
        client.table("appointments")
        .select("id, source, google_event_id, title, scheduled_at, duration_minutes, notes, location")
        .eq("org_id", org_id)
        .eq("id", appointment_id)
        .limit(1)
        .execute()
        .data
        or [None]
    )[0]
    if not appt:
        raise CalendarWriteError("Termin nicht gefunden.", 404)
    # ECHO-LOOP GUARD — only CRM-native appointments may be pushed.
    if appt.get("source") != "crm":
        raise CalendarWriteError(
            "Nur eigene CRM-Termine können zu Google übertragen werden — "
            "importierte Termine nicht.",
            400,
        )
    if appt.get("google_event_id"):
        return {
            "success": True,
            "already_pushed": True,
            "google_event_id": appt["google_event_id"],
        }

    if calendar_provider(org_id) != "google":
        raise CalendarWriteError(
            "Kein Google-Kalender verbunden — bitte zuerst den Kalender verbinden.", 409
        )
    access_token = get_valid_access_token(org_id, "google")
    gid = _insert_event(access_token, _appointment_to_gcal_event(appt))

    client.table("appointments").update({"google_event_id": gid}).eq("org_id", org_id).eq(
        "id", appointment_id
    ).execute()
    log.info("calendar_push org=%s appt=%s google_event_id=%s", org_id, appointment_id, gid)
    return {"success": True, "google_event_id": gid}


def _appointment_to_gcal_event(appt: dict) -> dict:
    """Build a Google Calendar event body from a CRM appointment."""
    start = _parse_stored_iso(appt.get("scheduled_at"))
    if not start:
        raise CalendarWriteError("Termin hat kein gültiges Datum.", 400)
    end = start + timedelta(minutes=int(appt.get("duration_minutes") or 60))
    loc = appt.get("location")
    loc_str = loc.get("raw") if isinstance(loc, dict) else (loc if isinstance(loc, str) else None)
    body: dict = {
        "summary": appt.get("title") or "Termin",
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
    }
    if appt.get("notes"):
        body["description"] = appt["notes"]
    if loc_str:
        body["location"] = loc_str
    return body


def _parse_stored_iso(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _insert_event(access_token: str, body: dict) -> str | None:
    """POST ``events.insert`` to the primary calendar; returns the new event id."""
    with httpx.Client(timeout=_TIMEOUT) as client:
        r = client.post(
            _EVENTS_URL,
            json=body,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )
    if r.status_code not in (200, 201):
        raise CalendarWriteError(f"google calendar insert {r.status_code}: {r.text[:300]}", 502)
    return (r.json() or {}).get("id")
