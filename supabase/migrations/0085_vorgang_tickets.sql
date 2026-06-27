-- 0085_vorgang_tickets.sql — Vorgang-as-ticket (additive, no data change).
--
-- A Vorgang bundles many calls; these support an aggregate AI title/summary that
-- refreshes as calls join/leave, a human-edit lock so the AI never clobbers a manual
-- title, and per-customer merge suggestions (the "this call looks like it belongs to
-- an open ticket — merge?" Open Action). Applied to UAT 2026-06-27.

alter table cases add column if not exists ai_summary text;
alter table cases add column if not exists title_locked boolean not null default false;

-- A pending suggestion = "the source Vorgang (one fresh call) probably belongs to the
-- target Vorgang of the same customer". Surfaced in the Open Actions; accept merges
-- source→target, reject dismisses it.
create table if not exists case_merge_suggestions (
  id             uuid primary key default gen_random_uuid(),
  org_id         uuid not null references organizations(id) on delete cascade,
  customer_id    uuid references customers(id) on delete cascade,
  source_case_id uuid not null references cases(id) on delete cascade,
  target_case_id uuid not null references cases(id) on delete cascade,
  confidence     numeric,
  reason         text,
  status         text not null default 'pending'
                 check (status in ('pending', 'accepted', 'rejected', 'stale')),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists idx_case_merge_suggestions_org_status
  on case_merge_suggestions (org_id, status);

-- At most one live suggestion per source Vorgang.
create unique index if not exists idx_case_merge_suggestions_source_pending
  on case_merge_suggestions (source_case_id) where status = 'pending';
