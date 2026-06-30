-- 0095_onboarding_events.sql
-- Paid-onboarding funnel (PAID_ONBOARDING_FUNNEL_BUILD.md §3). Additive, idempotent.
-- Per-stage idempotency + audit for the in-house orchestrator. checkout_session_id is
-- UNIQUE so Stripe webhook retries / re-runs never double-provision or double-buy a number.
-- Backend-only table: RLS ON, NO client policy. (Onboarding numbering is 0093-0096.)

CREATE TABLE IF NOT EXISTS onboarding_events (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  checkout_session_id text UNIQUE NOT NULL,                -- idempotency key (cs_...)
  lead_id             uuid REFERENCES onboarding_leads(id) ON DELETE SET NULL,
  org_id              uuid REFERENCES organizations(id)    ON DELETE SET NULL,
  stage               text CHECK (stage IN ('dispatched','agent_created','number_assigned','provisioned','failed')),
  payload             jsonb,
  error               text,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE onboarding_events ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_onboarding_events_stage ON onboarding_events(stage);
