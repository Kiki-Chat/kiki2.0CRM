-- 0043_calls_deleted_at.sql
-- Soft-delete for calls. The Call Logs cockpit "Anruf löschen" action stamps
-- deleted_at on the call row; the calls list AND the customer activity timeline
-- filter these out, so a deleted call actually disappears (and pagination counts
-- stay accurate). The linked inquiry is soft-deleted in the same operation.
--
-- Additive + reversible: `alter table public.calls drop column deleted_at;`

alter table public.calls add column if not exists deleted_at timestamptz;

-- Partial index backing the "active calls" list query (org_id + started_at desc,
-- deleted_at is null) — keeps the cockpit list fast as call volume grows.
create index if not exists idx_calls_org_active
  on public.calls (org_id, started_at desc)
  where deleted_at is null;
