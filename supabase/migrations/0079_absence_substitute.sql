-- 0079_absence_substitute.sql
-- Vacation/absence requests: substitute (Vertretung) selection.
--
-- Adds the chosen stand-in to an absence request so the approver sees WHO covers
-- the requester while they're away (and can weigh that person's open-ticket load
-- before approving). The manager-approval step itself already exists (0035:
-- status pending|approved|rejected + reviewed_by/reviewed_at); approval stays
-- org-admin-only, so no new role is introduced here.
--
-- Additive only: one nullable FK column (ON DELETE SET NULL so removing an
-- employee never orphans an absence row) + an index for substitute lookups.
-- Inert under old code, which never reads or writes this column.
alter table public.employee_absences
  add column if not exists substitute_employee_id uuid
    references public.employees (id) on delete set null;

create index if not exists idx_employee_absences_substitute
  on public.employee_absences (substitute_employee_id);
