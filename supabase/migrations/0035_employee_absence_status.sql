-- 0035_employee_absence_status.sql
-- Employee absence self-service + admin approval (Item A).
--
-- Adds an approval lifecycle to employee_absences so an employee can APPLY for
-- their OWN absence (status='pending') and an org-admin APPROVES or REJECTS it.
--
--   status ∈ 'pending' | 'approved' | 'rejected'   (enforced in the app layer,
--   like inquiries._ALLOWED_STATUS — no DB CHECK, so this stays purely additive)
--
-- Backfill: existing rows + admin-created absences default to 'approved' — they
-- were created by an admin and are already in effect; only the new
-- employee-submitted path sets 'pending'. reviewed_by / reviewed_at record which
-- admin actioned a request and when.
--
-- Additive only: ADD COLUMN IF NOT EXISTS (+ one index). Inert under old code,
-- which never reads or writes these columns.
alter table public.employee_absences
  add column if not exists status text not null default 'approved',
  add column if not exists reviewed_by uuid,
  add column if not exists reviewed_at timestamptz;

create index if not exists idx_employee_absences_org_status
  on public.employee_absences (org_id, status);
