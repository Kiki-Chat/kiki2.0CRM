-- 0082_backfill_call_titles.sql — ONE-TIME data backfill (no schema change).
--
-- Aligns existing Anfrage/Vorgang titles with the German `issue_summary` (the org's
-- Betreffzeile-prompt output) instead of ElevenLabs' generic, often-English
-- `summary_title`, and makes Vorgang titles unique per customer. The forward-looking
-- writers were changed in app/services/inquiries.py, app/services/projects_auto.py and
-- app/api/routes/cases.py + app/services/cases/titles.py; this fixes the rows already
-- stored. Applied to UAT 2026-06-27; run once on prod after the code deploy.

-- (a) Anfragen: title <- call.issue_summary, ONLY where the title is still the
--     auto-set summary_title (never manually edited) and an issue_summary exists.
update inquiries i
set title = btrim(c.data_collection->>'issue_summary')
from calls c
where c.id = i.call_id
  and i.title = c.summary_title
  and coalesce(btrim(c.data_collection->>'issue_summary'), '') <> '';

-- (b) Single-Anfrage Vorgänge: same flip, where the case title is still the
--     auto-inherited summary_title. Multi-Anfrage Vorgänge describe a GROUP, so their
--     titles are left to the KI-Gruppierung and only deduped below.
with case_counts as (
  select case_id from inquiries where case_id is not null group by case_id having count(*) = 1
)
update cases ca
set title = btrim(cl.data_collection->>'issue_summary')
from inquiries i
join calls cl on cl.id = i.call_id
join case_counts cc on cc.case_id = i.case_id
where ca.id = i.case_id
  and ca.title = cl.summary_title
  and coalesce(btrim(cl.data_collection->>'issue_summary'), '') <> '';

-- (c1) Dedupe within each (customer, title) group: keep the first, append a readable
--      German date ("… · Samstag, 27. Juni") to the rest. Skips already-dated titles.
with ranked as (
  select id, row_number() over (partition by org_id, customer_id, title order by created_at, id) as rn
  from cases where customer_id is not null
)
update cases ca
set title = left(
  ca.title || ' · ' ||
  ((array['Montag','Dienstag','Mittwoch','Donnerstag','Freitag','Samstag','Sonntag'])[extract(isodow from (ca.created_at at time zone 'Europe/Berlin'))::int]
   || ', ' || extract(day from (ca.created_at at time zone 'Europe/Berlin'))::int || '. '
   || (array['Januar','Februar','März','April','Mai','Juni','Juli','August','September','Oktober','November','Dezember'])[extract(month from (ca.created_at at time zone 'Europe/Berlin'))::int])
, 120)
from ranked r
where r.id = ca.id and r.rn > 1
  and ca.title !~ ' · (Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag), ';

-- (c2) Safety net: if dating still left a collision (same problem, same day, 3+ times),
--      append a small counter so every Vorgang title is unique within its customer.
with ranked2 as (
  select id,
         row_number() over (partition by org_id, customer_id, title order by created_at, id) as rn,
         count(*) over (partition by org_id, customer_id, title) as cnt
  from cases where customer_id is not null
)
update cases ca
set title = left(ca.title || ' (' || r.rn || ')', 120)
from ranked2 r
where r.id = ca.id and r.cnt > 1 and r.rn > 1;
