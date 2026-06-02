-- 0038_customers_org_created_index.sql
-- Speeds up the paginated customer list (filters org_id + status, orders by
-- created_at desc) now that an org can hold thousands of customers (a CSV import
-- of ~5k+). Additive (CREATE INDEX IF NOT EXISTS) — safe on the live DB.

create index if not exists idx_customers_org_created
  on customers (org_id, created_at desc);
