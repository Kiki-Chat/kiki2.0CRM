-- 0078_cost_estimate_kva_to_ag_prefix.sql
-- KVA → Angebot product-wide (Amber's call). The former "kva" doc-type is now
-- branded "Angebot", so its Aktenzeichen prefix changes KVA-…  →  AG-…
-- (e.g. KVA-2026-00001 → AG-2026-00001). The doc_type key stays "kva" in the DB;
-- gen_number() now mints AG- (app/services/cost_estimates.py).
--
-- Safe: data-only UPDATE, idempotent, scoped to kva-type rows that still carry KVA-.
-- Run manually in Supabase against UAT (Amber executes migrations).

update public.cost_estimates
set    number = 'AG-' || substring(number from 5)
where  type = 'kva'
  and  number like 'KVA-%';
