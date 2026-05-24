-- Planning board: vehicles + tools (assets) and appointment assignment.

create table if not exists vehicles (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations on delete cascade,
  name text not null,
  model text,
  license_plate text,
  capacity_hours integer default 8,
  assigned_employee_id uuid references employees on delete set null,
  color text,
  notes text,
  is_active boolean default true,
  created_at timestamptz default now()
);
create index if not exists idx_vehicles_org on vehicles (org_id);
alter table vehicles enable row level security;

create table if not exists tools (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations on delete cascade,
  name text not null,
  category text,
  serial_number text,
  assigned_employee_id uuid references employees on delete set null,
  storage_location text,
  notes text,
  is_active boolean default true,
  created_at timestamptz default now()
);
create index if not exists idx_tools_org on tools (org_id);
alter table tools enable row level security;

alter table appointments add column if not exists vehicle_id uuid references vehicles on delete set null;
alter table appointments add column if not exists tool_id uuid references tools on delete set null;
