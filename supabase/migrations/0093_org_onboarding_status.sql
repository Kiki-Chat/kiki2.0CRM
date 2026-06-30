-- 0093_org_onboarding_status.sql
-- Paid-onboarding funnel (PAID_ONBOARDING_FUNNEL_BUILD.md §3). Additive, idempotent.
-- CRM-visible signup/provision state set by the in-house orchestrator.
-- NUMBERING: prod 0086-0092 are the Employee↔Technician redesign (separate track,
-- applied ad-hoc to prod only). Onboarding therefore takes 0093-0096. Applied to UAT
-- (ifbluvdcbcesuhvkxsfn); must be applied to prod before flipping ONBOARDING_ENABLED.

ALTER TABLE organizations
  ADD COLUMN IF NOT EXISTS onboarding_status text;  -- pending | provisioning | active | failed

COMMENT ON COLUMN organizations.onboarding_status IS
  'Paid-onboarding orchestrator state: pending|provisioning|active|failed';
