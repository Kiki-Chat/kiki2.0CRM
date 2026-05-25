-- Invoices (Rechnungen).
-- The invoices table already exists from migration 0001 (id, org_id, customer_id,
-- cost_estimate_id, number, status, line_items, subtotal, tax_rate, total,
-- due_date, paid_at, created_at). Bring it to parity with the cost_estimates/KVA
-- module and add invoice-specific fields. We reuse the existing columns
-- subtotal (= net), total (= gross) and cost_estimate_id (the KVA link) to stay
-- consistent with cost_estimates; only the missing columns are added below.

alter table invoices add column if not exists subject text;
alter table invoices add column if not exists reference_number text;
alter table invoices add column if not exists invoice_date date default current_date;     -- Rechnungsdatum
alter table invoices add column if not exists performance_date date;                       -- Leistungsdatum (§14 UStG)
alter table invoices add column if not exists payment_terms_days integer default 14;       -- drives due_date
alter table invoices add column if not exists discount_pct numeric;                        -- Skonto %
alter table invoices add column if not exists discount_days integer;                       -- Skonto Tage
alter table invoices add column if not exists intro_text text;
alter table invoices add column if not exists closing_text text;
alter table invoices add column if not exists payment_terms_text text;
alter table invoices add column if not exists surcharge numeric default 0;
alter table invoices add column if not exists surcharge_description text;
alter table invoices add column if not exists total_discount_pct numeric default 0;
alter table invoices add column if not exists vat_amount numeric default 0;
alter table invoices add column if not exists sent_at timestamptz;
alter table invoices add column if not exists cancelled_at timestamptz;
alter table invoices add column if not exists created_by uuid references users on delete set null;
alter table invoices add column if not exists updated_at timestamptz default now();

create unique index if not exists idx_invoices_org_number on invoices (org_id, number);

-- The KVA list already renders an "Abgerechnet" (invoiced) status pill, and
-- converting a KVA to an invoice marks the source KVA as invoiced. Allow it.
alter table cost_estimates drop constraint if exists cost_estimates_status_check;
alter table cost_estimates add constraint cost_estimates_status_check
  check (status in ('draft', 'sent', 'accepted', 'rejected', 'expired', 'invoiced'));
