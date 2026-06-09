-- 0057 — human-readable case number (the staff- and call-log-facing "Fall" number).
-- Additive. Inquiry = Anfrage (ANF-…); Case = Fall, its own number FALL-YYYY-NNNN.

alter table cases add column if not exists number text;
create index if not exists idx_cases_number on cases (number);

-- Backfill numbers for cases already created (per org, per year, by creation order).
with ranked as (
  select id,
         'FALL-' || to_char(created_at, 'YYYY') || '-' ||
         lpad((row_number() over (partition by org_id, to_char(created_at, 'YYYY') order by created_at, id))::text, 4, '0') as num
  from cases
  where number is null
)
update cases c set number = r.num from ranked r where c.id = r.id;
