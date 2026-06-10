-- 0058 — Option A: platform org registration number as the record-number prefix.
-- Run manually in the Supabase SQL editor (MCP was down). Parts 1+2 are additive
-- and safe everywhere. Parts 3+4 RENUMBER existing records in the TWO TEST ORGS
-- only (prod orgs keep historical numbers) — run 3 (inquiries) BEFORE 4 (cases),
-- per the hierarchy: inquiries exist first, cases are assigned later.
--
-- New formats (generators already updated in app/services/common.py):
--   Anfrage : {ORG}-{YYYY}-A{NNNN}  e.g. K03-2026-A0007
--   Fall    : {ORG}-{YYYY}-{NNNN}   e.g. K03-2026-0001
-- ORG code = 'K' + zero-padded registration sequence (order of org creation).
-- Immutable: registration order never changes — rename-proof by construction.

-- ── 1) Org code column ───────────────────────────────────────────────────────
alter table organizations add column if not exists code text;
create unique index if not exists organizations_code_unique
  on organizations (code) where code is not null;

-- ── 2) Assign K-numbers by registration order ───────────────────────────────
with ranked as (
  select id, row_number() over (order by created_at nulls last, id) as rn
  from organizations
  where code is null
)
update organizations o
set code = 'K' || lpad(r.rn::text, 2, '0')   -- K01, K02, … (K100+ grows naturally)
from ranked r
where o.id = r.id;

-- ── 3) Renumber EXISTING inquiries — TEST ORGS ONLY (run before part 4) ─────
with target as (
  select id, org_id, created_at,
         row_number() over (partition by org_id, date_part('year', created_at)
                            order by created_at, id) as rn
  from inquiries
  where org_id in ('04acd916-b005-4f84-b4c0-9bbf4e2db934',   -- TobiasDachdecker
                   'c4dbf596-86fd-4484-88d9-095b2c082afb')   -- kiki-test-007
)
update inquiries i
set number = o.code || '-' || to_char(t.created_at, 'YYYY') || '-A' || lpad(t.rn::text, 4, '0')
from target t
join organizations o on o.id = t.org_id
where i.id = t.id;

-- ── 4) Renumber EXISTING cases — TEST ORGS ONLY ─────────────────────────────
with target as (
  select id, org_id, created_at,
         row_number() over (partition by org_id, date_part('year', created_at)
                            order by created_at, id) as rn
  from cases
  where org_id in ('04acd916-b005-4f84-b4c0-9bbf4e2db934',
                   'c4dbf596-86fd-4484-88d9-095b2c082afb')
)
update cases c
set number = o.code || '-' || to_char(t.created_at, 'YYYY') || '-' || lpad(t.rn::text, 4, '0')
from target t
join organizations o on o.id = t.org_id
where c.id = t.id;

-- Verify:
-- select code, name from organizations order by code;
-- select number, title from inquiries where org_id='04acd916-b005-4f84-b4c0-9bbf4e2db934' order by created_at desc limit 5;
-- select number, label from cases order by created_at desc limit 5;
