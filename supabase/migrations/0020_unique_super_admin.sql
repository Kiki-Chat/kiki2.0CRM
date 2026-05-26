-- Enforces "there can only be one super_admin" at the DB level (Amber's
-- explicit constraint: super_admin will only be one, cannot be multiple).
-- Partial unique index on the role column restricted to role='super_admin'
-- rows. Any second attempt to insert/promote a user to super_admin fails
-- at the DB. The application layer (super_admin.py PATCH /users/{id}/role)
-- also returns a 409 with a German message before reaching this constraint.

create unique index if not exists uniq_one_super_admin
  on public.users (role)
  where role = 'super_admin';
