-- 0033_appointments_google_calendar_sync.sql
-- Phase 0 (Google Calendar read-sync foundation): additive columns on
-- appointments linking CRM rows to external Google Calendar events + sync
-- bookkeeping. All nullable or constant-default → existing rows unaffected
-- (PG backfills `source`='crm' for every existing appointment; no table
-- rewrite). No CHECK constraint on `source` (kept additive per repo
-- convention — the app layer restricts to crm | google_import | ics).
alter table appointments add column if not exists google_event_id text;
alter table appointments add column if not exists source text not null default 'crm';
alter table appointments add column if not exists external_updated_at timestamptz;
alter table appointments add column if not exists last_synced_at timestamptz;

-- One CRM row per (org, Google event). Partial: CRM-origin rows
-- (google_event_id IS NULL) are exempt, so existing data is unaffected and the
-- upsert in calendar_sync.pull_google_events can use it as the conflict key.
create unique index if not exists uq_appointments_org_google_event
  on appointments (org_id, google_event_id)
  where google_event_id is not null;
