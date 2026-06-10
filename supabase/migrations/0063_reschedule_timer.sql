-- 0063 — reschedule request timer + intent (bug #3: reschedule duplicate)
--
-- A reschedule never creates a second appointment: the agent stamps the
-- customer's requested slot onto the EXISTING appointment (customer_proposed_*,
-- migration 0037) and the admin commits it via approve-proposal (in-place move).
-- These columns add the safety-timer + the customer's replace-intent so an
-- unconfirmed reschedule can't clog the calendar forever.
--
-- Purely ADDITIVE. Rollback = drop the three columns.

-- When the pending reschedule request should be auto-resolved if no admin acts.
alter table appointments
  add column if not exists reschedule_expires_at timestamptz;

-- TRUE  → customer wants the new time INSTEAD of the old (abandons the old slot)
--         → on decline / timeout the old slot may be released (cancelled).
-- FALSE/NULL → keep the original as a fallback; never auto-cancel it.
alter table appointments
  add column if not exists reschedule_replace_intent boolean;

-- Per-org timer length (hours) before a pending reschedule expires. The timer's
-- ACTION is gated by appointments autonomy level: L1/L2 only flag the admin
-- (computed client-side from reschedule_expires_at); L3 auto-resolves.
alter table agent_configs
  add column if not exists reschedule_request_timeout_hours integer not null default 24;
