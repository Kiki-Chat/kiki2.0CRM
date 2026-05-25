-- KI-Insights: track dismissals/snoozes of on-demand AI suggestions so the
-- dashboard doesn't re-surface a suggestion the user already handled.

create table if not exists ai_suggestion_actions (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  suggestion_key text not null,                 -- "{category}:{record_id}"
  action text not null check (action in ('done', 'snooze')),
  until_date timestamptz,                        -- for snooze: re-surface after this
  created_at timestamptz not null default now()
);

create index if not exists ai_suggestion_actions_org_idx
  on ai_suggestion_actions (org_id, suggestion_key);

alter table ai_suggestion_actions enable row level security;
drop policy if exists ai_suggestion_actions_org_all on ai_suggestion_actions;
create policy ai_suggestion_actions_org_all on ai_suggestion_actions
  for all using (org_id = auth_org_id()) with check (org_id = auth_org_id());
