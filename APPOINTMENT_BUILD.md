# Appointment outbound calls + emails — build notes

Running log for the appointment-epic build (CC builds, Amber approves). One section per item:
root-cause/design → fix → test → commit. Based on `APPOINTMENT_EPIC_FINDINGS.md` (read-only scan,
2026-06-01) and the live-code diagnosis below. HEAD at start = `d2a6155`.

**Standing safety:** prod = single shared Supabase, every write live. Every outbound call + email in
this epic is forced to the test scope (`+917879997839` / org `c4dbf596`) by a scope guard during the
build (see §S). Per-cluster commit; NO push / NO `railway up` without Amber's per-cluster go. Additive
migrations pre-authorized but flagged.

---

## Phase 0 — read-only diagnosis + design proposal (NO code) — AWAITING AMBER APPROVAL

### 0.1 Feasibility (verified live, read-only)
- Test org `c4dbf596` ("Muster Heizungsbau GmbH"): `elevenlabs_agent_id=agent_5001…py4` (SAFE),
  `elevenlabs_phone_number_id=phnum_1401…tm4` present → `place_outbound_call` can run.
- `agent_configs`: `outbound_enabled=false`, `outbound_occasions={"kva_followup":true}`,
  `appointment_reminder_days=1`. `pending_appts=0`, total 23, 17 customers w/ phone, 10 w/ email.
- UAT fixtures needed (pre-authorized test data in this org only): flip `outbound_enabled=true` +
  `outbound_occasions.appointment_reminder=true`; create one `pending` appointment with a
  phone+email customer.
- Safety grep: dangerous prod agent `agent_7201…` absent from code (only in SESSION_HANDOVER). ✅

### 0.2 What already exists (reuse, do not rebuild) — grounded in code
- **Outbound engine** — `services/outbound_dispatch.py`:
  - `OccasionSpec` frozen dataclass (`:527`): `key, anlass_typ, referenz_typ, table, columns, select,
    render, inquiry_id_of, case_gate, recurring, cooldown_*, max_cycles, org_flag, to_number_of`.
  - `OCCASIONS` registry + 7 wired occasions (`outbound_occasions.py:550`). Deferred comment at `:633`
    literally reserves `appointment_confirmation`.
  - `_dispatch_one` (`:217`) builds content + calls `place_outbound_call`; writes the `outbound_calls`
    ledger (cycle-aware idempotency) — **unless** `to_number_override` is set (UAT: cycle_no=1, no ledger).
  - `send_single_outbound(org_id, occasion, record_id, to_number_override, dry_run)` (`:452`) = the
    manual/click path. Fetches the record by id via `_fetch_record` (NOT `spec.select`), and **bypasses
    every gate** (window/weekday/occasion/case). This is the path the human click uses.
  - `place_outbound_call(agent_id, agent_phone_number_id, to_number, dynamic_variables,
    conversation_config_override)` (`outbound_call.py:30`) → ElevenLabs Twilio outbound. Already wired.
- **`build_call_content`** (`outbound_occasions.py:642`) → `{dynamic_variables, conversation_config_override}`.
  dynamic_variables = `outboundCallId, organisationId, anlassTyp, kundeId, kundenName, voicemailMessage,
  referenzTyp, referenzId`. override = `{agent:{first_message, language:"de", prompt:{prompt}}}`.
- **Appointment lifecycle** — `api/routes/appointments.py`:
  - `_confirm` (`:200`) pending→confirmed (+`confirmed_at`, clears `alternative_proposed_at`).
    **TODO at `:230`** explicitly reserves "customer notification" side-effects → our insertion point.
  - `_reject` (`:235`) pending→cancelled (+`rejected_at`,`rejection_reason`). = the action-card "Ablehnen".
  - `_propose_alternative` (`:269`) stores `alternative_start/end/note`+`alternative_proposed_at`,
    status stays pending. = the action-card "Alternative vorschlagen".
  - `_pending_for_call` (`:354`) → the single pending appt for a call's inquiry (powers the card).
  - `_cancel` (`:457`, Kalender "Stornieren") + `_delete` — separate, for confirmed appts; not the
    action-card path.
- **Agent reschedule tool** — `change_appointment` service (`services/appointments.py:394`): the
  `hk_changeAppointment` webhook does **not** apply a reschedule. It finds the customer's next upcoming
  appt and inserts an `inquiries` row `type="appointment_change", status="open"` with the new time **in
  free-text `notes` only** ("Wunschtermin neu: {iso}"), unlinked to the appt; returns
  `PENDING_CONFIRMATION` ("Sie werden zur Bestätigung kontaktiert"). → A counter-proposal already lands
  in the inbox, but notes-only + unlinked ⇒ not one-click-approvable yet.
- **Email** — `send_email(*, org_id, to_email, subject, body_html, body_text, attachments, cc, bcc,
  reply_to)` (`email_send.py:70`); 3-tier OAuth→SMTP→Brevo; empty-recipient fail-safe at `:88`.
  Renderer `email_templates.render_message_email(company_name, message_text, contact_email, address)`
  (`:82`). Trigger pattern to mirror = `invoices.py:320` / `cost_estimates.py:327` (subject+body_text →
  render → send_email to `customer.email`, `reply_to=org.email`). Customers have an `email` column.
- **Action-tab wiring** (frontend) — `CallLogsPage.tsx`: `AppointmentCard` confirm→`POST /confirm`,
  reject→`POST /reject`, propose-alt→`POST /propose-alternative` (body `{start_time,end_time,note}`);
  pending fetched via `GET /api/appointments/by-call/{id}/pending`. Invalidates
  `['pendingAppointment',callId]`,`['callInquiry',callId]`,`['dashboard','overview']`,`['customerDetail']`.
- **Cluster D data** — `direction` ("inbound"/"outbound", DB enum `0001:83`) already on the list
  (`calls.py:14`) and consumed by the card icon (`CallLogsPage.tsx:524`). Status shown = `inquiry_status`
  (open/in_progress/completed → Offen/In Bearbeitung/Abgeschlossen, `CallLogsPage.tsx:127`). Only a
  client-side search filter exists today (`:363`). **No API change needed** for Cluster D.

### 0.3 Design — Cluster A (occasions + human-click trigger)
1. **Three new `OccasionSpec`s** in `OCCASIONS` (no schema):
   - `appointment_confirmation` (anlassTyp `TERMIN_BESTAETIGUNG`, referenzTyp `Termin`)
   - `appointment_cancellation` (`TERMIN_ABSAGE`)
   - `appointment_reschedule` (`TERMIN_VERSCHIEBUNG`)
   Each: `table="appointments"`, `columns` extended to include
   `alternative_start_time, alternative_end_time, alternative_note, customer_proposed_start_time`;
   `case_gate="ignore"`; **`select=lambda …: []`** so the autonomous sweep can NEVER auto-dial them
   (brief: nothing fires on a state change — only the click). Belt-and-suspenders: their own occasion
   keys are never enabled in config either. New `render_*` fns producing German first_message /
   voicemail / task_block:
   - confirm: "…Ihr Termin am {datum} um {uhr} Uhr ist bestätigt."
   - cancel: "…Ihr Termin am {datum} um {uhr} Uhr wurde abgesagt."
   - reschedule: proposes `alternative_start_time`; task_block tells the agent — if the customer counters
     — to use `hk_getAvailableAppointments` (real slots) and `hk_changeAppointment` to record the agreed
     slot (no direct booking). **ABSENCE TODO** added here (availability is org-wide, ignores employee
     absence — deferred per brief, must not be silently forgotten).
2. **Human-click trigger** — extend `_confirm` / `_reject` / `_propose_alternative` to fire the matching
   occasion **after** the status mutation, via a new best-effort orchestrator
   `notify_appointment_outcome(org_id, appointment_id, occasion)`:
   - **Master-toggle gate** (NOT window/weekday — a human clicking at 9pm must still fire): a helper
     reads `agent_configs` and fires only when `outbound_enabled AND outbound_occasions["appointment_reminder"]`.
     If OFF → no call, no email (brief: the toggle is the sole master switch).
   - call = `send_single_outbound(occasion, record_id=appointment_id, to_number_override=<scope-guarded>)`.
   - email = the matching Cluster-B template (same scope guard).
   - **Non-blocking / non-fatal:** the status mutation already succeeded → return 200 regardless; the
     call/email result is surfaced in the response (`{appointment, outbound:{call, email}}`) and logged.
     A telephony failure never rolls back the click.
3. **Reschedule counter-slot → inbox → approval:**
   - Reschedule click → `propose-alternative` stores `alternative_*` (existing) + fires
     `appointment_reschedule` call+email proposing that time.
   - On the call, the agent lands on an agreed slot (the proposal, or a counter from real availability)
     and records it via the **existing** `hk_changeAppointment`. **[DECISION 1]** Recommended: enhance the
     `change_appointment` SERVICE to also stamp structured columns on the matched appointment
     (`customer_proposed_start_time`, `customer_proposed_at`, `customer_proposal_source='agent_call'`) +
     link the change-inquiry — **no new ElevenLabs tool, no agent write** (lowest risk). Alternative: add a
     dedicated `hk_proposeReschedule` agent tool (additive agent write, governed by the Kiki-Zentrale
     safety layer). Touching `change_appointment` is a behavior change to a LIVE inbound tool path
     (additive: it still creates the same inquiry + same return contract) — **flagged**.
   - The appointment now has `customer_proposed_start_time IS NOT NULL` → the action card shows
     "Kunde schlägt {time} vor — Genehmigen / Ablehnen".
   - **New approval endpoint** `POST /api/appointments/{id}/approve-proposal` (require_org): set
     `scheduled_at = customer_proposed_start_time`, `status='confirmed'`, `confirmed_at=now`, clear
     `customer_proposed_*`; then fire `appointment_confirmation` call+email (master-gated, scope-guarded).
   - Edge case (multi-upcoming-appt customer): `change_appointment` targets the next upcoming appt — an
     existing limitation; flagged, not fixed here.

### 0.4 Design — Cluster B (appointment email templates)
- New `services/appointment_emails.py` → `render_appointment_email(occasion, appointment, customer, org)
  -> (subject, body_html)`, German, built on the existing `render_message_email` shell (white-label
  header/footer already correct). Recipient = `customer.email`, `reply_to=org.email`. Same scope guard.
- Three bodies: confirmation / cancellation / reschedule (the reschedule email states the proposed time
  + that we'll call). Mirrors the invoice/KVA trigger exactly; reuses `send_email` transport untouched
  (Amber's email-send track unaffected — only triggering + templates, which the brief explicitly asks for).

### 0.5 Design — Cluster C (email on every outbound occasion)
- Add optional `email_render: Callable | None` to `OccasionSpec`. In `_dispatch_one`, after a successful
  call, if `spec.email_render` is set and the customer has an email, send it (best-effort, non-fatal,
  scope-guarded). One chokepoint serves both the sweep and the click.
- Wire `email_render` for all 3 new appointment occasions AND the existing 7 (reminder/kva/payment/
  satisfaction/review/maintenance/missed) — reusing the renderer.
- **GATED DEPLOY:** because this touches the 7 live occasions, the existing-7 email wiring builds now but
  its **deploy is gated** on Amber reviewing the diff (brief). The 3 appointment occasions are new, not gated.

### 0.6 Design — Cluster D (Call Logs colour + filters) — low-risk frontend, no separate gate
- Border by direction on the card outer div (`CallLogsPage.tsx:529`): **outbound → yellow, inbound →
  green**. Reconcile with existing green active-ring + green unread left-accent (proposal: full border
  by direction; keep unread as a left-accent bar + active as a ring/bg so no signal is lost). Render-prove.
- Filters added to the existing client-side `filtered` memo (`:363`), no backend change: **direction**
  (alle/eingehend/ausgehend) + **status** (alle/Offen/In Bearbeitung/Abgeschlossen via `inquiry_status`;
  handle null). Render proof for admin + employee views.

### 0.7 Safety scope guard (§S) — cross-cutting, every sending cluster
- New `services/outbound_scope.py`: env `OUTBOUND_TEST_SCOPE_ONLY` (**default ON**) + `OUTBOUND_TEST_NUMBER`
  (`+917879997839`) + allowed test org(s) (`c4dbf596`).
  - `enforce_call_scope(org_id, to_number) -> str`: scope-only ON ⇒ raise `OutOfScopeError` if org not in
    the test allowlist; **return the forced test number** (every epic call dials `+917879997839`).
  - `enforce_email_scope(org_id, to_email) -> str`: scope-only ON ⇒ raise if org not allowed; **[DECISION 3]**
    force the recipient to a designated test inbox (default proposal: `kikitest01@gmail.com`, a real inbox
    Amber controls) or refuse. Calls have a number in the brief; email has no analog given.
- **Required test (every sending cluster):** scope-only ON + out-of-scope org/number ⇒ `OutOfScopeError`
  (the "refused" proof); in-scope ⇒ forced to test target.
- Go-live = flip `OUTBOUND_TEST_SCOPE_ONLY=0` (guard becomes pass-through) once Amber approves real sends.
  Default-ON means a fresh deploy can't accidentally dial real customers.

### 0.8 Migrations to flag (all additive — pre-authorized, flagged)
- **`0037_appointment_customer_proposal.sql`** — `ALTER TABLE appointments ADD COLUMN IF NOT EXISTS
  customer_proposed_start_time timestamptz, customer_proposed_end_time timestamptz,
  customer_proposed_at timestamptz, customer_proposal_source text;` (+ partial index on
  `customer_proposed_at IS NOT NULL`). For the reschedule approval loop. **Only migration in the epic.**
  (Occasions, click trigger, email wiring, and the scope guard need no schema — they reuse the
  `outbound_calls` ledger, existing appointment columns, and env.)

### 0.9 Decisions needed from Amber (before Cluster A code)
1. **Reschedule write-back:** enhance existing `change_appointment` service to stamp structured counter
   columns (no agent write — recommended) **vs** new `hk_proposeReschedule` agent tool (additive agent write)?
2. **CANCEL mapping:** in the call-log action card, "Ablehnen" (reject pending request) = the brief's
   CANCEL → `appointment_cancellation`. Confirm (the Kalender "Stornieren"/`/cancel` route is a separate
   confirmed-appt path, not wired here).
3. **Email UAT recipient:** scope guard forces calls to `+917879997839`; email has no phone analog —
   force email to `kikitest01@gmail.com` during build, or keep email dry-run/log-only and you verify live?
4. **Side-effect failure policy:** best-effort/non-blocking (status click succeeds even if the call/email
   fails) — recommended. Confirm.
5. **Master toggle copy:** the "Terminerinnerung" (`appointment_reminder`) toggle gates all three
   appointment actions; I'll add copy under Kiki-Zentrale → Ausgehende Anrufe noting it also activates
   confirm/cancel/reschedule outbound calls. Confirm wording approach.

### 0.10 Incidental finding (flag, out of scope unless asked)
- Frontend `ConfigSections.tsx` occasion list uses key **`missed_call_callback`**, but the backend
  registry/gate uses **`missed_callback`** (`outbound_occasions.py:621`). The frontend toggle therefore
  writes a key the backend never reads → that occasion's toggle is effectively dead. Relevant to Cluster C
  (email-on-all-occasions); noting it, not fixing without your go. **→ FIXED in Cluster C.**

---

# Build outcome — overnight BUILD-ONLY run (2026-06-02). DEPLOYED NOTHING.

All 4 clusters built, committed (**NOT pushed, NOT deployed**), hermetic suite **397 pass**, frontend
build clean. Phase 0 design approved; Amber's 5 answers folded in. Scope guard stayed **DEFAULT ON** the
entire run; **no real call placed**.

Commits on `main` (local only — `origin/main..HEAD` = exactly these 4):

| Cluster | SHA | Scope |
|---|---|---|
| A — occasions + human-click trigger + reschedule loop | `0fe5ddb` | backend + frontend |
| B — appointment confirmation/cancellation/reschedule emails | `9d38e22` | backend |
| C — email on the existing 7 occasions (INERT) + key fix | `d613022` | backend + frontend |
| D — Call Logs direction colour + filters | `a74b2dd` | frontend |

### Migration (only schema change)
`0037_appointment_customer_proposal.sql` — additive `ADD COLUMN customer_proposed_start_time/end_time/at/source`
on `appointments` + partial index. **APPLIED to the shared prod Supabase** via MCP (pre-authorized
additive). Rollback (if ever): `ALTER TABLE appointments DROP COLUMN customer_proposed_*` — harmless to leave.

### Cluster A `0fe5ddb` — root cause/design → fix → test
- Design = Phase 0 §0.3. Fix: `outbound_scope.py` (guard); 3 occasions with `select=[]` (never swept);
  `appointment_notify.notify_appointment_outcome` (master-gate + scope + `send_single_outbound`), wired
  best-effort into confirm/reject(=cancel)/propose-alternative(=reschedule); `change_appointment` additive
  stamp; `POST /approve-proposal` + `/decline-proposal`; AppointmentCard "Kunde schlägt vor" state.
- **Reschedule STOP-CONDITION outcome: DONE ADDITIVELY.** `change_appointment` only gained one extra UPDATE
  (stamps `customer_proposed_*` on the matched appointment). The existing `appointment_change` inquiry
  insert, the tool return contract, and the agent-facing message are UNCHANGED (asserted by
  `test_appointment_reschedule_writeback`). Side note: every agent-initiated change request (inbound or
  reschedule-counter) now also surfaces the structured approval card — intended + additive.
- Tests: `test_outbound_scope`, `test_appointment_notify`, `test_appointment_occasions`,
  `test_appointment_reschedule_writeback`, + approve/decline in `test_appointments_actions`.
- Live proof: backend restarted; all 5 appointment routes present in live `/openapi.json`; live dry-run on
  the test org → forced to `+917879997839`, `anlassTyp=TERMIN_BESTAETIGUNG`, **no real call**.

### Cluster B `9d38e22` — appointment emails
- Fix: `appointment_emails.render_appointment_email` (3 German templates on the branded
  `render_message_email` shell, transport unchanged); `email_render` on the 3 occasions; the
  `_maybe_send_occasion_email` chokepoint in `_dispatch_one` (best-effort, scope-guarded);
  `_resolve_customers` now selects `email`.
- Tests: 3 renders + forced-to-test-inbox + out-of-scope refusal + best-effort swallow + send_single
  integration (call + email).

### Cluster C `d613022` — email on the existing 7 (INERT) + key fix
- Fix: `occasion_emails.render_occasion_email` (7 templates); `email_render` on the 7 via `_occ_email`;
  gated by `OUTBOUND_OCCASION_EMAILS_ENABLED` (**default OFF** → ships INERT). Frontend key
  `missed_call_callback`→`missed_callback`; + master-toggle copy under Ausgehende Anrufe.
- Tests: 7 renders; flag off=inert / on=sends (scope-forced); key alignment.
- **EXISTING-7 EMAIL DIFF — REVIEW BEFORE ENABLING (deploy-gated, per brief):**
  - Effect when `OUTBOUND_OCCASION_EMAILS_ENABLED=1`: every outbound CALL placed for the 7 existing
    occasions (reminder/kva/payment/satisfaction/review/maintenance/missed-callback) ALSO sends a German
    email to the customer (scope-guarded, best-effort). Flag unset (today) ⇒ **nothing changes** for these 7.
  - One chokepoint: `_maybe_send_occasion_email` (after a successful call, never blocks it).
  - Copy to review: `backend/app/services/occasion_emails.py` (note the soft, explicitly-not-a-Mahnung
    payment tone). Enable: set `OUTBOUND_OCCASION_EMAILS_ENABLED=1` on the backend.
  - Risk when enabled: the 7 fire via the daily SWEEP for real customers → real emails. Enable only when
    the copy + the intent are confirmed.

### Cluster D `a74b2dd` — Call Logs colour + filters
- Fix: card border by direction (amber `border-amber-400` outbound / green `border-green-primary` inbound;
  selection = ring + bg-tint; unread = green left accent); client-side direction + status filters. No
  backend change (`direction` + `inquiry_status` already on the list items).
- Live render proof (authenticated test org, preview MCP): outbound border `rgb(251,191,36)` ×10 / inbound
  `rgb(129,194,100)` ×9; direction=Ausgehend → 10 outbound only; status=completed → 2 only; no console
  errors. (Caught + fixed a bug mid-proof: the `/60` opacity modifier on the `green-primary` CSS-var token
  silently fell back to grey — switched to the solid token.)

### Scope-guard proof (the hard safety requirement)
- **Refusal (REQUIRED):** scope-only ON + out-of-scope org → `OutOfScopeError` for BOTH call and email
  (`test_outbound_scope`, `test_appointment_notify::test_out_of_scope_org_refused`,
  `test_appointment_emails::test_email_refused_out_of_scope`).
- **Forcing:** in-scope → call forced to `+917879997839`, email to `agrawalamber01@gmail.com` (asserted).
- **Live:** dry-run on the real DB forced to `+917879997839`, no real call.
- Guard is **default ON** (`OUTBOUND_TEST_SCOPE_ONLY`) and stayed ON all run.

### Test-org state left behind (kiki-test-007 / c4dbf596) — all reversible
- **CREATED:** test customer `a17438f0-b41e-49d1-96ba-65a43c42c4b4` ("UAT Testkunde (appointment epic)",
  customer_number 909001, phone **+917879997839**, email **agrawalamber01@gmail.com**) + a PENDING
  appointment `812434ab-c43d-4875-9ca7-956f4106f3c3` (~3 days out, "UAT Terminbestätigung"). Both note-tagged
  "safe to delete". Kept for the morning live UAT.
- **agent_configs: LEFT UNCHANGED — `outbound_enabled` is still FALSE.** I did NOT flip it (despite the brief
  listing it as a fixture). Reason: flipping it on the shared DB lets the ALREADY-DEPLOYED prod backend's
  cron sweep activate the existing occasions (`kva_followup` is already enabled in `outbound_occasions`) →
  real calls to real customers. The master toggle is yours to flip when ready (see below).
- Cleanup SQL: `delete from appointments where id='812434ab-c43d-4875-9ca7-956f4106f3c3'; delete from
  customers where id='a17438f0-b41e-49d1-96ba-65a43c42c4b4';`

## DEPLOY RUNBOOK (Amber throws every switch — awake). Nothing here is deployed.

0. **Pre-deploy:** `git log <last-deployed-SHA>..HEAD` to see everything that will ship (not just this
   epic). Per SESSION_HANDOVER, Item 4 (Redis/observability) is already live on prod, so the next backend
   deploy ships this epic's A/B/C backend changes (+ any already-deployed intervening commits). Optionally
   `git push origin main` first to sync history.
1. **Migration:** already applied (0037) — nothing to do.
2. **Backend** (`backend-production-3f88a`): `railway up backend --path-as-root --service backend --ci`.
   - New env required: **NONE** — all scope-guard vars have safe defaults (scope-only ON; test
     number/email/org baked). The epic is **inert-safe in prod** until you flip the guard off (step 4).
3. **Frontend** (`frontend-production-4bdf`): `railway up frontend --path-as-root --service frontend --ci`.
   Ships the AppointmentCard approval UI, the Kiki-Zentrale copy + key fix, and the Call Logs colour/filters.
4. **Go-live for real customers (when ready):** on the BACKEND service set `OUTBOUND_TEST_SCOPE_ONLY=0`
   (calls/emails then reach real customer numbers/emails for the 3 appointment occasions). Then per org:
   enable the org + "Terminerinnerung" in Kiki-Zentrale → Ausgehende Anrufe (= `outbound_enabled` +
   `outbound_occasions.appointment_reminder`).
5. **(Optional, gated) existing-7 emails:** after reviewing the Cluster-C diff, set
   `OUTBOUND_OCCASION_EMAILS_ENABLED=1` on the backend. Leave unset to keep off.

**Rollback per cluster:** each is a commit on `main` → `git revert <SHA>` or redeploy the prior SHA. D is
frontend-only. Reverting A also neutralises B/C's email chokepoint (becomes harmless dead code). Migration
0037 is additive — safe to leave. Fastest quarantine without a revert: set `OUTBOUND_TEST_SCOPE_ONLY=1`.

## What needs Amber (morning)
1. **First live UAT call** (the real proof I could not place overnight, guard stays ON → forces +91…):
   enable the test org master toggle (`outbound_enabled=true` + `outbound_occasions.appointment_reminder=true`
   on c4dbf596), then either (a) as a logged-in admin `POST /api/outbound/send {occasion:"appointment_confirmation",
   record_id:"812434ab-c43d-4875-9ca7-956f4106f3c3", to_number:"+917879997839"}` to place the real call
   directly, or (b) exercise the action-card click on a CALL-linked pending appointment (the fixture appt is
   standalone, not tied to a call). Expect a real ring to +91… (and, for the click path, a confirmation email
   to agrawalamber01@gmail.com).
2. **Cluster-C diff approval** before `OUTBOUND_OCCASION_EMAILS_ENABLED=1` (review occasion_emails.py copy).
3. **Scope-guard flip** (`OUTBOUND_TEST_SCOPE_ONLY=0`) — only when real customers should be reached.
4. **Deploy go** for backend + frontend (runbook above).
5. Decide whether to clear the test fixtures (cleanup SQL above) or keep them.

---

# DEPLOYED + LIVE-TESTED on prod (2026-06-02)

Per Amber's "deploy + test everything, keep only the per-org toggle" directive (prod = staging
replica, no real customers, prod writes authorized).

### Deployed
- `git push origin main` (`d2a6155..c5c6c72`), then `railway up backend` + `railway up frontend`
  (`--path-as-root --service … --ci`). Backend `/health` 200; all 5 appointment routes +
  `/api/outbound/send` live in prod `/openapi.json`; frontend serves the new bundle. Brevo
  (`BREVO_API_KEY`+`BREVO_SMTP_KEY`) + `ELEVENLABS_API_KEY` confirmed present (names only).

### Single per-org toggle (global guard removed from the path)
- Set on prod backend: **`OUTBOUND_TEST_SCOPE_ONLY=0`** (guard now pass-through — no
  forcing/intercepting) + **`OUTBOUND_OCCASION_EMAILS_ENABLED=1`**.
- Confirmed by read: per-org `agent_configs.outbound_enabled` is the ONLY gate; it's independent
  of the (now-off) guard (the guard only computes the destination AFTER the gate passes). **New orgs
  default `outbound_enabled=false`** (migration 0015 default + `DEFAULT_AGENT_CONFIG` doesn't set it →
  onboarding never auto-calls).
- Test org `c4dbf596` enabled (`outbound_enabled=true`, occasions `appointment_reminder`+`kva_followup`);
  every other org left OFF.

### Fixtures (kiki-test-007 / c4dbf596)
- Customer `a17438f0` (phone **+917879997839**, email **agrawalamber01@gmail.com**).
- Appointment `812434ab` — after the reschedule test it is now `confirmed` @ 2026-06-13T14:00Z.
- Cost estimate (KVA) `07fb9d56` (`KVA-TEST-APPT-EPIC`, sent, 8 days old).
- Cleanup: `delete from cost_estimates where id='07fb9d56-...'; delete from appointments where
  id='812434ab-...'; delete from customers where id='a17438f0-...';`

### Live test results — ALL PASS (6 real calls to +917879997839 + 6 Brevo emails to agrawalamber01)
| Occasion | conversation_id | call_sid (head) | email |
|---|---|---|---|
| appointment_confirmation | conv_4301kt3qdhn5f6sr0szzrnc2k833 | CA2f49ec24 | brevo_smtp ✓ |
| appointment_cancellation | conv_5801kt3qerp1em39pzp6ew5h8hks | CAde4a963b | brevo_smtp ✓ |
| appointment_reminder (existing-7) | conv_4901kt3qevdqe29vp4r5m20m39nr | CAef418772 | brevo_smtp ✓ |
| kva_followup (existing-7) | conv_3001kt3qexp8fc89e3p0b63wawq6 | CA1b9d6fe7 | brevo_smtp ✓ |
| reschedule → propose-alternative | conv_3801kt3qfr07e429m55x1m5r380r | CA9440f0a5 | brevo_smtp ✓ |
| reschedule → approve-proposal (confirmation) | conv_2101kt3qgvfjfxwbptefxbp3tpf8 | CA08efd97b | brevo_smtp ✓ |

- Calls corroborated in `outbound_calls` (the 4 `/send` rows `status=placed`); the 2 reschedule-loop
  calls used the override path (no ledger row, by design) and are proven by their API responses.
- Emails corroborated in prod logs: `email_send org=c4dbf596 tier=brevo_smtp to=agrawalamber01@gmail.com
  status=success` ×6 (each a Brevo `HTTP 201 Created`). Inbox arrival is Amber's to eyeball.
- Reschedule loop verified end-to-end: propose-alternative (call) → `customer_proposed_*` stamped
  (simulating the agent's mid-call counter via `change_appointment`) → approve-proposal applied the
  counter (`scheduled_at`→2026-06-13T14:00Z, status `confirmed`, proposal cleared) + fired the
  confirmation call+email.

### Flags / residual
- **Item 4 already live:** `REDIS_URL`+`OBSERVABILITY_ENABLED` were already set on prod (enabled
  2026-06-01). Left untouched (NOT unset — it's a working verified feature; the "keep inert" line was
  read non-destructively as "don't activate via this deploy", which holds).
- **Cron/sweep:** with the test org enabled + guard off, if the external cron hits `run-due-reminders`
  it will batch-dial/email the test org's qualifying records (appts ~1d out, sent KVAs ≥7d), not just
  the fixture. Fine on a staging replica; pause the cron if undesired. (The test KVA already has a
  placed ledger row → won't re-fire.)
- **Auth for testing:** used the `kikitest01` test-admin Supabase login (Amber authorized after the
  auto-classifier flagged agent-supplied credentials). Token was transient; not persisted in repo.
- **Prod URLs:** frontend https://frontend-production-4bdf.up.railway.app · backend
  https://backend-production-3f88a.up.railway.app

### Follow-up fix — Reply-To = company email (`22bc232`, deployed)
- Issue (from Amber's received mail): replies went to the Brevo From
  (`info@kiki-zusammenfassung.de`), not the company. Root cause: `send_email` set
  Reply-To to the connected sending account (or nothing → fell back to From).
- Fix (centralized in `send_email`, covers ALL email types — the 6 appointment/
  occasion emails + KVA + Invoice + Employee invite + test mail): Reply-To =
  `organizations.email` (new `_load_org_email`), overriding the connected-account
  preference and supplied even when a caller omits `reply_to`. Falls back to the
  caller value only if the org has no email. Hermetic suite **400 pass**; deployed;
  re-sent a live email post-deploy (`conv_4001kt3rgfpxf5zr5g1ffmjc8zmf` → agrawalamber01).
- **Flag:** 2 of 3 prod orgs have NO email on file → those still fall back to the
  From address (no company email exists to route to). Recommend requiring
  `org.email` at onboarding so every org has a reply target. (Test org `c4dbf596`
  email = dixitrahul825@gmail.com, so its replies now route there.)
