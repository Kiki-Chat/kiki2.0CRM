-- Assign inquiries/appointments to an employee (not a user); appointment color.
alter table inquiries add column if not exists assigned_employee_id uuid references employees on delete set null;
alter table appointments add column if not exists assigned_employee_id uuid references employees on delete set null;
alter table appointments add column if not exists color text;
create index if not exists idx_inquiries_call on inquiries (org_id, call_id);
