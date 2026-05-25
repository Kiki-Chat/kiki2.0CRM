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
6. **Local backend runs WITHOUT `--reload`** — after editing backend code you MUST restart uvicorn, or new/changed routes return 405/stale. Restart: `pkill -f "uvicorn app.main:app"; cd backend && nohup ./.venv/bin/uvicorn app.main:app --port 8000 --host 127.0.0.1 >/tmp/kiki_backend.log 2>&1 &`
7. **PDF generation uses `fpdf2` + bundled DejaVu fonts** (`backend/app/assets/fonts/`), NOT WeasyPrint — WeasyPrint can't load system libs (libgobject) on macOS/Railway. fpdf2 is pure-Python, zero system deps. Core fonts can't render `€`, so DejaVu TTFs are committed in the repo.
8. **The Supabase MCP connector can go stale** (`net::ERR_FAILED` on every call). Supabase itself stays up (the backend reaches it fine). Fix: user reconnects the Supabase connector in Claude settings. Migrations are applied via the Supabase MCP `apply_migration`.
9. **Migrations are applied to the live DB via the Supabase MCP**, not a CLI. After writing a `supabase/migrations/00XX_*.sql` file, apply it with the MCP `apply_migration` tool (there is no `supabase` CLI installed).

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

## Database (Supabase) — migrations 0001–0011 applied
Base tables: organizations, org_secrets, users, customers, calls, inquiries, appointments,
cost_estimates, invoices, employees, agent_configs, catalog_items, ai_suggestions,
time_entries, documents. Storage bucket: `customer-files` (private).
RLS scoped by `org_id` (backend uses service role and bypasses RLS).

New since 0007 (all applied via Supabase MCP):
- **0008** employee mgmt: `employees.{email,access_role,vacation_days_per_year,remaining_vacation_days,hourly_rate,activity_area,auto_assign,calendar_color,deleted}`; new table **employee_absences** (type/starts_at/ends_at/all_day/reason/internal_note).
- **0009** planning board: new tables **vehicles** + **tools** (assets); `appointments.{vehicle_id,tool_id}`.
- **0010** cost estimates: `cost_estimates.{type,subject,reference_number,is_binding,tolerance_pct,validity_days,inquiry_id,intro_text,closing_text,payment_terms,surcharge,surcharge_description,total_discount_pct,vat_amount,accepted_at,rejected_at,invoice_id,created_by,updated_at}` (reuses existing `number,status,line_items,subtotal,total,valid_until,sent_at`).
- **0011** catalog & templates: `catalog_items.{article_number,vat_rate,is_wage,purchase_price,supplier_id}` (price = existing `unit_price`); new table **text_modules** (name/category/content/sort_order/is_default); `vehicles.{vehicle_type,brand,tuev_until,insurance_until,next_maintenance,max_weight_kg,cargo_space_m3,status}`; `tools.{condition,next_maintenance,purchase_date,purchase_price}`.
- **0012** invoices (Rechnungen): brought the pre-existing `invoices` table (from 0001) to KVA-parity + invoice fields: `subject,reference_number,invoice_date,performance_date,payment_terms_days,discount_pct,discount_days (Skonto),intro_text,closing_text,payment_terms_text,surcharge(+description),total_discount_pct,vat_amount,sent_at,cancelled_at,created_by,updated_at`. **Reuses existing `subtotal`(net)/`total`(gross)/`cost_estimate_id`(KVA link)** for consistency with cost_estimates (API exposes the link as `kva_id`). Unique index `(org_id,number)`. Relaxed `cost_estimates_status_check` to also allow `'invoiced'`.
- Earlier added columns (0003–0006): `inquiries.number`, `calls.{agent_id,caller_number,summary_title,data_collection}`, `inquiries/appointments.assigned_employee_id`, `appointments.color`, `customers.{customer_type,vat_id,notes,status}`.

## Backend endpoints (FastAPI, all under prod URL)
- Health/util: `GET /health`, `GET /api/me`
- Provisioning: `POST /api/heykiki/provision` (master secret)
- ElevenLabs **tools** (10, all implemented): `POST /api/elevenlabs/tools/{identify-customer, update-customer, create-inquiry, get-available-slots, create-appointment, cancel-appointment, change-appointment, search-inquiries, query-knowledge-base, transfer-call}` — org resolved by `X-HeyKiki-Secret` or `_agentId`.
- `POST /api/elevenlabs/conversation-init` (returns dynamic_variables; wired on the agent).
- `POST /api/elevenlabs/post-call` (N8N → backend; secret `hk_sso_test_…`; idempotent on conversation_id; stores transcript/summary/data_collection; links/creates customer; Realtime broadcast `org:{org_id}:calls`).
- CRM: `GET /api/dashboard/overview`; `GET /api/calls`, `GET /api/calls/{id}`, `GET /api/calls/{id}/audio`, `POST /api/calls/{id}/inquiry`; `GET/POST /api/customers`, `GET/PATCH/DELETE /api/customers/{id}`, `GET/POST /api/customers/{id}/documents`; `POST /api/inquiries`, `PATCH /api/inquiries/{id}`.
- Appointments: `GET /api/appointments?from=&to=`, `POST /api/appointments`, `PATCH /api/appointments/{id}` (accepts vehicle_id/tool_id/status/etc.), `POST /api/appointments/import-ics`.
- Calendar settings: `GET /api/calendar/settings`, `PUT /api/calendar/business-hours` (stored in `agent_configs.scheduling.business_hours`; `get_available_slots` honors them).
- Employees: `GET /api/employees` (enriched: email/role/login/presence/vacation), `POST` (Supabase invite), `PATCH/DELETE /{id}`, `POST /{id}/resend-invite`, `POST /{id}/set-password`, `GET/POST /{id}/absences`, `GET /api/employees/absences` (org-wide, ?from=&to=).
- Planning board: `GET /api/planning-board?date=`; vehicles `GET/POST/PATCH/DELETE /api/vehicles` (list returns last_seen/next_appointment/in_use_today); tools `GET/POST/PATCH/DELETE /api/tools`. NOTE: the tools route module is `app/api/routes/tool_assets.py` (the `tools/` dir is the ElevenLabs voice tools — name collision).
- Cost estimates (KVA): `GET/POST /api/cost-estimates`, `GET/PATCH/DELETE /{id}`, `GET /{id}/pdf[?preview=true]` (fpdf2), `POST /api/cost-estimates/preview` (live PDF), `POST /{id}/send`, `POST /{id}/duplicate`, `PATCH /{id}/status`. PDF builder: `app/services/cost_estimates.py`.
- Catalog & templates: `GET/POST /api/catalog`, `PATCH/DELETE /{id}`, `GET /api/catalog/export` (CSV), `POST /api/catalog/import` (CSV), legacy `GET /api/catalog-items`; `GET/POST /api/text-modules`, `PATCH/DELETE /{id}`, `GET /api/text-modules/defaults` (one default per category for KVA autofill).
- Invoices (Rechnungen): `GET/POST /api/invoices`, `GET/PATCH/DELETE /{id}` (delete draft-only), `GET /{id}/pdf[?preview=true]`, `POST /api/invoices/preview` (live PDF), `POST /{id}/send`, `POST /{id}/duplicate`, `PATCH /{id}/status` (paid|cancelled|draft|sent). List **derives `overdue`** from due_date (not stored). Numbering `RE-YYYY-#####`. Creating with `kva_id` links the source KVA (sets `cost_estimates.invoice_id` + status `invoiced`). PDF reuses the KVA engine: `app/services/cost_estimates.py build_pdf(type="invoice")` (RECHNUNG meta block + 3-col Bankverbindung/Geschäftsführung/Steuernummer footer from `org.bank_details`/`org.tax_info`); numbering/date helpers in `app/services/invoices.py`. Routes: `app/api/routes/invoices.py`.

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
- **Customers detail** (`/customers/:id`): header + edit/delete modal, Anfragen (expandable) / Projekte tabs, Termine, activities timeline, Fotos/Dokumente with drag-drop upload to Storage. + Neue Anfrage / + Neuer Termin modals. "Kostenvoranschlag erstellen" → `/cost-estimates/new?customer_id=`.
- **Kalender** (`/calendar`): FullCalendar (month/week/day/list, German locale), events color-coded by employee + filter dropdown, create-on-slot-click modal, event detail modal, ICS import, Geschäftszeiten sub-page (`/calendar/business-hours`). Reads `?employee=` to preset the filter. Built on `@fullcalendar/*`. (Deferred: Blocked times + public holidays.)
- **Mitarbeiter** (`/employees`): tabs Mitarbeiter (table + new/edit/absence/permissions/password modals, invite) · Übersicht (absence cards + Urlaubstage table) · Kalender (FullCalendar of absences) · Anträge (empty state). `EmployeesPage.tsx`.
- **Planungstafel** (`/planning-board`): date strip, Fahrzeuge + Werkzeug columns with **drag-and-drop** assignment (`@dnd-kit`), asset column 3-dot menu (edit/assign employee/show in calendar/deactivate), asset modals, Timeline (Gantt) view, employee/status filter. `PlanningBoardPage.tsx`.
- **Kostenvoranschläge** (`/cost-estimates`): list (filter + summary + status pills + actions) · create/edit form (`/cost-estimates/new`, `/:id`) with **live PDF preview**, positions (catalog quick-select, drag-reorder, optional/subtotal/text), default-text autofill, URL-param autofill (customer_id/inquiry_id) · send modal. `CostEstimatesPage.tsx` + `CostEstimateFormPage.tsx`.
- **Katalog & Vorlagen** (`/catalog`): tabs Positionen (summary, filters, table w/ margin, new/edit modal, CSV import/export) · Textbausteine (list/empty + modal, default flag drives KVA autofill) · Fahrzeuge · Werkzeug (both reuse the same vehicles/tools data as Planning Board). `CatalogPage.tsx`.
- **Rechnungen** (`/invoices`): list (filter number/customer/status/year + 4-value Übersicht Entwürfe/Offen/Bezahlt/Storniert + **inline status dropdown** per row + actions preview/download/send/duplicate/mark-paid/cancel/edit/delete gated by status; overdue due-date in red) · create/edit form (`/invoices/new`, `/:id`) with **live PDF preview**, positions (catalog quick-select, dnd), Leistungsdatum + Zahlungsbedingungen (days → Fällig am) + Skonto, **"Aus KVA übernehmen"** dropdown + `?kva_id=` autofill, **"Erstellen & Rechnung senden"** (create+send) / "Nur erstellen" (draft) · send modal. KVA "In Rechnung umwandeln" now navigates to `/invoices/new?kva_id=`. `InvoicesPage.tsx` + `InvoiceFormPage.tsx`.

## Dependencies added this session
- Frontend: `@fullcalendar/{react,core,daygrid,timegrid,list,interaction}` (calendars), `@dnd-kit/{core,sortable,utilities}` (drag-and-drop).
- Backend: `fpdf2` (PDF) — in `requirements.txt`; bundled fonts in `backend/app/assets/fonts/DejaVuSans*.ttf`.

## Remaining work (priority order suggested)
1. ~~**Finanzen → Rechnungen** (invoices)~~ **DONE** — migration 0012 + full endpoints + `/invoices` list & create/edit form (live PDF preview) + KVA→Rechnung conversion (`/invoices/new?kva_id=`). See above.
2. **Projekte** (`/projects`) + **Project timeline**: needs a `projects` table (doesn't exist yet) — the calendar/planning Gantt for projects is blocked on this.
3. **Kiki-Zentrale** (`/kiki`): agent_configs editor → pushes to ElevenLabs. **Settings** (`/settings/personal`, `/settings/company`). Remaining **Dashboard** tabs (Calls/Finance/Time/AI) — all still `Placeholder`.
4. **Kalender**: Blocked times + auto public-holiday blocking (by Bundesland) — deferred earlier.
5. Polish: configure **Supabase SMTP / email templates** so employee invites + KVA send actually email (currently invite falls back to no-login + warning, and "set password" is the workaround); multi-select bulk actions on Customers; Maps distance (`— km`); deploy the **frontend to Vercel** (still local-only).

## Known limitations / deferred (intentional)
- queryKnowledgeBase returns a graceful "no info" (no KB store yet); transferCall returns the forwarding number but doesn't trigger Twilio.
- **Email not configured**: employee invite (`invite_user_by_email`), KVA `send` and invoice `send` don't actually email until Supabase SMTP/templates are set up. Invite gracefully creates a no-login employee + warning; use the 🔑 **set-password** action to give a working login. KVA/invoice `send` (incl. the invoice "Erstellen & Rechnung senden" button) just mark status='sent'.
- **Test data in the test org** (c4dbf596) from verification: extra employees (George Williams, Max Mustermann w/ absence), appointments ("Verifikationstermin", "UI-Klicktest", ICS imports, one assigned to REYB1998), KVAs (KVA-2026-00001..00005), vehicles (REYB1998, MP33XE0070), catalog items (5) + 2 default text modules. Harmless; clear if desired (no DELETE endpoint for appointments — use SQL/MCP).
- Projekte/projects table, Kiki-Zentrale, Settings not built. (**Rechnungen/invoices now built** — migration 0012.)
- Test org `c4dbf596` now has seeded **invoices** RE-2026-00001..00003 (paid/sent/draft) and its `name`/`address`/`bank_details`/`tax_info` were populated (Muster Heizungsbau GmbH, Münster) so the invoice PDF header+footer render fully. `org.bank_details` shape: `{account_holder,iban,bic,bank_name,managing_director}`; `org.tax_info` shape: `{vat_id,tax_number}` (the KVA PDF header now reads `tax_info.vat_id`).

## Working style that worked well
Build one screen at a time, verify in the browser via the Preview MCP (login `kikitest01@gmail.com`; if the preview session expires, ask Amber to log in — don't type passwords yourself). The preview **screenshot tool often returns stale/downscaled frames** — DOM/`preview_eval` reads are authoritative; prefer them. Restart the backend after edits (gotcha #6). Keep `backend/tests/` green. Commit per screen with an accurate message (only when Amber asks).
