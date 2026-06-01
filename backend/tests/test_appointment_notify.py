"""notify_appointment_outcome — the human-click trigger (call + email side-effect).

  * master toggle OFF → no call (fired:False, appointment_reminders_disabled);
  * master toggle ON + scope-only ON → fires; the dry-run proof asserts the click
    path builds the correct occasion + dynamic_variables and would dial the FORCED
    test number (NO real call placed overnight);
  * out-of-scope org → refused (fired:False, out_of_scope), no dispatch;
  * dispatch failure → best-effort (fired:False), NEVER raises.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.config import settings as cfg
from app.services import appointment_notify, outbound_dispatch
from app.services.outbound_call import OutboundCallError

TEST_ORG = "c4dbf596-86fd-4484-88d9-095b2c082afb"
OTHER_ORG = "00000000-0000-0000-0000-000000000999"

_ORG_ROW = {
    "id": TEST_ORG,
    "name": "Muster Heizungsbau GmbH",
    "elevenlabs_agent_id": "agent_safe",
    "elevenlabs_phone_number_id": "phnum_abc",
}
_APPT = {
    "id": "appt-1",
    "customer_id": "cust-1",
    "scheduled_at": "2026-06-10T08:00:00+00:00",
    "title": "Heizungswartung",
    "status": "pending",
    "alternative_start_time": None,
    "alternative_end_time": None,
    "alternative_note": None,
}
_CUST = {"id": "cust-1", "full_name": "Max Mustermann", "phone": "+49170REALCUSTOMER"}


class _Chain:
    """Catch-all chainable query builder — any filter/order method returns self."""

    def __init__(self, db, table):
        self._db, self._t = db, table

    def __getattr__(self, _name):
        return lambda *a, **k: self

    def execute(self):
        r = MagicMock()
        r.data = self._db._next(self._t)
        return r


class _DB:
    def __init__(self, resp):
        self._resp = {k: list(v) for k, v in resp.items()}

    def _next(self, t):
        q = self._resp.get(t)
        return q.pop(0) if q else []

    def table(self, n):
        return _Chain(self, n)


def _enabled_cfg(**over):
    base = {"outbound_enabled": True, "outbound_occasions": {"appointment_reminder": True}}
    base.update(over)
    return base


@pytest.fixture
def scope_on(monkeypatch):
    monkeypatch.setattr(cfg, "outbound_test_scope_only", True)
    monkeypatch.setattr(cfg, "outbound_test_number", "+917879997839")
    monkeypatch.setattr(cfg, "outbound_test_org_ids", TEST_ORG)


# ─── master toggle gating ────────────────────────────────────────────────────
def test_disabled_when_outbound_off(monkeypatch, scope_on):
    db = _DB({"agent_configs": [[_enabled_cfg(outbound_enabled=False)]]})
    monkeypatch.setattr(appointment_notify, "get_service_client", lambda: db)
    send = MagicMock()
    monkeypatch.setattr(outbound_dispatch, "send_single_outbound", send)

    res = appointment_notify.notify_appointment_outcome(TEST_ORG, "appt-1", "confirm")
    assert res == {"fired": False, "reason": "appointment_reminders_disabled"}
    send.assert_not_called()


def test_disabled_when_appointment_reminder_key_absent(monkeypatch, scope_on):
    db = _DB({"agent_configs": [[_enabled_cfg(outbound_occasions={"kva_followup": True})]]})
    monkeypatch.setattr(appointment_notify, "get_service_client", lambda: db)
    send = MagicMock()
    monkeypatch.setattr(outbound_dispatch, "send_single_outbound", send)

    res = appointment_notify.notify_appointment_outcome(TEST_ORG, "appt-1", "cancel")
    assert res["fired"] is False and res["reason"] == "appointment_reminders_disabled"
    send.assert_not_called()


def test_unknown_action_does_not_fire(monkeypatch, scope_on):
    send = MagicMock()
    monkeypatch.setattr(outbound_dispatch, "send_single_outbound", send)
    res = appointment_notify.notify_appointment_outcome(TEST_ORG, "appt-1", "bogus")
    assert res["fired"] is False
    send.assert_not_called()


# ─── the overnight proof: dry-run builds correct vars + FORCED test number ───
def test_confirm_dry_run_forces_test_number_and_builds_vars(monkeypatch, scope_on):
    # appointment_notify reads: agent_configs (gate), appointments + customers (phone).
    notify_db = _DB({
        "agent_configs": [[_enabled_cfg()]],
        "appointments": [[{"customer_id": "cust-1"}]],
        "customers": [[{"phone": "+49170REALCUSTOMER"}]],
    })
    monkeypatch.setattr(appointment_notify, "get_service_client", lambda: notify_db)
    # send_single_outbound (dry_run) reads: organizations, appointments, customers.
    dispatch_db = _DB({
        "organizations": [[_ORG_ROW]],
        "appointments": [[_APPT]],
        "customers": [[_CUST]],
    })
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: dispatch_db)
    placed = MagicMock()
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", placed)

    res = appointment_notify.notify_appointment_outcome(
        TEST_ORG, "appt-1", "confirm", dry_run=True
    )
    assert res["fired"] is True
    assert res["occasion"] == "appointment_confirmation"
    result = res["result"]
    # FORCED to the test number (NOT the real customer phone).
    assert result["to_number"] == "+917879997839"
    assert result["dry_run"] is True
    dv = result["dynamic_variables"]
    assert dv["anlassTyp"] == "TERMIN_BESTAETIGUNG"
    assert dv["referenzTyp"] == "Termin"
    assert dv["referenzId"] == "appt-1"
    # No real call placed (dry-run returns before placing).
    placed.assert_not_called()


def test_reschedule_maps_to_reschedule_occasion(monkeypatch, scope_on):
    notify_db = _DB({
        "agent_configs": [[_enabled_cfg()]],
        "appointments": [[{"customer_id": "cust-1"}]],
        "customers": [[{"phone": "+49170REALCUSTOMER"}]],
    })
    monkeypatch.setattr(appointment_notify, "get_service_client", lambda: notify_db)
    dispatch_db = _DB({
        "organizations": [[_ORG_ROW]],
        "appointments": [[{**_APPT, "alternative_start_time": "2026-06-12T13:00:00+00:00"}]],
        "customers": [[_CUST]],
    })
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: dispatch_db)
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", MagicMock())

    res = appointment_notify.notify_appointment_outcome(
        TEST_ORG, "appt-1", "reschedule", dry_run=True
    )
    assert res["result"]["dynamic_variables"]["anlassTyp"] == "TERMIN_VERSCHIEBUNG"


# ─── out-of-scope org is refused at the call boundary (no dispatch) ──────────
def test_out_of_scope_org_refused(monkeypatch, scope_on):
    notify_db = _DB({
        "agent_configs": [[_enabled_cfg()]],
        "appointments": [[{"customer_id": "cust-1"}]],
        "customers": [[{"phone": "+49170REALCUSTOMER"}]],
    })
    monkeypatch.setattr(appointment_notify, "get_service_client", lambda: notify_db)
    send = MagicMock()
    monkeypatch.setattr(outbound_dispatch, "send_single_outbound", send)

    res = appointment_notify.notify_appointment_outcome(OTHER_ORG, "appt-1", "confirm")
    assert res["fired"] is False and res["reason"] == "out_of_scope"
    send.assert_not_called()


# ─── best-effort: a dispatch failure never raises (status click already done) ─
def test_dispatch_failure_is_swallowed(monkeypatch, scope_on):
    notify_db = _DB({
        "agent_configs": [[_enabled_cfg()]],
        "appointments": [[{"customer_id": "cust-1"}]],
        "customers": [[{"phone": "+49170REALCUSTOMER"}]],
    })
    monkeypatch.setattr(appointment_notify, "get_service_client", lambda: notify_db)

    def _boom(**kw):
        raise OutboundCallError("elevenlabs down")

    monkeypatch.setattr(outbound_dispatch, "send_single_outbound", _boom)

    res = appointment_notify.notify_appointment_outcome(TEST_ORG, "appt-1", "confirm")
    assert res["fired"] is False and res["reason"] == "dispatch_failed"
