-- 0084_employee_absence_block_type.sql
-- Manual time-blocks: widen employee_absences.type to allow 'block' — a short,
-- time-bound unavailability ("blocked 14:00–16:00") distinct from a full-day
-- vacation/illness. The availability engine already counts any APPROVED absence
-- as busy, so a block needs no new table — only this value.
--
-- Additive: drop + recreate the CHECK with the extra value (the inline check from
-- 0008 is named <table>_<column>_check by Postgres). Idempotent via IF EXISTS.
alter table public.employee_absences
  drop constraint if exists employee_absences_type_check;
alter table public.employee_absences
  add constraint employee_absences_type_check
  check (type in ('vacation', 'illness', 'training', 'home_office', 'other', 'block'));
