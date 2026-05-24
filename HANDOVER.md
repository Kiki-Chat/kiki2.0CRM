# HeyKiki Portal — Session Handover

> Read this file first. It is the single source of truth for continuing the build
> in a new Claude Code session without losing context.

## What this is
A from-scratch, multi-tenant CRM for German tradespeople (Handwerker), fed in real
time by **ElevenLabs voice agents** (Kiki) via webhooks. Replaces a third-party
product (WerkPilot). UI is German; code/comments English.

- **Repo root:** `/Users/iamber/Code Jamming/KikiJarvis`
- **Layout:** `frontend/` (React+TS+Vite), `backend/` (Python FastAPI), `supabase/migrations/`, `scripts/`
- Reference docs are in `~/Downloads`: `CLAUDE_CODE_HANDOVER.md`, `01_navigation_architecture.md`, `02_design_system.md`, `05_dashboard_v3.jsx`, `hk_tools_payload_reference.md`.

## ⚠️ Environment gotchas (these cost time if missed)
1. **Backend runs on Python 3.13**, not the system's 3.14 (3.14 has no wheel for pydantic-core). venv is `backend/.venv` created with `python3.13`.
2. **supabase-py is pinned to 2.30.0** — older 2.11 rejects the new `sb_publishable_`/`sb_secret_` key format with "Invalid API key".
3. **Supabase signs JWTs with ES256** (asymmetric). Backend verifies via the project JWKS (`app/core/security.py`), not a shared HS256 secret.
4. **Deploy via the Railway CLI** (`railway up`), NOT the Railway MCP plugin — the plugin's token goes stale ("Unauthorized"). CLI is logged in as Amber.
5. `tzdata` is a backend dependency (slim Docker image lacks the tz database; needed for Europe/Berlin).

## Credentials (live in gitignored .env files — read them, don't guess)
- `backend/.env` — `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `MASTER_WEBHOOK_SECRET`, `POST_CALL_WEBHOOK_SECRET`, `ELEVENLABS_API_KEY` (values live in the gitignored file, not here).
- `frontend/.env` — `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_API_URL=http://localhost:8000`.
- **Security note:** the ElevenLabs API key is in plaintext in the Downloads reference docs — Amber should rotate it and keep it only in `backend/.env`.

## Key IDs
- **Supabase project:** `ifbluvdcbcesuhvkxsfn` (kikiJarvis), `https://ifbluvdcbcesuhvkxsfn.supabase.co`
- **Railway:** project `kikijarvis-backend` (`97ee09d0-0123-4a8f-bd75-873ce08fa942`), service `backend` (`f6ec2789-…`), env `production` (`227514ef-…`)
- **Backend prod URL:** `https://backend-production-3f88a.up.railway.app`
- **ElevenLabs agent:** `agent_5001ksahz3w7fhx90j71xr800py4` (ignore `agent_7201…` from old docs)
- **Test org:** `kiki-test-007`, org_id `c4dbf596-86fd-4484-88d9-095b2c082afb`
- **Test login:** `kikitest01@gmail.com` / password held by Amber (role org_admin) — ask for it when you need to verify the UI in the browser.

## How to run locally
```bash
# backend (terminal 1)
cd backend && ./.venv/bin/uvicorn app.main:app --port 8000
# frontend (terminal 2)
cd frontend && npm run dev    # http://localhost:5173
# tests
cd backend && ./.venv/bin/python -m pytest tests/ -q
```
To deploy backend: `cd backend && railway up --service backend --detach`, then poll the prod URL until the new route responds. Frontend is **local-only** (not deployed yet).

## Database (Supabase) — migrations 0001–0007 applied
Tables: organizations, org_secrets, users, customers, calls, inquiries, appointments,
cost_estimates, invoices, employees, agent_configs, catalog_items, ai_suggestions,
time_entries, documents. Notable added columns: `inquiries.number`,
`calls.{agent_id,caller_number,summary_title,data_collection}`,
`inquiries/appointments.assigned_employee_id`, `appointments.color`,
`customers.{customer_type,vat_id,notes,status}`. Storage bucket: `customer-files` (private).
RLS scoped by `org_id` (backend uses service role and bypasses RLS).

## Backend endpoints (FastAPI, all under prod URL)
- Health/util: `GET /health`, `GET /api/me`
- Provisioning: `POST /api/heykiki/provision` (master secret)
- ElevenLabs **tools** (10, all implemented): `POST /api/elevenlabs/tools/{identify-customer, update-customer, create-inquiry, get-available-slots, create-appointment, cancel-appointment, change-appointment, search-inquiries, query-knowledge-base, transfer-call}` — org resolved by `X-HeyKiki-Secret` or `_agentId`.
- `POST /api/elevenlabs/conversation-init` (returns dynamic_variables; wired on the agent).
- `POST /api/elevenlabs/post-call` (N8N → backend; secret `hk_sso_test_…`; idempotent on conversation_id; stores transcript/summary/data_collection; links/creates customer; Realtime broadcast `org:{org_id}:calls`).
- CRM: `GET /api/dashboard/overview`; `GET /api/calls`, `GET /api/calls/{id}`, `GET /api/calls/{id}/audio` (proxies ElevenLabs audio on demand), `POST /api/calls/{id}/inquiry`; `GET/POST /api/customers`, `GET/PATCH/DELETE /api/customers/{id}`, `GET/POST /api/customers/{id}/documents`; `GET /api/employees`; `POST /api/inquiries`, `PATCH /api/inquiries/{id}`; `POST /api/appointments`.

## ElevenLabs integration state
- 10 `hk_*` tools created/assigned to agent_5001, URLs point to prod backend. Idempotent provisioner: `scripts/create_hk_tools_safe.py` (`ELEVENLABS_API_KEY=… python3 scripts/create_hk_tools_safe.py <BASE_URL>`).
- conversation-init webhook URL set on the agent (`platform_settings.workspace_overrides.conversation_initiation_client_data_webhook`) with `X-HeyKiki-Secret` header.
- post-call: N8N HTTP node forwards the raw payload to `/api/elevenlabs/post-call`. Verified working.

## Frontend — built screens (all wired to real data, design tokens in `frontend/tailwind.config.js` + `src/index.css`)
- **Shell:** collapsible sidebar (German nav, grouped Aufträge/Finanzen, Kiki-Zentrale, profile menu), topbar (search, EN/DE, dark/light). `src/components/layout/`.
- **Auth:** Supabase email/password + magic link; protected routes. `src/auth/`.
- **Dashboard** (`/`): tab bar; Overview tab live (KPIs, open tasks, upcoming appts). Other tabs stubbed.
- **Call Logs** (`/calls`): 3-pane (list ← Realtime, transcript center with audio-on-demand, right panel with **Aktionen/Details/Verlauf** tabs). Actions: assign employee, status (incl. reopen), edit (Process modal), create appointment (Kunde/Privat tabs), delete. Details: collapsible summary, de-duped contact cards, customer→profile redirect. Verlauf: durchgeführte Aktionen + Termine + KVAs.
- **Customers list** (`/customers`): search, color-coded filter tabs with counts, cards with stats, + Neuer Kunde modal.
- **Customers detail** (`/customers/:id`): header + edit/delete modal, Anfragen (expandable) / Projekte tabs, Termine, activities timeline, Fotos/Dokumente with drag-drop upload to Storage. + Neue Anfrage / + Neuer Termin modals.

## Remaining work (priority order suggested)
1. **Kalender** (`/calendar`) — appointment calendar (week/month), status colors. Endpoint to add: `GET /api/appointments?from=&to=`.
2. **Aufträge**: Projekte + Planungstafel (kanban). Planungstafel also holds the future **inventory** (vehicles/tools) referenced in the appointment modal placeholder.
3. **Finanzen**: Kostenvoranschläge (KVA — the "bald" buttons), Rechnungen, Katalog. KVA generation + PDF.
4. **Mitarbeiter** (employees CRUD), **Kiki-Zentrale** (agent_configs editor → pushes to ElevenLabs), **Settings** (Personal/Company), remaining Dashboard tabs (Calls/Finance/Time/AI).
5. Polish: CSV import/export + multi-select on Customers list (currently disabled "bald"); Maps distance (currently `— km`); deploy the frontend (Vercel).

## Known limitations / deferred (intentional)
- queryKnowledgeBase returns a graceful "no info" (no KB store yet).
- transferCall returns the configured forwarding number but does not trigger Twilio yet.
- Appointment created from a call with no matched customer is unlinked (only happens for no-Caller-ID test calls; prod Twilio calls carry Caller-ID).
- KVA/cost-estimate, invoices, projects, inventory not built.

## Working style that worked well
Build one screen at a time, verify in the browser via the Preview MCP (login `kikitest01@gmail.com`), then deploy backend via Railway CLI and confirm the prod route. Keep `backend/tests/` green.
