-- Customer classification + fields for the Customers screen.
alter table customers add column if not exists customer_type text default 'new';
alter table customers add column if not exists vat_id text;
alter table customers add column if not exists notes text;
alter table customers add column if not exists status text default 'active';
create index if not exists idx_customers_type on customers (org_id, customer_type);
