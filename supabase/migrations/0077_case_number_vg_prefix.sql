-- 0077_case_number_vg_prefix.sql
-- Rename the case (Vorgang) number prefix FL- → VG- to match the German UI wording
-- ("Fall" → "Vorgang", global rule 2). The numeric sequence and org token are
-- untouched; only the human-readable prefix changes (FL-KC007-0001 → VG-KC007-0001).
--
-- Safe: data-only UPDATE, idempotent, scoped to rows that still carry the old prefix.
-- gen_case_number() now mints VG- (app/services/common.py); this aligns existing rows.

update public.cases
set    number = 'VG-' || substring(number from 4)
where  number like 'FL-%';
