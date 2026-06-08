-- 0053 — appointment lifecycle timestamps. Additive only.
--
-- Powers two fixes:
--   * cancelled_at  → emit an `appointment_cancelled` event into the Verlauf
--     timeline (per-call + customer) and surface a persistent "Termin storniert"
--     Aktion so employees are informed instead of the action silently vanishing.
--   * rescheduled_at → record a human (calendar "Verschieben/Bearbeiten") time
--     change so it shows as `appointment_rescheduled` in the timeline AND triggers
--     the reschedule confirmation call+email (previously the calendar PATCH was a
--     silent time update with no notification).
--
-- Distinct from rejected_at (staff "Ablehnen" of a still-pending request).

alter table appointments
  add column if not exists cancelled_at   timestamptz,
  add column if not exists rescheduled_at timestamptz;

comment on column appointments.cancelled_at is
  'When the appointment was cancelled (status=cancelled via /cancel or the agent cancel tool). Distinct from rejected_at (staff Ablehnen of a pending request).';
comment on column appointments.rescheduled_at is
  'When a human last changed the appointment time (calendar Verschieben/Bearbeiten). Drives the appointment_rescheduled timeline event + reschedule confirmation call.';
