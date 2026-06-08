-- Additive: a generated text column that flattens the TWO address jsonb shapes
-- into one sortable string:
--   {raw: "Hauptstr. 1, 10115 Berlin"}            (manual form)
--   {street, postal_code, city}                    (CSV import)
-- This (a) lets the Kunden list ORDER BY address across both shapes, and (b) is
-- a single source of truth for a flattened address (the frontend already mirrors
-- this fallback client-side so CSV-imported addresses no longer render blank).
alter table public.customers
  add column if not exists address_text text
  generated always as (
    coalesce(
      nullif(btrim(address ->> 'raw'), ''),
      nullif(
        btrim(
          concat_ws(
            ', ',
            nullif(btrim(address ->> 'street'), ''),
            nullif(btrim(concat_ws(' ', address ->> 'postal_code', address ->> 'city')), '')
          )
        ),
        ''
      )
    )
  ) stored;

-- Org-scoped index for ORDER BY address_text (mirrors idx on (org_id, phone)).
create index if not exists idx_customers_org_address_text
  on public.customers (org_id, address_text);
