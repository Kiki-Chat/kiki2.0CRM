-- 0096_twilio_numbers.sql
-- Paid-onboarding funnel (PAID_ONBOARDING_FUNNEL_BUILD.md §3). Additive, idempotent.
-- Replaces the `twilio_pool` Google Sheet as the SOURCE OF TRUTH for the Kiki number pool.
-- Sheet col -> table col mapping:
--   Session_Id -> session_id, Phone_number -> phone_number, Eleven_phone_id -> eleven_phone_id,
--   Status (Idle/Reserved/Assigned) -> status (idle/reserved/assigned),
--   Assigned_agent_id -> assigned_agent_id, Label -> label, Last_updated -> last_updated, Notes -> notes.
-- A read-only mirror back to Sheets (for non-tech visibility) is a DEFERRED phase; edits to the
-- sheet must NOT affect the DB (past incident). Backend-only table: RLS ON, NO client policy.
-- (Onboarding numbering is 0093-0096; prod 0086-0092 = technician redesign, separate track.)

CREATE TABLE IF NOT EXISTS twilio_numbers (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  phone_number      text UNIQUE NOT NULL,                  -- E.164, e.g. +4925197593212
  eleven_phone_id   text,                                   -- ElevenLabs phone_number_id (phnum_...)
  status            text NOT NULL DEFAULT 'idle'
                      CHECK (status IN ('idle','reserved','assigned')),
  session_id        text,                                   -- reserving checkout session / onboarding token
  assigned_agent_id text,                                   -- ElevenLabs agent_id once bound
  org_id            uuid REFERENCES organizations(id) ON DELETE SET NULL,
  label             text,
  twilio_sid        text,                                   -- Twilio IncomingPhoneNumbers sid (for release)
  notes             text,
  last_updated      timestamptz NOT NULL DEFAULT now(),
  created_at        timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE twilio_numbers ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_twilio_numbers_status ON twilio_numbers(status);
-- One number can be actively assigned to at most one agent at a time.
CREATE UNIQUE INDEX IF NOT EXISTS uq_twilio_numbers_assigned_agent
  ON twilio_numbers(assigned_agent_id)
  WHERE assigned_agent_id IS NOT NULL;
