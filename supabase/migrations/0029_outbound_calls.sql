-- 0029_outbound_calls.sql
-- P1: uniform outbound-call ledger + double-dispatch guard for ALL occasions
-- (appointment_reminder, kva_followup, … future: payment_reminder, etc.).
--
-- Each row IS one outbound call attempt. `id` is the `outboundCallId` dynamic
-- variable we pass into the ElevenLabs call (WerkPilot-parity schema), so the
-- post-call webhook can correlate the conversation back to the triggering
-- record. The partial unique index is the concurrency-safe idempotency guard:
-- at most ONE non-failed call per (org, occasion, referenced record) — so the
-- same occasion can never fire twice for the same appointment/KVA, even under
-- two overlapping sweeps. Additive; mirrors 0028 (service-role access, no RLS).

create table if not exists outbound_calls (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  occasion text not null,                 -- 'appointment_reminder' | 'kva_followup'
  anlass_typ text not null,               -- EL anlassTyp: 'TERMIN_ERINNERUNG' | 'KVA_NACHFASSEN'
  customer_id uuid,                        -- kundeId (nullable)
  referenz_typ text not null,             -- 'Termin' | 'KVA'
  referenz_id uuid not null,               -- appointments.id | cost_estimates.id
  to_number text not null,
  status text not null default 'pending', -- 'pending' | 'placed' | 'failed'
  conversation_id text,
  call_sid text,
  error text,
  dynamic_variables jsonb,                 -- audit snapshot of the vars we sent
  created_at timestamptz not null default now(),
  placed_at timestamptz
);

-- Idempotency guard: ≤1 non-failed call per (org, occasion, referenced record).
-- A 'failed' attempt is excluded so a transient ElevenLabs error can be retried
-- on the next sweep.
create unique index if not exists outbound_calls_dedup
  on outbound_calls (org_id, occasion, referenz_id)
  where status <> 'failed';

create index if not exists idx_outbound_calls_org_created
  on outbound_calls (org_id, created_at desc);
