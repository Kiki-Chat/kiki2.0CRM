-- 0027_outbound_call_tracking.sql
-- Outbound appointment-reminder calls via ElevenLabs (P1).
-- Additive only (nullable ADD COLUMN) — safe to apply to the live DB.

-- Per-org ElevenLabs phone-number resource id. This is the
-- `agent_phone_number_id` the outbound-call API requires — the ID ElevenLabs
-- assigns to the imported Twilio number, distinct from elevenlabs_agent_id.
-- Captured alongside phone_number on provision + every sync-agent-config run.
alter table organizations
  add column if not exists elevenlabs_phone_number_id text;

-- Track the outbound reminder call placed against an appointment so the daily
-- sweep stays idempotent: reminder_sent_at IS NOT NULL => already reminded, skip.
alter table appointments
  add column if not exists reminder_conversation_id text,
  add column if not exists reminder_call_sid text,
  add column if not exists reminder_sent_at timestamptz;
