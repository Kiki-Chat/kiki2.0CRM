-- Additive: index the secondary phone column so the customer dedup lookup
-- (services/customers.find_existing_customer) can match a mobile stored in
-- phone2 without scanning the org's customer rows. The dedup runs on the hot
-- inbound-call path (post_call) and on every manual/agent create.
--
-- Partial (phone2 IS NOT NULL) keeps the index small — most customers have only
-- one number. Org-scoped to mirror the existing (org_id, phone) index.
create index if not exists idx_customers_phone2
  on public.customers (org_id, phone2)
  where phone2 is not null;
