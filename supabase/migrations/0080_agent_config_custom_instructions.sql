-- "Anweisungen für Kiki" — a small free-text behavioural steer (ChatGPT/Claude-
-- style custom instructions) the customer can give their agent. Rendered into
-- the agent prompt's "# Besondere Hinweise" section, sanitized + length-capped at
-- render time (see services/agent_config.render_custom_instructions_block).
-- Additive, nullable; existing orgs read NULL → the section renders empty.
alter table agent_configs
  add column if not exists custom_instructions text;
