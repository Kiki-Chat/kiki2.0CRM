-- 0070: pds_sync_log — captures EVERY PDS API interaction (the request we send +
-- the raw JSON response body) for verification during the early integration
-- stages (Amber 2026-06-12 — logging materials are thin right now). Additive,
-- org-scoped. Later we'll roll the useful bits into the existing tables; this is
-- the diagnostic ledger for "is everything actually working".
create table if not exists pds_sync_log (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  operation text not null,             -- test_connection | log_call | greeting | create_contact | sync
  endpoint text,                       -- PDS REST path hit (person/listpersonen, crm/createaufgabe, …)
  call_id uuid,                        -- our calls.id when relevant (no FK: log survives a call delete)
  status text not null default 'success',  -- success | error
  request_payload jsonb,               -- exactly what we POSTed to PDS
  response_payload jsonb,              -- the raw JSON body PDS returned (object OR array)
  error_message text,
  created_at timestamptz not null default now()
);
create index if not exists idx_pds_sync_log_org_created on pds_sync_log (org_id, created_at desc);

alter table pds_sync_log enable row level security;
create policy pds_sync_log_org_all on pds_sync_log
  for all using (org_id = auth_org_id()) with check (org_id = auth_org_id());
