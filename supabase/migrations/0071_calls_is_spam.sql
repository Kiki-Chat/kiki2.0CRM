-- 0071_calls_is_spam.sql
-- "Als Spam" on a call (Posteingang triage). A spam call is hidden from the active
-- log via the existing `deleted_at is null` filter (set at runtime by the spam
-- endpoint, on the CALL only — never the inquiry), AND flagged is_spam so it is
-- distinct from a normal soft-delete and can be surfaced / undone separately.
-- Additive + reversible:
--   alter table public.calls drop column is_spam, drop column spam_at;
alter table public.calls add column if not exists is_spam boolean not null default false;
alter table public.calls add column if not exists spam_at timestamptz;
