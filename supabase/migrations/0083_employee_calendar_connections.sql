-- 0083_employee_calendar_connections.sql
-- Per-employee Google Calendar connections (real-time availability + two-way sync).
--
-- Parallels oauth_connections but is keyed by EMPLOYEE, not org — each employee
-- connects their OWN Google account so their personal busy time feeds the
-- availability engine and CRM-assigned appointments push into their calendar.
-- The existing org-level oauth_connections / oauth_purpose_links (the COMPANY
-- calendar) are left completely untouched, so that keeps working as-is.
--
-- Tokens are Fernet-encrypted at the app layer (SETTINGS_ENC_KEY) — the
-- *_encrypted columns never hold plaintext, exactly like oauth_connections.
-- Additive only.
create table if not exists employee_calendar_connections (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  employee_id uuid not null references employees(id) on delete cascade,
  provider text not null default 'google',   -- 'google' (microsoft/calendly later)
  access_token_encrypted text,
  refresh_token_encrypted text,
  token_expires_at timestamptz,
  account_email text,
  scope text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (employee_id, provider)
);

create index if not exists idx_emp_cal_conn_org on employee_calendar_connections (org_id);

alter table employee_calendar_connections enable row level security;
