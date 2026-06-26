-- Lightweight progress record for the historical EL call-import, so the
-- super-admin Migration view can show "Import läuft / abgeschlossen / N von M"
-- instead of inferring it from a growing row count. Written by
-- services/history_import.import_agent_history_until_done. Shape (jsonb):
--   {status: running|complete|incomplete, started_at, finished_at,
--    imported, seen, errors, more, passes}
-- Additive, nullable; orgs that never imported read NULL → "no import yet".
alter table organizations
  add column if not exists history_import_state jsonb;
