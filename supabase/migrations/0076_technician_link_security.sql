-- 0076_technician_link_security.sql
-- Technician link integrity (Batch 5, 5.3 / AUTH-029). The per-job capability
-- token (/job/<token>) and the standing technician portal token are the ONLY
-- credential on these public, no-login routes — yet a per-job link never
-- expired (only a re-dispatch or a closed case retired it) and we kept no
-- forensic trail of who actually submitted a report from where.
--
-- These columns close that gap (all on technician_job_links):
--   expires_at            : hard expiry stamped at link creation (created_at + 30d);
--                           once past, the public routes reject the token with
--                           "Dieser Link ist abgelaufen." NULL ⇒ legacy/no expiry.
--   first_viewed_at       : stamped on the FIRST public GET of the job; lets the
--                           CRM see whether the technician ever opened the link.
--   submitted_ip          : client IP captured on submit (audit only).
--   submitted_user_agent  : client User-Agent captured on submit (audit only).
--
-- Backend-only table (RLS on, service-role only — see 0064): no new policies.
--
-- Additive + reversible:
--   alter table public.technician_job_links
--     drop column if exists expires_at,
--     drop column if exists first_viewed_at,
--     drop column if exists submitted_ip,
--     drop column if exists submitted_user_agent;
alter table public.technician_job_links
  add column if not exists expires_at timestamptz,
  add column if not exists first_viewed_at timestamptz,
  add column if not exists submitted_ip text,
  add column if not exists submitted_user_agent text;
