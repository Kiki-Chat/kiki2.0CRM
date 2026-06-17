# CRM GLOSSARY — KikiJarvis (Onboarding Dictionary)

*Generated 2026-06-17 from the rule evidence, `_data/repo_map.json`, and the German rule docs in `docs/rules/`. The product UI is German; this glossary pairs the German label with the English meaning for customers, employees, and AI systems. "Governing rules" reference IDs in [BUSINESS_RULES.md](BUSINESS_RULES.md).*

---

### Organisation (Org / Tenant)
The top-level tenant — one trade business. Every record is scoped to an `org_id`; users, the voice agent, billing, and numbering are all per-org. Org code (e.g. `KC007` for "Kiki Chat GmbH") is embedded in record numbers. **Related:** User, Agent. **Rules:** AUTH-*. **Source:** `organizations` table; `app/api/deps.py`.

### Lead
A not-yet-qualified prospective customer. In KikiJarvis a lead is effectively the earliest customer/inquiry state — a caller who hasn't been converted to a managed Customer + Inquiry. **Related:** Customer, Inquiry. **Source:** `CUST` rules.

### Customer (Kunde)
A person or company the business serves. Has a `customer_number`, type (private/company), phone(s), address, VAT id. De-duplicated primarily by mobile phone (`CUST-001`). **Caveat:** identify-by-phone checks only the primary phone column, not `phone2` (`CUST-014`). **Related:** Inquiry, Case, Appointment, Invoice. **Source:** `customers`; `services/customers.py`, `services/identify.py`.

### Inquiry / Anfrage (ANF-)
A single customer request, usually created from a call. Numbered `ANF-<orgcode>-####`. Carries `status` (open/in_progress/completed/deleted), an optional `emergency_flag`, and links to a Call and a Case. **Business meaning:** the unit of incoming work. **Related:** Call, Case, Customer. **Rules:** INQ-*. **Source:** `inquiries`; `services/inquiries.py`, `tools/create_inquiry.py`.

### Case / Fall (FL-)
A grouping of related inquiries about the same job/issue for a customer. Numbered `FL-<orgcode>-####`. Inquiries are grouped into cases by AI with a provenance (`case_source` = ai / ai_confirmed / human) and a `case_confidence` score. Status: active / planning / completed. **Business meaning:** the "job" view that threads multiple touchpoints. **Related:** Inquiry, Project, Appointment, Technician dispatch. **Rules:** CASE-*. **Source:** `cases`; `services/cases/*`, `routes/cases.py`.

### Project / Projekt (PR-)
The tier above Case (restored by migration 0073), numbered `PR-<orgcode>-####`. Intended for larger multi-case engagements. **Runtime note:** currently **dormant** — cases are not linked to projects in practice (0/32 in the test org). **Related:** Case, Invoice. **Rules:** PROJ-*. **Source:** `projects`; `services/projects.py`.

### Cost Estimate / Kostenvoranschlag (KVA)
A priced quote (Angebot) of line items sent to a customer before work. Numbered with a doc-type prefix; VAT is **exclusive**. Can be converted to an Invoice (`INV-009`); has a validity window (`INV-012`). **Caveat:** Skonto (cash discount) is stored but **not applied to totals** (`INV-033`). **Related:** Invoice, Catalog, Customer. **Rules:** INV-*. **Source:** `cost_estimates`; `services/cost_estimates.py`, `tools/draft_cost_estimate.py`.

### Invoice / Rechnung
A billing document for completed work, line items with **exclusive VAT**, a payment status. Created from a KVA or directly. **Caveat:** an auto-invoice-on-case-completion path exists but is **dead code** (`INV-027`). **Related:** KVA, Case, Payment. **Rules:** INV-*. **Source:** `invoices`; `services/invoices.py`.

### Catalog (Katalog) / Catalog Item
The reusable price/service list used to build KVA and invoice line items. **Related:** KVA, Invoice, Price List KB. **Source:** `catalog_items`; `routes/catalog.py`.

### Employee / Mitarbeiter
A staff member of the org. Has a role (org_admin / employee), optional `activity_area` and `auto_assign` flags (**stored but not runtime-dispatched**, `EMP-030`), and absence records. Login is granted via a separate invite step. **Related:** Technician, Appointment, Absence. **Rules:** EMP-*. **Source:** `employees`; `services/employee_invite.py`.

### Technician / Techniker
A field worker assigned to do the job. Lightweight record; dispatched to a Case's jobs and works via a **token-based portal (no login)** (`AUTH-029`). **Related:** Case, Appointment, Vehicle, Job link. **Source:** `technician_jobs.py`, `public_technician.py`, `TechnicianPortalPage.tsx`.

### Vehicle / Fahrzeug
A company vehicle that can be associated with appointments/technicians. **Source:** `vehicles`; `routes/vehicles.py`.

### Absence / Abwesenheit
Employee unavailability (vacation/sick). Status enforced app-layer only (`EMP-015`); 28-day vacation default is `AMBIGUOUS` (`EMP-027`). **Source:** `employee_absences` (migration 0035), `MyAbsencePage.tsx`.

### Appointment / Termin
A scheduled visit. Rich lifecycle: `confirmed`, `cancelled`, plus schema states for rejected / rescheduled / customer-proposed / alternative slots. Constrained by scheduling rules (lead time, buffer, parallel slots) and optionally synced to **Google Calendar** (`google_event_id`). **Related:** Inquiry, Case, Employee, Technician, Calendar. **Rules:** APPT-*. **Source:** `appointments`; `services/appointments.py`, `scheduling.py`, `calendar_sync.py`.

### Calendar / Kalender & Planning Board (Planungstafel)
The scheduling surfaces. Calendar shows appointments; the Planning Board is the dispatch/assignment view. **Source:** `CalendarPage.tsx`, `PlanningBoardPage.tsx`, `routes/planning_board.py`, `calendar_settings.py`.

### Call / Anruf
An inbound or outbound phone interaction handled by Kiki. Stores transcript, summary, `data_collection`, duration, `direction`, `status` (completed), `is_spam`, soft-delete (`deleted_at`). An inbound call typically creates an Inquiry. **Related:** Inquiry, Customer, Agent. **Rules:** CALL-*. **Source:** `calls`; `services/post_call.py`, `conversation_init.py`.

### Missed Call / Verpasster Anruf
A call that wasn't completed. **Note:** the `missed_calls` table exists but the **writer is not yet built** (`CALL-039`); missed-callback outbound selection is partial (`OUT-017`). **Source:** `missed_calls` (migration 0032).

### Spam
A call flagged as spam (`is_spam`, `spam_at`). Excluded from normal call handling. **Source:** migration 0071; `CALL` rules.

### Emergency / Notdienst
An urgent request outside business hours. The agent flags `emergency_flag` (bilingual content fallback, fixed 2026-06-09) and can transfer to an emergency number with an optional surcharge notice. **Runtime-confirmed:** 6 flagged inquiries in the test org. **Rules:** INQ / KIKI emergency rules. **Source:** migration 0024; `render_emergency_block()`.

### Kiki Agent / Voice Agent (Sprachagent)
The per-org ElevenLabs Conversational-AI agent that answers calls in German. Configured via Kiki-Zentrale; one agent per org. **Related:** Prompt, Knowledge Base, Tools, Autonomy. **Rules:** KIKI-*. **Source:** `services/agent_config.py`, `elevenlabs_agent.py`.

### Kiki-Zentrale
The admin console for configuring the voice agent (persona, prompt, voice, behavior, knowledge, emergency, scheduling, conversation logic). See [KIKI_CENTRAL_AUDIT.md](KIKI_CENTRAL_AUDIT.md). **Source:** `routes/kiki_zentrale.py`, `KikiZentralePage.tsx`.

### Prompt (System-Prompt / Master-Prompt)
The full instruction text the agent runs on every call. **Re-derived** from `agent_prompt_template.txt` + config tables on each save (text not stored in DB); a `prompt_manual_override` gate lets super-admins hand-edit (with a drift caveat). **Rules:** KIKI-007/013. **Source:** `render_prompt_for_org()`.

### Knowledge Base (Wissensdatenbank) / RAG
The agent's company-specific answer source. Uses the **native ElevenLabs KB** (URL/PDF/text docs) — **not** the `hk_queryKnowledgeBase` webhook, which is a static stub (`KIKI-032`/`CALL-036`). Includes a toggleable **Price List KB** (Richtpreise). **Source:** `services/knowledge.py`, `price_knowledge.py`.

### Tool (hk_* Tools)
Webhook functions the agent can call mid-conversation: `hk_identifyCustomer`, `hk_createInquiry`, `hk_getAvailableAppointments`, `hk_bookAppointment`, `hk_changeAppointment`, `hk_cancelAppointment`, `hk_searchCustomerInquiries`, `hk_updateCustomerData`, `hk_draftCostEstimate`, `hk_queryKnowledgeBase`, transfer. **Source:** `routes/tools/*`.

### Autonomy / Autonomie (L1–L3)
Per-capability levels controlling how independently the **voice agent** acts (e.g. appointments, KVA). Distinct from the Copilot, whose autonomy is the confirm button only (`COP-027`). **Source:** `agent_configs.*_level`; migration 0044.

### Conversation Logic / Gesprächslogik (Wenn/Dann)
Org-specific If/Then rules injected as "Schritt 1a" into the agent prompt. **Caveat:** a compile failure silently drops the block (`KIKI` §4). **Source:** `agent_configs.conversation_logic`; `render_conversation_logic_block()`.

### Occasion / Anlass (Outbound)
The reason for an outbound call/email. Confirmed types: appointment_reminder (TERMIN_ERINNERUNG), appointment_confirmation, appointment_cancellation, appointment_reschedule, kva_followup, maintenance_due, missed_callback. **Rules:** OUT-*. **Source:** `services/outbound_occasions.py`.

### Outbound
Proactive calls/emails Kiki makes to customers. **LIVE to real customers** when `OUTBOUND_TEST_SCOPE_ONLY=0` (`OUT-009`). Time-window gated; supports retries. **Source:** `services/outbound_dispatch.py`, `outbound_scope.py`.

### AI Copilot
The in-CRM assistant that helps staff via chat, proposing actions for confirmation (never auto-executing). See [AI_COPILOT_RULEBOOK.md](AI_COPILOT_RULEBOOK.md). **Rules:** COP-*. **Source:** `services/copilot/*`, `routes/copilot.py`.

### Role & Permission (Rolle / Berechtigung)
`org_admin` (full org control), `employee` (scoped), and a **standalone super-admin** (separate app/login). Tools and data are role-gated and org-scoped. **Source:** `AUTH`/`COP` rules; `routes/super_admin.py`.

### Provisioning
The onboarding flow that creates an org, configures its ElevenLabs agent (prompt, tools, webhook, audio), and stamps `agent_provisioned_at`. **Source:** `configure_agent()`, `routes/provision.py`.

### Usage / Overage & Billing
Stripe-based metered billing — plans (Solo/Team/Premium) plus per-minute overage, usage caps with 80% warnings. **Status:** test-key-only until live keys + deploy. **Rules:** BILL-*. **Source:** `services/stripe_*`, `billing_usage.py`.

### Agent Sync / Sync-Status
The reconciliation of Kiki-Zentrale config onto the live ElevenLabs agent, protected by snapshot/verify/rollback/audit and surfaced via an `agent_sync_status` banner. **Source:** `agent_writes_audit`, `agent_config_snapshots`; see [ELEVENLABS_SYNC_AUDIT.md](ELEVENLABS_SYNC_AUDIT.md).

---
*For the full set of governing rules per term, see [TRACEABILITY_MATRIX.md](TRACEABILITY_MATRIX.md) and [BUSINESS_RULES.md](BUSINESS_RULES.md).*
