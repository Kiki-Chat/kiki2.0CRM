-- One-line LLM summary per Vorgang (Fall) for compact customer-page cards.
ALTER TABLE cases ADD COLUMN IF NOT EXISTS ai_summary text;
