-- 0087_employee_worker_kind.sql
-- Employee/Technician redesign — Track A, Phase 1 (ADDITIVE).
--
-- Role facet on the single employees table: office coordinator vs field technician vs both.
-- is_technician (0059) is KEPT as a synced shadow for back-compat (old code in
-- _dispatch_technician / _available_technicians still reads it); worker_kind is the
-- richer source of truth going forward ('both' = a Meister who coordinates AND visits).
--
-- NOTE: appointment_categories.description already exists in the schema — no change needed
-- there (it backs the description-driven intent matching at suggestion time).
--
-- Additive: ADD COLUMN + a one-time backfill. Inert under old code.

alter table public.employees
  add column if not exists worker_kind text not null default 'office'
  check (worker_kind in ('office','technician','both'));

-- Backfill from the existing boolean flag (only rows still at the default).
update public.employees
  set worker_kind = 'technician'
  where is_technician = true
    and worker_kind = 'office';
