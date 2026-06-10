-- Technician job links — tokenized, no-login job-report form per dispatch.
-- A link is created when a technician is dispatched from an appointment
-- confirmation; the technician opens /job/<token> (public, capability URL),
-- logs start/end, answers the questionnaire and uploads photos; the submitted
-- report threads back into the appointment's Vorgang (inquiries) timeline.
-- Validity: until the case is closed (inquiry completed) or the link is
-- revoked (a re-dispatch revokes prior links for the same appointment).
-- Backend-only table: RLS on, NO client policies (service role only).

create table if not exists technician_job_links (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  appointment_id uuid not null references appointments(id) on delete cascade,
  inquiry_id uuid references inquiries(id) on delete set null,
  employee_id uuid not null references employees(id) on delete cascade,
  token text not null unique,
  email_status text,
  started_at timestamptz,
  finished_at timestamptz,
  submitted_at timestamptz,
  report jsonb,
  photo_paths jsonb not null default '[]'::jsonb,
  revoked_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists idx_tjl_org_created on technician_job_links (org_id, created_at desc);
create index if not exists idx_tjl_appointment on technician_job_links (appointment_id);
create index if not exists idx_tjl_inquiry on technician_job_links (inquiry_id);

alter table technician_job_links enable row level security;
