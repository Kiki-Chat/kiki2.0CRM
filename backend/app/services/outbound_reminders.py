"""Outbound appointment-reminder dispatch (P1).

Selection + dispatch for the reminder sweep. Fired by an external cron / N8N
hitting ``POST /api/outbound/run-due-reminders`` (secret-protected); the logic
lives here so it stays unit-testable independent of the trigger.

Per-org gating (read from ``agent_configs``):
  * ``outbound_enabled`` is true
  * ``outbound_occasions["appointment_reminder"]`` is true
  * "now" (Europe/Berlin) is within ``[outbound_time_from, outbound_time_to]``
  * today's weekday (Berlin) is in ``outbound_weekdays``

Selection: appointments ``N = appointment_reminder_days`` calendar days out
(Berlin local day), ``status`` in (pending, confirmed), ``reminder_sent_at``
IS NULL, customer has a phone. Idempotent — ``reminder_sent_at`` is stamped on
success so a re-run never re-dials.

``send_reminder_for_appointment`` is the per-appointment manual trigger
(ad-hoc + UAT); it bypasses the window/weekday/occasion gate and accepts a
``to_number_override`` so UAT can dial a designated test number instead of a
real customer's stored phone (safety rule).
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone

from app.db.supabase_client import get_service_client
from app.services.outbound_call import OutboundCallError, place_outbound_call

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo

    _BERLIN = ZoneInfo("Europe/Berlin")
except Exception:  # pragma: no cover — zoneinfo db unavailable in container
    logger.warning("Europe/Berlin tz unavailable; falling back to UTC for windows")
    _BERLIN = timezone.utc

_ACTIVE_STATUSES = ["pending", "confirmed"]
_WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_REMINDER_OCCASION = "appointment_reminder"
_DEFAULT_REMINDER_DAYS = 1


# ─── small parsers ───────────────────────────────────────────────────────────
def _parse_iso(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_clock(value) -> time | None:
    if value in (None, ""):
        return None
    if isinstance(value, time):
        return value
    parts = str(value).split(":")
    return time(hour=int(parts[0]), minute=int(parts[1]) if len(parts) > 1 else 0)


def _within_window(now_local: time, frm: time | None, to: time | None) -> bool:
    if frm is None or to is None:
        return True
    if frm <= to:
        return frm <= now_local <= to
    # Overnight window (e.g. 20:00–06:00): allow before `to` or after `frm`.
    return now_local >= frm or now_local <= to


def _build_dynamic_variables(*, customer_name, scheduled_at_iso, title, company_name) -> dict:
    dt_local = _parse_iso(scheduled_at_iso).astimezone(_BERLIN)
    return {
        "customer_name": customer_name or "",
        "appointment_date": dt_local.strftime("%d.%m.%Y"),
        "appointment_time": dt_local.strftime("%H:%M"),
        "appointment_title": title or "",
        "company_name": company_name or "",
    }


def _resolve_org(db, org_id: str) -> dict:
    rows = (
        db.table("organizations")
        .select("name, elevenlabs_agent_id, elevenlabs_phone_number_id")
        .eq("id", org_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else {}


# ─── dispatch ────────────────────────────────────────────────────────────────
def _dispatch_one(db, *, org, org_id, appt, customer, to_number_override, dry_run, now):
    """Place (or, when dry_run, preview) one reminder. Returns a result dict;
    ``{"skipped": "no_phone"}`` when there is no number to dial."""
    appt_id = appt["id"]
    to_number = to_number_override or (customer or {}).get("phone")
    if not to_number:
        return {"appointment_id": appt_id, "skipped": "no_phone"}

    dyn = _build_dynamic_variables(
        customer_name=(customer or {}).get("full_name"),
        scheduled_at_iso=appt["scheduled_at"],
        title=appt.get("title"),
        company_name=org.get("name"),
    )
    if dry_run:
        return {
            "appointment_id": appt_id,
            "to_number": to_number,
            "dynamic_variables": dyn,
            "dry_run": True,
        }

    result = place_outbound_call(
        agent_id=org["elevenlabs_agent_id"],
        agent_phone_number_id=org.get("elevenlabs_phone_number_id"),
        to_number=to_number,
        dynamic_variables=dyn,
    )
    db.table("appointments").update(
        {
            "reminder_conversation_id": result.get("conversation_id"),
            "reminder_call_sid": result.get("callSid"),
            "reminder_sent_at": now.astimezone(timezone.utc).isoformat(),
        }
    ).eq("id", appt_id).eq("org_id", org_id).execute()
    return {
        "appointment_id": appt_id,
        "to_number": to_number,
        "conversation_id": result.get("conversation_id"),
        "call_sid": result.get("callSid"),
    }


def run_due_reminders(
    *,
    now: datetime | None = None,
    only_org_id: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Sweep all (or one) outbound-enabled orgs and dispatch due reminders.

    Idempotent: appointments already stamped with ``reminder_sent_at`` are
    excluded by the query, so re-running the sweep never re-dials.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    db = get_service_client()

    summary: dict = {
        "ran_at": now.astimezone(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "orgs_processed": 0,
        "dispatched": 0,
        "calls": [],
        "skipped": [],
        "errors": [],
    }

    q = (
        db.table("agent_configs")
        .select(
            "org_id, outbound_enabled, outbound_occasions, outbound_time_from, "
            "outbound_time_to, outbound_weekdays, appointment_reminder_days"
        )
        .eq("outbound_enabled", True)
    )
    if only_org_id:
        q = q.eq("org_id", only_org_id)
    configs = q.execute().data or []

    now_local = now.astimezone(_BERLIN)
    weekday_key = _WEEKDAY_KEYS[now_local.weekday()]

    for cfg in configs:
        org_id = cfg["org_id"]

        occ = cfg.get("outbound_occasions") or {}
        if not occ.get(_REMINDER_OCCASION):
            summary["skipped"].append({"org_id": org_id, "reason": "occasion_disabled"})
            continue

        weekdays = cfg.get("outbound_weekdays") or []
        if weekdays and weekday_key not in weekdays:
            summary["skipped"].append({"org_id": org_id, "reason": "weekday_excluded"})
            continue

        if not _within_window(
            now_local.time(),
            _parse_clock(cfg.get("outbound_time_from")),
            _parse_clock(cfg.get("outbound_time_to")),
        ):
            summary["skipped"].append({"org_id": org_id, "reason": "outside_window"})
            continue

        org = _resolve_org(db, org_id)
        if not org.get("elevenlabs_agent_id") or not org.get(
            "elevenlabs_phone_number_id"
        ):
            summary["skipped"].append(
                {"org_id": org_id, "reason": "missing_agent_identity"}
            )
            continue

        summary["orgs_processed"] += 1

        n_days = cfg.get("appointment_reminder_days")
        n_days = _DEFAULT_REMINDER_DAYS if n_days is None else int(n_days)
        target_date = (now_local + timedelta(days=n_days)).date()
        start_local = datetime.combine(target_date, time.min, tzinfo=_BERLIN)
        end_local = start_local + timedelta(days=1)

        appts = (
            db.table("appointments")
            .select(
                "id, customer_id, scheduled_at, title, status, reminder_sent_at"
            )
            .eq("org_id", org_id)
            .in_("status", _ACTIVE_STATUSES)
            .gte("scheduled_at", start_local.astimezone(timezone.utc).isoformat())
            .lt("scheduled_at", end_local.astimezone(timezone.utc).isoformat())
            .is_("reminder_sent_at", "null")
            .execute()
            .data
            or []
        )
        if not appts:
            continue

        cust_ids = [a["customer_id"] for a in appts if a.get("customer_id")]
        cust_map: dict = {}
        if cust_ids:
            cust_rows = (
                db.table("customers")
                .select("id, full_name, phone")
                .eq("org_id", org_id)
                .in_("id", cust_ids)
                .execute()
                .data
                or []
            )
            cust_map = {c["id"]: c for c in cust_rows}

        for appt in appts:
            try:
                res = _dispatch_one(
                    db,
                    org=org,
                    org_id=org_id,
                    appt=appt,
                    customer=cust_map.get(appt.get("customer_id")),
                    to_number_override=None,
                    dry_run=dry_run,
                    now=now,
                )
                if res.get("skipped"):
                    summary["skipped"].append(
                        {
                            "org_id": org_id,
                            "appointment_id": appt["id"],
                            "reason": res["skipped"],
                        }
                    )
                else:
                    summary["calls"].append({"org_id": org_id, **res})
                    if not dry_run:
                        summary["dispatched"] += 1
            except OutboundCallError as e:
                summary["errors"].append(
                    {"org_id": org_id, "appointment_id": appt["id"], "error": str(e)}
                )
            except Exception as e:  # pragma: no cover — defensive
                logger.exception("reminder dispatch failed for %s", appt.get("id"))
                summary["errors"].append(
                    {"org_id": org_id, "appointment_id": appt.get("id"), "error": repr(e)}
                )

    return summary


def send_reminder_for_appointment(
    *,
    org_id: str,
    appointment_id: str,
    to_number_override: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict:
    """Manual single-appointment reminder (ad-hoc / UAT).

    Bypasses the window/weekday/occasion gate. ``to_number_override`` dials a
    designated test number instead of the customer's stored phone — the UAT
    safety mechanism (never auto-dial a real customer in testing).

    Raises ``LookupError`` when the appointment is not found for the org, and
    ``OutboundCallError`` for config / dispatch failures.
    """
    now = now or datetime.now(timezone.utc)
    db = get_service_client()

    appt_rows = (
        db.table("appointments")
        .select("id, customer_id, scheduled_at, title, status, reminder_sent_at")
        .eq("id", appointment_id)
        .eq("org_id", org_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not appt_rows:
        raise LookupError(f"appointment {appointment_id} not found for this org")
    appt = appt_rows[0]

    org = _resolve_org(db, org_id)
    if not org.get("elevenlabs_agent_id"):
        raise OutboundCallError("org has no elevenlabs_agent_id")
    if not org.get("elevenlabs_phone_number_id"):
        raise OutboundCallError(
            "org has no elevenlabs_phone_number_id — run sync-agent-config first"
        )

    customer = None
    if appt.get("customer_id"):
        crows = (
            db.table("customers")
            .select("id, full_name, phone")
            .eq("org_id", org_id)
            .eq("id", appt["customer_id"])
            .limit(1)
            .execute()
            .data
            or []
        )
        customer = crows[0] if crows else None

    res = _dispatch_one(
        db,
        org=org,
        org_id=org_id,
        appt=appt,
        customer=customer,
        to_number_override=to_number_override,
        dry_run=dry_run,
        now=now,
    )
    if res.get("skipped") == "no_phone":
        raise OutboundCallError(
            "customer has no phone and no to_number override was provided"
        )
    return res
