-- 0023_org_existing_business_number: add organizations.existing_business_number (additive).
--
-- Wave 1 / Agent 1.3 (2026-05-28) — correct call-forwarding scope in the
-- Kiki-Zentrale Telefon section. The tradesperson's existing business
-- number is configured at the telco layer to forward to HeyKiki's Twilio
-- number (approach A — telco-level forwarding). We store the customer's
-- own number here so it can be displayed alongside the read-only HeyKiki
-- number, with help text + doc link explaining the forwarding setup.
--
-- HeyKiki never bridges or dials this number — it's purely informational
-- for the tradesperson (and a future "did you set up the forward?" check).
--
-- Additive only: ADD COLUMN IF NOT EXISTS, nullable, no default backfill.
-- Existing orgs keep NULL until the tradesperson saves the field.
--
-- Pre-authorized per Amber's additive-migrations standing rule.

ALTER TABLE public.organizations
  ADD COLUMN IF NOT EXISTS existing_business_number text NULL;
