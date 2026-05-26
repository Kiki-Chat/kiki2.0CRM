-- P0.6 — Super-admin org enable/disable.
-- disabled_at = NULL → org is active (default).
-- disabled_at = <timestamp> → all users in the org are blocked from login
--   with "Diese Organisation ist deaktiviert" until super-admin re-enables.
--
-- Note: P0.7-build's structured-prompt-fields migration (currently
-- documented as 0018 in P0.7_PROMPT_EDITOR_DESIGN.md v2) shifts to 0019
-- because P0.6 lands first. The design MD will be re-iterated to v3
-- ahead of Phase A.

alter table organizations add column if not exists disabled_at timestamptz null;
