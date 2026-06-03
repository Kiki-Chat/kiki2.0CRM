"""Live-UAT: fire ONE appointment-reminder outbound call to the TEST number via
the prod ElevenLabs workspace. Manual single dispatch (bypasses the time-window
gate); to_number_override forces the designated test number (UAT safety).

Run from backend/:  PYTHONPATH=. ./.venv/bin/python ../scripts/fire_test_call.py
"""
from app.services import outbound_dispatch

OID = "c4dbf596-86fd-4484-88d9-095b2c082afb"      # kiki-test-007
APPT = "812434ab-c43d-4875-9ca7-956f4106f3c3"      # test customer a17438f0 appointment
TEST_NUMBER = "+917879997839"                       # forced override (your test phone)

# Dry-run first: confirm the path resolves (agent/phone/scope) WITHOUT ringing.
dry = outbound_dispatch.send_single_outbound(
    org_id=OID, occasion="appointment_reminder", record_id=APPT,
    to_number_override=TEST_NUMBER, dry_run=True,
)
print("DRY_RUN:", dry)

# Real call.
live = outbound_dispatch.send_single_outbound(
    org_id=OID, occasion="appointment_reminder", record_id=APPT,
    to_number_override=TEST_NUMBER, dry_run=False,
)
print("LIVE:", live)
