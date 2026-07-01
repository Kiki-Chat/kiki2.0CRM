-- 0099_onboarding_lead_tracking.sql
-- Session-tracking + attribution for the paid onboarding funnel (ADDITIVE).
--
-- The lead `token` (0094) is the stable session id. It is now carried in the funnel
-- URL as `?s=<token>` so a refresh / back / mistakenly-aborted session resumes the
-- SAME lead instead of spawning a duplicate — and the token stays the single binding
-- key from signup → Stripe (client_reference_id) → org creation, so payment and org
-- never mismatch.
--
-- These columns let that same session token anchor marketing attribution now and a
-- refer-and-earn program later, without another schema change:
--   * utm            — {source, medium, campaign, term, content} captured from the
--                      landing URL (?utm_source=… etc.) at signup time.
--   * referral_code  — the inviter's code (?ref=…), for a future refer-and-earn flow.
alter table onboarding_leads add column if not exists utm jsonb;
alter table onboarding_leads add column if not exists referral_code text;
