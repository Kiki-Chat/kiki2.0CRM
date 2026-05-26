-- P0.4 — Gmail-style read/unread state for calls.
-- NULL read_at = unread (default for any pre-existing or new row);
-- non-null timestamp = when the call was opened in Call Logs.
-- Index on (org_id) WHERE read_at IS NULL gives a fast unread count
-- for the sidebar badge without a full scan.

alter table calls add column if not exists read_at timestamptz null;
create index if not exists idx_calls_unread on calls (org_id) where read_at is null;
