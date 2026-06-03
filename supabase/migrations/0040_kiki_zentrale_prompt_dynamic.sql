-- 0040 — Dynamic prompt pipeline for Kiki-Zentrale.
-- Additive. Lets Kiki-Zentrale config drive the rendered agent prompt:
--   * problem_description   — the org's "Anliegen / Problembeschreibung" definition
--                             (separate from the per-field required-field descriptions),
--                             rendered into the {{KZ_PROBLEM_DESCRIPTION}} prompt block.
--   * prompt_manual_override — when a super-admin hand-edits the live prompt via the
--                             manual editor, this is set true so the auto-render-on-save
--                             pipeline stops overwriting their edits. Default false →
--                             config changes re-render + re-push the prompt.
alter table agent_configs add column if not exists problem_description text;
alter table agent_configs add column if not exists prompt_manual_override boolean not null default false;
