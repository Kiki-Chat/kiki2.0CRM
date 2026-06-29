-- 0088_two_stage_columns.sql
-- Employee/Technician redesign — Track A, Phase 1 (ADDITIVE).
--
-- The two orthogonal axes that the old single column collapsed:
--   * appointments.coordinator_employee_id -> the OFFICE employee who owns/confirms the
--     ticket (background; their calendar gates NOTHING). The visiting technician lives on
--     appointment_jobs (0089), NOT on assigned_employee_id anymore.
--   * cases.department_id -> the vertical a ticket belongs to (routing + Track B visibility).
--   * employee_absences.source -> distinguishes admin-entered absences from self/OAuth ones.
--     Nullable: legacy rows stay NULL (unknown); new writes set it explicitly.
--
-- All additive nullable columns. Inert under old code.

alter table public.appointments
  add column if not exists coordinator_employee_id uuid references employees(id) on delete set null;

alter table public.cases
  add column if not exists department_id uuid references departments(id) on delete set null;

alter table public.employee_absences
  add column if not exists source text
  check (source in ('self','admin'));   -- NULL allowed = legacy/unknown
