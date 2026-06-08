-- Make "Anliegen / Problembeschreibung" a reorderable required field instead of a
-- separate config block, so each org controls WHERE in the ask order Kiki captures
-- the problem details (item 3b — fully draggable).
--
-- Backfill: give every existing org a locked 'problem_description' required field,
-- seeded with its current agent_configs.problem_description text, appended after
-- its existing fields. Idempotent (skips orgs that already have the field) and
-- additive (INSERT only — the old agent_configs.problem_description column is kept
-- as a dormant backup; the agent now reads the field, and render suppresses the
-- old standalone block whenever this field is present).
insert into agent_required_fields
  (org_id, field_key, label, description, is_locked, is_duty, identification_role, sort_order)
select
  ac.org_id,
  'problem_description',
  'Anliegen / Problembeschreibung',
  nullif(btrim(coalesce(ac.problem_description, '')), ''),
  true,   -- is_locked: can't be deleted, only reordered + its description edited
  true,   -- is_duty
  null,   -- identification_role
  coalesce(
    (select max(f.sort_order) from agent_required_fields f where f.org_id = ac.org_id),
    -1
  ) + 1
from agent_configs ac
where not exists (
  select 1 from agent_required_fields f2
  where f2.org_id = ac.org_id and f2.field_key = 'problem_description'
);
