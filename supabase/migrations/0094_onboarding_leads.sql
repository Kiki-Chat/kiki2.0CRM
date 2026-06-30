-- 0094_onboarding_leads.sql
-- Paid-onboarding funnel (PAID_ONBOARDING_FUNNEL_BUILD.md §3). Additive, idempotent.
-- Pre-payment lead: the org does NOT exist yet. `token` is the Stripe client_reference_id
-- that binds the funnel session to the eventual org on checkout.session.completed.
-- Backend-only table: RLS ON, NO client policy (service role bypasses RLS). Mirrors the
-- billing_* / org_secrets convention. (Onboarding numbering is 0093-0096; see 0093.)

CREATE TABLE IF NOT EXISTS onboarding_leads (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  token             text UNIQUE NOT NULL,                 -- = Stripe client_reference_id (pre-org key)
  company_name      text,
  contact_name      text,
  email             text,
  phone             text,
  billing_address   jsonb,
  trade             text,                                  -- Gewerk
  plan_title        text,                                  -- e.g. 'Kiki Pro'
  interval          text,                                  -- 'month' | 'year'
  stripe_session_id text UNIQUE,                           -- cs_... once checkout is created
  stripe_customer_id text,
  org_id            uuid REFERENCES organizations(id) ON DELETE SET NULL,  -- set on conversion
  status            text NOT NULL DEFAULT 'created'
                      CHECK (status IN ('created','converted','abandoned')),
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE onboarding_leads ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_onboarding_leads_status ON onboarding_leads(status);
CREATE INDEX IF NOT EXISTS idx_onboarding_leads_email  ON onboarding_leads(lower(email));
