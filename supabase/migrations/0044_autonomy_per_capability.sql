-- 0044_autonomy_per_capability.sql
--
-- Autonomy redesign (topics 19/21/22): replace the single agent_configs.kiki_level
-- with PER-CAPABILITY toggles + levels for four capabilities:
--   * Termine (appointments)   — in-call (agent prompt)
--   * KVA (cost estimates)     — in-call (agent prompt)
--   * Projekte/Plantafel       — back-office automation (on appointment confirm)
--   * Rechnungen (invoices)    — back-office automation (on project completion)
--
-- Notdienst + "Termin verschieben" leave the autonomy matrix (emergency = pure
-- forward-to-number; reschedule follows the Termine level).
--
-- ADDITIVE ONLY. kiki_level and kva_automation_enabled are kept in place but go
-- dormant once the code reads the new columns; a later cleanup migration drops them.

alter table agent_configs
  add column if not exists appointments_enabled boolean not null default true,
  add column if not exists appointments_level integer not null default 2 check (appointments_level in (1, 2, 3)),
  add column if not exists kva_enabled boolean not null default false,
  add column if not exists kva_level integer not null default 2 check (kva_level in (1, 2, 3)),
  add column if not exists projects_enabled boolean not null default false,
  add column if not exists projects_level integer not null default 2 check (projects_level in (1, 2, 3)),
  add column if not exists invoices_enabled boolean not null default false,
  add column if not exists invoices_level integer not null default 2 check (invoices_level in (1, 2, 3));

-- Backfill from the legacy single level so existing orgs keep their behaviour:
--   * appointments always worked        -> appointments_enabled stays true
--   * appointments/KVA autonomy level   -> inherit kiki_level
--   * KVA only ran when automation on   -> kva_enabled = kva_automation_enabled
--   * projects/invoices are new         -> stay OFF (opt-in)
update agent_configs
   set appointments_level = coalesce(kiki_level, 2),
       kva_level          = coalesce(kiki_level, 2),
       kva_enabled        = coalesce(kva_automation_enabled, false);
