# UAT Round 2 — Fix Status & Test Plan (2026-06-04)

Status of the "Topics for rectification" list (23 numbered items; **#11 was blank**, so 22 real topics).

- **Done: 22 — all topics** (topic 11 was blank in your list).

> ⚠️ **Restart the backend (uvicorn) before UAT** — it has no hot-reload, so all backend changes (autonomy #19/21/22, emergency-weekday prompt #13, projects/invoices automation, required-field priority #8, outbound sub-options + retry #17/#18, time-based welcome webhook #20) only go live after a restart. The frontend is on the running preview at **localhost:5173**.
- All changes are **local / UAT only** and **not yet committed** (held for eyeball).
- Automated checks passing: `tsc -b` clean · 16 unit tests green · dev server boots with no build/console errors.

---

## How to run / prerequisites

1. **Frontend** dev server at `http://localhost:5173` (already running; otherwise `npm run dev` in `frontend/`).
2. **Backend** at `http://localhost:8000` (`uvicorn app.main:app --port 8000` in `backend/`) — needed for live calls, appointments, settings.
3. **Log in as an admin** of `kiki-test-007` (Kiki-Zentrale + most settings are admin-only).
4. **Test data needed** for some steps: a few calls with different statuses, at least one call with a *pending appointment*, and appointments on the planning-board date.

> Note: I cannot drive the logged-in screens myself (Supabase login + no credentials), so the per-item steps below are for manual UAT. The code is verified by typecheck + unit tests.

---

## Part A — Fixes done (how to test each)

### 1. Dashboard greeting timings
**Route:** `/` (Dashboard)
**Expected:** Greeting at top matches current **Berlin** time:
- 05:00–12:00 → **Guten Morgen**
- 12:00–15:00 → **Guten Mittag**
- 15:00–18:00 → **Guten Tag**
- 18:00–21:00 → **Guten Abend**
- 21:00–05:00 → **Gute Nacht**

**Steps:** Open the Dashboard, confirm the greeting matches the current time band. (To test other bands, change the machine clock.)
**Note:** I kept the grammatically correct **"Gute Nacht"** (your list said "Guten Nacht"); say if you want it changed.

### 2. Call-log cards (left inbox)
**Route:** `/calls`
**Expected per card:**
- **Bold top line = the reason/subject** of the call (was the name before).
- **Second line = customer name** (or number / "Unbekannt" when unknown).
- **Left color rail = STATUS**, not direction: **blue = Offen**, **orange = In Bearbeitung**, **green = Erledigt**.
- Inbound/outbound is still shown by the **small badge**, and the status pill is still there.

**Steps:** Scan the list — verify a call with an **unknown caller** still shows the subject as the headline; verify rail colors change with status (compare an open vs. in-progress vs. completed call).

### 3. Duplicate "Offene Aktion" header removed
**Route:** `/calls` → select a call that has a pending appointment → right panel, **Aktionen** tab.
**Expected:** The "**Offene Aktion**" heading appears **once** (above the card), not twice.

### 4. Custom-duration placeholder fixed
**Route:** same appointment card → expand "**Kategorie, Dauer & Zuweisung**" → **Dauer**.
**Expected:** The custom-minutes input shows a readable placeholder "**z. B. 45**" next to "Min", no longer clipped/overflowing past the 30/60 pills.

### 5 & 6. Appointment card persists after an action
**Route:** `/calls` → call with a pending appointment.
**Steps & expected:**
- Click **Bestätigen** → card **stays**, shows a green **"Termin bestätigt"** banner + **Bestätigt** pill; action buttons disappear.
- (On another pending appointment) click **Ablehnen** → card **stays**, **"Termin abgelehnt"** banner + **Abgelehnt** pill.
- Click **Alternative vorschlagen** → send → card **stays** as **"Alternative gesendet"** (unchanged from before).
- Click **Ausblenden** → card **collapses** to a one-line summary; click the line → it **re-expands**.
- Click the **✕** (top-right) → card is **removed** from the list.

**Caveat (known):** persistence is **session-scoped** — after a full page reload a confirmed/rejected appointment is no longer "pending" and won't reappear. Surviving reloads needs a small backend change (ask if wanted).

### 7. Planning board — click to view details
**Route:** `/planning-board` → **Tag** (day) view.
**Steps & expected:**
- **Click** an appointment card (without dragging) → the **detail modal** opens (Zeit, Kunde, Mitarbeiter, Ort, Fahrzeug, Werkzeug).
- **Drag** an appointment onto a vehicle/tool column → it still **assigns** (drag unchanged).
- Both must work; a quick tap should open details, a drag should not.

### 9. Business hours moved into Kiki-Zentrale
**Route:** `/kiki-zentrale` → left nav group **Terminplanung** → **Geschäftszeiten**.
**Steps & expected:**
- The business-hours editor renders (presets, per-day open/close, breaks, copy-to-weekdays, Save). **Save** works and shows "Gespeichert ✓".
- `/calendar` **no longer** has a "Geschäftszeiten" button.
- Visiting the old `/calendar/business-hours` **redirects** to `/kiki-zentrale/geschaeftszeiten`.
- Command palette (**Cmd/Ctrl-K**) → "Geschäftszeiten" jumps to the new section.

**Heads-up:** This section is now **admin-only** (Kiki-Zentrale is admin-gated). Non-admins who open the old URL land on the "admin only" panel. Tell me if business hours should remain non-admin-editable.

### 10. Emergency keyword templates split
**Route:** `/kiki-zentrale/notdienst` → **Stichwörter** → **Gewerk-Vorlagen**.
**Expected:** Separate **Dachdecker** and **Garten** templates exist (the old combined "Dachdecker / Garten / Sturmschäden" is gone) and **"Sturmschaden"** is no longer in the Dachdecker keywords.

### 12. Emergency templates toggle on/off
**Route:** same Gewerk-Vorlagen.
**Steps & expected:**
- Click a template (e.g., **Schlüsseldienst**) → it turns **green with a ✓** and its keywords appear as chips above.
- Click it **again** → it returns to normal (**+**) and its keywords are **removed**.
- Click **Speichern** to persist.

### 13. Emergency time windows now support weekdays
**Route:** `/kiki-zentrale/notdienst` → **Zusätzliche Zeitfenster**.
**Steps & expected:**
- Add a window (**+ Zeitfenster**), set From/To and an optional label.
- A new **"Tage:"** row of weekday chips (Mo–So) appears — toggle the days the window applies to; selected days turn **green**.
- With **no** day selected it shows "(gilt an allen Tagen)".
- **Speichern** → the days are saved on each window (additive JSON; no migration).
- After a **backend restart**, the agent prompt's "Zusätzliche Notdienst-Zeiten" line reflects the days, e.g. `Mittwoch (Mi 14:00–18:00 Uhr)`.

**Backend note:** the prompt-rendering change needs a **uvicorn restart** to go live (no hot-reload). Verified directly: a window `{from:14:00, to:18:00, weekdays:[wed], label:"Mittwoch"}` renders `Mittwoch (Mi 14:00–18:00 Uhr)`.

### 14 / 15 / 16. Call-forwarding guide — real number + correct codes + structure
**Route:** `/docs/rufumleitung` (also reachable: Kiki-Zentrale → **Telefon** → Anleitung link).
**Expected:**
- **Settings UI is now first** (primary method): **iPhone** (Einstellungen → Telefon → Rufweiterleitung → Weiterleiten an) and **Android** (Telefon-App → ⋮ → Einstellungen → Anrufe → Rufweiterleitung → Immer weiterleiten; Samsung path noted).
- **Fallback codes** live in a separate card ("Falls die Einstellungen keine Rufumleitung anbieten…") with the **correct GSM registration codes**: `**21*<nr>#` (alle Anrufe), `*#21#` (Status), `##21#` / `##002#` (aus), plus `**67*` (besetzt), `**61*<nr>**20#` (nicht angenommen, 5–30 s), `**62*` (nicht erreichbar).
- The **real HeyKiki number** is filled into every code + the iPhone/Android step 4; falls back to the "IHRE-HEYKIKI-NUMMER" placeholder when none is assigned.

**Decision noted:** always-forward (`**21*`) is set as the **recommended primary** mode (so Kiki answers every call); the conditional modes are listed as alternatives. Tell me if a different primary is preferred.

### 19 / 21 / 22. Autonomy redesign (per-capability toggles + levels)
**Route:** `/kiki-zentrale/verhalten` → **Autonomie pro Bereich** card.
**UI checks:**
- Four capabilities, each with a **toggle** + **Stufe 1/2/3** + a one-line description: **Termine**, **KVA**, **Projekte & Plantafel** (Hintergrund badge), **Rechnungen** (Hintergrund badge).
- Changing a toggle/level shows **"Nicht gespeichert"** and does **not** push — it only saves when you click **"Autonomie speichern"** (dedicated button).
- The old single 1/2/3 selector + matrix is gone; the **KVA-Automatisierung** menu item (under *Automatisierung*) is gone.
- The persona/voice/welcome bottom Save is separate (its "agent change" confirm dialog no longer fires for autonomy edits).

**Behaviour (after a backend restart):**
- **Termine** — L1 = inquiry only (no booking); L2 = books *pending* (team confirms); L3 = books + confirms in-call. Reflected in the agent prompt and in how `hk_bookAppointment` lands.
- **KVA** — off/L1 = never offers a KVA; L2 = drafts (team sends); L3 = drafts + auto-sends (needs customer email).
- **Projekte** (background, default **OFF**) — when an appointment is **confirmed**, L2 creates a project as `planning`, L3 as `active`; appears on the planning board. Verify: enable Projekte L2, confirm an appointment → a new project exists linked to it.
- **Rechnungen** (background, default **OFF**) — when a project is marked **`completed`**, L2/L3 auto-drafts an invoice from the project's **accepted KVA** (skips if none; one per project). The **L3 e-mail send is intentionally not wired** here (rides your Brevo track) — the invoice is created as a **draft**. Verify: enable Rechnungen, have a project with an accepted KVA, set its status to completed → a draft invoice appears.
- Saving Verhalten triggers a **background prompt re-render + push** to ElevenLabs.

**Backfill:** existing orgs inherited Termine/KVA levels from the old `kiki_level`; Projekte/Rechnungen start OFF.

---

## Part B — Final 5 topics (now done)

### 8. Required-field priority order
**Where:** the agent prompt (set the order in Kiki-Zentrale → **Pflichtfelder**, drag to reorder).
**Expected (after backend restart):** the prompt's Pflichtfelder block now opens with *"Erfasse und bestätige die folgenden Felder in DIESER Reihenfolge — das oberste Feld hat die höchste Priorität …"* and lists the fields in your configured order — so the agent asks/confirms the top-priority field first.

### 17. Outbound appointment sub-options + hint removed
**Route:** `/kiki-zentrale/ausgehende-anrufe`
- Enable **Terminerinnerung** → a **"Termin-Anrufe"** block appears with three independent toggles: **Bestätigen / Absagen / Verschieben**. The old hint paragraph is gone.
- Turn one off (e.g. Absagen) + **Speichern**. Then clicking **Absagen** on a call no longer fires an outbound call/e-mail, while Bestätigen/Verschieben still do.

### 18. Outbound retry + short-hangup recall
**Route:** `/kiki-zentrale/ausgehende-anrufe` → **"Wiederholung & Rückruf"** card.
- Set **Wiederholungen (max.)** + **Abstand (Min.)**; toggle **"Erneut anrufen, wenn der Kunde sehr früh auflegt"** → a **Schwelle (Sek.)** field appears. Save. (Default OFF: 0 attempts, recall off.)
- **Behaviour (after restart):** when an outbound call ends shorter than the threshold and recall is on (and attempts remain), the call's ledger row is stamped with `next_retry_at`; the next outbound sweep re-dials it (new attempt), up to the max.
- **Note:** the re-dial cadence is driven by the **external sweep** (N8N/cron hitting `/api/outbound/run-due-reminders`). Short-hangup recall works end-to-end with the existing post-call webhook; a pure "no-answer" retry additionally needs the Twilio status-callback that isn't built yet.

### 20. Time-based welcome messages
**Route:** `/kiki-zentrale/verhalten` → **"Zeitabhängige Begrüßung"** card.
- Add variants (from–to + message), e.g. **05:00–12:00** "Guten Morgen! …", **18:00–21:00** "Guten Abend! …". Save. (Windows may wrap midnight, e.g. 21:00–05:00.)
- **Behaviour (after restart):** on an **inbound** call the conversation-init webhook returns the variant matching the current **Berlin** time as the agent's first_message; if none matches, the agent's default greeting is used.

### 23. Prompt-size reduction strategy
- Deliverable is the written strategy in **[PROMPT_SIZE_STRATEGY_2026-06-04.md](PROMPT_SIZE_STRATEGY_2026-06-04.md)** (no code). It covers MCP-server tools (biggest win), knowledge-base offload, dynamic per-call injection, dedup/concision, and capability-gating — with a token budget (~16–18k → ~8–9k) and a phased rollout.

---

## ✅ All 22 topics implemented
Topic 11 was blank; **1–10 and 12–23 are done**. Backend changes need a **uvicorn restart** to go live; the frontend is on the running preview.

---

## Part C — Automated verification (re-runnable)

```bash
# frontend
cd frontend
npx tsc -b --force                              # expect: no errors
npx vitest run src/test/configSections.test.ts  # expect: 16 passed
# backend boots cleanly (catches import/wiring errors)
cd ../backend && ./.venv/bin/python -c "from app.main import app; print('routes', len(app.routes))"
```

**Migrations applied (both additive):** `0044_autonomy_per_capability`, `0045_outbound_options_welcome_variants`.

**Backend touched:** `services/agent_config.py` (prompt: autonomy + emergency weekdays #13 + required-field priority #8), `api/routes/kiki_zentrale.py`, `services/appointments.py`, `services/post_call.py`, `services/cost_estimates.py`, `services/projects.py`, `services/invoices.py`, `api/routes/projects.py`, `api/routes/appointments.py`, `services/appointment_notify.py`, `services/outbound_dispatch.py`, `services/conversation_init.py`, `services/copilot/tools.py`.

**Frontend touched:** `DashboardPage.tsx`, `calls/{Inbox,AppointmentCard,CallDetail}.tsx`, `PlanningBoardPage.tsx`, `CalendarPage.tsx`, `components/kiki/{ConfigSections,VerhaltenSection,GeschaeftszeitenSection}.tsx`, `KikiZentralePage.tsx`, `App.tsx`, `components/layout/CommandPalette.tsx`, `pages/RufumleitungGuidePage.tsx`, `lib/kikiApi.ts`; removed `pages/BusinessHoursPage.tsx`.

**Strategy / design docs (no code):** `PROMPT_SIZE_STRATEGY_2026-06-04.md`, `AUTONOMY_REDESIGN_DESIGN_2026-06-04.md`.
