-- Reference number for inquiries (e.g. ANF-2026-0089), returned to the AI agent.
alter table inquiries add column if not exists number text;
create index if not exists idx_inquiries_number on inquiries (org_id, number);
