-- 0085_appointment_employee_google_event.sql
-- Two-way per-employee sync, PUSH side: the id of the event WE created in the
-- ASSIGNED employee's OWN Google calendar (so a confirmed job shows on their
-- phone). Kept SEPARATE from google_event_id (which is the org/company-calendar
-- push) so an appointment can be pushed to both without clobbering, and so the
-- per-employee pull's echo-loop guard can skip it. Additive.
alter table public.appointments
  add column if not exists employee_google_event_id text;
