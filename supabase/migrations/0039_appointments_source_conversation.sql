-- 0039_appointments_source_conversation.sql
-- Correlate an agent-booked appointment back to its originating call so the
-- call-detail action card can show it. hk_bookAppointment creates a SEPARATE
-- inquiry (the call's own inquiry is created later at post-call ingest), so
-- linking by inquiry alone misses agent bookings. Storing the ElevenLabs
-- conversation id lets _pending_for_call match the appointment to the call via
-- calls.elevenlabs_conversation_id. Additive.

alter table appointments
  add column if not exists source_conversation_id text;

create index if not exists idx_appointments_source_conversation
  on appointments (org_id, source_conversation_id)
  where source_conversation_id is not null;
