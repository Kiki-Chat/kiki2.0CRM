-- 0049 — Stripe billing Phase 2 (provisioning/checkout, trial, dunning, notifications).
-- ALL ADDITIVE. Same backend-only RLS stance as 0048 (enabled, no client policy).

-- ─── Notifications ledger (over-quota / trial-ending / payment-failed) ───────
-- Recorded ALWAYS; real email send is gated (Amber owns the email track) — this
-- table is the source of truth + powers the in-app feed regardless of email.
create table if not exists billing_notifications (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references organizations(id) on delete cascade,
  type text not null,                                   -- over_quota|trial_will_end|trial_ended|payment_failed|payment_succeeded
  channel text not null default 'in_app',               -- in_app|email
  title text,
  body text,
  status text not null default 'recorded'
    check (status in ('recorded','sent','failed','suppressed')),
  dedup_key text,                                       -- e.g. 'over_quota:<org>:<period>' — one per period
  meta jsonb,
  created_at timestamptz not null default now(),
  sent_at timestamptz
);
create unique index if not exists billing_notifications_dedup_idx
  on billing_notifications (dedup_key) where dedup_key is not null;
create index if not exists billing_notifications_org_idx
  on billing_notifications (org_id, created_at desc);

-- ─── Checkout sessions we create (subscribe flow) ───────────────────────────
create table if not exists billing_checkout_sessions (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references organizations(id) on delete cascade,
  stripe_session_id text unique not null,
  plan_title text,
  interval text,                                        -- month|year
  trial_days integer,
  status text not null default 'created'
    check (status in ('created','completed','expired')),
  created_at timestamptz not null default now(),
  completed_at timestamptz
);
create index if not exists billing_checkout_sessions_org_idx
  on billing_checkout_sessions (org_id, created_at desc);

-- ─── RLS (backend-only; service role bypasses; NO client policy) ────────────
alter table billing_notifications     enable row level security;
alter table billing_checkout_sessions enable row level security;
