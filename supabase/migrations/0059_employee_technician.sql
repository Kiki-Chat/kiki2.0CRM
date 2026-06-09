-- 0059: Technician tag on employees (user decision 2026-06-10: technicians are
-- tagged employees, NOT a separate entity — they appear in assignment pickers
-- (Zuweisung ergänzen, Plantafel, Kalender) and need no login).

alter table employees
  add column if not exists is_technician boolean not null default false;
