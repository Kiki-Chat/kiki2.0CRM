-- 0098_final_client_export_view.sql
-- Paid-onboarding funnel. Additive (read-only VIEW), idempotent.
-- Canonical DB projection of the "Final Client" Google Sheet (the source of truth is the
-- DB; this view is what the Sheets MIRROR writes for non-tech staff). Column changes vs
-- the old ChatDash sheet: CD Project ID -> org_id (uuid), CD Dashboard Link -> static
-- crm.kikichat.de/login.

CREATE OR REPLACE VIEW final_client_export AS
SELECT
  o.id                              AS org_id,                 -- replaces "CD Project ID"
  COALESCE(au.full_name, o.name)    AS client_name,
  o.phone_number                    AS voice_agent_number,     -- the assigned Kiki/Twilio number
  o.email                           AS email,
  'crm.kikichat.de/login'           AS dashboard_link,         -- replaces "CD Dashboard Link"
  o.existing_business_number        AS client_phone_number,    -- the customer's own line
  o.elevenlabs_agent_id             AS agent_id,
  ac.forwarding_number              AS emergency_number,       -- where Kiki forwards a human transfer
  o.billing_plan_title              AS plan_title,
  o.onboarding_status               AS onboarding_status,
  o.created_at                      AS created_at
FROM organizations o
LEFT JOIN agent_configs ac ON ac.org_id = o.id
LEFT JOIN LATERAL (
  SELECT u.full_name
  FROM users u
  WHERE u.org_id = o.id AND u.role = 'org_admin'
  ORDER BY u.created_at
  LIMIT 1
) au ON true
WHERE o.disabled_at IS NULL;
