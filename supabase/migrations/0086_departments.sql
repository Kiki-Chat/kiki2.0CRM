-- 0086_departments.sql
-- Employee/Technician redesign — Track A, Phase 1 (ADDITIVE).
--
-- Normalized vertical/department taxonomy. This is the STRUCTURED form of the
-- existing free-text "Area of Activity" (employees.activity_area): an org defines
-- its verticals once (pipes/heating = trade_vertical; tax/finance/legal = admin_vertical)
-- and people are linked to them. It anchors BOTH:
--   * ticket routing  -> the office employee who OWNS a vertical (is_owner = true)
--   * per-employee visibility (Track B) -> what a non-admin may see
-- activity_area is kept untouched as a fallback during the transition.
--
-- Additive only. Org-scoped RLS via the standard auth_org_id() + <table>_org_all
-- pattern (mirrors 0074) so this does NOT repeat the 0083 RLS-on/no-policy gap.

create table if not exists departments (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  name text not null,
  kind text not null default 'trade_vertical'
    check (kind in ('trade_vertical','admin_vertical')),
  color text,
  sort_order integer not null default 0,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);
create index if not exists idx_departments_org on departments (org_id);
alter table departments enable row level security;

create table if not exists employee_departments (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  employee_id uuid not null references employees(id) on delete cascade,
  department_id uuid not null references departments(id) on delete cascade,
  -- true = the OFFICE employee who manages/owns this vertical (the ticket-routing target).
  -- technicians get is_owner=false rows for the trade verticals they can service (competence).
  is_owner boolean not null default false,
  created_at timestamptz not null default now(),
  unique (employee_id, department_id)
);
create index if not exists idx_emp_dept_org on employee_departments (org_id);
create index if not exists idx_emp_dept_dept on employee_departments (department_id);
create index if not exists idx_emp_dept_emp on employee_departments (employee_id);
alter table employee_departments enable row level security;

-- Org-scoped RLS (standard auth_org_id() + <table>_org_all pattern; see 0074).
do $$
begin
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='departments' and policyname='departments_org_all') then
    create policy departments_org_all on public.departments
      for all using (org_id = auth_org_id()) with check (org_id = auth_org_id());
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='employee_departments' and policyname='employee_departments_org_all') then
    create policy employee_departments_org_all on public.employee_departments
      for all using (org_id = auth_org_id()) with check (org_id = auth_org_id());
  end if;
end $$;
