-- 0067: PROJECTS MERGE — clean slate (Amber's explicit decision 2026-06-12:
-- "ungroup all the things"). Instead of backfilling old cases into projects,
-- ALL legacy grouping pointers are cleared: every inquiry starts ungrouped, the
-- KI-Gruppierung rebuilds projects on demand, and NEW inquiries auto-file via
-- projects_auto. The cases/projects rows themselves are NOT deleted (history) —
-- only the pointers on inquiries are reset. Idempotent.
update inquiries
set case_id = null,
    project_id = null,
    case_confidence = null,
    case_reason = null,
    case_source = null
where case_id is not null or project_id is not null;
