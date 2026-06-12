-- 0066: Technician contact + persistent no-login portal (Luca-meeting item 17).
-- Technicians stay tagged employees (see 0059) — NOT a separate entity, so the
-- existing dispatch/picker/job-link flow is untouched. These add the only two
-- fields a lightweight technician needs beyond name+email:
--   * phone                    — future WhatsApp dispatch (Amber 2026-06-12).
--   * technician_portal_token  — a standing, unguessable token so the technician
--                                sees ALL their jobs (past + current) at
--                                /techniker/<token> without ever logging in.
alter table employees
  add column if not exists phone text,
  add column if not exists technician_portal_token text;

-- One token = one technician; partial so the many non-technician rows (NULL) don't
-- collide on the uniqueness constraint.
create unique index if not exists uq_employees_technician_portal_token
  on employees (technician_portal_token)
  where technician_portal_token is not null;
