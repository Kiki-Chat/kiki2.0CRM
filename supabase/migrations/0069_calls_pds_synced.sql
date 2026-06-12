-- 0069: calls.pds_synced_at (additive) — when this call was logged into the
-- org's PDS as an Aufgabe (auto-sync on post-call ingest, or manual "Jetzt
-- synchronisieren"). NULL = not yet synced; the manual sync uses this to avoid
-- duplicate PDS tasks.
alter table calls
  add column if not exists pds_synced_at timestamptz;
