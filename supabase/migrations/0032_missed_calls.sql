-- 0032_missed_calls.sql
-- Data source for the missed_callback (RUECKRUF_VERPASST) outbound occasion.
-- A genuinely missed/unanswered inbound call leaves NO record today (calls are
-- written only by the completed-conversation post-call webhook). This table is
-- where missed calls get recorded so the agent can ring them back.
--
-- ⚠️ DEPENDENCY (not built this session): the real writer is a Twilio
-- status-callback handler (no-answer/busy/failed → insert a row here). Until
-- that exists, rows are seeded manually; the occasion flow itself is complete.
-- Additive.

create table if not exists missed_calls (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  customer_id uuid references customers(id) on delete set null,
  caller_number text not null,
  missed_at timestamptz not null default now(),
  status text not null default 'pending',   -- 'pending' | 'called_back' | 'closed'
  created_at timestamptz not null default now()
);

create index if not exists idx_missed_calls_org_status
  on missed_calls (org_id, status);
