-- 0055 — Vorgang (case) threading foundation. Additive + idempotent backfill.
--
-- Elevates `inquiries` into the customer-facing "Vorgang" (case) and ties EVERY call to
-- its case so the call-log action buttons stop dying on outbound calls.
--
--  * calls.inquiry_id  — the case a call belongs to. INBOUND: set when the call's request
--    inquiry is ensured. OUTBOUND: stamped from outbound_calls.inquiry_id (the triggering
--    case) at post-call time. Backfilled below for existing rows. ON DELETE SET NULL so
--    deleting a case never deletes call history.
--  * inquiries.subject — a SHORT human topic ("Heizung Badezimmer"). The EXTERNAL,
--    customer-facing label the agent uses; customers never hear the ANF-/VG- number.
--  * case_links        — relate/duplicate links between two distinct cases (Link/Merge).
--
-- The staff-facing case number REUSES the existing inquiries.number (ANF-YYYY-NNNN); no new
-- number column is minted.

alter table calls
  add column if not exists inquiry_id uuid references inquiries(id) on delete set null;

create index if not exists idx_calls_inquiry on calls (inquiry_id);

alter table inquiries
  add column if not exists subject text;

create table if not exists case_links (
  id              uuid primary key default gen_random_uuid(),
  org_id          uuid not null references organizations(id) on delete cascade,
  case_id         uuid not null references inquiries(id) on delete cascade,
  related_case_id uuid not null references inquiries(id) on delete cascade,
  relation        text not null default 'related' check (relation in ('related','duplicate')),
  created_by      uuid references users(id) on delete set null,
  created_at      timestamptz not null default now(),
  unique (org_id, case_id, related_case_id),
  check (case_id <> related_case_id)
);

create index if not exists idx_case_links_org on case_links (org_id);
create index if not exists idx_case_links_case on case_links (case_id);
create index if not exists idx_case_links_related on case_links (related_case_id);

-- ─── Backfill calls.inquiry_id for existing rows (safe, idempotent) ───────────
-- INBOUND: the request inquiry points back via inquiries.call_id. Pick the earliest
-- non-deleted one per call (matches the call-log enrichment's "first if multiple").
update calls c
set inquiry_id = (
  select i.id from inquiries i
  where i.call_id = c.id
    and i.org_id = c.org_id
    and i.status <> 'deleted'
  order by i.created_at asc
  limit 1
)
where c.inquiry_id is null
  and exists (
    select 1 from inquiries i2
    where i2.call_id = c.id
      and i2.org_id = c.org_id
      and i2.status <> 'deleted'
  );

-- OUTBOUND: the case lives in the outbound_calls ledger, correlated by the ElevenLabs
-- conversation_id that post-call wrote onto the calls row.
update calls c
set inquiry_id = oc.inquiry_id
from outbound_calls oc
where oc.conversation_id = c.elevenlabs_conversation_id
  and oc.org_id = c.org_id
  and oc.inquiry_id is not null
  and c.inquiry_id is null;
