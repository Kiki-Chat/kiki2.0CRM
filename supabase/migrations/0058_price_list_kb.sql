-- 0058: Preisauskunft — price list as ElevenLabs knowledge-base document.
-- Stores the EL doc id of the auto-generated "Preisliste (Richtpreise)" text
-- document per org (managed by services/price_knowledge.py; deliberately NOT a
-- knowledge_resources row so it never shows in the manual Wissens-Quellen list
-- and its kind check ('url','pdf') stays untouched).

alter table agent_configs
  add column if not exists price_list_doc_id text;
