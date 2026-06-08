-- Additive: a generated text column that flattens the TWO address jsonb shapes
-- into one sortable string:
--   {raw: "Hauptstr. 1, 10115 Berlin"}            (manual form)
--   {street, postal_code, city}                    (CSV import)
-- This (a) lets the Kunden list ORDER BY address across both shapes, and (b) is
-- a single source of truth for a flattened address (the frontend already mirrors
-- this fallback client-side so CSV-imported addresses no longer render blank).
-- NOTE: the generation expression must be IMMUTABLE. concat_ws() is only STABLE
-- in Postgres, so it is rejected (ERROR 42P17). Build the fallback with the `||`
-- operator + coalesce + regexp_replace (all immutable) instead.
alter table public.customers
  add column if not exists address_text text
  generated always as (
    coalesce(
      nullif(btrim(address ->> 'raw'), ''),
      nullif(
        btrim(regexp_replace(
          coalesce(address ->> 'street', '') || ' ' ||
          coalesce(address ->> 'postal_code', '') || ' ' ||
          coalesce(address ->> 'city', ''),
          '\s+', ' ', 'g'
        )),
        ''
      )
    )
  ) stored;

-- Org-scoped index for ORDER BY address_text (mirrors idx on (org_id, phone)).
create index if not exists idx_customers_org_address_text
  on public.customers (org_id, address_text);
