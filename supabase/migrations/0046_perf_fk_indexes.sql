-- 0046_perf_fk_indexes.sql
-- Cover the foreign keys flagged by the Supabase performance advisor
-- (unindexed_foreign_keys). Additive + idempotent (CREATE INDEX IF NOT EXISTS).
-- Generated from a LIVE get_advisors(type="performance") run on 2026-06-05.
--
-- Context: the CSV import already landed (~4,880 customers live), so lookups
-- into/around the big tables are doing sequential scans today. These keep every
-- WHERE customer_id / call_id / inquiry_id = ... an index lookup as data grows.

-- ── agent / audit / copilot (low volume; clears the linter) ──────────────────
create index if not exists idx_agent_config_snapshots_actor_id     on public.agent_config_snapshots(actor_id);
create index if not exists idx_agent_writes_audit_actor_id         on public.agent_writes_audit(actor_id);
create index if not exists idx_agent_writes_audit_rolled_back_by   on public.agent_writes_audit(rolled_back_by);
create index if not exists idx_agent_writes_audit_snapshot_id      on public.agent_writes_audit(snapshot_id);
create index if not exists idx_ai_usage_log_user_id               on public.ai_usage_log(user_id);
create index if not exists idx_copilot_action_audit_conversation_id on public.copilot_action_audit(conversation_id);
create index if not exists idx_copilot_action_audit_user_id        on public.copilot_action_audit(user_id);
create index if not exists idx_copilot_conversations_user_id       on public.copilot_conversations(user_id);
create index if not exists idx_copilot_escalations_conversation_id on public.copilot_escalations(conversation_id);
create index if not exists idx_copilot_escalations_user_id         on public.copilot_escalations(user_id);
create index if not exists idx_copilot_messages_org_id            on public.copilot_messages(org_id);

-- ── hot paths: inquiries / calls / appointments / cost_estimates / documents ─
create index if not exists idx_inquiries_call_id                  on public.inquiries(call_id);
create index if not exists idx_inquiries_customer_id              on public.inquiries(customer_id);
create index if not exists idx_inquiries_assigned_employee_id     on public.inquiries(assigned_employee_id);
create index if not exists idx_inquiries_assigned_to             on public.inquiries(assigned_to);
create index if not exists idx_calls_customer_id                 on public.calls(customer_id);
create index if not exists idx_appointments_customer_id          on public.appointments(customer_id);
create index if not exists idx_appointments_inquiry_id           on public.appointments(inquiry_id);
create index if not exists idx_appointments_assigned_employee_id  on public.appointments(assigned_employee_id);
create index if not exists idx_appointments_assigned_to          on public.appointments(assigned_to);
create index if not exists idx_appointments_tool_id              on public.appointments(tool_id);
create index if not exists idx_appointments_vehicle_id           on public.appointments(vehicle_id);
create index if not exists idx_cost_estimates_customer_id        on public.cost_estimates(customer_id);
create index if not exists idx_cost_estimates_inquiry_id         on public.cost_estimates(inquiry_id);
create index if not exists idx_cost_estimates_created_by         on public.cost_estimates(created_by);
create index if not exists idx_documents_customer_id            on public.documents(customer_id);
create index if not exists idx_documents_inquiry_id             on public.documents(inquiry_id);

-- ── employees / categories / catalog / assets ───────────────────────────────
create index if not exists idx_employees_user_id                on public.employees(user_id);
create index if not exists idx_appointment_categories_default_employee_id on public.appointment_categories(default_employee_id);
create index if not exists idx_catalog_items_supplier_id         on public.catalog_items(supplier_id);
create index if not exists idx_tools_assigned_employee_id        on public.tools(assigned_employee_id);
create index if not exists idx_vehicles_assigned_employee_id     on public.vehicles(assigned_employee_id);

-- ── invoices / projects / maintenance / missed_calls / time_entries ─────────
create index if not exists idx_invoices_customer_id             on public.invoices(customer_id);
create index if not exists idx_invoices_cost_estimate_id         on public.invoices(cost_estimate_id);
create index if not exists idx_invoices_created_by              on public.invoices(created_by);
create index if not exists idx_projects_customer_id             on public.projects(customer_id);
create index if not exists idx_projects_created_by              on public.projects(created_by);
create index if not exists idx_project_employees_employee_id     on public.project_employees(employee_id);
create index if not exists idx_maintenance_plans_customer_id     on public.maintenance_plans(customer_id);
create index if not exists idx_missed_calls_customer_id          on public.missed_calls(customer_id);
create index if not exists idx_time_entries_customer_id          on public.time_entries(customer_id);
create index if not exists idx_time_entries_employee_id          on public.time_entries(employee_id);
create index if not exists idx_time_entries_inquiry_id           on public.time_entries(inquiry_id);
