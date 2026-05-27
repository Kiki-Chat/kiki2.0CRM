-- 0021_org_updated_at: add organizations.updated_at (additive).
--
-- The super_admin routes (added in P0.6, restructured to /admin/* under §3)
-- read + write `organizations.updated_at`. The column was never created
-- (init schema only has created_at), so /api/super-admin/orgs and
-- /orgs-stats throw `column organizations.updated_at does not exist`
-- → 500 → CORS middleware drops the Allow-Origin header on the error
-- response → browser shows the canonical "Failed to fetch" net::ERR_FAILED.
--
-- Additive only: ADD COLUMN IF NOT EXISTS, nullable, no default backfill.
-- New writes (super_admin PATCH / disable / enable) stamp it via _now();
-- existing rows keep NULL until they're next touched. Frontend renders
-- NULL as "—" via fmtDate.
--
-- Pre-authorized per Amber's additive-migrations standing rule.

ALTER TABLE public.organizations
  ADD COLUMN IF NOT EXISTS updated_at timestamptz NULL;
