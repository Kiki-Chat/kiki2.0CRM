-- 0045_outbound_options_welcome_variants.sql
--
-- Remaining UAT topics 17, 18, 20. ADDITIVE ONLY.
--
-- 17: per-action outbound appointment sub-options (Confirm / Cancel / Reschedule
--     become independent toggles instead of one bundled "Terminerinnerung").
-- 18: outbound retry config (re-call after N minutes up to M attempts; re-call
--     when the customer hung up within X seconds) + ledger retry tracking.
-- 20: time-based welcome-message variants for inbound calls.

alter table agent_configs
  -- 17 — appointment outbound sub-options (default on = today's behaviour)
  add column if not exists outbound_appt_confirm_enabled boolean not null default true,
  add column if not exists outbound_appt_cancel_enabled boolean not null default true,
  add column if not exists outbound_appt_reschedule_enabled boolean not null default true,
  -- 18 — outbound retry config (default OFF: 0 attempts, short-hangup recall off)
  add column if not exists outbound_retry_max_attempts integer not null default 0
    check (outbound_retry_max_attempts between 0 and 10),
  add column if not exists outbound_retry_interval_minutes integer not null default 5
    check (outbound_retry_interval_minutes between 1 and 1440),
  add column if not exists outbound_recall_on_short_hangup boolean not null default false,
  add column if not exists outbound_short_hangup_seconds integer not null default 20
    check (outbound_short_hangup_seconds between 5 and 120),
  -- 20 — time-based welcome variants: [{from:"HH:MM", to:"HH:MM", message:"…"}, …]
  add column if not exists welcome_messages jsonb not null default '[]'::jsonb;

alter table outbound_calls
  -- 18 — retry tracking on the ledger
  add column if not exists retry_of uuid,
  add column if not exists retry_count integer not null default 0,
  add column if not exists retry_reason text,
  add column if not exists next_retry_at timestamptz;
