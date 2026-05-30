-- 0030_outbound_calls_case_link.sql
-- Case-link foundation + cycle-based dedup for the outbound ledger.
--
--  * inquiry_id  — the case this outbound call belongs to, derived at dispatch
--    from the triggering record (appointment/KVA inquiry_id; invoice via its KVA;
--    satisfaction/review = the inquiry itself). Nullable: a record with no case
--    still dispatches (the close-case gate is a no-op when NULL). ON DELETE SET
--    NULL so deleting a case never deletes the call history.
--  * cycle_no   — supports recurring occasions (e.g. weekly payment reminders).
--    One-shot occasions always use cycle_no=1, so the dedup index below behaves
--    exactly like the previous absolute guard for them.
--
-- Index swap: the dedup uniqueness moves from (org, occasion, referenz_id) to
-- (org, occasion, referenz_id, cycle_no). Safe — outbound_calls is empty (0 rows).
-- Additive otherwise.

alter table outbound_calls
  add column if not exists inquiry_id uuid references inquiries(id) on delete set null;

alter table outbound_calls
  add column if not exists cycle_no integer not null default 1;

drop index if exists outbound_calls_dedup;

create unique index if not exists outbound_calls_dedup
  on outbound_calls (org_id, occasion, referenz_id, cycle_no)
  where status <> 'failed';

create index if not exists idx_outbound_calls_inquiry
  on outbound_calls (inquiry_id);
