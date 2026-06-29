-- 0091_menu_access_preferred_technician.sql
-- Employee/Technician redesign — Track A, Phase 5 (ADDITIVE).
--
-- (1) employee_menu_access — per-employee menu LOCKS. A row = that menu key is
--     HIDDEN for that employee. Default (no rows) = sees everything their role
--     allows (fail-open). Admin-managed in the Employees edit modal. Office
--     employees only — technicians get the fixed light portal, no locks apply.
-- (2) customers.preferred_technician_id — the explicit "customer prefers tech X"
--     signal used by the assignment ladder (step 3, after continuity + workload).
--
-- Additive only. Org-scoped RLS via the standard auth_org_id() + <table>_org_all
-- pattern (mirrors 0074); never repeats the 0083 RLS-on/no-policy gap.

create table if not exists employee_menu_access (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  employee_id uuid not null references employees(id) on delete cascade,
  menu_key text not null,            -- a key from frontend nav.ts (e.g. 'invoices', 'catalog')
  created_at timestamptz not null default now(),
  unique (employee_id, menu_key)
);
create index if not exists idx_emp_menu_access_org on employee_menu_access (org_id);
create index if not exists idx_emp_menu_access_emp on employee_menu_access (employee_id);
alter table employee_menu_access enable row level security;

do $$
begin
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='employee_menu_access' and policyname='employee_menu_access_org_all') then
    create policy employee_menu_access_org_all on public.employee_menu_access
      for all using (org_id = auth_org_id()) with check (org_id = auth_org_id());
  end if;
end $$;

alter table public.customers
  add column if not exists preferred_technician_id uuid references employees(id) on delete set null;
