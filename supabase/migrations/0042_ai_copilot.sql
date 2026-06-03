-- 0042 — AI Copilot ("Kiki Assistent") foundation (Phase 0). ALL ADDITIVE.
-- Conversation state, action audit, the complaint/escalation register, and the
-- AI usage/cost ledger. Inert until COPILOT_ENABLED=1 + OPENAI_API_KEY is set.
-- Mirrors the 0015 org-scoped RLS idiom (backend uses the service role and bypasses).

-- ─── Conversation state ──────────────────────────────────────────────────────
create table if not exists copilot_conversations (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  user_id uuid not null references users(id) on delete cascade,
  title text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists copilot_messages (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  conversation_id uuid not null references copilot_conversations(id) on delete cascade,
  role text not null check (role in ('user','assistant','tool','system')),
  content text,
  tool_calls jsonb,
  tool_call_id text,
  created_at timestamptz not null default now()
);

-- ─── Action audit (every executed write the copilot performs) ────────────────
create table if not exists copilot_action_audit (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  user_id uuid not null references users(id) on delete cascade,
  conversation_id uuid references copilot_conversations(id) on delete set null,
  tool_name text not null,
  args jsonb,
  result_status text,
  confirmed boolean not null default false,
  created_at timestamptz not null default now()
);

-- ─── Complaint / escalation register (emailed out to info.kikichat@gmail.com) ─
create table if not exists copilot_escalations (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  user_id uuid not null references users(id) on delete cascade,
  conversation_id uuid references copilot_conversations(id) on delete set null,
  summary text not null,
  body text,
  emailed_to text,
  email_status text,
  created_at timestamptz not null default now()
);

-- ─── AI usage + cost ledger (all AI features: copilot + classifiers) ─────────
create table if not exists ai_usage_log (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references organizations(id) on delete cascade,
  user_id uuid references users(id) on delete set null,
  feature text not null,
  model text not null,
  prompt_tokens integer not null default 0,
  completion_tokens integer not null default 0,
  cost_estimate numeric(12,6) not null default 0,
  created_at timestamptz not null default now()
);

-- ─── Indexes ─────────────────────────────────────────────────────────────────
create index if not exists copilot_conversations_org_user_idx on copilot_conversations (org_id, user_id, updated_at desc);
create index if not exists copilot_messages_conv_idx on copilot_messages (conversation_id, created_at);
create index if not exists copilot_action_audit_org_created_idx on copilot_action_audit (org_id, created_at desc);
create index if not exists copilot_escalations_org_created_idx on copilot_escalations (org_id, created_at desc);
create index if not exists ai_usage_log_org_created_idx on ai_usage_log (org_id, created_at desc);

-- ─── RLS (org-scoped; backend uses the service role and bypasses) ────────────
do $$
declare t text;
begin
  foreach t in array array[
    'copilot_conversations','copilot_messages','copilot_action_audit',
    'copilot_escalations','ai_usage_log'
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
