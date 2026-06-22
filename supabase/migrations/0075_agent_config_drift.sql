-- 0075_agent_config_drift.sql
-- Kiki-Zentrale drift safety (Batch 1, 1.3). Tracks WHEN a config change could
-- not be pushed to the live ElevenLabs agent because the org sits behind a manual
-- prompt override, and WHEN the agent prompt was last successfully re-pushed.
--
--   config_dirty_since : stamped to now() the first time a re-render no-ops on the
--                        manual_override gate while still NULL; cleared back to NULL
--                        on the next successful push. NULL ⇒ agent is in step.
--   last_repush_at     : timestamp of the last SUCCESSFUL prompt push to the agent.
--   last_repush_seq    : monotonic sync seq of that last successful push (room for a
--                        future "which save won" diagnostic; defaults to 0).
--
-- Additive + reversible:
--   alter table public.agent_configs
--     drop column if exists config_dirty_since,
--     drop column if exists last_repush_at,
--     drop column if exists last_repush_seq;
alter table public.agent_configs
  add column if not exists config_dirty_since timestamptz;
alter table public.agent_configs
  add column if not exists last_repush_at timestamptz;
alter table public.agent_configs
  add column if not exists last_repush_seq bigint not null default 0;
