-- 0054 — per-action to-do state for the Aktionen tab. Additive.
--
-- Aktionen are DERIVED from live entity state (pending appointments, cancellations,
-- KVAs…), so they have nowhere to record "a human picked this up / marked it done /
-- deleted it". This table overlays that manual to-do state, keyed by a stable
-- action_key = "<kind>:<entity_id>" (e.g. "termin_anfrage:<appt_id>").
--
-- The aggregator LEFT-JOINs this:
--   * dismissed         → hidden (deleted by the user)
--   * done              → shown struck-through, then dropped 3 days after done_at
--   * claimed           → shown as "übernommen von <user>"
--   * open / no row     → normal open task

create table if not exists action_tasks (
  id          uuid primary key default gen_random_uuid(),
  org_id      uuid not null references organizations(id) on delete cascade,
  action_key  text not null,
  status      text not null default 'open' check (status in ('open','claimed','done','dismissed')),
  claimed_by  uuid references users(id) on delete set null,
  done_at     timestamptz,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (org_id, action_key)
);

create index if not exists idx_action_tasks_org on action_tasks (org_id);
