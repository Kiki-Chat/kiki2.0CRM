-- 0031_maintenance_plans.sql
-- Data source for the maintenance_due (WARTUNG_FAELLIG) outbound occasion.
-- Minimal recurring-service entity: a customer's maintenance cadence + when the
-- next service is due. The occasion selects active plans whose next_due_at has
-- passed and calls to schedule the Wartung. Additive.

create table if not exists maintenance_plans (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  customer_id uuid references customers(id) on delete set null,
  last_service_at date,
  interval_months integer not null default 12,
  next_due_at date,
  status text not null default 'active',   -- 'active' | 'paused' | 'cancelled'
  created_at timestamptz not null default now()
);

create index if not exists idx_maintenance_plans_org_due
  on maintenance_plans (org_id, next_due_at);
