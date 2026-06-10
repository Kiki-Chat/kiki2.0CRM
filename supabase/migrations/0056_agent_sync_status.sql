-- 0056: Agent-sync status tracking (Kiki-Zentrale "Einstellungen werden übertragen" loader).
-- Additive only. Every config save that triggers a background prompt re-push to
-- ElevenLabs now records pending → applied/failed on the org's agent_configs row,
-- so the frontend can show a live sync banner. agent_sync_seq is a monotonically
-- increasing request id: a stale background completion (older seq) never
-- overwrites the state of a newer save (last-write-wins).
-- NOTE: 0055 is reserved by feature/vorgang-case-threading (unapplied).

alter table agent_configs
  add column if not exists agent_sync_status text not null default 'idle'
    check (agent_sync_status in ('idle', 'pending', 'applied', 'failed')),
  add column if not exists agent_sync_label text,
  add column if not exists agent_sync_error text,
  add column if not exists agent_sync_seq bigint not null default 0,
  add column if not exists agent_sync_requested_at timestamptz,
  add column if not exists agent_sync_finished_at timestamptz;

-- Atomic begin-sync: bump the seq and flip to pending in one statement
-- (supabase-py cannot express `set seq = seq + 1 ... returning`).
create or replace function kz_begin_agent_sync(p_org uuid, p_label text)
returns bigint
language sql
as $$
  update agent_configs
     set agent_sync_seq = agent_sync_seq + 1,
         agent_sync_status = 'pending',
         agent_sync_label = p_label,
         agent_sync_error = null,
         agent_sync_requested_at = now(),
         agent_sync_finished_at = null
   where org_id = p_org
   returning agent_sync_seq;
$$;
