-- 0061: Gesprächslogik — structured Wenn/Dann rule tree per org.
-- One jsonb document (validated server-side, compiled deterministically into the
-- numbered "# Gesprächsführung" prompt block via {{KZ_CONVERSATION_LOGIC}}).
-- Replaces hand-written conditional prompt sections (prompt_manual_override).

alter table agent_configs
  add column if not exists conversation_logic jsonb,
  add column if not exists conversation_logic_enabled boolean not null default true;
