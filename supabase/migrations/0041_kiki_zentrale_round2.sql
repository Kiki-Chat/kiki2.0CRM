-- 0041 — Kiki-Zentrale round 2.
-- (a) Re-point appointment_categories.default_employee_id FK from users(id) to
--     employees(id), so EVERY employee (not only those with a login) is assignable
--     as a category's default Mitarbeiter. Existing values are NULL; the UPDATE is a
--     defensive pre-clear for any non-employee value before the constraint swap.
update appointment_categories set default_employee_id = null
 where default_employee_id is not null
   and default_employee_id not in (select id from employees);

alter table appointment_categories
  drop constraint if exists appointment_categories_default_employee_id_fkey;

alter table appointment_categories
  add constraint appointment_categories_default_employee_id_fkey
  foreign key (default_employee_id) references employees(id) on delete set null;

-- (b) Required-field defaults: the third mandatory identification field is the
--     customer's ADDRESS (so Kiki can confirm the address already on file), not the
--     "Anliegen/concern" (concern now lives in agent_configs.problem_description).
--     Convert any existing 'concern' default → 'address'; final order Name(0)/Telefon(1)/Adresse(2).
--     Idempotent.
update agent_required_fields
   set field_key = 'address', label = 'Adresse',
       description = 'Anschrift des Kunden / Einsatzorts',
       identification_role = 'address', sort_order = 2
 where field_key = 'concern';
update agent_required_fields set sort_order = 0 where field_key = 'name';
update agent_required_fields set sort_order = 1 where field_key = 'phone';
