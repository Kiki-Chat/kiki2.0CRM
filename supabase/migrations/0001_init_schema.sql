-- HeyKiki Portal — initial schema (Phase 1)
-- Multi-tenant CRM. Every tenant table carries org_id and is RLS-scoped.

create extension if not exists "pgcrypto";

-- ─── ORGANIZATIONS ──────────────────────────────────────────────────────────
create table organizations (
  id uuid primary key default gen_random_uuid(),
  heykiki_org_id text unique not null,
  name text not null,
  slug text unique,
  elevenlabs_agent_id text unique,
  phone_number text,
  email text,
  address jsonb,
  bank_details jsonb,
  tax_info jsonb,
  trade text,
  logo_url text,
  accent_color text default '#81C264',
  font_preference text default 'Inter',
  ai_minutes_quota integer default 100,
  created_at timestamptz default now()
);
create index idx_orgs_agent on organizations (elevenlabs_agent_id);

-- ─── PER-ORG WEBHOOK SECRETS ────────────────────────────────────────────────
create table org_secrets (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations on delete cascade,
  secret text unique not null,
  created_at timestamptz default now()
);
create index idx_org_secrets_org on org_secrets (org_id);

-- ─── USERS (employees + admins) ─────────────────────────────────────────────
create table users (
  id uuid primary key references auth.users on delete cascade,
  org_id uuid references organizations on delete cascade,
  full_name text,
  email text unique,
  role text not null default 'employee'
    check (role in ('super_admin', 'org_admin', 'employee')),
  avatar_url text,
  created_at timestamptz default now()
);
create index idx_users_org on users (org_id);

-- Helper: org_id for the current authenticated user (used by RLS policies).
create or replace function auth_org_id()
returns uuid
language sql
stable
security definer
set search_path = public
as $$
  select org_id from public.users where id = auth.uid()
$$;

-- ─── CUSTOMERS ──────────────────────────────────────────────────────────────
create table customers (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations on delete cascade,
  full_name text,
  phone text,
  email text,
  address jsonb,
  customer_number text,
  identified_by text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
create index idx_customers_org on customers (org_id);
create index idx_customers_phone on customers (org_id, phone);
create index idx_customers_number on customers (org_id, customer_number);

-- ─── CALLS ──────────────────────────────────────────────────────────────────
create table calls (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations on delete cascade,
  customer_id uuid references customers on delete set null,
  elevenlabs_conversation_id text unique,
  direction text check (direction in ('inbound', 'outbound')),
  started_at timestamptz,
  duration_seconds integer,
  status text check (status in ('active', 'completed', 'missed')),
  transcript jsonb,
  audio_url text,
  audio_size_bytes integer,
  summary text,
  created_at timestamptz default now()
);
create index idx_calls_org on calls (org_id);
create index idx_calls_conversation on calls (elevenlabs_conversation_id);

-- ─── INQUIRIES ──────────────────────────────────────────────────────────────
create table inquiries (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations on delete cascade,
  call_id uuid references calls on delete set null,
  customer_id uuid references customers on delete set null,
  assigned_to uuid references users on delete set null,
  title text,
  type text,
  status text default 'open'
    check (status in ('open', 'in_progress', 'completed', 'deleted')),
  notes text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
create index idx_inquiries_org on inquiries (org_id);
create index idx_inquiries_status on inquiries (org_id, status);

-- ─── APPOINTMENTS ───────────────────────────────────────────────────────────
create table appointments (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations on delete cascade,
  inquiry_id uuid references inquiries on delete set null,
  customer_id uuid references customers on delete set null,
  assigned_to uuid references users on delete set null,
  title text,
  scheduled_at timestamptz,
  duration_minutes integer,
  location jsonb,
  category text,
  status text default 'pending'
    check (status in ('pending', 'confirmed', 'cancelled', 'completed')),
  notes text,
  created_at timestamptz default now()
);
create index idx_appointments_org on appointments (org_id);
create index idx_appointments_sched on appointments (org_id, scheduled_at);

-- ─── COST ESTIMATES (KVA) ───────────────────────────────────────────────────
create table cost_estimates (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations on delete cascade,
  customer_id uuid references customers on delete set null,
  number text,
  status text default 'draft'
    check (status in ('draft', 'sent', 'accepted', 'rejected', 'expired')),
  line_items jsonb,
  subtotal numeric,
  tax_rate numeric,
  total numeric,
  valid_until date,
  sent_at timestamptz,
  created_at timestamptz default now()
);
create index idx_kva_org on cost_estimates (org_id);

-- ─── INVOICES ───────────────────────────────────────────────────────────────
create table invoices (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations on delete cascade,
  customer_id uuid references customers on delete set null,
  cost_estimate_id uuid references cost_estimates on delete set null,
  number text,
  status text default 'draft'
    check (status in ('draft', 'sent', 'paid', 'overdue', 'cancelled')),
  line_items jsonb,
  subtotal numeric,
  tax_rate numeric,
  total numeric,
  due_date date,
  paid_at timestamptz,
  created_at timestamptz default now()
);
create index idx_invoices_org on invoices (org_id);

-- ─── EMPLOYEES ──────────────────────────────────────────────────────────────
create table employees (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations on delete cascade,
  user_id uuid references users on delete set null,
  display_name text,
  role_in_company text,
  skills text[],
  is_active boolean default true,
  created_at timestamptz default now()
);
create index idx_employees_org on employees (org_id);

-- ─── AGENT CONFIG (Kiki-Zentrale) ───────────────────────────────────────────
create table agent_configs (
  id uuid primary key default gen_random_uuid(),
  org_id uuid unique not null references organizations on delete cascade,
  welcome_message text,
  forwarding_number text,
  incoming_forwarding_number text,
  autonomy_level integer check (autonomy_level in (1, 2, 3)),
  trade_specialty text,
  mandatory_fields jsonb,
  appointment_categories jsonb,
  scheduling jsonb,
  emergency_service jsonb,
  kva_automation_enabled boolean default false,
  proactive_ai_enabled boolean default true,
  updated_at timestamptz default now()
);

-- ─── CATALOG ────────────────────────────────────────────────────────────────
create table catalog_items (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations on delete cascade,
  name text,
  description text,
  unit_price numeric,
  unit text,
  category text,
  is_active boolean default true,
  created_at timestamptz default now()
);
create index idx_catalog_org on catalog_items (org_id);

-- ─── AI SUGGESTIONS ─────────────────────────────────────────────────────────
create table ai_suggestions (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations on delete cascade,
  type text,
  reference_id uuid,
  reference_type text,
  message text,
  status text default 'pending'
    check (status in ('pending', 'actioned', 'dismissed')),
  generated_at timestamptz default now()
);
create index idx_ai_suggestions_org on ai_suggestions (org_id);

-- ─── TIME TRACKING ──────────────────────────────────────────────────────────
create table time_entries (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations on delete cascade,
  employee_id uuid references employees on delete set null,
  customer_id uuid references customers on delete set null,
  inquiry_id uuid references inquiries on delete set null,
  description text,
  hours numeric,
  hourly_rate numeric,
  billed boolean default false,
  date date,
  created_at timestamptz default now()
);
create index idx_time_entries_org on time_entries (org_id);

-- ─── ROW LEVEL SECURITY ─────────────────────────────────────────────────────
-- The backend uses the service-role key (bypasses RLS). These policies are
-- defense-in-depth for any direct client (supabase-js) access: a user may only
-- see rows belonging to their own organization.

alter table organizations  enable row level security;
alter table org_secrets    enable row level security;
alter table users          enable row level security;
alter table customers      enable row level security;
alter table calls          enable row level security;
alter table inquiries      enable row level security;
alter table appointments   enable row level security;
alter table cost_estimates enable row level security;
alter table invoices       enable row level security;
alter table employees      enable row level security;
alter table agent_configs  enable row level security;
alter table catalog_items  enable row level security;
alter table ai_suggestions enable row level security;
alter table time_entries   enable row level security;

-- org_secrets has NO client policy on purpose: never readable by the browser.

create policy org_self_read on organizations
  for select using (id = auth_org_id());

create policy users_same_org on users
  for select using (org_id = auth_org_id() or id = auth.uid());

-- Tenant tables: full access scoped to the caller's org.
do $$
declare t text;
begin
  foreach t in array array[
    'customers','calls','inquiries','appointments','cost_estimates',
    'invoices','employees','agent_configs','catalog_items',
    'ai_suggestions','time_entries'
  ]
  loop
    execute format(
      'create policy %I_org_all on %I for all
         using (org_id = auth_org_id())
         with check (org_id = auth_org_id())',
      t, t
    );
  end loop;
end $$;
