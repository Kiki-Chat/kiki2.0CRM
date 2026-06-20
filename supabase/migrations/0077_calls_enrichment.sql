-- 0077 — call enrichment (our-AI-over-transcript) cache.
--
-- Additive, nullable JSONB on calls. Holds the structured output of one post-call
-- LLM pass over the transcript: a bullet-point summary, intent flags (the caller
-- asked about a KVA / invoice / appointment), and extracted pre-fill fields
-- (service description, address, problem, preferred time). Powers:
--   • the bullet-point Kiki-Zusammenfassung in the call drawer,
--   • smarter pre-fill of the KVA / Rechnung / Termin forms,
--   • the kva_suggested / invoice_suggested Open Actions.
--
-- Generated best-effort at post-call ingest and lazily back-filled when an older
-- call is opened. Nullable: a call with no enrichment simply falls back to the
-- ElevenLabs paragraph summary and shows no AI-suggested actions. Reversible:
--   alter table calls drop column enrichment;
alter table calls add column if not exists enrichment jsonb;

comment on column calls.enrichment is
  'Our-AI-over-transcript output: {version, generated_at, summary_bullets[], intent{wants_kva,wants_invoice,wants_appointment}, prefill{service_description,address,problem,preferred_time}}. Best-effort, nullable.';
