-- 0060: "Pflichtfelder" → "Leitfaden" rework.
-- Per-field on/off toggle + linked offer-steps that mirror real settings:
--   offer_appointment ↔ agent_configs.appointments_enabled
--   offer_kva         ↔ agent_configs.kva_enabled
--   offer_price_info  ↔ agent_configs.price_info_enabled
-- Linked rows live in agent_required_fields ONLY for their position in the
-- guide order (single sort_order space); their ACTIVE state always derives
-- from agent_configs (single source of truth per concern — the row's own
-- is_active is ignored for linked rows).

alter table agent_required_fields
  add column if not exists is_active boolean not null default true,
  add column if not exists linked_setting text
    check (linked_setting in ('appointments_enabled', 'kva_enabled', 'price_info_enabled')
           or linked_setting is null);

-- Seed the optional email field per org (inactive by default — asking for the
-- email proactively is opt-in).
insert into agent_required_fields
  (org_id, field_key, label, description, is_locked, is_duty, identification_role, sort_order, is_active)
select ac.org_id, 'email', 'E-Mail-Adresse',
       'E-Mail des Kunden (für Bestätigungen und Kostenvoranschläge)',
       false, false, null,
       coalesce((select max(f.sort_order) from agent_required_fields f where f.org_id = ac.org_id), -1) + 1,
       false
from agent_configs ac
where not exists (
  select 1 from agent_required_fields f2
  where f2.org_id = ac.org_id and f2.field_key = 'email'
);

-- Seed the three linked offer rows per org (locked: position-only rows).
insert into agent_required_fields
  (org_id, field_key, label, description, is_locked, is_duty, identification_role, sort_order, is_active, linked_setting)
select ac.org_id, v.field_key, v.label, v.description, true, false, null,
       coalesce((select max(f.sort_order) from agent_required_fields f where f.org_id = ac.org_id), -1) + v.offset_n,
       true, v.linked_setting
from agent_configs ac
cross join (values
  ('offer_appointment', 'Termin anbieten',
   'Kiki bietet an dieser Stelle aktiv einen Termin an', 1, 'appointments_enabled'),
  ('offer_kva', 'Kostenvoranschlag anbieten',
   'Kiki bietet an dieser Stelle aktiv einen unverbindlichen Kostenvoranschlag an', 2, 'kva_enabled'),
  ('offer_price_info', 'Preisauskunft',
   'Kiki beantwortet Preisfragen an dieser Stelle (Richtpreise aus den Artikeln)', 3, 'price_info_enabled')
) as v(field_key, label, description, offset_n, linked_setting)
where not exists (
  select 1 from agent_required_fields f2
  where f2.org_id = ac.org_id and f2.field_key = v.field_key
);
