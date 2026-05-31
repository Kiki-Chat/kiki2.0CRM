-- 0034_oauth_purpose_links.sql
-- Decouple the EMAIL and CALENDAR axes of an OAuth connection.
--
-- Before: one google/microsoft consent lit up BOTH email + calendar implicitly
-- (email via the email_configs mirror; calendar hardcoded to provider 'google').
-- This table makes the linkage EXPLICIT and per-purpose: exactly one provider
-- per (org, purpose), so the two axes are independent and exclusivity is
-- DB-enforced.
--
--   purpose  ∈ 'email' | 'calendar'
--   provider ∈ 'google' | 'microsoft' | 'calendly'  (calendly = calendar only)
--
-- The GRANT (tokens) still lives in oauth_connections(org_id, provider); a
-- single grant may be referenced by 0, 1, or 2 purpose links (e.g. google
-- serving both email + calendar = two rows pointing at the same grant). The
-- email_configs mirror is unchanged (the email-send read path) — kept in sync
-- by the OAuth routes when the email purpose links to google/microsoft.
--
-- Additive: new table only; oauth_connections and email_configs untouched.
create table if not exists oauth_purpose_links (
  org_id uuid not null references organizations(id) on delete cascade,
  purpose text not null,                 -- 'email' | 'calendar'
  provider text not null,                -- 'google' | 'microsoft' | 'calendly'
  account_email text,                    -- denormalized for display
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (org_id, purpose)          -- one provider per purpose → exclusivity
);

create index if not exists idx_oauth_purpose_links_org on oauth_purpose_links (org_id);
