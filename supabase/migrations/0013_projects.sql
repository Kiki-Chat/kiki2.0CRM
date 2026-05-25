-- Projects (Projekte): bundle all work for one customer job into a single view.
-- A project links calls (via customer), inquiries, appointments, cost estimates,
-- invoices, documents and assigned employees.

create table if not exists projects (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations on delete cascade,
  customer_id uuid references customers on delete set null,
  number text,                                   -- PRJ-YYYY-NNNNN
  title text not null,
  description text,
  status text default 'planning'
    check (status in ('planning', 'active', 'completed', 'archived')),
  start_date date,
  end_date date,
  planned_budget numeric,
  project_address jsonb,                          -- {street, postcode, city}
  internal_notes text,
  notes_updated_at timestamptz,
  created_by uuid references users on delete set null,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
create index if not exists idx_projects_org on projects (org_id);
create unique index if not exists idx_projects_org_number on projects (org_id, number);

create table if not exists project_employees (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects on delete cascade,
  employee_id uuid not null references employees on delete cascade,
  added_at timestamptz default now(),
  unique (project_id, employee_id)
);
create index if not exists idx_project_employees_project on project_employees (project_id);

-- Link existing record types to a project.
alter table inquiries      add column if not exists project_id uuid references projects on delete set null;
alter table appointments   add column if not exists project_id uuid references projects on delete set null;
alter table cost_estimates add column if not exists project_id uuid references projects on delete set null;
alter table invoices       add column if not exists project_id uuid references projects on delete set null;
alter table documents      add column if not exists project_id uuid references projects on delete set null;

create index if not exists idx_inquiries_project on inquiries (project_id);
create index if not exists idx_appointments_project on appointments (project_id);
create index if not exists idx_cost_estimates_project on cost_estimates (project_id);
create index if not exists idx_invoices_project on invoices (project_id);
create index if not exists idx_documents_project on documents (project_id);

-- RLS (backend uses the service role and bypasses this; kept consistent with the rest).
alter table projects enable row level security;
create policy projects_org_all on projects
  for all using (org_id = auth_org_id()) with check (org_id = auth_org_id());

alter table project_employees enable row level security;
create policy project_employees_org_all on project_employees
  for all using (
    exists (select 1 from projects p where p.id = project_employees.project_id and p.org_id = auth_org_id())
  ) with check (
    exists (select 1 from projects p where p.id = project_employees.project_id and p.org_id = auth_org_id())
  );
