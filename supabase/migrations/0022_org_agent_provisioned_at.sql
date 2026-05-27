-- 0022_org_agent_provisioned_at: add organizations.agent_provisioned_at (additive).
--
-- Step B (2026-05-27) — provision_org now configures the ElevenLabs agent
-- after the DB inserts (phone fetch, hk_* tool merge, master prompt write,
-- conversation-initiation webhook enable, audio assertion). The prompt-write
-- step (B.3) must only fire on the FIRST provisioning of an agent — re-runs
-- on an existing org would silently trample any customer edits to the prompt.
--
-- This column lets the agent-config helper detect re-runs:
--   NULL  → fresh agent, prompt may be applied
--   set   → already provisioned, skip prompt (other additive steps still run)
--
-- Additive only: ADD COLUMN IF NOT EXISTS, nullable, no default backfill.
-- Existing orgs (kiki-test-007, kiki-customer-009) keep NULL so a manual
-- `update organizations set agent_provisioned_at = now() where ...` is the
-- explicit "this customer's prompt is hand-edited, leave it alone" marker.
-- Newly-provisioned orgs stamp it inside provision_org after the prompt write
-- succeeds.
--
-- Pre-authorized per Amber's additive-migrations standing rule.

ALTER TABLE public.organizations
  ADD COLUMN IF NOT EXISTS agent_provisioned_at timestamptz NULL;
