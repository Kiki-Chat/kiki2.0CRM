-- 0082_agent_config_suggest_employee.sql
-- Real-time on-call employee routing — the SPOKEN-NAME toggle.
--
-- The availability + workload routing that picks the right, free, least-loaded
-- competent person is ALWAYS on (it just makes scheduling correct). This flag
-- controls only ONE thing: whether Kiki says that employee's NAME out loud to the
-- caller (e.g. "Steve kann um 16 Uhr kommen"). Default FALSE — naming is opt-in,
-- flipped per org with a single command and read on the next tool call.
--
-- Additive only: ADD COLUMN IF NOT EXISTS. Inert under old code (which never
-- reads the column); the slot finder also guards the read, so a backend that
-- predates this column simply behaves as "off".
alter table public.agent_configs
  add column if not exists suggest_employee_enabled boolean not null default false;
