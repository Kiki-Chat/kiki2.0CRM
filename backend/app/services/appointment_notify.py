"""Human-click trigger for appointment outbound calls (+ emails).

A human clicking Confirm / Cancel / Reschedule in the call-log action tab fires
the matching outbound occasion for that appointment — gated ONLY by the org's
master "Appointment Reminders" toggle (``outbound_enabled`` AND
``outbound_occasions["appointment_reminder"]``); NOT by the daily
time-window/weekday gate (a human click must fire whenever it is made, per the
approved design). The call routes through the scope guard so it dials the
designated test number while ``OUTBOUND_TEST_SCOPE_ONLY`` is ON.

The matching email rides along inside ``outbound_dispatch._dispatch_one``
(wired in Cluster B/C), so call + email share one chokepoint for both the
autonomous sweep and this click path.

Best-effort by design: routes call this AFTER the status mutation has committed,
so a telephony/email failure never rolls back the click — the failure is
captured in the returned dict and logged, never raised.
"""
from __future__ import annotations

import logging

from app.db.supabase_client import get_service_client
from app.services import outbound_dispatch
from app.services.outbound_call import OutboundCallError
from app.services.outbound_scope import OutOfScopeError, enforce_call_scope

logger = logging.getLogger(__name__)

# Action the human clicked → outbound occasion key.
APPOINTMENT_OCCASIONS = {
    "confirm": "appointment_confirmation",
    "cancel": "appointment_cancellation",
    "reschedule": "appointment_reschedule",
}

# Single master toggle gating ALL appointment-action calls/emails
# (Kiki-Zentrale → Ausgehende Anrufe → Terminerinnerung), per the approved design.
MASTER_OCCASION_KEY = "appointment_reminder"


# Per-action toggle columns (topic 17): master gate + an independent
# Confirm / Cancel / Reschedule switch.
_ACTION_TOGGLE_COL = {
    "confirm": "outbound_appt_confirm_enabled",
    "cancel": "outbound_appt_cancel_enabled",
    "reschedule": "outbound_appt_reschedule_enabled",
}


def appointment_outbound_enabled(org_id: str, action: str | None = None) -> bool:
    """True iff the org authorises this appointment outbound call: master
    (``outbound_enabled`` AND ``outbound_occasions['appointment_reminder']``) AND,
    when ``action`` is given, the per-action toggle (topic 17)."""
    try:
        rows = (
            get_service_client()
            .table("agent_configs")
            .select(
                "outbound_enabled, outbound_occasions, outbound_appt_confirm_enabled, "
                "outbound_appt_cancel_enabled, outbound_appt_reschedule_enabled"
            )
            .eq("org_id", org_id)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception:  # pragma: no cover — can't read config ⇒ safest is "don't fire"
        logger.warning("could not read outbound config for org %s; treating as disabled", org_id)
        return False
    if not rows or not rows[0].get("outbound_enabled"):
        return False
    row = rows[0]
    occ = row.get("outbound_occasions") or {}
    if not occ.get(MASTER_OCCASION_KEY):
        return False
    if action:
        col = _ACTION_TOGGLE_COL.get(action)
        if col and row.get(col) is False:
            return False
    return True


def _customer_phone(org_id: str, appointment_id: str) -> str | None:
    """Stored phone of the appointment's customer (the real number; the scope
    guard forces the test number while scope-only is ON)."""
    db = get_service_client()
    rows = (
        db.table("appointments").select("customer_id")
        .eq("org_id", org_id).eq("id", appointment_id).limit(1).execute().data
        or []
    )
    cid = rows[0].get("customer_id") if rows else None
    if not cid:
        return None
    crows = (
        db.table("customers").select("phone")
        .eq("org_id", org_id).eq("id", cid).limit(1).execute().data
        or []
    )
    return crows[0].get("phone") if crows else None


def notify_appointment_outcome(
    org_id: str, appointment_id: str, action: str, *, dry_run: bool = False
) -> dict:
    """Fire the outbound call (+ email) for an appointment action. Best-effort.

    ``action`` ∈ {confirm, cancel, reschedule}. Returns a result dict the route
    surfaces to the caller — NEVER raises, so the status mutation that already
    committed is never rolled back by a telephony/email failure."""
    occasion = APPOINTMENT_OCCASIONS.get(action)
    if occasion is None:
        return {"fired": False, "reason": f"unknown_action:{action}"}

    if not appointment_outbound_enabled(org_id, action):
        return {"fired": False, "reason": "appointment_reminders_disabled"}

    try:
        to_number = enforce_call_scope(org_id, _customer_phone(org_id, appointment_id))
    except OutOfScopeError as e:
        logger.warning("appointment outbound refused by scope guard: %s", e)
        return {"fired": False, "occasion": occasion, "reason": "out_of_scope", "error": str(e)}

    try:
        res = outbound_dispatch.send_single_outbound(
            org_id=org_id,
            occasion=occasion,
            record_id=appointment_id,
            to_number_override=to_number,
            dry_run=dry_run,
        )
        return {"fired": True, "occasion": occasion, "dry_run": dry_run, "result": res}
    except (OutboundCallError, LookupError, OutOfScopeError) as e:
        logger.warning("appointment outbound failed (%s/%s): %s", occasion, appointment_id, e)
        return {"fired": False, "occasion": occasion, "reason": "dispatch_failed", "error": str(e)}
    except Exception as e:  # pragma: no cover — defensive; never break the click
        logger.exception("appointment outbound unexpected error")
        return {"fired": False, "occasion": occasion, "reason": "error", "error": repr(e)}
