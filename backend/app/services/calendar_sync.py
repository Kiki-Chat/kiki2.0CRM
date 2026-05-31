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
from app.services.oauth_tokens import get_valid_access_token

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
