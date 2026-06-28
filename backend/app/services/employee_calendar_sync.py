"""Per-employee Google Calendar sync (read side).

PULL: mirror an employee's personal Google busy times into ``appointments`` as
OPAQUE blocked time so the availability engine and the admin master calendar see
when that person is busy — WITHOUT leaking their personal event details:

  • ``source='employee_busy'`` (distinct from the org/company 'google_import') so
    personal busy never reduces ORG-WIDE slot capacity — it blocks ONLY that
    employee (the availability engine counts it via ``assigned_employee_id``; the
    legacy org-wide slot finder excludes ``source='employee_busy'``).
  • title = "Gebucht", NO summary/notes/location copied (free-busy privacy).
  • ``google_event_id`` namespaced ``emp:<employee_id>:<gid>`` so it can never
    collide with the company import or another employee on the partial unique
    index ``(org_id, google_event_id)``.

Reuses the Google fetch + Berlin parsing from ``services.calendar_sync``; the
access token comes from ``services.employee_calendar`` (per-employee grant,
auto-refresh). The CRM→employee PUSH (appointments onto the phone) is a separate
step; this module is the read half + cleanup.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.db.supabase_client import get_service_client
from app.services import calendar_sync, employee_calendar, oauth_tokens

log = logging.getLogger(__name__)

SOURCE_EMPLOYEE_BUSY = "employee_busy"
_BUSY_TITLE = "Gebucht"  # opaque label — no personal event details leak to the admin
_DEFAULT_WINDOW_DAYS = 60


def _emp_gid(employee_id: str, gid: str) -> str:
    return f"emp:{employee_id}:{gid}"


def pull_employee_busy(
    org_id: str,
    employee_id: str,
    *,
    window_days: int = _DEFAULT_WINDOW_DAYS,
    now: datetime | None = None,
) -> dict:
    """Mirror the employee's Google busy times for ``[now, now+window_days]`` into
    opaque ``source='employee_busy'`` appointment rows. Insert-new / update-existing
    / cancel-vanished, scoped to this employee. Raises ``OAuthTokenError`` when the
    employee has no usable calendar connection."""
    now_dt = now or datetime.now(timezone.utc)
    time_min = now_dt.isoformat()
    time_max = (now_dt + timedelta(days=window_days)).isoformat()

    access_token = employee_calendar.get_valid_access_token(org_id, employee_id)
    events = calendar_sync._fetch_events(access_token, time_min, time_max)

    client = get_service_client()
    pushed = _employee_pushed_gids(client, org_id, employee_id)  # raw gids WE pushed → skip
    rows, seen = _to_busy_rows(org_id, employee_id, events, now_dt, skip_gids=pushed)
    existing = _existing_busy_rows(client, org_id, employee_id, time_min, time_max)
    created, updated = _apply(client, org_id, employee_id, rows, existing)
    cancelled = _reconcile_deletions(client, org_id, employee_id, existing, seen, now_dt)

    log.info(
        "employee_calendar_sync org=%s emp=%s fetched=%d created=%d updated=%d cancelled=%d",
        org_id, employee_id, len(events), created, updated, cancelled,
    )
    return {
        "success": True,
        "fetched": len(events),
        "created": created,
        "updated": updated,
        "cancelled": cancelled,
        "synced_at": now_dt.isoformat(),
    }


def purge_employee_busy(org_id: str, employee_id: str) -> int:
    """Delete an employee's mirrored busy blocks (on disconnect). Scoped strictly
    to ``source='employee_busy'`` for that employee — real CRM appointments
    assigned to them are NEVER touched."""
    rows = (
        get_service_client()
        .table("appointments")
        .delete()
        .eq("org_id", org_id)
        .eq("assigned_employee_id", employee_id)
        .eq("source", SOURCE_EMPLOYEE_BUSY)
        .execute()
        .data
        or []
    )
    log.info("employee_calendar_sync org=%s emp=%s purged=%d", org_id, employee_id, len(rows))
    return len(rows)


# ─── mapping (pure) ──────────────────────────────────────────────────────────
def _to_busy_rows(
    org_id: str, employee_id: str, events: list[dict], now_dt: datetime, *, skip_gids: set[str]
) -> tuple[list[dict], set[str]]:
    """Google events → opaque busy rows. Skips cancelled, transparent (free), and
    events WE pushed (echo-loop). Returns ``(rows, seen_prefixed_gids)``."""
    rows: list[dict] = []
    seen: set[str] = set()
    for ev in events:
        gid = ev.get("id")
        if not gid or ev.get("status") == "cancelled" or gid in skip_gids:
            continue
        if ev.get("transparency") == "transparent":
            continue  # "free" events don't block
        start = calendar_sync._event_dt(ev.get("start"))
        if not start:
            continue
        prefixed = _emp_gid(employee_id, gid)
        seen.add(prefixed)
        end = calendar_sync._event_dt(ev.get("end"))
        duration = 60
        if end and end > start:
            duration = max(15, int((end - start).total_seconds() // 60))
        rows.append(
            {
                "org_id": org_id,
                "assigned_employee_id": employee_id,
                "google_event_id": prefixed,
                "source": SOURCE_EMPLOYEE_BUSY,
                "title": _BUSY_TITLE,  # opaque — no summary/notes/location
                "scheduled_at": start.astimezone(timezone.utc).isoformat(),
                "duration_minutes": duration,
                "status": "confirmed",  # counts as the employee's blocked time
                "category": "google",
                "external_updated_at": ev.get("updated"),
                "last_synced_at": now_dt.isoformat(),
            }
        )
    return rows, seen


# ─── DB apply / reconcile (scoped to the employee) ───────────────────────────
def _existing_busy_rows(
    client, org_id: str, employee_id: str, time_min: str, time_max: str
) -> dict[str, dict]:
    rows = (
        client.table("appointments")
        .select("id, google_event_id, status")
        .eq("org_id", org_id)
        .eq("assigned_employee_id", employee_id)
        .eq("source", SOURCE_EMPLOYEE_BUSY)
        .gte("scheduled_at", time_min)
        .lte("scheduled_at", time_max)
        .execute()
        .data
        or []
    )
    return {r["google_event_id"]: r for r in rows if r.get("google_event_id")}


def _apply(
    client, org_id: str, employee_id: str, rows: list[dict], existing: dict[str, dict]
) -> tuple[int, int]:
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
    client, org_id: str, employee_id: str, existing: dict[str, dict], seen: set[str], now_dt: datetime
) -> int:
    """Cancel mirrored busy rows no longer present in the employee's Google (so
    they stop blocking the employee)."""
    stale = [g for g, r in existing.items() if g not in seen and r.get("status") != "cancelled"]
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


def _employee_pushed_gids(client, org_id: str, employee_id: str) -> set[str]:
    """Raw Google event ids WE pushed into this employee's calendar
    (``appointments.employee_google_event_id``). The pull skips these so a pushed
    appointment is never re-imported as a duplicate 'Gebucht' block."""
    rows = (
        client.table("appointments")
        .select("employee_google_event_id")
        .eq("org_id", org_id)
        .eq("assigned_employee_id", employee_id)
        .execute()
        .data
        or []
    )
    return {r["employee_google_event_id"] for r in rows if r.get("employee_google_event_id")}


# ─── PUSH: CRM appointment → the assigned employee's own Google calendar ──────
def push_appointment_to_employee(org_id: str, appointment_id: str) -> str | None:
    """Best-effort: write a CRM appointment into its ASSIGNED employee's OWN Google
    calendar, so the confirmed job shows up on their phone. Stores the returned
    event id in ``appointments.employee_google_event_id``.

    No-ops (returns None) when: the row is external busy/import; nobody is
    assigned; the appointment was already pushed (idempotent); or the employee
    hasn't connected their calendar. NEVER raises — a push hiccup must never block
    the confirm/booking it rides behind."""
    try:
        client = get_service_client()
        appt = (
            client.table("appointments")
            .select(
                "id, source, status, assigned_employee_id, title, scheduled_at, "
                "duration_minutes, notes, location, employee_google_event_id"
            )
            .eq("org_id", org_id)
            .eq("id", appointment_id)
            .limit(1)
            .execute()
            .data
            or [None]
        )[0]
        if not appt:
            return None
        if appt.get("source") in (SOURCE_EMPLOYEE_BUSY, calendar_sync.SOURCE_GOOGLE):
            return None  # external busy/import — never push back (echo-loop)
        emp_id = appt.get("assigned_employee_id")
        if not emp_id or appt.get("employee_google_event_id"):
            return None  # unassigned, or already pushed (idempotent)
        try:
            access_token = employee_calendar.get_valid_access_token(org_id, emp_id)
        except oauth_tokens.OAuthTokenError:
            return None  # employee hasn't connected their calendar — nothing to push
        gid = calendar_sync._insert_event(access_token, calendar_sync._appointment_to_gcal_event(appt))
        if gid:
            client.table("appointments").update({"employee_google_event_id": gid}).eq(
                "org_id", org_id
            ).eq("id", appointment_id).execute()
        log.info("employee_push org=%s appt=%s emp=%s gid=%s", org_id, appointment_id, emp_id, gid)
        return gid
    except Exception as exc:  # noqa: BLE001 — push is best-effort
        log.warning("employee_push failed appt=%s: %s", appointment_id, exc)
        return None


def remove_appointment_from_employee(org_id: str, appointment_id: str, *, employee_id: str | None) -> bool:
    """Best-effort: delete the appointment's event from ``employee_id``'s Google
    calendar and clear the stored link. Used on cancel / delete / reassign (pass
    the employee whose calendar holds it). NEVER raises."""
    try:
        client = get_service_client()
        appt = (
            client.table("appointments")
            .select("employee_google_event_id")
            .eq("org_id", org_id)
            .eq("id", appointment_id)
            .limit(1)
            .execute()
            .data
            or [None]
        )[0]
        gid = (appt or {}).get("employee_google_event_id")
        if not gid or not employee_id:
            return False
        ok = False
        try:
            access_token = employee_calendar.get_valid_access_token(org_id, employee_id)
            ok = _delete_event(access_token, gid)
        except oauth_tokens.OAuthTokenError:
            pass  # can't reach the calendar — still clear our link below
        client.table("appointments").update({"employee_google_event_id": None}).eq(
            "org_id", org_id
        ).eq("id", appointment_id).execute()
        return ok
    except Exception as exc:  # noqa: BLE001 — removal is best-effort
        log.warning("employee_remove failed appt=%s: %s", appointment_id, exc)
        return False


def _delete_event(access_token: str, gid: str) -> bool:
    """DELETE a Google Calendar event; 404/410 (already gone) count as success."""
    import httpx

    try:
        with httpx.Client(timeout=15.0) as c:
            r = c.delete(
                f"{calendar_sync._EVENTS_URL}/{gid}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        return r.status_code in (200, 204, 404, 410)
    except Exception:  # noqa: BLE001 — best-effort
        return False
