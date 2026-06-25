"""The 3 appointment-action occasions (confirm / cancel / reschedule).

  * build_call_content → correct WerkPilot dynamic_variables (anlassTyp/referenz*)
    and German, server-rendered first_message / voicemail / prompt;
  * reschedule proposes the stored alternative_start_time (and degrades gracefully
    when none is set);
  * select=[] so the autonomous sweep can NEVER auto-dial them; email_always=True.
"""
from __future__ import annotations

from app.services import outbound_occasions

_ORG = {"id": "org-1", "name": "Muster Heizungsbau GmbH"}
_CUST = {"id": "cust-1", "full_name": "Max Mustermann", "phone": "+49170"}
_APPT = {
    "id": "appt-1",
    "customer_id": "cust-1",
    "scheduled_at": "2026-06-10T08:00:00+00:00",  # → 10:00 Berlin (CEST)
    "title": "Heizungswartung",
    "status": "pending",
    "alternative_start_time": None,
    "alternative_end_time": None,
    "alternative_note": None,
}


def _content(key, record, customer=_CUST):
    return outbound_occasions.build_call_content(
        outbound_occasions.OCCASIONS[key],
        record=record,
        customer=customer,
        org=_ORG,
        outbound_call_id="ocid-1",
    )


def test_confirmation_vars_and_text():
    c = _content("appointment_confirmation", _APPT)
    dv = c["dynamic_variables"]
    assert dv["anlassTyp"] == "TERMIN_BESTAETIGUNG"
    assert dv["referenzTyp"] == "Termin" and dv["referenzId"] == "appt-1"
    assert dv["kundenName"] == "Max Mustermann"
    fm = c["conversation_config_override"]["agent"]["first_message"]
    assert "bestätigen" in fm and "10:00" in fm and "Heizungswartung" in fm
    assert c["conversation_config_override"]["agent"]["language"] == "de"
    assert dv["voicemailMessage"].startswith("Guten Tag")


def test_cancellation_vars_and_text():
    c = _content("appointment_cancellation", _APPT)
    assert c["dynamic_variables"]["anlassTyp"] == "TERMIN_ABSAGE"
    fm = c["conversation_config_override"]["agent"]["first_message"]
    assert "absagen" in fm and "10:00" in fm


def test_reschedule_proposes_alternative_time():
    appt = {**_APPT, "alternative_start_time": "2026-06-12T13:00:00+00:00"}  # → 15:00 Berlin
    c = _content("appointment_reschedule", appt)
    assert c["dynamic_variables"]["anlassTyp"] == "TERMIN_VERSCHIEBUNG"
    fm = c["conversation_config_override"]["agent"]["first_message"]
    assert "verschieben" in fm and "15:00" in fm
    # the agent is told to use live availability + record (not book) the counter.
    prompt = c["conversation_config_override"]["agent"]["prompt"]["prompt"]
    assert "hk_getAvailableAppointments" in prompt and "hk_changeAppointment" in prompt


def test_reschedule_without_alternative_states_new_time_and_confirms_first():
    # Definite-move case (manual calendar/copilot reschedule): scheduled_at IS the
    # NEW committed time. The call must STATE that new time (10:00 Berlin) and ask
    # the customer to confirm it — NOT frame it as a slot to abandon and immediately
    # offer fresh slots (the reported bug).
    c = _content("appointment_reschedule", _APPT)  # no alternative_start_time
    fm = c["conversation_config_override"]["agent"]["first_message"]
    assert "10:00" in fm  # states the NEW time
    assert "neue Termin" in fm  # asks whether the new appointment fits
    prompt = c["conversation_config_override"]["agent"]["prompt"]["prompt"]
    # Alternatives are offered ONLY on decline ("erst DANN") — never up front.
    assert "erst DANN" in prompt and "hk_getAvailableAppointments" in prompt


def test_appointment_occasions_are_never_swept_and_email_always():
    for key in ("appointment_confirmation", "appointment_cancellation", "appointment_reschedule"):
        spec = outbound_occasions.OCCASIONS[key]
        assert spec.select(None, "org-1", {}, None) == []  # sweep finds nothing → never auto-dials
        assert spec.email_always is True
        assert spec.table == "appointments"
