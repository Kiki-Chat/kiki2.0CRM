# Appointment Epic — READ-ONLY feasibility findings (2026-06-01)

Pure code reconnaissance for the next session. **No code was written.** Bottom line: most of the appointment-booking capability **already exists and is wired end-to-end** — the agent can book during a call today, availability is computed from business-hours + Google-imported busy time, the action-tab slot is already structured, and a full outbound-call engine exists (missing only specific occasion types + appointment emails).

---

## 1. Can the voice agent create an appointment during an inbound call today? — YES, fully wired

The ElevenLabs agent (`agent_5001…`, the SAFE test agent) has **7 appointment-related tools**, registered in [scripts/create_hk_tools_safe.py](scripts/create_hk_tools_safe.py) (`TOOLS` 55-125, built as `hk_<name>` → `{base}/api/elevenlabs/tools{path}`):

| Agent tool | Webhook path | Purpose |
|---|---|---|
| `hk_getAvailableAppointments` | `/get-available-slots` | "Always call before bookAppointment." |
| `hk_bookAppointment` | `/create-appointment` | Book a slot after caller confirms |
| `hk_cancelAppointment` | `/cancel-appointment` | Cancel |
| `hk_changeAppointment` | `/change-appointment` | Reschedule |

The book path is **real, not stubbed**: `/create-appointment` → [book_appointment.py:11-16](backend/app/api/routes/tools/book_appointment.py#L11) → `appointments.book_appointment()` ([appointments.py:187-282](backend/app/services/appointments.py#L187)) **INSERTs an `appointments` row `status="confirmed"`** + a linked `inquiries` row (`type="appointment_request"`), with idempotency (same customer+slot → existing booking) and a `SLOT_TAKEN` guard vs `parallel_slots`.
- **Soft-book phrasing:** the prompt tells the agent to say "Ich reserviere den Termin…" not "gebucht" ([outbound_occasions.py:133]) — but the DB row is written immediately as `confirmed`.
- Org resolution (multi-tenant): [deps.py:175-201](backend/app/api/deps.py#L175) `resolve_tool_org` via `X-HeyKiki-Secret` or `_agentId` → `organizations.elevenlabs_agent_id`.
- ⚠ **Stale comment** [main.py:95](backend/app/main.py#L95) says tool handlers "return 501 for now" — inaccurate; they're fully implemented.

## 2. Where would appointment availability come from? — TWO sources exist; NO live free/busy

- **(a) Business-hours config — EXISTS, primary source.** `agent_configs.scheduling` jsonb ([0001_init_schema.sql:195]); helpers in [scheduling.py](backend/app/services/scheduling.py) (`default_business_hours` Mon–Fri 08:00–17:00, per-day open/start/end/break). Consumed by `get_available_slots()` ([appointments.py:93-168](backend/app/services/appointments.py#L93)) which walks each day generating hourly slots respecting open/close/lunch, plus `lead_days`/`parallel_slots`. Editable via [calendar_settings.py](backend/app/api/routes/calendar_settings.py).
- **(b) Google-imported busy time — EXISTS, subtracts availability (indirectly).** **No `freebusy` API call anywhere.** Instead [calendar_sync.py](backend/app/services/calendar_sync.py) PULLs the org's Google **primary** calendar (read-only) and mirrors events into `appointments` as `source='google_import'`, `status='confirmed'`; `get_available_slots` counts confirmed appts as busy and skips full slots. There's also CRM→Google write-back gated to `source='crm'` + manual per-event push.
- **(c) Employee schedules — MINIMAL.** No per-employee working-hours/shift table; `get_available_slots` attaches only the first active employee (or literal "Team"). Absence status (0035) is NOT consulted by the slot finder. Availability is currently org-wide, not per-employee.
- **Appointments table schema** (assembled across migrations): base [0001:115-132] (`scheduled_at`, `duration_minutes`, `location` jsonb, `category`, `status` CHECK `pending|confirmed|cancelled|completed`, `assigned_to`→users); +`assigned_employee_id`→employees & `color` (0005, **code uses this, not `assigned_to`**); +`vehicle_id`/`tool_id` (0009); +`project_id` (0013); +confirm/reject/alternative lifecycle cols (0026); +`reminder_*` outbound-tracking (0027); +`google_event_id`/`source`/`last_synced_at` + partial unique `(org_id, google_event_id)` (0033). New lifecycle states are encoded as **additive timestamp columns**, never new enum values.

## 3. Action-tab "create appointment" control — slot ALREADY exists between Assigned and Status

Component: **`ActionsTab`** in [CallLogsPage.tsx:1161-1251](frontend/src/pages/CallLogsPage.tsx#L1161). Render order is already exactly **"Zugewiesen an" → appointment slot → "Status-Aktionen"**:
- "Zugewiesen an" (assignee `<select>`): [CallLogsPage.tsx:1184-1201](frontend/src/pages/CallLogsPage.tsx#L1184).
- **Between-slot placeholder:** `{appointmentSlot}` at [CallLogsPage.tsx:1203-1205](frontend/src/pages/CallLogsPage.tsx#L1203) (comment: "sits between Zugewiesen an and Status-Aktionen").
- "Status-Aktionen" block: [CallLogsPage.tsx:1207-1240] — already includes a `Termin erstellen` ActionRow ([:1238]) wired to `onAppointment` → `setModal('appointment')` ([:888]).
- `appointmentSlot` is built at [:807-820] and only renders today when the AGENT already proposed a pending appointment (`AppointmentCard` = confirm/reject/propose-alternative, [calls/AppointmentCard.tsx]). A net-new from-scratch "create appointment" control for any inquiry would drop into this same `{appointmentSlot}` position (independent of the `pendingAppointment` gate).

## 4. Outbound-call infrastructure — EXISTS as a full engine; specific occasions MISSING

- **Transport:** [outbound_call.py](backend/app/services/outbound_call.py) `place_outbound_call()` POSTs to ElevenLabs `POST /v1/convai/twilio/outbound-call` — **no separate Twilio/TwiML layer in-repo** (auto-configured ElevenLabs-side when the number is imported). Supports `dynamic_variables` + per-call `conversation_config_override`.
- **Orchestration:** [outbound_dispatch.py](backend/app/services/outbound_dispatch.py) registry engine. Entrypoints in [outbound.py](backend/app/api/routes/outbound.py): `POST /api/outbound/run-due-reminders` (secret-protected sweep, fired by **external cron/N8N** — no in-repo scheduler) + `POST /api/outbound/send` (manual single, `to_number` override = UAT-safe). Idempotency ledger `outbound_calls` ([0029]) with partial unique `(org_id, occasion, referenz_id) where status<>'failed'`; case-link gating ([0030]).
- **7 wired occasions** ([outbound_occasions.py:550-628]): `appointment_reminder`, `kva_followup`, `payment_reminder`, `satisfaction_survey`, `review_request`, `maintenance_due`, `missed_callback`. (`_render_appointment_reminder` even tells the outbound agent to use `hk_changeAppointment`/`hk_cancelAppointment` mid-call.)
- **MISSING for D1–D4 (cancel/confirm/change outbound + emails):**
  - No `appointment_confirmation` / cancel / change occasion — explicitly deferred ([outbound_occasions.py:22-25]). Adding one = a new `OccasionSpec` (key + `select` + `render`); engine/ledger/transport/gating all reuse as-is.
  - Email side: generic transport exists ([email_send.py] Gmail/MS Graph/Brevo/SMTP) but **no appointment-specific cancel/confirm/change templates** ([email_templates.py] only a generic renderer). Email-send is Amber-owned (separate track).

### Cross-cutting notes
- `appointments` is the single source of truth for CRM bookings + Google-imported busy time (`source='google_import'`) + ICS imports (`source='ics'`) — all three feed `get_available_slots`.
- Schema drift: appointments has both `assigned_to`(→users, original) and `assigned_employee_id`(→employees, 0005); booking code + frontend use `assigned_employee_id`.
- Ignore the stale `main.py:95` "501 stub" comment — handlers are live.
