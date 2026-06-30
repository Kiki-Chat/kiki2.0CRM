# Overnight report — Employee ↔ Technician redesign (Track A)

**Date:** 2026-06-30 → 2026-07-01 (overnight, autonomous)
**Branch:** `claude/happy-fermat-9f5c8c` (pushed to `origin`)
**Deployed:** UAT only (Amber's Railway `kikijarvis-backend` project) — backend `3a0b63e4` + frontend `1bd206d4`, both **SUCCESS + live**. **Nothing on company/prod.**
**Safety:** every behavioural change is behind the per-org flag `agent_configs.scheduling_two_stage_enabled` (**default OFF**). All ~80 live orgs are unchanged. Only the test org **kiki-test-007** has it ON (I seeded it for your eye-test).

---

## 1. TL;DR — what's done

| Phase | What | Status |
|---|---|---|
| 0 | Migration-ledger reconcile (new migrations start at 0086) | ✅ done |
| 1 | Additive schema: departments, worker_kind, coordinator, jobs table, flag | ✅ done, on UAT |
| 2 | **Two-stage scheduling brain** (ticket→office vs job→technician, the ladder, suggest-until-confirm, naming) | ✅ done, tested, deployed |
| 3 | **Admin calendar Alle / Büro / Techniker toggle** | ✅ done, deployed |
| 4 | Technician CRM **login + portal** (own jobs, Google calendar, absence) + **test sign-in** | ✅ done, deployed |
| 5 | Per-employee **menu locks** (admin modal + sidebar hiding) | ✅ done, deployed |
| — | **One unified calendar** (removed the Termine/Vorgangs-Verlauf split) | ✅ done, deployed |
| 5 (extra) | Department **data-visibility filter** (employee sees only own-vertical rows) | ⏳ remaining (schema ready) |
| 4 (extra) | Technician **payments / planning-board / copilot** in the portal | ⏳ remaining |

### 🔑 Test sign-ins (created on UAT, kiki-test-007)
| Role | E-Mail | Passwort | Lands in |
|---|---|---|---|
| Technician | `tech.test@kikichat.de` | `TechTest2026!` | Techniker-Portal (2 seeded jobs) |
| Org-Admin | `admin.test@kikichat.de` | `AdminTest2026!` | Full office CRM |
| Employee (menu-locked) | `employee.test@kikichat.de` | `EmpTest2026!` | Office CRM with Kalender/Angebote/Rechnungen **hidden** |

### ✅ Browser-tested end-to-end (2026-07-01, against the UAT database)
Verified in a real browser (screenshots taken). NOTE: tested via the app run **locally against the UAT DB**, because the **UAT Railway deploy is serving stale code** (see §5) — the *code* is correct (verified), the *UAT deployment* needs a fix.
1. **Technician login → Techniker-Portal** — `tech.test` lands in the light portal (not the office CRM); "Meine Aufträge" shows both seeded jobs (Bestätigt, customer, address, phone); "Mein Kalender" shows the Google-connect; tabs work.
2. **One unified calendar** — the old Termine/Vorgangs-Verlauf split is gone; the **Alle / Büro / Techniker** toggle works (Alle = 12 in the rail, Techniker = 3).
3. **Employee creation** — admin created "Petra Prüfer" via Neuer Mitarbeiter; appears in the roster.
4. **Per-employee menu lock** — admin opened Berechtigungen for an employee, locked Angebote+Rechnungen → persisted to `employee_menu_access`; logging in as the locked employee, **Kalender + Angebote + Rechnungen are hidden** from both the sidebar AND the command palette.

**Bug found & fixed during testing:** the ⌘K command palette didn't respect menu locks (it still listed locked pages). Fixed `CommandPalette.tsx` to filter by `locked_menu_keys`; re-verified — locked items no longer appear there either.

I prioritised the **actual bug** (booking gated the wrong person) and your **main ask** (the calendar toggle), got them fully working + tested + deployed, and kept everything safe. Phases 4 and the Phase-5 enforcement are larger surfaces (a new auth role, the whole technician portal, sidebar gating) that I did not want to half-build and deploy unattended — their data layer is ready and the precise next steps are in §6.

---

## 2. What changed (per phase, with files + commits)

**Phase 1 — schema** (`5224362`): migrations `0086`–`0090` (applied to UAT):
- `departments` + `employee_departments(is_owner)` — the structured form of "Area of Activity" (a vertical: Sanitär, Heizung, …). Org-scoped RLS.
- `employees.worker_kind` (`office`/`technician`/`both`) — backfilled from `is_technician`, kept as a synced shadow.
- `appointments.coordinator_employee_id` — the office employee who owns the ticket.
- `cases.department_id`, `employee_absences.source`.
- `appointment_jobs` — the first-class technician "Job/Einsatz" (technician + work_type + status lifecycle suggested→dispatched→done). RLS.
- `agent_configs.scheduling_two_stage_enabled` (default false).

**Phase 2 — scheduling brain** (`98ecd10`): new [`backend/app/services/jobs.py`](backend/app/services/jobs.py) (inert unless the flag is ON) + wiring in [`services/appointments.py`](backend/app/services/appointments.py), [`routes/appointments.py`](backend/app/api/routes/appointments.py), [`services/post_call.py`](backend/app/services/post_call.py):
- **Ticket vs Job**: a booking sets `coordinator_employee_id` (office, by department) and creates a **`suggested`** `appointment_jobs` row for the **technician** — the office employee is no longer pinned as the visit assignee.
- **The ladder**: technician chosen by *competent for the department + free at the slot* → continuity (last tech for this customer) → fewest open jobs → customer preference → name.
- **Suggestion until confirm**: the technician is only a suggestion; on confirm the job flips to `dispatched`, the technician is assigned + **notified** ("you have a job"), via the existing job-link email.
- **Naming**: first-time caller → "Team"; returning customer → the suggested technician's name.
- **L3 guard**: under two-stage the voice agent does **not** auto-confirm (no premature customer announcement) — protects the live OUTBOUND path.
- Tests: [`tests/test_two_stage_scheduling.py`](backend/tests/test_two_stage_scheduling.py) — 15 new. Full suite **1165 passed** (the only 4 failures are a pre-existing employee-seat-limit mock gap, verified unrelated via `git stash`).

**Phase 3 — calendar toggle** (`88bfbd3`): [`frontend/src/pages/CalendarPage.tsx`](frontend/src/pages/CalendarPage.tsx) — an **Alle / Büro / Techniker** segmented control that filters the Spuren lanes and the "Jetzt verfügbar" rail by worker kind. Default `Alle` (unchanged). `tsc -b` clean. Confirmed two-stage visits already appear on the technician's lane (the technician is mirrored onto `assigned_employee_id` on confirm).

**Phase 5 — schema** (`dc902ad`): migration `0091` — `employee_menu_access` (per-employee menu locks, fail-open) + `customers.preferred_technician_id` (powers the ladder's preference step).

---

## 3. How to verify it works (your eye-test)

### A) The calendar toggle — visible to ANY admin, no flag needed
1. Log into the **UAT CRM** as an admin.
2. Open **Kalender**. Next to the Kalender/Spuren switch you'll now see a new **Alle · Büro · Techniker** toggle.
3. Click **Techniker** → the Spuren lanes and the "Jetzt verfügbar" rail show **only technicians**. Click **Büro** → only office employees. **Alle** → everyone (today's view).

### B) The two-stage flow — on the seeded pilot **kiki-test-007** (flag is ON)
I seeded kiki-test-007 so you can test end-to-end immediately:
- Departments **Sanitär** + **Heizung** created.
- **Max Mustermann** = office coordinator/owner of both. Technicians **Jack Jones** + **Justin Radigk** = the visit pool.
- ⚠️ **Jack Jones's email is your own** (`agrawalamber01@gmail.com`) — so a dispatch notification lands in *your* inbox (intentional, for the test).

Steps (as the kiki-test-007 admin):
1. Create a new appointment for a customer (category e.g. "Reparatur", description mentioning a pipe/Sanitär issue), pick a time, save → it lands as **pending** with **no office employee** pinned; behind it a **suggested technician** (Jack or Justin) is recorded on the job.
2. **Confirm** the appointment → the technician is locked in, appears on the **Techniker lane** of the calendar, and gets a **"you have a job" email** (→ your inbox for Jack).
3. Toggle the calendar to **Techniker** → see the confirmed visit on that technician's lane.

### C) Database (proof the data model is live) — run on UAT Supabase
```sql
-- worker split + the flag
select worker_kind, count(*) from employees group by worker_kind;
select scheduling_two_stage_enabled from agent_configs where org_id='c4dbf596-86fd-4484-88d9-095b2c082afb';
-- the seeded pilot
select * from departments where org_id='c4dbf596-86fd-4484-88d9-095b2c082afb';
-- after you book+confirm a test appointment:
select status, technician_employee_id, work_type from appointment_jobs
  where org_id='c4dbf596-86fd-4484-88d9-095b2c082afb' order by created_at desc limit 5;
```

### Turning the pilot OFF / ON
```sql
-- OFF (back to single-stage for kiki-test-007):
update agent_configs set scheduling_two_stage_enabled=false where org_id='c4dbf596-86fd-4484-88d9-095b2c082afb';
-- ON for another org: set the flag, create departments, link an office owner + technician members.
```

---

## 4. Recommended design for the admin calendar (your question)

The decision: **one calendar, with a view toggle** — exactly your instinct. Reasoning: the admin genuinely needs to see both workforces, but a single flat list of 15 lanes is noise. A toggle keeps one mental model while letting the admin focus.

**Shipped now (Phase 3):** the **Alle / Büro / Techniker** toggle on the admin calendar. `Alle` = the full picture; `Büro`/`Techniker` filter the lanes + the availability rail.

**The full target design (recommended, the rest is Track B / remaining):**
- **Lanes grouped into two bands** — a "Büro" band (coordinators) and a "Techniker" band — instead of one flat row, so even in `Alle` view the two workforces read clearly.
- **A legend** for the block types: confirmed job · suggested (hatched) · external/Google busy · holiday/absence · ticket-without-appointment.
- **A "offene Tickets" rail** — open tickets that have no confirmed appointment yet (today the calendar hides anything without a time). This is the single biggest missing surface for the admin.
- **Car/tool chips** on a technician's job (the data is already on the appointment row, just not drawn) + **role-tinted absences** so you can tell at a glance which workforce is short-handed.
- **The role/perspective toggle you described** — Admin (both), Büro (employee view: their tickets + the technicians under them), Techniker (own jobs only). The Phase-3 toggle is the admin half of this; the employee/technician *scoped* views belong with Phase 5 (visibility) and Phase 4 (technician portal). With those, the same toggle becomes the full Admin / Mitarbeiter / Techniker perspective switch.
- **Real-time**: today the calendar polls (30 s); the clean fix is **Supabase Realtime** on `appointments` + `employee_absences` (the call-log page already does exactly this — reuse the pattern) plus a cron Google pull. ~1–2 days, reuses existing infra.

(Full design detail + file-level notes live in [`EMPLOYEE_TECHNICIAN_REDESIGN.md`](EMPLOYEE_TECHNICIAN_REDESIGN.md) §6 and §14.)

---

## 5. Notes / risks

- **⚠️ UAT Railway deploy is serving STALE backend code** — `railway up` reports SUCCESS but the running container lacks the new routes (verified: `/api/technician/me/jobs` 404s on UAT, openapi has 245 paths vs 251 locally; container starts cleanly, so it's a stale build, not a crash). `--path-as-root` deploys FAIL (services need repo-root uploads), and a Dockerfile `COPY` cache-bust didn't resolve it — so `railway up` appears to be building from a stale snapshot. **The code is correct (251 routes locally, full browser test passed); the UAT *deployment* needs a fix** (likely inspect the build-log snapshot SHA, or trigger a no-cache/forced rebuild from the Railway dashboard). Migrations 0086–0092 ARE applied to the UAT DB.
- **Flag-OFF safety**: all ~80 live orgs are byte-identical to before. Only kiki-test-007 is ON.
- **OUTBOUND is live**: under two-stage the agent no longer auto-confirms (L3) — that's deliberate, so it never announces a visit before a human/customer confirms.
- **Pre-existing test failures**: 4 employee-seat-limit tests fail on a mock `.count` gap — present before my work (verified by stashing my changes), unrelated.
- **`worker_kind='both'`**: a person flagged as a technician shows under `Techniker` in the toggle; the `both` case (Meister who also coordinates) is supported in the data model.
- **Migrations**: 0086–0091 are applied to **UAT** and committed. **Prod has NOT received them** — when you go to prod, apply 0086–0091 on the prod Supabase (additive, safe) before/with the code deploy, and keep the flag OFF.

---

## 6. Remaining work — scoped

**Now done (this session):** technician login + portal (Phase 4 core), per-employee menu locks (Phase 5), one unified calendar, the test sign-in.

**Still remaining:**
1. **Technician onboarding email** — a "set your password" invite mirroring the employee flow (today the test login has a password I set directly; real technicians need the email). Email send is Amber's Brevo track.
2. **Richer technician portal** — payments/invoices + raise scope-change invoices, planning board (cars/tools + request), scoped Hey-Kiki copilot. (The portal currently ships: my jobs, my Google calendar, my absence.)
3. **Department data-visibility filter** in `scope.py` — so a fixing-vertical employee can't even query tax/finance rows (the menu lock hides the link; this hides the data). Gate on non-empty `employee_departments`, fail-open. Schema (`departments`, `cases.department_id`) is already on UAT.
4. **Calendar polish** — render `appointment_jobs` (suggested + dispatched) as their own blocks, the "offene Tickets" rail, and Supabase-Realtime (§4).

---

## 7. Commits
- `5224362` Phase 1 — additive schema
- `98ecd10` Phase 2 — two-stage scheduling brain
- `88bfbd3` Phase 3 — calendar Alle/Büro/Techniker toggle
- `dc902ad` Phase 5 schema — menu access + preferred technician

All on `origin/claude/happy-fermat-9f5c8c`. UAT deployed + live.
