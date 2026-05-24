-- Columns to store the ElevenLabs post-call payload on the calls row.
alter table calls add column if not exists agent_id text;
alter table calls add column if not exists caller_number text;
alter table calls add column if not exists summary_title text;
alter table calls add column if not exists data_collection jsonb;
create index if not exists idx_calls_caller on calls (org_id, caller_number);
