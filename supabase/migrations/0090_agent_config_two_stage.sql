-- 0090_agent_config_two_stage.sql
-- Employee/Technician redesign — Track A, Phase 1 (ADDITIVE).
--
-- Per-org kill-switch for the two-stage scheduling flow (office coordinator owns the
-- ticket; technician is dispatched to the visit and gates the slot). Default FALSE ->
-- behaviour is byte-identical to today's single-stage path. Mirrors the
-- suggest_employee_enabled (0082) rollout pattern: flip per org, read on the next call.
--
-- Additive: ADD COLUMN IF NOT EXISTS, default false. Inert under old code.

alter table public.agent_configs
  add column if not exists scheduling_two_stage_enabled boolean not null default false;
