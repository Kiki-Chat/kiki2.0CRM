-- 0037_appointment_customer_proposal.sql
-- Appointment epic — reschedule counter-slot approval loop.
-- Additive only (ADD COLUMN IF NOT EXISTS) — safe on the live shared DB.
--
-- When a customer, on an outbound RESCHEDULE call, agrees to a slot (the time we
-- proposed, or a counter the agent surfaced via hk_getAvailableAppointments),
-- the agent records it via the EXISTING hk_changeAppointment tool. The
-- change_appointment service now ALSO stamps these structured columns on the
-- matched appointment — purely additive: the existing appointment_change inquiry
-- creation and the tool's return contract are unchanged.
--
-- `customer_proposed_at IS NOT NULL` is the discriminator the call-detail action
-- card uses to render the "Kunde schlägt {time} vor — Genehmigen / Ablehnen"
-- state. A human approval click applies it (scheduled_at := proposed,
-- status := 'confirmed') and fires the appointment_confirmation outbound call+email.
-- `customer_proposal_source` records provenance (e.g. 'agent_call').

alter table appointments
  add column if not exists customer_proposed_start_time timestamptz,
  add column if not exists customer_proposed_end_time   timestamptz,
  add column if not exists customer_proposed_at         timestamptz,
  add column if not exists customer_proposal_source     text;

-- "Appointments awaiting human approval of a customer counter-proposal", scoped
-- by org. Partial index over the discriminator only (keeps it tiny).
create index if not exists idx_appointments_customer_proposed
  on appointments (org_id, customer_proposed_at)
  where customer_proposed_at is not null;
