-- Employee management: extra employee fields + absence tracking.

alter table employees add column if not exists email text;
alter table employees add column if not exists access_role text default 'employee'; -- admin | employee
alter table employees add column if not exists vacation_days_per_year integer default 28;
alter table employees add column if not exists remaining_vacation_days integer;
alter table employees add column if not exists hourly_rate numeric;
alter table employees add column if not exists activity_area text;
alter table employees add column if not exists auto_assign boolean default false;
alter table employees add column if not exists calendar_color text;
alter table employees add column if not exists deleted boolean default false;

create table if not exists employee_absences (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations on delete cascade,
  employee_id uuid not null references employees on delete cascade,
  type text not null default 'vacation'
    check (type in ('vacation', 'illness', 'training', 'home_office', 'other')),
  starts_at timestamptz not null,
  ends_at timestamptz not null,
  all_day boolean default true,
  reason text,
  internal_note text,
  created_at timestamptz default now()
);
create index if not exists idx_emp_absences_org on employee_absences (org_id);
create index if not exists idx_emp_absences_emp on employee_absences (employee_id);

alter table employee_absences enable row level security;
