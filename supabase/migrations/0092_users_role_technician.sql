-- 0092_users_role_technician.sql
-- Employee/Technician redesign — Track A, Phase 4.
--
-- Allow users.role = 'technician' so a field technician can have a real (toned-
-- down) CRM login. WIDENS the existing CHECK (only adds an allowed value) — it
-- cannot invalidate any existing row, so it is safe/reversible.
--
-- Reversible: drop + re-add the 3-value check (after ensuring no row uses
-- 'technician').

alter table public.users drop constraint if exists users_role_check;
alter table public.users
  add constraint users_role_check
  check (role in ('super_admin', 'org_admin', 'employee', 'technician'));
