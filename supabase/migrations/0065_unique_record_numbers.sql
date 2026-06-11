-- 0065: numbering integrity (audit 2026-06-11, batch D).
-- The COUNT+1 number generators raced: two concurrent creates in one org could
-- mint the same K-number silently (cases had only a PLAIN index from 0057).
-- Generators are now MAX+1 (code side); these partial unique indexes are the DB
-- backstop — a racing twin insert now FAILS loudly instead of corrupting the
-- org's staff-facing numbering. Partial (number is not null) tolerates legacy
-- rows that never got a number. Verified 2026-06-11: zero existing duplicates
-- in cases (14 rows) and inquiries (227 rows), so creation is safe.
create unique index if not exists uq_cases_org_number
  on public.cases (org_id, number) where number is not null;
create unique index if not exists uq_inquiries_org_number
  on public.inquiries (org_id, number) where number is not null;
