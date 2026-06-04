"""Outbound dispatch engine (Path A) — occasion-agnostic sweep + manual trigger.

Registry-driven engine that serves EVERY occasion through one code path:

  * uniform gate (``_passes_gate``) — outbound_enabled AND outbound_occasions[key]
    (absent ⇒ False) AND time-window AND weekday. Plus an optional per-occasion
    org flag (e.g. ``google_reviews_enabled`` for review_request).
  * case link — at dispatch the triggering record is resolved to its case
    (``inquiry_id``) via ``spec.inquiry_id_of``. Occasions tagged
    ``case_gate='must_be_open'`` do NOT fire if the linked inquiry is
    completed/deleted (a closed case stops its outbound calls). NULL inquiry_id
    ⇒ no gate (the record has no case). Post-completion occasions
    (satisfaction/review) are ``must_be_completed`` and select completed cases
    directly.
  * cycle-based idempotency — each dispatch inserts a claim into ``outbound_calls``
    with a ``cycle_no``; the partial unique index
    ``(org_id, occasion, referenz_id, cycle_no) WHERE status<>'failed'`` is the
    atomic guard. One-shot occasions stay at cycle_no=1 (one call ever); recurring
    occasions (payment) advance a cycle once the cooldown elapses, capped by
    ``max_cycles``.

``run_due_outbound`` = scheduled sweep. ``send_single_outbound`` = manual/UAT;
with a ``to_number_override`` it dials a TEST number, skips all gates AND the
ledger claim (repeatable).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, time, timedelta, timezone

from app.core.config import settings
from app.db.supabase_client import get_service_client
from app.services.email_send import send_email
from app.services.outbound_call import OutboundCallError, place_outbound_call
from app.services.outbound_occasions import (
    OCCASION_KEYS,
    OCCASIONS,
    build_call_content,
)
from app.services.outbound_scope import OutOfScopeError, enforce_email_scope

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo

    _BERLIN = ZoneInfo("Europe/Berlin")
except Exception:  # pragma: no cover
    logger.warning("Europe/Berlin tz unavailable; falling back to UTC for windows")
    _BERLIN = timezone.utc

_WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_CLOSED_STATUSES = ("completed", "deleted")


# ─── small parsers / window ──────────────────────────────────────────────────
def _parse_iso(value):
    if not value:
        return None
    if isinstance(value, str) and value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(value)
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
    return now_local >= frm or now_local <= to  # overnight window


# ─── THE uniform gate — identical for every occasion ─────────────────────────
def _passes_gate(cfg: dict, occasion_key: str, now_local: datetime, weekday_key: str) -> str | None:
    """Return None if ``occasion_key`` may fire for this org now, else a skip reason."""
    if not cfg.get("outbound_enabled"):
        return "outbound_disabled"
    occ = cfg.get("outbound_occasions") or {}
    if not occ.get(occasion_key):  # absent key ⇒ falsy ⇒ disabled ⇒ never fires
        return "occasion_disabled"
    weekdays = cfg.get("outbound_weekdays") or []
    if weekdays and weekday_key not in weekdays:
        return "weekday_excluded"
    if not _within_window(
        now_local.time(),
        _parse_clock(cfg.get("outbound_time_from")),
        _parse_clock(cfg.get("outbound_time_to")),
    ):
        return "outside_window"
    return None


# ─── data resolution ──────────────────────────────────────────────────────────
def _resolve_org(db, org_id: str) -> dict:
    rows = (
        db.table("organizations")
        .select(
            "id, name, phone_number, elevenlabs_agent_id, "
            "elevenlabs_phone_number_id, google_reviews_enabled"
        )
        .eq("id", org_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else {}


def _resolve_customers(db, org_id: str, customer_ids: list) -> dict:
    ids = [c for c in customer_ids if c]
    if not ids:
        return {}
    rows = (
        db.table("customers")
        .select("id, full_name, phone, email")
        .eq("org_id", org_id)
        .in_("id", ids)
        .execute()
        .data
        or []
    )
    return {r["id"]: r for r in rows}


def _maybe_send_occasion_email(*, spec, record, customer, org, org_id) -> str | None:
    """Best-effort per-occasion email (Cluster B/C). The 3 appointment occasions
    (``email_always``) send unconditionally; the existing 7 only when
    ``OUTBOUND_OCCASION_EMAILS_ENABLED`` is set (so that wiring ships INERT).
    Scope-guarded (forced to the test inbox / refused out-of-scope while the
    guard is on) and NEVER fatal — an email failure must not affect the placed
    call. Returns the address actually emailed, or None."""
    if not spec.email_render:
        return None
    if not (spec.email_always or settings.outbound_occasion_emails_enabled):
        return None
    try:
        to_email = enforce_email_scope(org_id, (customer or {}).get("email"))
    except OutOfScopeError as e:
        logger.info("occasion email skipped (out of scope): %s", e)
        return None
    try:
        subject, body_html = spec.email_render(record, customer, org)
        send_email(
            org_id=org_id,
            to_email=to_email,
            subject=subject,
            body_html=body_html,
            reply_to=(org.get("email") or None),
        )
        return to_email
    except Exception as e:  # pragma: no cover — never break the placed call
        logger.warning("occasion email failed (%s): %s", spec.key, e)
        return None


def _resolve_inquiry_statuses(db, org_id: str, inquiry_ids: list) -> dict:
    ids = [i for i in set(inquiry_ids) if i]
    if not ids:
        return {}
    rows = (
        db.table("inquiries")
        .select("id, status")
        .eq("org_id", org_id)
        .in_("id", ids)
        .execute()
        .data
        or []
    )
    return {r["id"]: r.get("status") for r in rows}


def _fetch_record(db, spec, org_id: str, record_id: str) -> dict | None:
    rows = (
        db.table(spec.table)
        .select(spec.columns)
        .eq("id", record_id)
        .eq("org_id", org_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def _existing_attempts(db, org_id: str, occasion: str) -> dict:
    """Non-failed ledger rows grouped by referenz_id (for cycle decisions)."""
    rows = (
        db.table("outbound_calls")
        .select("referenz_id, created_at, cycle_no, status")
        .eq("org_id", org_id)
        .eq("occasion", occasion)
        .neq("status", "failed")
        .execute()
        .data
        or []
    )
    out: dict = {}
    for r in rows:
        out.setdefault(r.get("referenz_id"), []).append(r)
    return out


def _cycle_decision(spec, attempts: list, cfg: dict, now: datetime):
    """Return (eligible, cycle_no, reason). One-shot ⇒ fire once ever. Recurring ⇒
    advance a cycle once the cooldown elapses, up to max_cycles."""
    n = len(attempts)
    if not spec.recurring:
        return (False, None, "already_dispatched") if n else (True, 1, None)
    if spec.max_cycles is not None and n >= spec.max_cycles:
        return (False, None, "max_cycles_reached")
    if n:
        cooldown = cfg.get(spec.cooldown_config_key) if spec.cooldown_config_key else None
        cooldown = int(cooldown if cooldown is not None else (spec.cooldown_days or 0))
        if cooldown:
            last = max(
                (d for d in (_parse_iso(a.get("created_at")) for a in attempts) if d),
                default=None,
            )
            if last and now < last + timedelta(days=cooldown):
                return (False, None, "cooldown")
    return (True, n + 1, None)


def _claim(db, claim: dict) -> bool:
    """Insert the pending claim. False if a concurrent sweep already claimed this
    (cycle) — the atomic double-dispatch guard."""
    try:
        db.table("outbound_calls").insert(claim).execute()
        return True
    except Exception as e:  # unique violation / transient
        logger.info("outbound claim rejected (already dispatched?): %s", e)
        return False


# ─── per-record dispatch ──────────────────────────────────────────────────────
def _dispatch_one(
    db, *, org, org_id, spec, record, customer, inquiry_id, cycle_no, to_number_override, dry_run, now
):
    to_number = to_number_override or (
        spec.to_number_of(record, customer) if spec.to_number_of else (customer or {}).get("phone")
    )
    if not to_number:
        return {"skipped": "no_phone", "referenz_id": record["id"]}

    outbound_call_id = str(uuid.uuid4())
    content = build_call_content(
        spec, record=record, customer=customer, org=org, outbound_call_id=outbound_call_id
    )
    dv = content["dynamic_variables"]
    override = content["conversation_config_override"]

    if dry_run:
        return {
            "referenz_id": record["id"],
            "to_number": to_number,
            "outbound_call_id": outbound_call_id,
            "anlass_typ": spec.anlass_typ,
            "inquiry_id": inquiry_id,
            "cycle_no": cycle_no,
            "dynamic_variables": dv,
            "first_message": override["agent"]["first_message"],
            "dry_run": True,
        }

    # UAT override dials a TEST number → skip the ledger claim (repeatable).
    use_ledger = to_number_override is None
    if use_ledger:
        claim = {
            "id": outbound_call_id,
            "org_id": org_id,
            "occasion": spec.key,
            "anlass_typ": spec.anlass_typ,
            "customer_id": (customer or {}).get("id"),
            "referenz_typ": spec.referenz_typ,
            "referenz_id": record["id"],
            "inquiry_id": inquiry_id,
            "cycle_no": cycle_no,
            "to_number": to_number,
            "status": "pending",
            "dynamic_variables": dv,
        }
        if not _claim(db, claim):
            return {"skipped": "already_dispatched", "referenz_id": record["id"]}

    try:
        result = place_outbound_call(
            agent_id=org["elevenlabs_agent_id"],
            agent_phone_number_id=org.get("elevenlabs_phone_number_id"),
            to_number=to_number,
            dynamic_variables=dv,
            conversation_config_override=override,
        )
    except OutboundCallError as e:
        if use_ledger:
            db.table("outbound_calls").update(
                {"status": "failed", "error": str(e)[:500]}
            ).eq("id", outbound_call_id).execute()
        raise

    if use_ledger:
        db.table("outbound_calls").update(
            {
                "status": "placed",
                "conversation_id": result.get("conversation_id"),
                "call_sid": result.get("callSid"),
                "placed_at": now.astimezone(timezone.utc).isoformat(),
            }
        ).eq("id", outbound_call_id).execute()

    # Per-occasion email side-effect — one chokepoint for the sweep AND the click.
    # Best-effort + scope-guarded; never affects the placed call above.
    email_to = _maybe_send_occasion_email(
        spec=spec, record=record, customer=customer, org=org, org_id=org_id
    )

    return {
        "referenz_id": record["id"],
        "to_number": to_number,
        "outbound_call_id": outbound_call_id,
        "anlass_typ": spec.anlass_typ,
        "inquiry_id": inquiry_id,
        "cycle_no": cycle_no,
        "conversation_id": result.get("conversation_id"),
        "call_sid": result.get("callSid"),
        "email_to": email_to,
    }


# ─── the sweep ────────────────────────────────────────────────────────────────
def run_due_outbound(
    *,
    now: datetime | None = None,
    only_org_id: str | None = None,
    occasions: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """Sweep all (or one) outbound-enabled orgs and dispatch every due occasion.
    Idempotent via the outbound_calls ledger (cycle-aware)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    occasions = occasions or OCCASION_KEYS
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
    # Topic 18: process any due short-hangup re-dials on the same sweep tick.
    summary["retries"] = run_due_retries(now=now, dry_run=dry_run)

    q = (
        db.table("agent_configs")
        .select(
            "org_id, outbound_enabled, outbound_occasions, outbound_time_from, "
            "outbound_time_to, outbound_weekdays, appointment_reminder_days, "
            "kva_followup_days, payment_reminder_days"
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
        org: dict | None = None
        org_counted = False

        for occ_key in occasions:
            spec = OCCASIONS.get(occ_key)
            if spec is None:
                continue

            reason = _passes_gate(cfg, occ_key, now_local, weekday_key)
            if reason:
                summary["skipped"].append({"org_id": org_id, "occasion": occ_key, "reason": reason})
                continue

            if org is None:
                org = _resolve_org(db, org_id)
            if not org.get("elevenlabs_agent_id") or not org.get("elevenlabs_phone_number_id"):
                summary["skipped"].append(
                    {"org_id": org_id, "occasion": occ_key, "reason": "missing_agent_identity"}
                )
                continue
            if spec.org_flag and not org.get(spec.org_flag):
                summary["skipped"].append(
                    {"org_id": org_id, "occasion": occ_key, "reason": "org_flag_off", "flag": spec.org_flag}
                )
                continue

            if not org_counted:
                summary["orgs_processed"] += 1
                org_counted = True

            records = spec.select(db, org_id, cfg, now_local)
            if not records:
                continue

            rec_inq = {r["id"]: spec.inquiry_id_of(db, org_id, r) for r in records}
            status_map = (
                _resolve_inquiry_statuses(db, org_id, list(rec_inq.values()))
                if spec.case_gate == "must_be_open"
                else {}
            )
            attempts = {} if dry_run else _existing_attempts(db, org_id, occ_key)
            cust_map = _resolve_customers(db, org_id, [r.get("customer_id") for r in records])

            for record in records:
                inquiry_id = rec_inq.get(record["id"])

                # Close-case gate (work occasions only).
                if (
                    spec.case_gate == "must_be_open"
                    and inquiry_id
                    and status_map.get(inquiry_id) in _CLOSED_STATUSES
                ):
                    summary["skipped"].append(
                        {"org_id": org_id, "occasion": occ_key, "referenz_id": record["id"], "reason": "case_closed"}
                    )
                    continue

                if dry_run:
                    eligible, cycle_no, dreason = True, 1, None
                else:
                    eligible, cycle_no, dreason = _cycle_decision(
                        spec, attempts.get(record["id"], []), cfg, now
                    )
                if not eligible:
                    summary["skipped"].append(
                        {"org_id": org_id, "occasion": occ_key, "referenz_id": record["id"], "reason": dreason}
                    )
                    continue

                try:
                    res = _dispatch_one(
                        db,
                        org=org,
                        org_id=org_id,
                        spec=spec,
                        record=record,
                        customer=cust_map.get(record.get("customer_id")),
                        inquiry_id=inquiry_id,
                        cycle_no=cycle_no or 1,
                        to_number_override=None,
                        dry_run=dry_run,
                        now=now,
                    )
                    if res.get("skipped"):
                        summary["skipped"].append(
                            {"org_id": org_id, "occasion": occ_key, "referenz_id": record["id"], "reason": res["skipped"]}
                        )
                    else:
                        summary["calls"].append({"org_id": org_id, "occasion": occ_key, **res})
                        if not dry_run:
                            summary["dispatched"] += 1
                except OutboundCallError as e:
                    summary["errors"].append(
                        {"org_id": org_id, "occasion": occ_key, "referenz_id": record["id"], "error": str(e)}
                    )
                except Exception as e:  # pragma: no cover — defensive
                    logger.exception("outbound dispatch failed for %s", record.get("id"))
                    summary["errors"].append(
                        {"org_id": org_id, "occasion": occ_key, "referenz_id": record.get("id"), "error": repr(e)}
                    )

    return summary


# ─── manual / UAT single trigger ──────────────────────────────────────────────
def send_single_outbound(
    *,
    org_id: str,
    occasion: str,
    record_id: str,
    to_number_override: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict:
    """Manual single-record dispatch (ad-hoc / UAT). Bypasses window/weekday/
    occasion AND close-case gates. ``to_number_override`` dials a designated TEST
    number and skips the ledger claim (repeatable). The case (inquiry_id) is still
    derived and recorded when a real (non-override) dispatch writes the ledger.

    Raises ``LookupError`` when the record isn't found, ``OutboundCallError`` for
    config / dispatch failures.
    """
    now = now or datetime.now(timezone.utc)
    spec = OCCASIONS.get(occasion)
    if spec is None:
        raise OutboundCallError(f"unknown occasion '{occasion}'")

    db = get_service_client()
    org = _resolve_org(db, org_id)
    if not org.get("elevenlabs_agent_id"):
        raise OutboundCallError("org has no elevenlabs_agent_id")
    if not org.get("elevenlabs_phone_number_id"):
        raise OutboundCallError(
            "org has no elevenlabs_phone_number_id — run sync-agent-config first"
        )

    record = _fetch_record(db, spec, org_id, record_id)
    if not record:
        raise LookupError(f"{spec.referenz_typ} {record_id} not found for this org")

    customer = _resolve_customers(db, org_id, [record.get("customer_id")]).get(
        record.get("customer_id")
    )
    inquiry_id = spec.inquiry_id_of(db, org_id, record)

    if to_number_override:
        cycle_no = 1  # no ledger written for UAT override
    else:
        cycle_no = len(_existing_attempts(db, org_id, occasion).get(record_id, [])) + 1

    res = _dispatch_one(
        db,
        org=org,
        org_id=org_id,
        spec=spec,
        record=record,
        customer=customer,
        inquiry_id=inquiry_id,
        cycle_no=cycle_no,
        to_number_override=to_number_override,
        dry_run=dry_run,
        now=now,
    )
    if res.get("skipped") == "no_phone":
        raise OutboundCallError(
            "customer has no phone and no to_number override was provided"
        )
    return res


# ─── Topic 18: retry on short hangup ─────────────────────────────────────────
def schedule_short_hangup_retry(client, org_id, conversation_id, duration_seconds, now=None) -> None:
    """If an OUTBOUND call hung up within the org's short-hangup window and recall
    is enabled (and attempts remain), stamp ``next_retry_at`` on the ledger row so
    the next sweep re-dials. Best-effort; never raises. No-op unless configured."""
    try:
        if duration_seconds is None:
            return
        dur = int(duration_seconds)
        cfg = (
            client.table("agent_configs")
            .select(
                "outbound_recall_on_short_hangup, outbound_short_hangup_seconds, "
                "outbound_retry_max_attempts, outbound_retry_interval_minutes"
            )
            .eq("org_id", org_id)
            .limit(1)
            .execute()
            .data
        )
        row = cfg[0] if cfg else {}
        if not row.get("outbound_recall_on_short_hangup"):
            return
        threshold = int(row.get("outbound_short_hangup_seconds") or 20)
        max_attempts = int(row.get("outbound_retry_max_attempts") or 0)
        interval = int(row.get("outbound_retry_interval_minutes") or 5)
        if dur >= threshold or max_attempts <= 0:
            return
        led = (
            client.table("outbound_calls")
            .select("id, cycle_no, retry_count")
            .eq("org_id", org_id)
            .eq("conversation_id", conversation_id)
            .limit(1)
            .execute()
            .data
        )
        if not led:
            return
        lrow = led[0]
        # cycle_no = attempt number of this call (1 = original). Allow a retry
        # while attempts so far <= the configured max (so we make `max` retries).
        if int(lrow.get("cycle_no") or 1) > max_attempts:
            return
        now = now or datetime.now(timezone.utc)
        nxt = (now + timedelta(minutes=interval)).astimezone(timezone.utc).isoformat()
        client.table("outbound_calls").update(
            {
                "next_retry_at": nxt,
                "retry_reason": "short_hangup",
                "retry_count": int(lrow.get("retry_count") or 0) + 1,
            }
        ).eq("org_id", org_id).eq("id", lrow["id"]).execute()
    except Exception:  # noqa: BLE001 — never break post-call ingest
        logger.warning("schedule_short_hangup_retry failed (org %s, conv %s)", org_id, conversation_id)


def run_due_retries(now: datetime | None = None, dry_run: bool = False) -> dict:
    """Re-dial outbound calls whose ``next_retry_at`` has elapsed (topic 18). Each
    is re-fired via ``send_single_outbound`` (which advances cycle_no), then its
    marker is cleared. Driven by the same external sweep as ``run_due_outbound``."""
    now = now or datetime.now(timezone.utc)
    db = get_service_client()
    due = (
        db.table("outbound_calls")
        .select("id, org_id, occasion, referenz_id")
        .lte("next_retry_at", now.astimezone(timezone.utc).isoformat())
        .limit(200)
        .execute()
        .data
        or []
    )
    fired, errors = 0, []
    for r in due:
        rid = r["id"]
        org_id, occasion, referenz_id = r.get("org_id"), r.get("occasion"), r.get("referenz_id")
        if not dry_run:
            # Clear first so a concurrent sweep can't double-fire this row.
            db.table("outbound_calls").update({"next_retry_at": None}).eq("id", rid).execute()
        if not (org_id and occasion and referenz_id):
            continue
        try:
            send_single_outbound(
                org_id=org_id, occasion=occasion, record_id=referenz_id, dry_run=dry_run, now=now
            )
            fired += 1
        except Exception as e:  # noqa: BLE001 — one failed retry must not stop the rest
            errors.append({"id": rid, "error": str(e)[:200]})
            logger.warning("retry re-dial failed (%s/%s): %s", occasion, referenz_id, e)
    return {"due": len(due), "fired": fired, "errors": errors}
