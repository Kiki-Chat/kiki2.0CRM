-- Lean-case rework: a stable, human-readable per-org token (e.g. KC007) that
-- prefixes inquiry (ANF-) and case (FL-) numbers, making them unique + readable
-- across client orgs. Derived from company initials + slug number; persisted so
-- it survives renames and can be edited by super-admin later.
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS case_prefix text;
CREATE UNIQUE INDEX IF NOT EXISTS idx_org_case_prefix ON organizations (case_prefix) WHERE case_prefix IS NOT NULL;
