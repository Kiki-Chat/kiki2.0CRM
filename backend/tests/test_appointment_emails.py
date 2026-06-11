"""Cluster B — appointment emails + the dispatch email chokepoint.

  * render_appointment_email → German subject/body on the branded shell;
  * _maybe_send_occasion_email → appointment occasions email (email_always) and
    are FORCED to the test inbox / REFUSED out-of-scope; an occasion without an
    email_render stays inert; an email failure is swallowed (never breaks the call);
  * send_single_outbound integration → places the call AND emails (to the test inbox).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.config import settings as cfg
from app.services import outbound_dispatch
from app.services.appointment_emails import render_appointment_email
from app.services.outbound_occasions import OCCASIONS

TEST_ORG = "c4dbf596-86fd-4484-88d9-095b2c082afb"
OTHER_ORG = "00000000-0000-0000-0000-000000000999"

_ORG = {
    "id": TEST_ORG,
    "name": "Muster Heizungsbau GmbH",
    "email": "info@muster.de",
    "address": {"street": "Hauptstr. 1", "postal_code": "20095", "city": "Hamburg"},
    "elevenlabs_agent_id": "agent_safe",
    "elevenlabs_phone_number_id": "phnum_abc",
}
_CUST = {"id": "cust-1", "full_name": "Max Mustermann", "phone": "+49170", "email": "max@real.de"}
_APPT = {
    "id": "appt-1",
    "customer_id": "cust-1",
    "scheduled_at": "2026-06-10T08:00:00+00:00",  # → 10:00 Berlin
    "title": "Heizungswartung",
    "status": "pending",
    "alternative_start_time": None,
    "alternative_end_time": None,
    "alternative_note": None,
}


@pytest.fixture
def scope_on(monkeypatch):
    monkeypatch.setattr(cfg, "outbound_test_scope_only", True)
    monkeypatch.setattr(cfg, "outbound_test_email", "agrawalamber01@gmail.com")
    monkeypatch.setattr(cfg, "outbound_test_org_ids", TEST_ORG)
    monkeypatch.setattr(cfg, "outbound_occasion_emails_enabled", False)


# ─── templates ───────────────────────────────────────────────────────────────
def test_confirmation_email_render():
    subj, html = render_appointment_email("appointment_confirmation", _APPT, _CUST, _ORG)
    assert "Terminbestätigung" in subj and "10:00" in subj
    assert "Max Mustermann" in html and "bestätigen" in html and "Heizungswartung" in html
    assert "Muster Heizungsbau GmbH" in html  # white-label header/footer


def test_cancellation_email_render():
    subj, html = render_appointment_email("appointment_cancellation", _APPT, _CUST, _ORG)
    assert "Terminabsage" in subj
    assert "absagen" in html


def test_reschedule_email_render_with_alternative():
    appt = {**_APPT, "alternative_start_time": "2026-06-12T13:00:00+00:00"}  # → 15:00 Berlin
    subj, html = render_appointment_email("appointment_reschedule", appt, _CUST, _ORG)
    assert "Terminverschiebung" in subj and "15:00" in subj
    assert "verschieben" in html and "15:00" in html


def test_unknown_occasion_raises():
    with pytest.raises(ValueError):
        render_appointment_email("nope", _APPT, _CUST, _ORG)


# ─── dispatch chokepoint (_maybe_send_occasion_email) ────────────────────────
def test_appointment_email_forced_to_test_inbox(monkeypatch, scope_on):
    sent: dict = {}
    monkeypatch.setattr(outbound_dispatch, "send_email", lambda **kw: sent.update(kw))
    to = outbound_dispatch._maybe_send_occasion_email(
        spec=OCCASIONS["appointment_confirmation"], record=_APPT, customer=_CUST, org=_ORG, org_id=TEST_ORG
    )
    assert to == "agrawalamber01@gmail.com"
    assert sent["to_email"] == "agrawalamber01@gmail.com"  # NOT max@real.de
    assert "Terminbestätigung" in sent["subject"]


def test_email_refused_out_of_scope(monkeypatch, scope_on):
    send = MagicMock()
    monkeypatch.setattr(outbound_dispatch, "send_email", send)
    to = outbound_dispatch._maybe_send_occasion_email(
        spec=OCCASIONS["appointment_confirmation"], record=_APPT, customer=_CUST,
        org={**_ORG, "id": OTHER_ORG}, org_id=OTHER_ORG,
    )
    assert to is None
    send.assert_not_called()


def test_existing_occasion_inert_when_flag_off(monkeypatch, scope_on):
    # scope_on sets OUTBOUND_OCCASION_EMAILS_ENABLED=False. kva_followup now has an
    # email_render (Cluster C) but email_always=False → flag-gated → ships INERT.
    send = MagicMock()
    monkeypatch.setattr(outbound_dispatch, "send_email", send)
    to = outbound_dispatch._maybe_send_occasion_email(
        spec=OCCASIONS["kva_followup"],
        record={"id": "k", "number": "KVA-1", "subject": "Heizung", "total": 100, "sent_at": None},
        customer=_CUST, org=_ORG, org_id=TEST_ORG,
    )
    assert to is None
    send.assert_not_called()


def test_email_failure_is_swallowed(monkeypatch, scope_on):
    def _boom(**kw):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(outbound_dispatch, "send_email", _boom)
    to = outbound_dispatch._maybe_send_occasion_email(
        spec=OCCASIONS["appointment_confirmation"], record=_APPT, customer=_CUST, org=_ORG, org_id=TEST_ORG
    )
    assert to is None  # best-effort, no raise


# ─── integration: send_single_outbound places the call AND emails ────────────
class _Chain:
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


def test_send_single_appointment_places_call_and_emails(monkeypatch, scope_on):
    db = _DB({
        "organizations": [[_ORG]],
        "appointments": [[_APPT], [_APPT]],  # selector/fetch + pre-dial liveness re-check
        "customers": [[_CUST]],
    })
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    placed = MagicMock(return_value={"success": True, "conversation_id": "c", "callSid": "CA"})
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", placed)
    sent: dict = {}
    monkeypatch.setattr(outbound_dispatch, "send_email", lambda **kw: sent.update(kw))

    res = outbound_dispatch.send_single_outbound(
        org_id=TEST_ORG, occasion="appointment_confirmation",
        record_id="appt-1", to_number_override="+917879997839",
    )
    # call placed to the forced test number…
    assert placed.call_args.kwargs["to_number"] == "+917879997839"
    # …and the email forced to the test inbox (NOT the customer's real email).
    assert res["email_to"] == "agrawalamber01@gmail.com"
    assert sent["to_email"] == "agrawalamber01@gmail.com"
