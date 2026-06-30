-- 0097_onboarding_lead_password.sql
-- Paid-onboarding funnel. Additive, idempotent.
-- The onboarding form (Q6) lets the customer CHOOSE their password before payment.
-- We must carry it to provision_org AFTER checkout.session.completed, so it is stored
-- Fernet-encrypted (app/core/crypto.py, key = SETTINGS_ENC_KEY) on the lead and CLEARED
-- on conversion. Never stored in plaintext. Backend-only table (RLS on, no client policy).

ALTER TABLE onboarding_leads
  ADD COLUMN IF NOT EXISTS password_encrypted text;
