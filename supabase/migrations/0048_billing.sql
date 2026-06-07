-- 0048 — Stripe billing module (Phase 1, read-first foundation). ALL ADDITIVE.
-- Reflects an already-LIVE Stripe account into the CRM: an audit ledger for every
-- Stripe call we initiate, a deduped webhook inbox, an idempotent per-call usage
-- ledger, the dry-run customer↔org match log, and a pre-auth security log. Plus
-- nullable billing_* columns on organizations/calls. Inert until
-- STRIPE_BILLING_ENABLED=1 + a Stripe key is set. Mirrors the 0015/0042 idioms.
--
-- RLS stance: these are backend-only tables. The API (service role, bypasses RLS)
-- is the ONLY reader — the browser never touches them. So they follow the
-- org_secrets convention from 0001: RLS ENABLED + NO client policy = deny-all for
-- any client token. (Keeps the security advisor green without a usable policy.)

-- ─── Audit ledger: every Stripe API call we initiate ─────────────────────────
-- Analogous to agent_writes_audit (0015). status pending → succeeded|failed.
create table if not exists billing_events (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references organizations(id) on delete cascade,   -- nullable: account-level events
  actor_user_id uuid references users(id) on delete set null,   -- nullable: system / webhook-triggered
  event_type text not null,                                     -- 'portal_session.create', 'usage.report', …
  stripe_object text,                                           -- 'sub_…', 'cus_…', 'mbur_…'
  request_payload jsonb,
  response_payload jsonb,
  status text not null default 'pending' check (status in ('pending','succeeded','failed')),
  idempotency_key text,
  error_code text,
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- ─── Webhook inbox: every event Stripe sends us (dedup primitive) ────────────
-- stripe_event_id UNIQUE = the idempotency guarantee against Stripe's retries.
create table if not exists billing_webhook_events (
  id uuid primary key default gen_random_uuid(),
  stripe_event_id text unique not null,                         -- evt_…
  event_type text not null,
  livemode boolean,
  processing_status text not null default 'received'
    check (processing_status in ('received','processed','failed','ignored')),
  payload jsonb,
  processing_notes text,
  received_at timestamptz not null default now(),
  processed_at timestamptz
);

-- ─── Usage ledger: every usage record we POST (one call = at most one report) ─
-- call_id UNIQUE is the architectural guarantee against double-billing.
create table if not exists billing_usage_reports (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references organizations(id) on delete cascade,
  call_id uuid unique not null references calls(id) on delete cascade,
  subscription_item_id text,                                    -- si_…
  quantity_minutes numeric,
  stripe_usage_record_id text,                                  -- mbur_… returned by Stripe
  status text not null default 'pending'
    check (status in ('pending','reported','failed','skipped')),
  skip_reason text,                                             -- 'no_customer' | 'no_metered_sub' | 'legacy_connect_sub'
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- ─── Migration log: dry-run org↔Stripe-customer match proposals (review queue) ─
-- Phase 1 writes proposals ONLY here; no write-back to live Stripe metadata.
create table if not exists billing_migration_log (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  stripe_customer_id text,
  match_method text check (match_method in ('email_exact','name_fuzzy','manual','none')),
  match_confidence numeric,
  candidate_payload jsonb,                                      -- Stripe customer snapshot for review
  status text not null default 'proposed' check (status in ('proposed','approved','rejected')),
  reviewed_by uuid references users(id) on delete set null,     -- super-admin reviewer
  reviewed_at timestamptz,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- ─── Security log: webhook signature failures (pre-auth; no org_id) ──────────
create table if not exists billing_security_events (
  id uuid primary key default gen_random_uuid(),
  event_type text not null default 'webhook_signature_failure',
  source_ip text,
  error_message text,
  raw_excerpt text,
  created_at timestamptz not null default now()
);

-- ─── Column adds (all nullable, additive) ───────────────────────────────────
alter table organizations
  add column if not exists stripe_customer_id text unique,
  add column if not exists billing_status text,                 -- active|trialing|past_due|unpaid|canceled|incomplete|paused|legacy
  add column if not exists billing_plan_title text,             -- 'Kiki Solo' | 'Kiki Team' | 'Kiki Premium' | 'Custom'
  add column if not exists billing_subscription_id text,        -- sub_… (primary active subscription)
  add column if not exists billing_subscription_application text,-- 'ca_…' if legacy Connect-created, null if CRM-owned
  add column if not exists billing_quota_minutes integer,       -- from product.metadata.included_call_minutes (cached)
  add column if not exists billing_period_start timestamptz,
  add column if not exists billing_period_end timestamptz,
  add column if not exists billing_last_sync_at timestamptz;    -- last reconcile from Stripe

-- calls.billing_usage_report_id closes the call → usage-report link. Added AFTER
-- billing_usage_reports exists (FK cycle: both ends nullable, so no deadlock).
alter table calls
  add column if not exists billing_usage_report_id uuid
    references billing_usage_reports(id) on delete set null;

-- ─── Indexes (incl. FK indexes — perf advisor, see 0046/0047) ───────────────
create index if not exists billing_events_org_created_idx on billing_events (org_id, created_at desc);
create index if not exists billing_events_idem_idx on billing_events (idempotency_key);
create index if not exists billing_events_actor_idx on billing_events (actor_user_id);
create index if not exists billing_webhook_events_type_idx on billing_webhook_events (event_type, received_at desc);
create index if not exists billing_usage_reports_org_created_idx on billing_usage_reports (org_id, created_at desc);
create index if not exists billing_usage_reports_status_idx on billing_usage_reports (status);
create index if not exists billing_migration_log_status_idx on billing_migration_log (status, match_confidence desc);
create index if not exists billing_migration_log_org_idx on billing_migration_log (org_id);
create index if not exists billing_migration_log_reviewed_by_idx on billing_migration_log (reviewed_by);
create index if not exists calls_billing_usage_report_idx on calls (billing_usage_report_id);
-- NOTE: no index on organizations.stripe_customer_id / billing_usage_reports.call_id /
-- billing_webhook_events.stripe_event_id — their UNIQUE constraints already provide one
-- (a second would be a duplicate-index advisor warning; cf. 0047).

-- ─── RLS (backend-only tables; service role bypasses; NO client policy) ──────
-- Mirrors org_secrets (0001): enabled + no policy ⇒ never readable by the browser.
alter table billing_events          enable row level security;
alter table billing_webhook_events  enable row level security;
alter table billing_usage_reports   enable row level security;
alter table billing_migration_log   enable row level security;
alter table billing_security_events enable row level security;
