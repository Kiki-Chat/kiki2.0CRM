-- 0062: Hey-Kiki chat sessions — persistence for the panel's history view.
--
-- copilot_conversations + copilot_messages ALREADY EXIST since migration 0042;
-- the creates below are no-ops on existing databases and only matter for a
-- from-scratch setup. The assistant turn's action cards are stored in the
-- PRE-EXISTING copilot_messages.tool_calls jsonb (as
-- {"actions": [...], "client_actions": [...]}) — no new column needed.
-- (Applied 2026-06-10: only the two idx_* indexes were new; they duplicate the
-- 0042 copilot_*_idx indexes — harmless, kept for from-scratch parity.)

create table if not exists copilot_conversations (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations on delete cascade,
  user_id uuid not null,
  title text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_copilot_conversations_user
  on copilot_conversations (org_id, user_id, updated_at desc);

create table if not exists copilot_messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references copilot_conversations on delete cascade,
  org_id uuid not null,
  role text not null check (role in ('user', 'assistant')),
  content text,
  tool_calls jsonb,
  created_at timestamptz not null default now()
);
create index if not exists idx_copilot_messages_conversation
  on copilot_messages (conversation_id, created_at);
