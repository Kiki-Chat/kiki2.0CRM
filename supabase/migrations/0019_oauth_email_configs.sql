-- P1.8 — Gmail + Outlook OAuth columns on email_configs.
-- Additive: every existing org's email_configs row stays SMTP-mode
-- (oauth_provider = NULL → email-send falls through to the SMTP path).
-- When oauth_provider IS NOT NULL and tokens are valid, the send path uses
-- Gmail API / Microsoft Graph instead. See P1.8_OAUTH_SETUP.md.
--
-- Note on numbering: P0.7-build's structured-prompt-fields migration
-- (designed as 0018, then renumbered to 0019 in P0.6 prep) shifts again
-- to 0020 because P1.8 lands first. MD re-iteration tracks this.

alter table email_configs add column if not exists oauth_provider text;
-- Note: no DB-level CHECK on oauth_provider — would fall outside additive
-- migration pre-auth. Application layer (settings.py OAuth routes) restricts
-- to ('google', 'microsoft'). Can be tightened later with explicit OK + a
-- targeted check-only migration.
alter table email_configs add column if not exists oauth_refresh_token_encrypted text;
alter table email_configs add column if not exists oauth_access_token_encrypted text;
alter table email_configs add column if not exists oauth_token_expires_at timestamptz;
alter table email_configs add column if not exists oauth_account_email text;
