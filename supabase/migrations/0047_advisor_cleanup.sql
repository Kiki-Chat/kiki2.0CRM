-- 0047_advisor_cleanup.sql
-- Resolve the two remaining performance-advisor warnings (both non-additive,
-- approved by Amber). No data change.

-- 1) Duplicate index: idx_kva_org is identical to idx_cost_estimates_org. Keep one.
drop index if exists public.idx_kva_org;

-- 2) RLS init-plan: users_same_org re-evaluated auth fns per row. Wrap them in
--    (select ...) so Postgres evaluates once per statement (InitPlan). Predicate,
--    command (SELECT) and role (public) unchanged -> behavior-preserving.
drop policy if exists users_same_org on public.users;
create policy users_same_org on public.users
  for select
  to public
  using ((org_id = (select auth_org_id())) or (id = (select auth.uid())));
