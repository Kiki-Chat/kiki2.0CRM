-- 0089_appointment_jobs.sql
-- Employee/Technician redesign — Track A, Phase 1 (ADDITIVE).
--
-- First-class "Job / Einsatz": the technician dispatch for a visit, a child of an
-- appointment. It carries the TECHNICIAN + work category + the status lifecycle, kept
-- distinct from the office coordinator (who owns the ticket, on appointments.coordinator_employee_id).
--
-- status lifecycle:
--   suggested  -> proposed while building the appointment SUGGESTION (no notification yet)
--   confirmed  -> customer confirmed the appointment; technician locked in
--   dispatched -> technician notified ("you have a job"), job link sent
--   en_route / done -> field progress
--   cancelled  -> re-dispatch or cancellation (old row cancelled, a new one created),
--                 which makes Google-event + job-link cleanup explicit.
-- One appointment -> 0..n jobs.
--
-- Additive. Org-scoped RLS via the standard auth_org_id() + <table>_org_all pattern.

create table if not exists appointment_jobs (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  appointment_id uuid not null references appointments(id) on delete cascade,
  technician_employee_id uuid references employees(id) on delete set null,
  department_id uuid references departments(id) on delete set null,
  work_type text,                 -- denormalized from the appointment category (repair/visit/...)
  status text not null default 'suggested'
    check (status in ('suggested','confirmed','dispatched','en_route','done','cancelled')),
  scheduled_at timestamptz,
  duration_minutes integer,
  job_link_id uuid references technician_job_links(id) on delete set null,
  technician_google_event_id text,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_appt_jobs_org on appointment_jobs (org_id);
create index if not exists idx_appt_jobs_appointment on appointment_jobs (appointment_id);
create index if not exists idx_appt_jobs_technician on appointment_jobs (technician_employee_id);
create index if not exists idx_appt_jobs_status on appointment_jobs (status);
alter table appointment_jobs enable row level security;

do $$
begin
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='appointment_jobs' and policyname='appointment_jobs_org_all') then
    create policy appointment_jobs_org_all on public.appointment_jobs
      for all using (org_id = auth_org_id()) with check (org_id = auth_org_id());
  end if;
end $$;
