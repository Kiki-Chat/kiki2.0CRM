-- Wave 2 / Agent 2.1 — list-item enrichment (CallLogsPage).
-- inquiries.assigned_employee_id already exists (added in 0005). This migration
-- only adds the emergency flag so the list-card NOTDIENST badge can render
-- without coupling to free-text category strings.
--
-- Additive only: nullable boolean defaulting to false, plus a partial index
-- on (org_id) where emergency_flag = true for fast "show me the urgent ones"
-- filtering. Old rows automatically take the default; backfill is intentionally
-- not done here (a separate job can later flip the flag for legacy "Notdienst"
-- / "Notfall" category rows if/when we want them to glow retroactively).

alter table inquiries
  add column if not exists emergency_flag boolean not null default false;

create index if not exists idx_inquiries_emergency_open
  on inquiries (org_id)
  where emergency_flag = true and status <> 'deleted';
