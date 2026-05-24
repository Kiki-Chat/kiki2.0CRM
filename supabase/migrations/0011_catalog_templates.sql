-- Catalog & Templates: richer catalog items, text modules, asset fields.

-- catalog_items extra fields (table already exists from 0001)
alter table catalog_items add column if not exists article_number text;
alter table catalog_items add column if not exists vat_rate numeric default 19;
alter table catalog_items add column if not exists is_wage boolean default false;
alter table catalog_items add column if not exists purchase_price numeric;
alter table catalog_items add column if not exists supplier_id uuid references customers on delete set null;

create table if not exists text_modules (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations on delete cascade,
  name text not null,
  category text not null,
  content text not null,
  sort_order integer default 0,
  is_default boolean default false,
  created_at timestamptz default now()
);
create index if not exists idx_text_modules_org on text_modules (org_id);
alter table text_modules enable row level security;

-- vehicles extra fields (license_plate, model already exist from 0009)
alter table vehicles add column if not exists vehicle_type text;
alter table vehicles add column if not exists brand text;
alter table vehicles add column if not exists tuev_until date;
alter table vehicles add column if not exists insurance_until date;
alter table vehicles add column if not exists next_maintenance date;
alter table vehicles add column if not exists max_weight_kg numeric;
alter table vehicles add column if not exists cargo_space_m3 numeric;
alter table vehicles add column if not exists status text default 'available';

-- tools extra fields
alter table tools add column if not exists condition text default 'new';
alter table tools add column if not exists next_maintenance date;
alter table tools add column if not exists purchase_date date;
alter table tools add column if not exists purchase_price numeric;
