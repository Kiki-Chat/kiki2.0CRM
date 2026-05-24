-- Customer documents/photos: storage bucket + metadata table.
create table if not exists documents (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations on delete cascade,
  customer_id uuid references customers on delete cascade,
  inquiry_id uuid references inquiries on delete set null,
  name text,
  path text not null,
  category text,
  mime_type text,
  size_bytes integer,
  is_image boolean default false,
  uploaded_at timestamptz default now()
);
create index if not exists idx_documents_customer on documents (org_id, customer_id);

alter table documents enable row level security;
create policy documents_org_all on documents
  for all using (org_id = auth_org_id()) with check (org_id = auth_org_id());

-- Private bucket; backend uploads via service role, downloads via signed URLs.
insert into storage.buckets (id, name, public)
values ('customer-files', 'customer-files', false)
on conflict (id) do nothing;
