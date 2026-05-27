-- Wave 2 / Agent 2.4 — appointment confirm/reject/propose-alternative.
--
-- The OFFENE AKTIONEN appointment card on the call-detail right panel needs to
-- track three new lifecycle events on top of the existing
-- `pending|confirmed|cancelled|completed` status enum:
--   - confirm   → stamps confirmed_at, sets status='confirmed'.
--   - reject    → stamps rejected_at (+ optional rejection_reason), sets
--                 status='cancelled' (re-uses the existing terminal status so
--                 the migration stays strictly additive — `rejected_at IS NOT
--                 NULL` is the discriminator vs a customer-initiated cancel).
--   - propose alternative → fills alternative_start_time / alternative_end_time
--                 / alternative_note / alternative_proposed_at; status stays
--                 'pending' (the card switches to "Alternative gesendet" by
--                 looking for `alternative_proposed_at IS NOT NULL`).
--
-- Why no check-constraint changes: the existing `status in ('pending',
-- 'confirmed','cancelled','completed')` constraint already covers every
-- terminal state we need; the new behavior is encoded in additive timestamp +
-- text columns, not in a wider status enum. This keeps the migration purely
-- additive (pre-authorized per Amber's standing rule) and matches the
-- "ADD COLUMN IF NOT EXISTS" idiom already in use.

alter table appointments
  add column if not exists confirmed_at timestamptz,
  add column if not exists rejected_at timestamptz,
  add column if not exists rejection_reason text,
  add column if not exists alternative_start_time timestamptz,
  add column if not exists alternative_end_time timestamptz,
  add column if not exists alternative_note text,
  add column if not exists alternative_proposed_at timestamptz;

-- Speed up the "find the pending appointment that the right-panel card should
-- render for this inquiry" lookup. Partial index over status='pending' (the
-- only status the card ever displays) scoped by org for tenant isolation.
create index if not exists idx_appointments_pending_by_inquiry
  on appointments (org_id, inquiry_id)
  where status = 'pending';
