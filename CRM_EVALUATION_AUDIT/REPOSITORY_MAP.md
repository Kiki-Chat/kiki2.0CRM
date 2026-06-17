# REPOSITORY MAP — KikiJarvis CRM

*Structure, modules, tables, dependencies and data flows. Generated 2026-06-17.*

## Repository Structure

| Path | Role | Key Files |
|---|---|---|
| `backend/` | FastAPI Python backend (Python 3.12, uvicorn/gunicorn). All business logic, ElevenLabs agent integration, post-call processing, outbound orchestration, billing, and third-party integrations. | backend/app/main.py<br>backend/app/core/config.py<br>backend/app/db/supabase_client.py<br>backend/requirements.txt |
| `frontend/` | Vite + React 19 SPA. German-only UI, Supabase auth, React Query v5 for server state, Tailwind + Radix UI components, recharts for dashboards, FullCalendar for appointments. | frontend/src/main.tsx<br>frontend/src/App.tsx<br>frontend/src/lib/supabase.ts<br>frontend/src/lib/api.ts<br>frontend/src/lib/env.ts<br>frontend/Dockerfile<br>frontend/package.json |
| `supabase/migrations/` | 73 numbered SQL migrations applied to Supabase (PostgreSQL). Defines all schema: tables, RLS policies, indexes. | supabase/migrations/0001_init_schema.sql<br>supabase/migrations/0015_kiki_zentrale.sql<br>supabase/migrations/0056_cases.sql<br>supabase/migrations/0073_case_project_split.sql |
| `backend/app/api/routes/` | FastAPI routers — one file per domain. Includes a tools/ sub-directory for 11 ElevenLabs agent tool webhook handlers. | backend/app/api/routes/post_call.py<br>backend/app/api/routes/conversation_init.py<br>backend/app/api/routes/outbound.py<br>backend/app/api/routes/pds.py<br>backend/app/api/routes/stripe_webhook.py |
| `backend/app/services/` | Business-logic layer. Every route delegates to a service function here. Sub-dirs: ai/ (OpenAI copilot), cases/ (LLM grouper), copilot/ (orchestrator + tools). | backend/app/services/elevenlabs_agent.py<br>backend/app/services/post_call.py<br>backend/app/services/outbound_call.py<br>backend/app/services/email_send.py<br>backend/app/services/calendar_sync.py<br>backend/app/services/pds.py<br>backend/app/services/stripe_billing.py<br>backend/app/services/provisioning.py<br>backend/app/services/transfer.py |
| `backend/app/core/` | Cross-cutting infrastructure: config (Pydantic Settings), Redis cache, Fernet crypto, logging/observability middleware. | backend/app/core/config.py<br>backend/app/core/cache.py<br>backend/app/core/crypto.py |
| `CRM_EVALUATION_AUDIT/` | Architecture audit artefacts. _data/ holds machine-readable maps (this file). rules/ for audit rules. | CRM_EVALUATION_AUDIT/_data/repo_map.json |
| `scripts/` | One-off operational scripts (history import, backfills, etc.). |  |
| `n8n_heykiki_provision.json` | n8n workflow export — legacy automation blueprint for provisioning and post-call forwarding (superseded by native backend routes). |  |

## Backend Modules

| Area | Routes | Services |
|---|---|---|
| Core infrastructure | GET /<br>GET /api/health | app.core.config<br>app.core.cache<br>app.core.crypto<br>app.core.logging_config<br>app.core.observability<br>app.db.supabase_client |
| Provisioning & super-admin | POST /api/heykiki/provision<br>GET\|POST /api/super-admin/orgs<br>POST /api/super-admin/orgs/{id}/import-history | app.services.provisioning<br>app.services.history_import<br>app.services.agent_config |
| ElevenLabs agent webhooks (inbound call flow) | POST /api/elevenlabs/conversation-init<br>POST /api/elevenlabs/post-call<br>POST /api/tools/identify-customer<br>POST /api/tools/update-customer<br>POST /api/tools/create-inquiry<br>POST /api/tools/get-available-slots<br>POST /api/tools/book-appointment<br>POST /api/tools/cancel-appointment<br>POST /api/tools/change-appointment<br>POST /api/tools/search-inquiries<br>POST /api/tools/query-knowledge-base<br>POST /api/tools/transfer-call<br>POST /api/tools/draft-cost-estimate | app.services.conversation_init<br>app.services.post_call<br>app.services.identify<br>app.services.inquiries<br>app.services.scheduling<br>app.services.appointments<br>app.services.knowledge<br>app.services.transfer<br>app.services.cost_estimates<br>app.services.elevenlabs_agent |
| Outbound calling | POST /api/outbound/run-due-reminders<br>POST /api/outbound/send | app.services.outbound_call<br>app.services.outbound_dispatch<br>app.services.outbound_occasions<br>app.services.outbound_scope |
| Calls & inquiries | GET /api/calls<br>GET /api/calls/{id}<br>DELETE /api/calls/{id}<br>GET /api/inquiries<br>GET /api/inquiries/{id}<br>POST /api/inquiries<br>PATCH /api/inquiries/{id} | app.services.inquiries |
| Cases | GET /api/cases<br>POST /api/cases<br>PATCH /api/cases/{id}<br>DELETE /api/cases/{id}<br>GET /api/cases/{id}/jobs<br>POST /api/cases/group<br>POST /api/cases/apply | app.services.cases.grouper<br>app.services.cases.apply_run<br>app.services.cases.dryrun |
| Customers | GET /api/customers<br>GET /api/customers/{id}<br>POST /api/customers<br>PATCH /api/customers/{id} | app.services.customers<br>app.services.csv_import |
| Appointments & calendar | GET /api/appointments<br>POST /api/appointments<br>PATCH /api/appointments/{id}<br>DELETE /api/appointments/{id}<br>POST /api/calendar-settings/sync-google | app.services.appointments<br>app.services.scheduling<br>app.services.calendar_sync<br>app.services.appointment_notify<br>app.services.appointment_emails<br>app.services.appointment_classifier |
| Projects | GET /api/projects<br>POST /api/projects<br>GET /api/projects/{id}<br>PATCH /api/projects/{id}<br>DELETE /api/projects/{id} | app.services.projects<br>app.services.projects_auto |
| Planning board | GET /api/planning-board<br>PATCH /api/planning-board/assignments |  |
| Cost estimates & invoices | GET /api/cost-estimates<br>POST /api/cost-estimates<br>GET /api/invoices<br>POST /api/invoices | app.services.cost_estimates<br>app.services.invoices |
| Catalog & text modules | GET /api/catalog<br>POST /api/catalog/items<br>GET /api/text-modules<br>POST /api/text-modules | app.services.stripe_catalog |
| Employees & users | GET /api/employees<br>POST /api/employees<br>PATCH /api/employees/{id}<br>GET /api/users/me<br>POST /api/users/invite | app.services.employee_invite |
| Kiki-Zentrale (agent config UI) | GET /api/kiki-zentrale/config<br>PATCH /api/kiki-zentrale/config<br>POST /api/kiki-zentrale/knowledge-resources<br>DELETE /api/kiki-zentrale/knowledge-resources/{id}<br>GET /api/kiki-zentrale/agent-health<br>POST /api/kiki-zentrale/rollback/{snapshot_id} | app.services.elevenlabs_agent<br>app.services.agent_config<br>app.services.knowledge<br>app.services.price_knowledge |
| OAuth & email settings | GET /api/settings/oauth/{provider}/authorize<br>GET /api/settings/oauth/{provider}/callback<br>DELETE /api/settings/oauth/{provider}<br>GET /api/settings/email-config<br>PATCH /api/settings/email-config | app.services.oauth_tokens<br>app.services.oauth_providers<br>app.services.email_send |
| Billing (Stripe, gate: STRIPE_BILLING_ENABLED) | GET /api/billing/status<br>POST /api/billing/portal<br>POST /api/stripe-webhook | app.services.stripe_billing<br>app.services.stripe_webhook<br>app.services.stripe_provisioning<br>app.services.stripe_matcher<br>app.services.stripe_admin_actions<br>app.services.billing_usage<br>app.services.billing_notifications |
| PDS integration | POST /api/pds/log-call<br>POST /api/pds/greeting<br>POST /api/pds/create-contact | app.services.pds |
| AI copilot (gate: COPILOT_ENABLED) | POST /api/copilot/message<br>GET /api/copilot/conversations | app.services.copilot.orchestrator<br>app.services.copilot.tools<br>app.services.ai.client<br>app.services.ai.usage |
| Documents & vehicles | GET /api/documents<br>POST /api/documents<br>GET /api/vehicles<br>POST /api/vehicles |  |
| Public / no-auth portals | GET /api/public/jobs/{token}<br>GET /api/public/technician/{token} | app.services.technician_jobs |
| Action suggestions | GET /api/actions<br>POST /api/actions/{id}/apply<br>DELETE /api/actions/{id} |  |
| Dashboard | GET /api/dashboard/overview |  |

## Frontend Modules

| Area | Pages |
|---|---|
| Auth | src/auth/AuthProvider.tsx<br>src/auth/ProtectedRoute.tsx<br>src/pages/LoginPage.tsx<br>src/pages/SetPasswordPage.tsx<br>src/admin/AdminAuthProvider.tsx |
| Dashboard | src/pages/DashboardPage.tsx |
| Call log | src/pages/CallLogsPage.tsx<br>src/pages/PosteingangPage.tsx |
| Customers | src/pages/CustomersPage.tsx<br>src/pages/CustomerDetailPage.tsx |
| Cases (Fälle) | src/pages/CasesPage.tsx<br>src/pages/VorgangThreadPage.tsx |
| Projects | src/pages/ProjectsPage.tsx<br>src/pages/ProjectWorkspacePage.tsx<br>src/pages/ProjectFormPage.tsx |
| Calendar & appointments | src/pages/CalendarPage.tsx<br>src/pages/MyAbsencePage.tsx |
| Planning board | src/pages/PlanningBoardPage.tsx |
| Cost estimates & invoices | src/pages/CostEstimatesPage.tsx<br>src/pages/CostEstimateFormPage.tsx<br>src/pages/InvoicesPage.tsx<br>src/pages/InvoiceFormPage.tsx |
| Catalog | src/pages/CatalogPage.tsx |
| Employees | src/pages/EmployeesPage.tsx |
| Kiki-Zentrale (agent config) | src/pages/KikiZentralePage.tsx<br>src/pages/RufumleitungGuidePage.tsx |
| Settings | src/pages/SettingsPage.tsx |
| Technician portal (public) | src/pages/JobLinkPage.tsx<br>src/pages/TechnicianPortalPage.tsx |
| Super-admin (separate React tree) | src/admin/AdminApp.tsx<br>src/admin/AdminOrgsPage.tsx<br>src/admin/AdminBillingPage.tsx<br>src/admin/AdminOrgFormPage.tsx |
| Copilot widget | src/components/kiki/VerlaufSection.tsx |
| Shared libs | src/lib/api.ts<br>src/lib/supabase.ts<br>src/lib/env.ts<br>src/lib/kikiApi.ts<br>src/lib/dashApi.ts<br>src/lib/datetime.ts |

## Database Tables (52)

| Table | Introduced By | Purpose |
|---|---|---|
| `organizations` | 0001_init_schema.sql | Root tenant table: one row per tradesperson business. Holds ElevenLabs agent_id, org_code, billing fields. |
| `org_secrets` | 0001_init_schema.sql | Per-org encrypted secrets (legacy; main secrets now in env or oauth_connections). |
| `users` | 0001_init_schema.sql | CRM user accounts (org_admin + employees). Linked to Supabase Auth. |
| `customers` | 0001_init_schema.sql | Customer/caller contact records per org. |
| `calls` | 0001_init_schema.sql | Inbound/outbound call records from ElevenLabs. Central CRM event. Enhanced by many later migrations (emergency_flag 0024, deleted_at 0043, pds_synced 0069, is_spam 0071). |
| `inquiries` | 0001_init_schema.sql | Service requests created during a call (ANF- numbered). Linked to calls, customers, cases. |
| `appointments` | 0001_init_schema.sql | Scheduled appointments, slots, and Google Calendar imports (source='google_import' from migration 0033). |
| `cost_estimates` | 0001_init_schema.sql | KVA (Kostenvoranschlag) / cost estimate documents with line items. |
| `invoices` | 0001_init_schema.sql | Invoices linked to customers and projects, with PDF generation. |
| `employees` | 0001_init_schema.sql | Employee records per org with roles, colors, absence tracking. Extended by 0059 (is_technician). |
| `agent_configs` | 0001_init_schema.sql | Per-org Kiki AI agent config: scheduling rules, autonomy level, enabled features. |
| `catalog_items` | 0001_init_schema.sql | Service catalog items with pricing (used for cost estimates and price knowledge base). |
| `ai_suggestions` | 0001_init_schema.sql | AI-generated suggestions for CRM actions (proactive AI). |
| `time_entries` | 0001_init_schema.sql | Time tracking entries for employees. |
| `documents` | 0007_documents.sql | File attachments (PDFs, images) linked to various entities. Stored in Supabase Storage. |
| `employee_absences` | 0008_employee_management.sql | Employee absence records (vacation, sick leave) affecting slot availability. |
| `vehicles` | 0009_planning_board.sql | Fleet vehicles for the planning board. |
| `tools` | 0009_planning_board.sql | Tool/equipment inventory for the planning board. |
| `text_modules` | 0011_catalog_templates.sql | Reusable text snippets for cost estimates, invoices, emails. |
| `projects` | 0013_projects.sql (originally), recreated by 0073_case_project_split.sql | Top-layer project grouping above Cases (PR- numbered). Restored in migration 0073 as a separate layer above cases. |
| `project_employees` | 0013_projects.sql | Many-to-many: project ↔ employee assignments. |
| `email_configs` | 0014_settings_fields.sql | Per-org email sending config: OAuth provider choice or custom SMTP credentials (Fernet-encrypted). |
| `pds_configs` | 0014_settings_fields.sql | PDS-Software ERP integration config: API URL + Bearer key (Fernet-encrypted) per org. |
| `agent_required_fields` | 0015_kiki_zentrale.sql | Ordered list of fields Kiki must capture during a call (name, phone, address, etc.). |
| `appointment_categories` | 0015_kiki_zentrale.sql | Named appointment types per org with duration defaults. |
| `agent_services` | 0015_kiki_zentrale.sql | Services the agent is trained to handle (plumbing, heating, etc.). |
| `knowledge_resources` | 0015_kiki_zentrale.sql | Knowledge base documents (URL/file/text) pushed to ElevenLabs KB. Tracks sync status and elevenlabs_doc_id. |
| `agent_config_snapshots` | 0015_kiki_zentrale.sql | Full ElevenLabs agent config snapshots before every write (enables rollback). |
| `agent_writes_audit` | 0015_kiki_zentrale.sql | Audit log of every ElevenLabs agent config mutation: diff, HTTP status, rollback flag. |
| `ai_suggestion_actions` | 0016_ai_suggestion_actions.sql | Structured actions attached to AI suggestions (e.g., create appointment, update customer). |
| `outbound_calls` | 0029_outbound_calls.sql | Ledger for outbound call dispatches — idempotency guard prevents double-dialing. |
| `maintenance_plans` | 0031_maintenance_plans.sql | Recurring service maintenance plan records per customer. |
| `missed_calls` | 0032_missed_calls.sql | Calls that went unanswered, for follow-up tracking. |
| `oauth_connections` | 0028_oauth_connections.sql | Stored OAuth tokens (Google/Microsoft/Calendly) per org. Refresh tokens encrypted at rest. |
| `oauth_purpose_links` | 0034_oauth_purpose_links.sql | Links an oauth_connection to a purpose (email, calendar) enabling multi-provider routing. |
| `copilot_conversations` | 0042_ai_copilot.sql (recreated by 0062_copilot_conversations.sql) | AI copilot session threads per org/user. |
| `copilot_messages` | 0042_ai_copilot.sql (recreated by 0062_copilot_conversations.sql) | Individual messages within a copilot conversation (user + assistant turns). |
| `copilot_action_audit` | 0042_ai_copilot.sql | Audit log of copilot-initiated CRM mutations. |
| `copilot_escalations` | 0042_ai_copilot.sql | Cases where the copilot escalated to a human operator. |
| `ai_usage_log` | 0042_ai_copilot.sql | Per-org AI spend ledger (tokens * cost) enforcing monthly cap (COPILOT_MONTHLY_COST_CAP_USD). |
| `action_tasks` | 0054_action_tasks.sql | Scheduled/deferred action tasks triggered by agent suggestions or outbound occasions. |
| `case_links` | 0055_vorgang_threading.sql | Many-to-many links between calls/inquiries and cases for the Vorgang threading view. |
| `cases` | 0056_cases.sql | Case records (FL- numbered). The core CRM ticket: groups calls + inquiries under a customer. Renamed from former projects table in migration 0073. |
| `billing_events` | 0048_billing.sql | Write ledger for every Stripe mutation (audit-first model, like agent_writes_audit). |
| `billing_webhook_events` | 0048_billing.sql | Received Stripe webhook events for idempotency and audit. |
| `billing_usage_reports` | 0048_billing.sql | Per-call Stripe usage records (idempotent by call_id). |
| `billing_migration_log` | 0048_billing.sql | Log of subscription migration steps when moving orgs between Stripe plans. |
| `billing_security_events` | 0048_billing.sql | Security-sensitive billing events (cross-org guard violations, etc.). |
| `billing_notifications` | 0049_billing_phase2.sql | In-app billing alert records (80% usage warning, plan upgrade prompts). |
| `billing_checkout_sessions` | 0049_billing_phase2.sql | Stripe Checkout session records for plan upgrades. |
| `technician_job_links` | 0064_technician_job_links.sql | Token-secured job links sent to field technicians (no login required — token IS the credential). |
| `pds_sync_log` | 0070_pds_sync_log.sql | Log of PDS-Software sync attempts (call log push, contact create) with status and error details. |

## Module Relationship Diagram

```mermaid
flowchart LR
  frontend_src_lib_supabase_ts["frontend/src/lib/supabase.ts"]
  Supabase["Supabase"]
  frontend_src_lib_supabase_ts --> Supabase
  frontend_src_lib_api_ts["frontend/src/lib/api.ts"]
  backend_FastAPI["backend FastAPI"]
  frontend_src_lib_api_ts --> backend_FastAPI
  backend_app_db_supabase_client_py["backend/app/db/supabase_client.py"]
  backend_app_db_supabase_client_py --> Supabase
  backend_app_services_elevenlabs_agent_py["backend/app/services/elevenlabs_agent.py"]
  ElevenLabs["ElevenLabs"]
  backend_app_services_elevenlabs_agent_py --> ElevenLabs
  backend_app_services_outbound_call_py["backend/app/services/outbound_call.py"]
  backend_app_services_outbound_call_py --> ElevenLabs
  backend_app_api_routes_tools_["backend/app/api/routes/tools/"]
  backend_app_api_routes_tools_ --> ElevenLabs
  backend_app_api_routes_conversation_init["backend/app/api/routes/conversation_init.py"]
  backend_app_api_routes_conversation_init --> ElevenLabs
  backend_app_api_routes_post_call_py["backend/app/api/routes/post_call.py"]
  n8n["n8n"]
  backend_app_api_routes_post_call_py --> n8n
  backend_app_services_post_call_py["backend/app/services/post_call.py"]
  PDS_Software["PDS-Software"]
  backend_app_services_post_call_py --> PDS_Software
  backend_app_services_transfer_py["backend/app/services/transfer.py"]
  Twilio["Twilio"]
  backend_app_services_transfer_py --> Twilio
  backend_app_services_email_send_py["backend/app/services/email_send.py"]
  Google["Google"]
  backend_app_services_email_send_py --> Google
  Microsoft["Microsoft"]
  backend_app_services_email_send_py --> Microsoft
  Brevo__SMTP___HTTP_API_["Brevo (SMTP + HTTP API)"]
  backend_app_services_email_send_py --> Brevo__SMTP___HTTP_API_
  backend_app_services_calendar_sync_py["backend/app/services/calendar_sync.py"]
  backend_app_services_calendar_sync_py --> Google
  backend_app_services_ai_client_py["backend/app/services/ai/client.py"]
  OpenAI["OpenAI"]
  backend_app_services_ai_client_py --> OpenAI
  backend_app_services_stripe_billing_py["backend/app/services/stripe_billing.py"]
  Stripe["Stripe"]
  backend_app_services_stripe_billing_py --> Stripe
  backend_app_api_routes_stripe_webhook_py["backend/app/api/routes/stripe_webhook.py"]
  backend_app_api_routes_stripe_webhook_py --> Stripe
  backend_app_core_cache_py["backend/app/core/cache.py"]
  Redis["Redis"]
  backend_app_core_cache_py --> Redis
  backend_app_services_ratelimit_py["backend/app/services/ratelimit.py"]
  backend_app_services_ratelimit_py --> Redis
  backend_app_main_py["backend/app/main.py"]
  Sentry["Sentry"]
  backend_app_main_py --> Sentry
```

### Dependency Edges

| From | To | Reason |
|---|---|---|
| frontend/src/lib/supabase.ts | Supabase | Auth sessions (anon key + JWT). Two clients: heykiki-customer-auth + heykiki-admin-auth storage keys. |
| frontend/src/lib/api.ts | backend FastAPI | All CRM data reads/writes via VITE_API_URL + Supabase JWT Bearer token. |
| backend/app/db/supabase_client.py | Supabase | Service-role client for all DB operations. HTTP/1.1 forced for thread-safe concurrent fan-out. |
| backend/app/services/elevenlabs_agent.py | ElevenLabs | Agent config CRUD, knowledge base management, health probes via xi-api-key REST. |
| backend/app/services/outbound_call.py | ElevenLabs | POST /v1/convai/twilio/outbound-call to place outbound calls via ElevenLabs-Twilio bridge. |
| backend/app/api/routes/tools/ | ElevenLabs | Tool webhook handlers called by ElevenLabs agent during active calls. |
| backend/app/api/routes/conversation_init.py | ElevenLabs | Conversation initiation webhook — ElevenLabs calls this on call connect to get per-org config. |
| backend/app/api/routes/post_call.py | n8n | n8n forwards ElevenLabs post-call payload here after call ends. |
| backend/app/services/post_call.py | PDS-Software | Auto-sync call log to PDS after processing (best-effort, non-fatal). |
| backend/app/services/transfer.py | Twilio | Direct Twilio REST API call to redirect live inbound call TwiML to human number. |
| backend/app/services/email_send.py | Google | Tier-1 email: Gmail API via OAuth access token. |
| backend/app/services/email_send.py | Microsoft | Tier-1 email: Microsoft Graph API via OAuth access token. |
| backend/app/services/email_send.py | Brevo (SMTP + HTTP API) | Tier-3 fallback email relay when org has no OAuth or custom SMTP configured. |
| backend/app/services/calendar_sync.py | Google | Read-only pull of Google primary calendar events into appointments table. |
| backend/app/services/ai/client.py | OpenAI | Copilot chat completions and tool calls. Classifiers for emergency detection and employee auto-assign. |
| backend/app/services/stripe_billing.py | Stripe | Subscription reads, usage records, billing portal sessions, customer management. |
| backend/app/api/routes/stripe_webhook.py | Stripe | Receives Stripe webhook events (subscription created/updated/deleted, invoice paid). |
| backend/app/core/cache.py | Redis | Org-scoped caching for read-heavy endpoints. Fail-open: disabled when REDIS_URL not set. |
| backend/app/services/ratelimit.py | Redis | Per-org rate limiting using Redis counters. |
| backend/app/main.py | Sentry | Error tracking for unhandled exceptions. Dormant until SENTRY_DSN set. |

## Data Flows

```mermaid
flowchart TD
  subgraph F0["Inbound call: caller rings → inquiry created"]
  Inbound_call__caller_rings___inquiry_cre_0["1. Caller dials Twilio number linked to ElevenLa"]
  Inbound_call__caller_rings___inquiry_cre_1["2. ElevenLabs fires GET /api/elevenlabs/conversa"]
  Inbound_call__caller_rings___inquiry_cre_0 --> Inbound_call__caller_rings___inquiry_cre_1
  Inbound_call__caller_rings___inquiry_cre_2["3. ElevenLabs conducts conversation; each tool c"]
  Inbound_call__caller_rings___inquiry_cre_1 --> Inbound_call__caller_rings___inquiry_cre_2
  Inbound_call__caller_rings___inquiry_cre_3["4. Call ends → ElevenLabs notifies n8n with post"]
  Inbound_call__caller_rings___inquiry_cre_2 --> Inbound_call__caller_rings___inquiry_cre_3
  Inbound_call__caller_rings___inquiry_cre_4["5. n8n forwards to POST /api/elevenlabs/post-cal"]
  Inbound_call__caller_rings___inquiry_cre_3 --> Inbound_call__caller_rings___inquiry_cre_4
  Inbound_call__caller_rings___inquiry_cre_5["6. post_call.py normalizes payload, inserts/upda"]
  Inbound_call__caller_rings___inquiry_cre_4 --> Inbound_call__caller_rings___inquiry_cre_5
  Inbound_call__caller_rings___inquiry_cre_6["7. If org has PDS config: best-effort sync of ca"]
  Inbound_call__caller_rings___inquiry_cre_5 --> Inbound_call__caller_rings___inquiry_cre_6
  Inbound_call__caller_rings___inquiry_cre_7["8. If STRIPE_USAGE_REPORTING_ENABLED: background"]
  Inbound_call__caller_rings___inquiry_cre_6 --> Inbound_call__caller_rings___inquiry_cre_7
  end
  subgraph F1["Outbound call: occasion-driven reminder"]
  Outbound_call__occasion_driven_reminder_0["1. Cron / n8n fires POST /api/outbound/run-due-r"]
  Outbound_call__occasion_driven_reminder_1["2. outbound_dispatch.py scans outbound-enabled o"]
  Outbound_call__occasion_driven_reminder_0 --> Outbound_call__occasion_driven_reminder_1
  Outbound_call__occasion_driven_reminder_2["3. Scope guard: if OUTBOUND_TEST_SCOPE_ONLY=1, o"]
  Outbound_call__occasion_driven_reminder_1 --> Outbound_call__occasion_driven_reminder_2
  Outbound_call__occasion_driven_reminder_3["4. outbound_call.py POSTs to ElevenLabs /v1/conv"]
  Outbound_call__occasion_driven_reminder_2 --> Outbound_call__occasion_driven_reminder_3
  Outbound_call__occasion_driven_reminder_4["5. ElevenLabs + Twilio places the call; conversa"]
  Outbound_call__occasion_driven_reminder_3 --> Outbound_call__occasion_driven_reminder_4
  Outbound_call__occasion_driven_reminder_5["6. Call ends → post-call flow (same as inbound) "]
  Outbound_call__occasion_driven_reminder_4 --> Outbound_call__occasion_driven_reminder_5
  Outbound_call__occasion_driven_reminder_6["7. Optional occasion email (OUTBOUND_OCCASION_EM"]
  Outbound_call__occasion_driven_reminder_5 --> Outbound_call__occasion_driven_reminder_6
  end
  subgraph F2["Agent configuration (Kiki-Zentrale)"]
  Agent_configuration__Kiki_Zentrale__0["1. Org admin edits config in KikiZentralePage (f"]
  Agent_configuration__Kiki_Zentrale__1["2. Frontend POSTs to /api/kiki-zentrale/config."]
  Agent_configuration__Kiki_Zentrale__0 --> Agent_configuration__Kiki_Zentrale__1
  Agent_configuration__Kiki_Zentrale__2["3. Backend calls patch_agent_safely(): cross-org"]
  Agent_configuration__Kiki_Zentrale__1 --> Agent_configuration__Kiki_Zentrale__2
  Agent_configuration__Kiki_Zentrale__3["4. On verify failure: automatic rollback to snap"]
  Agent_configuration__Kiki_Zentrale__2 --> Agent_configuration__Kiki_Zentrale__3
  Agent_configuration__Kiki_Zentrale__4["5. Knowledge resources: uploaded to Supabase Sto"]
  Agent_configuration__Kiki_Zentrale__3 --> Agent_configuration__Kiki_Zentrale__4
  end
  subgraph F3["Call transfer (emergency / staff)"]
  Call_transfer__emergency___staff__0["1. ElevenLabs agent detects transfer intent and "]
  Call_transfer__emergency___staff__1["2. transfer.py reads emergency_number / incoming"]
  Call_transfer__emergency___staff__0 --> Call_transfer__emergency___staff__1
  Call_transfer__emergency___staff__2["3. If Twilio creds + call_sid present: Twilio RE"]
  Call_transfer__emergency___staff__1 --> Call_transfer__emergency___staff__2
  Call_transfer__emergency___staff__3["4. Returns success + transfer message regardless"]
  Call_transfer__emergency___staff__2 --> Call_transfer__emergency___staff__3
  end
  subgraph F4["Email send (3-tier chain)"]
  Email_send__3_tier_chain__0["1. Trigger: appointment confirmation, KVA PDF, i"]
  Email_send__3_tier_chain__1["2. Tier 1: if org has Google OAuth → Gmail API s"]
  Email_send__3_tier_chain__0 --> Email_send__3_tier_chain__1
  Email_send__3_tier_chain__2["3. Tier 2: if org has Microsoft OAuth → Microsof"]
  Email_send__3_tier_chain__1 --> Email_send__3_tier_chain__2
  Email_send__3_tier_chain__3["4. Tier 3: if org has customer SMTP → smtplib SM"]
  Email_send__3_tier_chain__2 --> Email_send__3_tier_chain__3
  Email_send__3_tier_chain__4["5. Tier 4 (HeyKiki fallback): Brevo HTTP API (ap"]
  Email_send__3_tier_chain__3 --> Email_send__3_tier_chain__4
  end
  subgraph F5["Google Calendar sync"]
  Google_Calendar_sync_0["1. Org admin triggers sync from SettingsPage → P"]
  Google_Calendar_sync_1["2. calendar_sync.py fetches OAuth token (auto-re"]
  Google_Calendar_sync_0 --> Google_Calendar_sync_1
  Google_Calendar_sync_2["3. Google Calendar API: GET primary calendar eve"]
  Google_Calendar_sync_1 --> Google_Calendar_sync_2
  Google_Calendar_sync_3["4. Events upserted into appointments table (sour"]
  Google_Calendar_sync_2 --> Google_Calendar_sync_3
  Google_Calendar_sync_4["5. Deleted events → status='cancelled' to free s"]
  Google_Calendar_sync_3 --> Google_Calendar_sync_4
  end
  subgraph F6["Org provisioning"]
  Org_provisioning_0["1. Super-admin POSTs to /api/heykiki/provision ("]
  Org_provisioning_1["2. provisioning.py: creates organization row, se"]
  Org_provisioning_0 --> Org_provisioning_1
  Org_provisioning_2["3. agent_config.py: configures ElevenLabs agent "]
  Org_provisioning_1 --> Org_provisioning_2
  Org_provisioning_3["4. Background: history_import.py fetches histori"]
  Org_provisioning_2 --> Org_provisioning_3
  Org_provisioning_4["5. Optional Stripe: stripe_provisioning.py links"]
  Org_provisioning_3 --> Org_provisioning_4
  end
  subgraph F7["Stripe billing lifecycle"]
  Stripe_billing_lifecycle_0["1. Customer visits /settings/abrechnung → GET /a"]
  Stripe_billing_lifecycle_1["2. Upgrade: POST /api/billing/portal → Stripe Bi"]
  Stripe_billing_lifecycle_0 --> Stripe_billing_lifecycle_1
  Stripe_billing_lifecycle_2["3. Stripe webhook: POST /api/stripe-webhook (sig"]
  Stripe_billing_lifecycle_1 --> Stripe_billing_lifecycle_2
  Stripe_billing_lifecycle_3["4. Per-call usage: post-call hook triggers billi"]
  Stripe_billing_lifecycle_2 --> Stripe_billing_lifecycle_3
  Stripe_billing_lifecycle_4["5. 80% warning: billing_notifications inserted →"]
  Stripe_billing_lifecycle_3 --> Stripe_billing_lifecycle_4
  end
  subgraph F8["PDS-Software sync (post-call)"]
  PDS_Software_sync__post_call__0["1. post_call.py finishes inserting call row."]
  PDS_Software_sync__post_call__1["2. If org has pds_configs row: pds.sync_call_to_"]
  PDS_Software_sync__post_call__0 --> PDS_Software_sync__post_call__1
  PDS_Software_sync__post_call__2["3. pds.py decrypts Bearer token from pds_configs"]
  PDS_Software_sync__post_call__1 --> PDS_Software_sync__post_call__2
  PDS_Software_sync__post_call__3["4. Result (success/error) written to pds_sync_lo"]
  PDS_Software_sync__post_call__2 --> PDS_Software_sync__post_call__3
  end
  subgraph F9["AI copilot (Kiki Assistent)"]
  AI_copilot__Kiki_Assistent__0["1. User types message in copilot widget (VITE_CO"]
  AI_copilot__Kiki_Assistent__1["2. POST /api/copilot/message → copilot/orchestra"]
  AI_copilot__Kiki_Assistent__0 --> AI_copilot__Kiki_Assistent__1
  AI_copilot__Kiki_Assistent__2["3. OpenAI gpt-4o completion with tool definition"]
  AI_copilot__Kiki_Assistent__1 --> AI_copilot__Kiki_Assistent__2
  AI_copilot__Kiki_Assistent__3["4. Tool calls: copilot/tools.py executes CRM act"]
  AI_copilot__Kiki_Assistent__2 --> AI_copilot__Kiki_Assistent__3
  AI_copilot__Kiki_Assistent__4["5. Response + actions streamed back. ai_usage_lo"]
  AI_copilot__Kiki_Assistent__3 --> AI_copilot__Kiki_Assistent__4
  end
```

- **Inbound call: caller rings → inquiry created:** 1. Caller dials Twilio number linked to ElevenLabs agent. → 2. ElevenLabs fires GET /api/elevenlabs/conversation-init → backend looks up org by phone number, returns per-org config (business hours, first message, agent prompt override). → 3. ElevenLabs conducts conversation; each tool call hits /api/tools/* webhook endpoints (identify-customer, create-inquiry, book-appointment, etc.). → 4. Call ends → ElevenLabs notifies n8n with post-call payload. → 5. n8n forwards to POST /api/elevenlabs/post-call (secret-protected). → 6. post_call.py normalizes payload, inserts/updates call row in Supabase, links inquiry, creates missed_call if needed. → 7. If org has PDS config: best-effort sync of call log to PDS-Software via pds.py. → 8. If STRIPE_USAGE_REPORTING_ENABLED: background task reports call duration to Stripe usage records. → 9. Appointment notification emails sent if appointment was booked (email_send.py 3-tier chain).  _(integrations: ElevenLabs, n8n, Supabase, PDS-Software, Stripe, Brevo (SMTP + HTTP API))_
- **Outbound call: occasion-driven reminder:** 1. Cron / n8n fires POST /api/outbound/run-due-reminders (secret-protected). → 2. outbound_dispatch.py scans outbound-enabled orgs for due occasions (appointment_reminder, kva_followup, etc.). → 3. Scope guard: if OUTBOUND_TEST_SCOPE_ONLY=1, only allowed org IDs can proceed; real numbers replaced by test number. → 4. outbound_call.py POSTs to ElevenLabs /v1/convai/twilio/outbound-call with per-call dynamic variables + prompt override. → 5. ElevenLabs + Twilio places the call; conversation_id written to outbound_calls ledger. → 6. Call ends → post-call flow (same as inbound) processes the conversation. → 7. Optional occasion email (OUTBOUND_OCCASION_EMAILS_ENABLED) sent in parallel via email_send.py.  _(integrations: ElevenLabs, Twilio, n8n, Supabase, Brevo (SMTP + HTTP API))_
- **Agent configuration (Kiki-Zentrale):** 1. Org admin edits config in KikiZentralePage (first message, prompt, voice, business hours, knowledge resources). → 2. Frontend POSTs to /api/kiki-zentrale/config. → 3. Backend calls patch_agent_safely(): cross-org guard → snapshot to agent_config_snapshots → deep-merge → audio assertion → PATCH ElevenLabs REST → post-write verify → audit to agent_writes_audit. → 4. On verify failure: automatic rollback to snapshot + VerificationFailedError returned. → 5. Knowledge resources: uploaded to Supabase Storage → pushed to ElevenLabs KB API → doc_id stored in knowledge_resources.  _(integrations: ElevenLabs, Supabase)_
- **Call transfer (emergency / staff):** 1. ElevenLabs agent detects transfer intent and calls /api/tools/transfer-call. → 2. transfer.py reads emergency_number / incoming_forwarding_number from agent_configs. → 3. If Twilio creds + call_sid present: Twilio REST API redirects live call TwiML to human number. → 4. Returns success + transfer message regardless (graceful degradation if Twilio not configured).  _(integrations: ElevenLabs, Twilio, Supabase)_
- **Email send (3-tier chain):** 1. Trigger: appointment confirmation, KVA PDF, invoice, employee invite. → 2. Tier 1: if org has Google OAuth → Gmail API send. → 3. Tier 2: if org has Microsoft OAuth → Microsoft Graph API send. → 4. Tier 3: if org has customer SMTP → smtplib SMTP (Fernet-decrypt password). → 5. Tier 4 (HeyKiki fallback): Brevo HTTP API (api.brevo.com/v3) — Railway blocks outbound SMTP 587.  _(integrations: Google, Microsoft, Brevo (SMTP + HTTP API), Supabase)_
- **Google Calendar sync:** 1. Org admin triggers sync from SettingsPage → POST /api/calendar-settings/sync-google. → 2. calendar_sync.py fetches OAuth token (auto-refresh via oauth_tokens.py). → 3. Google Calendar API: GET primary calendar events for 60-day forward window. → 4. Events upserted into appointments table (source='google_import') to block AI slot finder. → 5. Deleted events → status='cancelled' to free slots.  _(integrations: Google, Supabase)_
- **Org provisioning:** 1. Super-admin POSTs to /api/heykiki/provision (MASTER_WEBHOOK_SECRET required). → 2. provisioning.py: creates organization row, seeds agent_configs with defaults, creates required_fields. → 3. agent_config.py: configures ElevenLabs agent (webhook URL, tool IDs, override flags, language). → 4. Background: history_import.py fetches historical ElevenLabs conversations and backfills calls table. → 5. Optional Stripe: stripe_provisioning.py links org to Stripe customer.  _(integrations: ElevenLabs, Supabase, Stripe)_
- **Stripe billing lifecycle:** 1. Customer visits /settings/abrechnung → GET /api/billing/status (reads Stripe subscription). → 2. Upgrade: POST /api/billing/portal → Stripe Billing Portal session URL → redirect. → 3. Stripe webhook: POST /api/stripe-webhook (signature verified) → stripe_webhook.py updates org billing fields in Supabase. → 4. Per-call usage: post-call hook triggers billing_usage.report_call_usage → Stripe usage record. → 5. 80% warning: billing_notifications inserted → frontend billing banner.  _(integrations: Stripe, Supabase)_
- **PDS-Software sync (post-call):** 1. post_call.py finishes inserting call row. → 2. If org has pds_configs row: pds.sync_call_to_pds() called (best-effort, non-fatal). → 3. pds.py decrypts Bearer token from pds_configs, calls PDS API: person/listpersonen (lookup by phone) → crm/createaufgabe (log call task). → 4. Result (success/error) written to pds_sync_log.  _(integrations: PDS-Software, Supabase)_
- **AI copilot (Kiki Assistent):** 1. User types message in copilot widget (VITE_COPILOT_ENABLED=1 + COPILOT_ENABLED=1). → 2. POST /api/copilot/message → copilot/orchestrator.py. → 3. OpenAI gpt-4o completion with tool definitions (read/write CRM data). → 4. Tool calls: copilot/tools.py executes CRM actions (create inquiry, update customer, etc.), audited in copilot_action_audit. → 5. Response + actions streamed back. ai_usage_log updated. Monthly cap checked.  _(integrations: OpenAI, Supabase)_

