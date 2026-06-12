-- 0067: PROJECTS MERGE backfill (Luca-meeting item 6, Amber's ruling 2026-06-12).
-- The case (Fall/Vorgang) layer merges INTO projects: every existing `cases` row
-- gets a matching `projects` row, and its member inquiries' project_id is stamped.
-- Purely additive + idempotent: the marker 'migrated:case:<id>' in internal_notes
-- guards against double-runs; nothing is deleted (cases stays as read-only history).
with existing_max as (
  select org_id,
         coalesce(max((regexp_match(number, '(\d+)$'))[1]::int), 0) as max_n
  from projects
  where number ~ '^PRJ-\d{4}-\d+$'
  group by org_id
),
to_migrate as (
  select c.id as case_id, c.org_id, c.customer_id, c.label, c.status,
         c.created_by, c.created_at,
         row_number() over (partition by c.org_id order by c.created_at, c.id) as rn
  from cases c
  where not exists (
    select 1 from projects p
    where p.org_id = c.org_id and p.internal_notes = 'migrated:case:' || c.id
  )
),
ins as (
  insert into projects (org_id, customer_id, number, title, status, description,
                        internal_notes, created_by, created_at)
  select t.org_id, t.customer_id,
         'PRJ-' || to_char(coalesce(t.created_at, now()), 'YYYY') || '-' ||
           lpad((coalesce(e.max_n, 0) + t.rn)::text, 5, '0'),
         coalesce(nullif(t.label, ''), 'Projekt'),
         case t.status
           when 'completed' then 'completed'
           when 'closed' then 'archived'
           else 'active'
         end,
         'Übernommen aus Fall (Projects-Merge 2026-06-12).',
         'migrated:case:' || t.case_id,
         t.created_by, t.created_at
  from to_migrate t
  left join existing_max e on e.org_id = t.org_id
  returning id, org_id, internal_notes
)
update inquiries i
set project_id = ins.id
from ins
where i.org_id = ins.org_id
  and i.case_id = substring(ins.internal_notes from 'migrated:case:(.*)')::uuid
  and i.project_id is null;
