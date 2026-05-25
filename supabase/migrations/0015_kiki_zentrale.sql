-- Kiki-Zentrale: full agent control surface.
-- Normalizes the jsonb stubs from 0001 (mandatory_fields, appointment_categories,
-- emergency_service) into real columns + child tables, and adds snapshot/audit
-- tables that back the "safe writes, not blocked writes" safety model.
--
-- NOTE: kiki_level overlaps the legacy agent_configs.autonomy_level (same concept,
-- different name). 0015 introduces kiki_level as the canonical field; autonomy_level
-- is left in place for now. TODO(reconcile): migrate autonomy_level -> kiki_level and
-- drop autonomy_level + the legacy jsonb stubs once provisioning is updated.

-- ─── agent_configs additions (idempotent) ───────────────────────────────────
alter table agent_configs
  add column if not exists kiki_level integer not null default 2 check (kiki_level in (1, 2, 3)),
  add column if not exists welcome_message text,           -- HeyKiki-side conversation init (already present from 0001; no-op)
  add column if not exists trade text,
  add column if not exists knowledge_text text default '',
  add column if not exists forwarding_number text,
  add column if not exists incoming_forwarding_number text,
  add column if not exists scheduling_enabled boolean not null default true,
  add column if not exists buffer_minutes integer not null default 30,
  add column if not exists max_appointments_per_day integer not null default 4,
  add column if not exists parallel_slots integer not null default 1,
  add column if not exists lead_time_days integer not null default 1,
  add column if not exists lead_time_only_weekdays boolean not null default true,
  add column if not exists lead_time_earliest_clock time,
  add column if not exists price_info_enabled boolean not null default false,
  add column if not exists emergency_enabled boolean not null default false,
  add column if not exists emergency_number text,
  add column if not exists emergency_only_outside_business_hours boolean not null default true,
  add column if not exists emergency_keywords jsonb not null default '[]'::jsonb,
  add column if not exists emergency_extra_windows jsonb not null default '[]'::jsonb,
  add column if not exists emergency_surcharge_notice_enabled boolean not null default true,
  add column if not exists emergency_surcharge_text text,
  add column if not exists outbound_enabled boolean not null default false,
  add column if not exists outbound_occasions jsonb not null default '{}'::jsonb,
  add column if not exists outbound_time_from time not null default '09:00',
  add column if not exists outbound_time_to time not null default '20:00',
  add column if not exists outbound_weekdays jsonb not null default '["mon","tue","wed","thu","fri"]'::jsonb;

-- ─── Child tables ───────────────────────────────────────────────────────────
create table if not exists agent_required_fields (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  field_key text not null,
  label text not null,
  description text,
  is_locked boolean not null default false,
  is_duty boolean not null default true,
  identification_role text,        -- null | 'caller_id' | 'customer_number' | 'address'
  sort_order integer not null default 0,
  created_at timestamptz not null default now()
);

create table if not exists appointment_categories (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  name text not null,
  description text,
  duration_minutes integer not null default 60,
  default_employee_id uuid references users(id) on delete set null,
  sort_order integer not null default 0,
  created_at timestamptz not null default now()
);

create table if not exists agent_services (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  name text not null,
  is_offered boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists knowledge_resources (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  kind text not null check (kind in ('url','pdf')),
  source text not null,
  display_name text not null,
  chunk_count integer not null default 0,
  status text not null default 'pending' check (status in ('pending','processing','ready','error')),
  status_message text,
  elevenlabs_doc_id text,           -- the ID returned by ElevenLabs KB API
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Full pre-write snapshots for rollback
create table if not exists agent_config_snapshots (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  agent_id text not null,
  actor_id uuid references users(id),
  endpoint_label text not null,
  full_config jsonb not null,       -- full ElevenLabs agent payload before the write
  created_at timestamptz not null default now()
);

-- Per-field diff audit
create table if not exists agent_writes_audit (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  agent_id text not null,
  actor_id uuid references users(id),
  endpoint_label text not null,
  snapshot_id uuid references agent_config_snapshots(id) on delete set null,
  fields_changed jsonb not null,    -- {field_path: {old, new}}
  elevenlabs_response_status integer,
  elevenlabs_response_excerpt text,
  rolled_back boolean not null default false,
  rolled_back_at timestamptz,
  rolled_back_by uuid references users(id),
  created_at timestamptz not null default now()
);

-- ─── Indexes ────────────────────────────────────────────────────────────────
create index if not exists agent_writes_audit_org_created_idx on agent_writes_audit (org_id, created_at desc);
create index if not exists agent_config_snapshots_org_created_idx on agent_config_snapshots (org_id, created_at desc);
create index if not exists agent_required_fields_org_idx on agent_required_fields (org_id, sort_order);
create index if not exists appointment_categories_org_idx on appointment_categories (org_id, sort_order);
create index if not exists agent_services_org_idx on agent_services (org_id);
create index if not exists knowledge_resources_org_idx on knowledge_resources (org_id);

-- ─── RLS (org-scoped; backend uses the service role and bypasses) ────────────
do $$
declare t text;
begin
  foreach t in array array[
    'agent_required_fields','appointment_categories','agent_services',
    'knowledge_resources','agent_config_snapshots','agent_writes_audit'
  ]
  loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists %I_org_all on %I', t, t);
    execute format(
      'create policy %I_org_all on %I for all using (org_id = auth_org_id()) with check (org_id = auth_org_id())',
      t, t
    );
  end loop;
end $$;

-- ─── Storage bucket for uploaded knowledge PDFs (private; signed-URL access) ──
-- Backend reads/writes via the service role (bypasses storage RLS); the browser
-- only ever gets short-lived signed URLs minted by the backend.
insert into storage.buckets (id, name, public)
values ('agent-knowledge', 'agent-knowledge', false)
on conflict (id) do nothing;

-- ─── Seed default required fields for the test org (idempotent) ──────────────
insert into agent_required_fields
  (org_id, field_key, label, description, is_locked, is_duty, identification_role, sort_order)
select o.id, v.field_key, v.label, v.description, v.is_locked, v.is_duty, v.identification_role, v.sort_order
from organizations o
cross join (values
  ('concern', 'Anliegen',       'Das Anliegen des Anrufers', true, true, null::text,   0),
  ('name',    'Name',           'Vor- und Nachname',         true, true, null::text,   1),
  ('phone',   'Telefonnummer',  'Rückrufnummer',             true, true, 'caller_id',  2)
) as v(field_key, label, description, is_locked, is_duty, identification_role, sort_order)
where o.heykiki_org_id = 'kiki-test-007'
  and not exists (
    select 1 from agent_required_fields a
    where a.org_id = o.id and a.field_key = v.field_key
  );

-- TODO(retention): keep only the latest 50 agent_config_snapshots per org.
-- Implement as a scheduled cleanup (pg_cron or a backend job). Stub for now.
