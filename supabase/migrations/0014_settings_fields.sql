-- Settings (Einstellungen) module: org profile fields, per-user UI language,
-- AI suggestion thresholds, and credential-bearing config tables (email + PDS).

-- ── Org additions ──
alter table organizations
  add column if not exists fax text,
  add column if not exists website text,
  add column if not exists management jsonb,                              -- {name, title}
  add column if not exists chamber_of_crafts text,
  add column if not exists google_reviews_enabled boolean not null default false;

-- ── User UI language (cross-device persistence) ──
alter table public.users
  add column if not exists language_preference text not null default 'de';

-- ── AI suggestion thresholds (live on agent_configs) ──
alter table agent_configs
  add column if not exists ai_suggestions_enabled boolean not null default true,
  add column if not exists kva_followup_days integer not null default 7,
  add column if not exists payment_reminder_days integer not null default 14,
  add column if not exists appointment_reminder_days integer not null default 1,
  add column if not exists maintenance_reminder_days integer not null default 30;

-- ── Email config (credentials kept OUT of organizations; password encrypted) ──
create table if not exists email_configs (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null unique references organizations(id) on delete cascade,
  provider text not null default 'smtp',           -- 'gmail' | 'outlook' | 'smtp'
  smtp_host text,
  smtp_port integer default 465,
  smtp_username text,
  smtp_password_encrypted text,
  smtp_sender_name text,
  smtp_sender_email text,
  use_ssl boolean not null default true,
  invoice_email_subject text,
  invoice_email_body text,
  kva_email_subject text,
  kva_email_body text,
  updated_at timestamptz not null default now()
);

-- ── PDS integration config (api key encrypted) ──
create table if not exists pds_configs (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null unique references organizations(id) on delete cascade,
  api_url text,
  api_user text,
  api_key_encrypted text,
  auto_sync_enabled boolean not null default false,
  sync_interval text default 'every_30_min',       -- 'every_15_min' | 'every_30_min' | 'hourly' | 'daily'
  sync_entities jsonb not null default '{}'::jsonb, -- {customers: 'bidirectional', ...}
  last_sync_at timestamptz,
  updated_at timestamptz not null default now()
);

-- ── RLS (org-scoped; backend uses the service role and bypasses) ──
alter table email_configs enable row level security;
drop policy if exists email_configs_org_all on email_configs;
create policy email_configs_org_all on email_configs
  for all using (org_id = auth_org_id()) with check (org_id = auth_org_id());

alter table pds_configs enable row level security;
drop policy if exists pds_configs_org_all on pds_configs;
create policy pds_configs_org_all on pds_configs
  for all using (org_id = auth_org_id()) with check (org_id = auth_org_id());
