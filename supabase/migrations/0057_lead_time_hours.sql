-- 0057: Terminregeln — Vorlaufzeit in HOURS instead of days (user decision
-- 2026-06-10: "24h gap after the call before the calendar opens for booking").
-- Additive: lead_time_days stays for rollback/compat; code prefers
-- lead_time_hours and falls back to lead_time_days*24.

alter table agent_configs
  add column if not exists lead_time_hours integer;

update agent_configs
   set lead_time_hours = coalesce(lead_time_days, 1) * 24
 where lead_time_hours is null;
