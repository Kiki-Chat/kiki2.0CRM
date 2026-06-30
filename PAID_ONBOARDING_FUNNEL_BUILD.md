# Paid Onboarding Funnel — Execution Plan (in-house, replaces n8n)

_Authored 2026-06-30. Supersedes the "out-of-repo funnel" assumption in
`STRIPE_ONBOARDING_AND_MIGRATION_SPEC.md` and the "n8n owns the chain" assumption in
`ONBOARDING_ORCHESTRATION_SPEC.md`. Those two specs are still the source of truth for the
data-model shapes and the money-safety doctrine; this doc is the **build order** that brings
the whole chain in-house._

## 0. Decisions locked (Amber, 2026-06-30)

| Decision | Choice |
|---|---|
| **Scope of this build** | **New funnel only.** Defer Sheets→DB migration + legacy ~80-customer migration to later phases. |
| **Payment model** | **Charge immediately** at Stripe Checkout (no trial). Calendly = "try before buy". |
| **Pricing / interval** | Deployed catalog: **Basis €99 / Pro €249 / Enterprise €599**, net + 19 % MwSt, annual = 2 months free (10×). `Kiki Legacy` hidden (`self_serve=False`). |
| **Provisioning** | **Fully in-house** backend orchestrator: create EL agent → assign Twilio number (reuse idle DB-pool number first, buy a fresh +49 local only if none) → provision CRM. **n8n removed from the live path.** |

**Defaults chosen for the remaining small questions** (override any of these):
- Funnel lives as **public, no-auth routes inside this repo's `frontend/`** (shares the green theme + the Stripe/provision backend + one deploy). "Start" on the marketing site (`heykiki.de`) links into it.
- **One** combined onboarding email from us (welcome + login link + Kiki number + forwarding how-to). **Stripe sends its own receipt + invoice email** — we never duplicate it.
- Login uses a **set-your-password / magic link** (Supabase) instead of mailing a plaintext password (the old n8n `changeme123`).
- Demo widget is **removed** from the funnel; the demo is the **Calendly** booking on the payment page (`https://calendly.com/kiki-chat/einrichtung-der-testphase-von-heykiki`).
- "Sign in with Google" is **in scope** (Phase G) — small, rides on Supabase Auth.

## 1. End-to-end flow

```
heykiki.de "Start"
      │
      ▼  (public, no auth, this repo)
┌─────────────────────────────────────────────────────────────┐
│ STEP 1  Onboarding form (fonio-style, green theme)           │
│   Q1 Gewerk (dropdown, 18 trades)  Q2 Name  Q3 Firma         │
│   Q4 Email (dup-check)  Q5 Telefon (auto country+flag)        │
│   Q6 Passwort (+confirm, show-toggle, ≥8)                     │
│   POST /api/onboarding/start  ──►  onboarding_leads row       │
├─────────────────────────────────────────────────────────────┤
│ STEP 2  Plan picker (Basis / Pro / Enterprise, monat/jahr)   │
│   teases features; Calendly "Demo buchen" CTA                 │
│   POST /api/onboarding/checkout  ──►  Stripe Checkout URL     │
├─────────────────────────────────────────────────────────────┤
│ STEP 3  Stripe Checkout (hosted, prefilled name/email/phone) │
│   billing address + VAT id collected HERE → mirrored to CRM  │
└─────────────────────────────────────────────────────────────┘
      │  checkout.session.completed  (Stripe → our webhook, signature-verified)
      ▼
backend webhook: dedupe (event id + onboarding_events.checkout_session_id)
      │  read lead via client_reference_id → schedule BACKGROUND orchestration → 200
      ▼
ORCHESTRATOR  (idempotent, staged in onboarding_events)
  1. create ElevenLabs agent (from template, org name + trade)   stage=agent_created
  2. allocate Twilio number (reuse idle pool → else buy +49) +
     bind to EL agent                                            stage=number_assigned
  3. provision_org(...) → org + org_admin user + agent_configs +
     link stripe_customer_id + plan + address + phone + trade    stage=provisioned
  4. send ONE onboarding email (login link + number + how-to)
  5. mark lead converted
      ▼
Customer logs in → plan is live, menus match plan, Stammdaten pre-filled,
Abrechnung shows the subscription + invoice. Stripe sent the receipt separately.
```

## 2. Scope

**In scope (this build):** public funnel UI (3 steps), `onboarding_leads`, no-org checkout endpoint, webhook lead-branch, in-house orchestrator (EL create + Twilio allocate/bind + provision), `twilio_numbers` DB pool, one onboarding email, Stripe↔org linkage, "Sign in with Google".

**Sheets↔DB sync — BUILT 2026-06-30 (inert until creds), DB is canonical:**
- `migration 0098` = `final_client_export` VIEW (org+agent_configs → the Final-Client columns; `org_id` replaces CD Project ID, static `crm.kikichat.de/login`). Applied UAT.
- `app/services/sheets_sync.py` + `routes/sheets_sync.py` (master-secret, mounted when `SHEETS_SYNC_ENABLED`): `import_twilio_pool` (Sheets→DB seed of the legacy pool, upsert on phone_number), `mirror_twilio_pool` + `mirror_final_clients` (DB→Sheets read-only mirror for non-tech staff). Google libs (gspread/google-auth) lazy-imported → app runs without them; in `requirements.txt`.
- Config: `SHEETS_SYNC_ENABLED`, `GOOGLE_SERVICE_ACCOUNT_JSON` (content or path), `TWILIO_POOL_SHEET_ID`, `FINAL_CLIENT_SHEET_ID`.
- **Still need from Amber:** a Google service account with read+write on both sheets + the live sheet ids (`twilio_pool` = `1RMNYg_…`). Then: `POST /api/sheets/import/twilio-pool` to seed the real pool, and the funnel assigns real numbers — **this is the UAT-ready path** (no throwaway). The sheet is a one-way mirror; editing it never affects the DB.

**Deferred (later phases, acknowledged):**
- **Legacy ~80-customer migration** onto `Kiki Legacy` (link, don't re-bill) — per `STRIPE_ONBOARDING_AND_MIGRATION_SPEC.md` §3. (The `import_final_clients` direction = org-creation-from-sheet is part of this and intentionally not built yet.)

### 2.1 Deferred-mirror sheet formats (received 2026-06-30)

**Final Client Sheet** (Workflow-C source-of-truth → becomes a read-only export/view of `organizations` + `agent_configs`). Two column changes vs the old ChatDash sheet: **`CD Project ID` → the org id (uuid we assign at provision)**, and **`CD Dashboard Link` → static `crm.kikichat.de/login`**. Mapping:

| Sheet column | DB source |
|---|---|
| Client name | `organizations.name` (or admin `users.full_name`) |
| Voice Agent Number | `organizations.phone_number` (the assigned Kiki/Twilio number) |
| Email | `organizations.email` |
| ~~CD Project ID~~ → **Org ID** | `organizations.id` (uuid) |
| ~~CD Dashboard Link~~ → **Dashboard** | static `crm.kikichat.de/login` |
| Client Phone Number | `organizations.existing_business_number` (their own line) |
| Agent ID | `organizations.elevenlabs_agent_id` |
| Emergency Number | `agent_configs.emergency_service` forwarding number |

→ **No new schema needed** for this sheet; it's a projection over existing columns. The mirror writer (Phase 2) just `appendOrUpdate`s a row per org keyed on Org ID.

**Twilio Pool sheet** → already mapped 1:1 onto `twilio_numbers` (§3, migration `0089`). Sample row confirms shapes: `Phone_number` E.164 like `+4925197593212`, `Eleven_phone_id` like `phnum_…`, `Assigned_agent_id` like `agent_…`, `Status` ∈ Idle/Reserved/Assigned, `Notes` like `twilio,inbound=true,outbound=true`.

## 3. Data model — additive migrations (onboarding = `0093`–`0096`)

> **STATUS (2026-06-30):** Files `0093`–`0096` written to `supabase/migrations/` AND applied to **UAT** (`ifbluvdcbcesuhvkxsfn`) — verified present. Idempotent (`IF NOT EXISTS`).
> **Numbering:** prod `0086`–`0092` are the **Employee↔Technician redesign** (separate track; applied ad-hoc via MCP to **prod only** — not in repo, not in UAT). So onboarding takes `0093`–`0096`. `0086`–`0089` are left free for the technician track to commit.
> **⚠️ APPLY TO PROD before go-live:** prod does NOT yet have these onboarding objects — apply `0093`–`0096` to prod (`xjgtqannrpksvtdxwryr`, not MCP-reachable from here) before flipping `ONBOARDING_ENABLED`. (UAT already has the technician `0086`–`0092` too — verified 2026-06-30: `departments`, `appointment_jobs`, `employees.worker_kind`, `users.role`+`technician`, etc. — built on the technician branch; prod has them per Amber. So both tracks coexist 0086–0096.)

All pure `ADD COLUMN` / `CREATE TABLE` (pre-authorized; applied to UAT Supabase `ifbluvdcbcesuhvkxsfn` via MCP). Backend-only tables get **RLS on, no client policy** (mirrors `billing_*` / `org_secrets`).

- **`0093_org_onboarding_status.sql`** — `organizations ADD COLUMN onboarding_status text` (`pending|provisioning|active|failed`). Set by the orchestrator; surfaced in super-admin.
- **`0094_onboarding_leads.sql`** — pre-payment lead (org does not exist yet):
  `id uuid pk, token text UNIQUE (= Stripe client_reference_id), company_name, contact_name, email, phone, billing_address jsonb, trade text, plan_title text, interval text, stripe_session_id text UNIQUE, stripe_customer_id text, org_id uuid NULL REFERENCES organizations(id) ON DELETE SET NULL, status text DEFAULT 'created' CHECK (created|converted|abandoned), created_at, updated_at.`
- **`0095_onboarding_events.sql`** — per-stage idempotency/audit (mirror `billing_webhook_events`):
  `id uuid pk, checkout_session_id text UNIQUE NOT NULL, lead_id uuid NULL, org_id uuid NULL, stage text CHECK (dispatched|agent_created|number_assigned|provisioned|failed), payload jsonb, error text, created_at, updated_at.`
- **`0096_twilio_numbers.sql`** — replaces the `twilio_pool` Google Sheet (sheet col → table col):
  `id uuid pk, phone_number text UNIQUE NOT NULL (E.164), eleven_phone_id text (=EL phone_number_id), status text DEFAULT 'idle' CHECK (idle|reserved|assigned), session_id text (reserving checkout session/token), assigned_agent_id text (EL agent id), org_id uuid NULL, label text, twilio_sid text (for release), notes text, last_updated timestamptz, created_at.` Index `(status)` for pool pick; partial-unique on active assignment.

_(Skipping `entitlement_overrides` — only needed for the deferred legacy migration.)_

## 4. Backend

### 4.1 Config additions (`app/core/config.py`)
- `el_template_agent_id: str = ""` (`EL_TEMPLATE_AGENT_ID`) — the demo/template agent to clone.
- `twilio_purchase_enabled: bool = False` (`TWILIO_PURCHASE_ENABLED`) — arms the **buy** path; ships inert (reuse-only) until set.
- `twilio_number_area_default: str = "+49251"` (`TWILIO_NUMBER_AREA`) — Münster local default (matches old workflow).
- `onboarding_enabled: bool = False` (`ONBOARDING_ENABLED`) — gates the whole public funnel + webhook lead-branch so it ships inert.
- Reuse existing: `elevenlabs_api_key`, `twilio_account_sid/auth_token`, `master_webhook_secret`, `frontend_public_url`, `brevo_*`, `stripe_*`.

### 4.2 New service `app/services/onboarding_provision.py` (the in-house orchestrator)
- `create_agent_from_template(org_name, trade) -> agent_id` — POST EL `/v1/convai/agents/create` cloning `EL_TEMPLATE_AGENT_ID` (mirror the n8n `Create Agent Generator` config: voice, first message, German master prompt with `{{company}}`/`{{trade}}`, `data_collection` vars, post-call webhook). Reuse `agent_config.patch_agent_safely` for the follow-up PATCH.
- `allocate_twilio_number(session_id, agent_id, *, area=TWILIO_NUMBER_AREA) -> {phone_number, eleven_phone_id, twilio_sid}` —
  1. `twilio_numbers` SELECT `status='idle'` → reserve (`status='reserved', session_id`) — **DB pool reuse first**.
  2. else if `TWILIO_PURCHASE_ENABLED`: Twilio `AvailablePhoneNumbers/DE/Local` (Contains=area) → `IncomingPhoneNumbers.create` (with the existing `AddressSid`/`BundleSid` from the n8n flow) → insert row.
  3. register with EL `/v1/convai/phone-numbers` (twilio sid+token) → capture `eleven_phone_id`; PATCH it to bind `agent_id`; set row `status='assigned', assigned_agent_id`.
  - **Idempotent on `session_id`**: if a number is already reserved/assigned for this session, return it (no second buy).
- `onboard(lead, checkout_session) -> org_id` — staged, each stage writes `onboarding_events`:
  agent → number+bind → `provision_org(ProvisionRequest(elevenlabs_agent_id, elevenlabs_phone_number_id, phone_number, address, trade, login_email, login_password=<random>, org_name, admin_name, stripe_customer_id, plan_title))` → email. Because the number is bound **before** `provision_org`, the default `configure_agent` path finds the bound phone and succeeds (no `agent_externally_managed` needed).

### 4.3 `ProvisionRequest` + `provision_org` (additive)
- Add `stripe_customer_id` / `plan_title` to `app/schemas/provision.py` and write them onto the `organizations` insert in `provisioning.py:120` (`stripe_customer_id`, `billing_plan_title`), and set `onboarding_status='active'`. Everything else (`address`, `phone_number`, `trade`, EL agent) is already supported. This makes the very first `/api/billing/summary` read "configured".

### 4.4 Public endpoints `app/api/routes/onboarding.py` (no auth; rate-limited; gated by `ONBOARDING_ENABLED`)
- `POST /api/onboarding/check-email` → `{available: bool}` (Q4 dup-check against `users.email` + open leads).
- `POST /api/onboarding/start` → validates form, inserts `onboarding_leads` (status `created`), returns `{token}`.
- `POST /api/onboarding/checkout` `{token, plan_title, interval}` → builds a Stripe Checkout **without an org**: `client_reference_id=token`, customer prefilled (name/email/phone), `automatic_tax`, `billing_address_collection=required`, `tax_id_collection`, `phone_number_collection`, base+metered line items via `find_plan_prices`, **no trial**, `success_url`/`cancel_url` → funnel. Stores `stripe_session_id` on the lead. _(New no-org variant beside the existing org-scoped `create_checkout_session`; the existing one is untouched.)_

### 4.5 Stripe webhook lead-branch (`app/services/stripe_webhook.py`)
- In `_handle_checkout_completed`: if the session has **no org** (look up `onboarding_leads` by `client_reference_id`) → record `onboarding_events(checkout_session_id, stage='dispatched')`, then `BackgroundTask(onboard, lead, session)`; return 200 fast (Stripe needs a quick ack — heavy work runs in background, exactly like the `/provision` route schedules `import_agent_history`). Existing org-link path unchanged. Dedup: `billing_webhook_events.stripe_event_id` UNIQUE **and** `onboarding_events.checkout_session_id` UNIQUE → Stripe retries never double-provision.
- `customer.subscription.*` / `invoice.*` then sync as today onto `organizations.billing_*`.
- Add a tiny **retry sweep** (`POST /api/super-admin/onboarding/retry/{checkout_session_id}`, master/super-admin) that re-runs `onboard` from the last failed stage using `onboarding_events`.

### 4.6 Onboarding email (`app/services/billing_notifications.py` + `email_send.py`)
- New `notify_crm_account_created(org_id, login_url, phone_number, agent_id)` → one HTML email (reuse the green-gradient template already in the n8n nodes; sender via existing `send_email()` 3-tier Brevo chain; `dedup_key=onboarding:<session>`). Content: willkommen + **set-password/login link** (`{frontend_public_url}` Supabase magic/reset link) + Kiki number + forwarding how-to (FRITZ!Box video + GSM codes, from the old Twilio email) + Calendly. **Replaces** the current generic welcome at `stripe_webhook.py:384` for the lead-branch path. Stripe still owns receipt/invoice.

## 5. Frontend — public funnel (`frontend/src/pages/onboarding/`)

Green theme tokens from the brand swatch: `brand #81C264`, `primary #4A9B3F`, `deep #2D6B3D`, `tint-200 #C8E3B8` (org default `accent_color` is already `#81C264`). German UI only. Public routes added to `App.tsx` **outside** the auth-required wrapper (auth today = Supabase `AuthProvider`; the funnel needs none). API base = existing `VITE_API_URL`.

- `OnboardingLayout` — fonio split layout: left = form/steps, right = testimonial/brand panel.
- **Step 1 `SignupForm`** — the 6 questions:
  - Q1 **Gewerk** dropdown (the 18 trades: Dachdecker, Zimmerer, Tischler, Hausmeisterservice, Gebäudereiniger, KFZ-Mechaniker, SHK-Installateure, Elektrotechniker, Maler und Lackierer, Klempner, Fliesenleger, Maurer, Garten- und Landschaftsbauer, Solarteur, Schlosser, Isolierer, Raumausstatter, Hausverwalter).
  - Q2 Name · Q3 Firmenname.
  - Q4 **Email** — format + **async dup-check** (`/check-email`, debounced) → "Diese E-Mail ist bereits registriert".
  - Q5 **Telefon** — `libphonenumber-js` + a country-select with flags; **auto-detect country** from browser locale (`navigator.language`) / IP fallback; validate E.164.
  - Q6 **Passwort** + **confirm** + show/hide toggle; "Mindestens 8 Zeichen"; mismatch guard.
  - → `/start` → `{token}` held in funnel state (sessionStorage) → Step 2.
- **Step 2 `PlanPicker`** — 3 cards (Basis/Pro/Enterprise) from `GET /api/billing/plans` (live catalog, no hardcoded prices), monthly/annual toggle ("2 Monate gratis"), Pro = "Empfehlung", per-card feature lists, "30 Tage Geld-zurück", **Calendly "Demo buchen"** CTA. → `/checkout` → `window.location = url`.
- **Step 3** — redirect to Stripe; `success_url` → `/onboarding/success` ("Zahlung bestätigt — wir richten Kiki ein, Login-Mail folgt"), `cancel_url` → back to plan.

## 6. "Sign in with Google" (Phase G — rides on Supabase Auth)

Auth is Supabase (`signInWithPassword`/OTP via `AuthProvider`); `provision_org` already creates the Supabase user with `email_confirm=True`. So:
1. **Amber (Supabase dashboard):** enable the **Google** auth provider (reuse the `GOOGLE_CLIENT_ID/SECRET` from `P1.8_OAUTH_SETUP.md`; add Supabase callback URL); turn on **"Link accounts with the same email"**.
2. **Frontend:** add a "Mit Google anmelden" button on `LoginPage.tsx` → `supabase.auth.signInWithOAuth({ provider:'google', options:{ redirectTo } })`. The existing `AuthProvider` picks up the returned session automatically.
3. **Orphan guard:** after OAuth login the app calls `/api/me`; if the Supabase user has **no `users`/org row** (i.e. never provisioned), sign them out with "Kein Konto gefunden — bitte zuerst registrieren." → prevents random Google self-signup from creating orgless access. (No self-serve signup via Google; access stays provision-only.)

## 7. Money- & identity-safety checklist (the user's "don't dent reputation" requirement)

- **Org created only after `checkout.session.completed`** — no orphan paid-but-no-account or account-but-no-pay. Pre-payment key = `onboarding_leads.token` (= `client_reference_id`), never an org id.
- **Idempotency end-to-end**, all keyed on the checkout session: webhook dedup (`stripe_event_id` UNIQUE) + `onboarding_events.checkout_session_id` UNIQUE + Twilio allocation keyed on `session_id` (no double-buy) + `provision_org` 409 dedup on `heykiki_org_id`/email. Stripe retries / re-runs are safe.
- **Payer == account == billing**: `customer.email` (payer) = login email = org contact; phone → `organizations.phone_number`; `stripe_customer_id` + `billing_subscription_id` + `billing_plan_title` written at provision → first `/summary` is correct.
- **Address parity**: billing address from Stripe Checkout → `organizations.address` (jsonb) so Stammdaten + invoices match what they paid with.
- **Right menus**: `billing_plan_title` set at provision → `/api/me` returns that plan's `features` → nav soft-gates correctly immediately (hard 402 enforcement still flips at the org-wide `ENTITLEMENTS_ENFORCED` cutover, unchanged).
- **Failure is visible + retryable**: any stage failure → `onboarding_events.stage='failed'` + `organizations.onboarding_status='failed'`; super-admin retry endpoint resumes. Email send is best-effort and never blocks provisioning.
- **Ships inert**: `ONBOARDING_ENABLED=0` + `TWILIO_PURCHASE_ENABLED=0` until the funnel + EL template + Stripe live-webhook are ready. Local = UAT; **no `railway up` without Amber's approval**; test-key-only until go-live (per `STRIPE_PHASE2_HANDOVER.md`).

## 8. Build sequence (each phase independently verifiable)

| # | Phase | Where | Verify |
|---|---|---|---|
| 1 | Migrations 0093–0097 ✅ DONE (UAT) | `supabase/migrations` | applied + verified on UAT 2026-06-30; **apply to prod before go-live** |
| 2 | Twilio number service (pool reuse; buy gated) ✅ BUILT | `onboarding_provision.py` | import-verified; live buy/bind NOT run (creates real resources) |
| 3 | EL agent create ✅ BUILT | `onboarding_provision.py` | import-verified; live create NOT run |
| 4 | `provision_org` + `ProvisionRequest` Stripe linkage ✅ DONE+VERIFIED | `provisioning.py`, `schemas/provision.py` | ProvisionRequest accepts stripeCustomerId/planTitle; 117 tests green |
| 5 | Public endpoints (`/plans`,`/check-email`,`/start`,`/checkout`,`/retry`) ✅ DONE+VERIFIED | `routes/onboarding.py` | e2e on UAT+Stripe test: lead→checkout URL `cs_test_…`, lead linked, cleaned up |
| 6 | Webhook lead-branch + background `onboard` + retry ✅ BUILT | `stripe_webhook.py`, `onboarding_provision.py` | import-verified + mounted; live onboard NOT run |
| 7 | Onboarding email ✅ BUILT | `onboarding_provision.py` (`_send_welcome_email`) | uses generate_set_password_link + render_email; live send NOT run |
| 8 | Funnel UI (3 steps, green theme) ✅ DONE+VERIFIED | `frontend/src/pages/onboarding/*`, `lib/onboardingApi.ts` | `tsc -b` clean; preview render proof of /onboarding (6-Q form), /onboarding/tarif (LIVE catalog), /onboarding/success; 0 console errors |
| 9 | Google sign-in button + orphan guard ✅ DONE+VERIFIED | `AuthProvider.tsx`, `LoginPage.tsx`, `ProtectedRoute.tsx` | `signInWithGoogle` + button + register link rendered; orphan guard (org_id null & !super_admin → "Kein Konto gefunden") in ProtectedRoute |

Recommended order **1→4→2→3→5→6→7→8→9**. **ALL PHASES (1–9) DONE + verified 2026-06-30** (backend: 117 focused tests green + funnel checkout proven on UAT+Stripe-test; frontend: tsc -b clean + preview render proof). All inert behind `ONBOARDING_ENABLED`/`TWILIO_PURCHASE_ENABLED`. ONLY the Google-Sheets mirror is deferred (awaiting sheet access). **Remaining for go-live (not code):** apply `0093–0097` to prod; enable the Supabase Google provider + "link same email"; set `ONBOARDING_ENABLED=1` (+ `TWILIO_PURCHASE_ENABLED=1` once Twilio Address/Bundle SIDs set) on prod; run one deliberate live EL/Twilio onboard on the test org. No prod deploy without approval.

## 9. Inputs needed from Amber (non-blocking for Phases 1–9 build start)
- `EL_TEMPLATE_AGENT_ID` (which existing agent to clone) + confirm the EL workspace post-call webhook id to attach.
- Confirm Twilio `AddressSid`/`BundleSid` to reuse for purchases (the n8n flow used `AD880…`/`BU24d…`).
- Sender/Reply-To for the onboarding email (email-send is Amber's track) — default Brevo `info@kiki-zusammenfassung.de` / Reply-To `info@kikichat.de`.
- Enable the Supabase Google provider + "link same email" (Phase G).
- **For deferred Phase 2:** the Workflow-C Google Sheet + the `twilio_pool` sheet id.
