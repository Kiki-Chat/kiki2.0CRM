-- Cost estimates (Kostenvoranschläge): extend for full KVA documents.

alter table cost_estimates add column if not exists type text default 'kva';            -- kva | offer | invoice
alter table cost_estimates alter column status set default 'draft';
alter table cost_estimates add column if not exists subject text;
alter table cost_estimates add column if not exists reference_number text;
alter table cost_estimates add column if not exists is_binding boolean default false;
alter table cost_estimates add column if not exists tolerance_pct integer default 20;
alter table cost_estimates add column if not exists validity_days integer default 30;
alter table cost_estimates add column if not exists inquiry_id uuid references inquiries on delete set null;
alter table cost_estimates add column if not exists intro_text text;
alter table cost_estimates add column if not exists closing_text text;
alter table cost_estimates add column if not exists payment_terms text;
alter table cost_estimates add column if not exists surcharge numeric default 0;
alter table cost_estimates add column if not exists surcharge_description text;
alter table cost_estimates add column if not exists total_discount_pct numeric default 0;
alter table cost_estimates add column if not exists vat_amount numeric default 0;
alter table cost_estimates add column if not exists accepted_at timestamptz;
alter table cost_estimates add column if not exists rejected_at timestamptz;
alter table cost_estimates add column if not exists invoice_id uuid;
alter table cost_estimates add column if not exists created_by uuid references users on delete set null;
alter table cost_estimates add column if not exists updated_at timestamptz default now();

create index if not exists idx_cost_estimates_org on cost_estimates (org_id);
