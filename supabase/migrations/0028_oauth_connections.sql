-- 0028_oauth_connections.sql
-- P3: provider-agnostic OAuth connection store for calendar sync (+ general
-- OAuth). Canonical store for google / microsoft / calendly connections.
-- Tokens are Fernet-encrypted at the application layer (SETTINGS_ENC_KEY) —
-- the *_encrypted columns never hold plaintext. Additive; does NOT touch the
-- existing email_configs.oauth_* columns that the email-send path reads (a
-- single google/microsoft consent grants both calendar + email scopes, so the
-- callback writes both stores until the email path migrates here).

create table if not exists oauth_connections (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  provider text not null,                 -- 'google' | 'microsoft' | 'calendly'
  access_token_encrypted text,
  refresh_token_encrypted text,
  token_expires_at timestamptz,
  account_email text,
  scope text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (org_id, provider)
);

create index if not exists idx_oauth_connections_org on oauth_connections (org_id);
