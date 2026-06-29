# Employee ↔ Technician Redesign — Consolidated Spec

**Date:** 2026-06-30
**Status:** Design locked (product decisions captured below). Awaiting go-ahead to build.
**Baseline:** scheduling engine `f5e6f23` is deployed to **UAT + prod**; migrations 0082–0085 on UAT and **0085 confirmed applied to prod Supabase (2026-06-30, per Amber)**. All work here is **additive + feature-flagged (default OFF)** so the ~80 live orgs see zero behaviour change until opted in. The one destructive cleanup is deferred behind explicit approval.

**Existing signals reused (per product confirmation 2026-06-30):** the employee/technician form's **"Area of Activity" (Tätigkeitsbereich / `activity_area`)** field is the WHO/department signal (which vertical a person serves), and **Appointment Category** is the WHAT/work-type signal. The redesign keeps BOTH — the only change is turning free-text Area of Activity into a managed per-org list so routing is exact and visibility can bind to it (same field, same UI label). The employee form's auto-assign toggle also feeds routing (in/out of the routing pool). CORRECTION (product owner 2026-06-30): there is **no 'description' field and none will be added** — **Area of Activity (`activity_area`)**, present on every employee AND technician at creation, IS the field that determines which vertical/competence they belong to. Form fields today: `display_name`, `email`, `access_role`, `is_active`, `is_technician`, `calendar_color`, `activity_area`, `auto_assign`.
**Full investigation output (11 agents, file:line evidence):** `…/tasks/wrufv8e95.output` (this session's scratchpad/tasks dir).

---

## 1. The root cause (one paragraph)

A single column, `appointments.assigned_employee_id`, is overloaded for two different people: the **office employee** (chosen + availability-checked by the auto-router, `assignment.py:122-136`, `appointments.py:614`) and the **technician** (written by the separate manual dispatch step, which *overwrites* the same column, `appointments.py:1052`). On top of that, **no department/vertical entity exists** anywhere (competence is one free-text `activity_area` box), and the auto-router **never filters `is_technician`** — that check exists only in the manual dispatch path. So booking gates the wrong person, technicians are a second-class flag, and there is nothing to anchor routing or visibility to.

## 2. The model (locked)

**Ticket ≠ Job.**
- **Ticket** = the case/Vorgang. Owned by an **office employee**, routed by **department/vertical**. Background coordination — the employee's calendar gates nothing. Decides *who handles what*.
- **Job** = the visit/appointment. Owned by the **technician**. The appointment is created *for the technician*, named to the customer; its **category** sets the work-type + duration, while the **Area of Activity (vertical)** — NOT the category — determines the technician pool.
- **Two intents per request:** (1) the **office vertical-manager** who owns the ticket (background, **not** customer-facing), and (2) the **technician** who does the work (customer-facing, can be several). For a returning customer we ask *which technician by name* — technicians are the registered/customer-facing people; office employees are not customer-facing today.
- The technician is a **suggestion** until the appointment is **confirmed**. Category, duration, suggested timing and suggested technician are all resolved **while building the suggestion** (see §5); the customer can adjust anything (incl. the time) before confirming. On confirm → **lock it in + notify the technician** ("you have a job"). Nothing is category-matched *after* confirm — confirmation only locks + notifies.

**Two availability gates:** the **technician's** availability gates the visit slot. The office employee's availability gates nothing.

## 3. Technician assignment ladder (product rules)

```
HARD FILTERS:  competent for the job's department  AND  free at the chosen slot
RANK among survivors (first non-tie wins):
  1. Continuity  — returning customer + same issue type → technician who handled it last
  2. Workload    — fewest open jobs right now
  3. Preference  — customer's preferred technician (if set)
  4. Random      — break remaining ties
```
New/unknown caller: 1 and 3 don't apply → availability → workload → random.

## 4. Naming policy (replaces blunt `suggest_employee_enabled`)
- **First-time / unknown caller:** never name a person → "a technician from the team will be scheduled."
- **Returning customer:** may name the likely/continuity technician for that issue type.

## 5. Category + intent matching
- Categories remain **org-defined in Kiki-Zentrale**, each gaining a **2-line description** (NEW `appointment_categories.description`).
- **The appointment category does NOT attach a person (decided 2026-06-30).** Category = `name` + `description` (for intent matching) + `duration` + `work_type` only. WHO does the job comes solely from **Area of Activity** (vertical/competence) + the assignment ladder — the two are orthogonal axes, so a technician is never pinned to a category. Legacy `appointment_categories.default_employee_id` is **left unused for routing** (deprecate later). This reverses the earlier "flip category→assignee to technicians" note.
- **Intent → category matching runs BEFORE confirmation, while building the appointment SUGGESTION** (product owner 2026-06-30 — corrected from an earlier wrong "post-confirm" note). Flow: what the call is about → semantic (LLM, description-driven, not harsh) match to a category → category sets the **duration** and the **technician pool** → suggest timing + technician. The customer sees the suggestion and can change anything (incl. the time); **confirmation just locks it in + notifies the technician**. Category must be known up front — you can't propose a slot length without it.
- Category drives **duration + work-type only** — it does **not** select the technician (that's Area of Activity + the ladder).
- Note: the old `default_employee_id → users(id)` bug was already fixed in `0041` (FK re-pointed to employees); the new linkage targets technicians/competence.

## 6. Calendar (F2)
- **Technicians now get their own Google OAuth calendar sync** (via their new login — see §8), exactly like office employees (`employee_calendar_connections` keyed by `employee_id`). Admin-entered absences remain a fallback (`employee_absences`, already role-agnostic).
- **One unified admin feed:** new `GET /api/calendar/unified?from&to` returns appointments + jobs + **everyone's** absences + blocks, each tagged with `worker_kind` + department. Today `_list` (`appointments.py:121`) returns appointments only and never joins absences — that is the whole F2 gap.
- **Frontend lanes split** into Büro-Koordinatoren vs Techniker (`SpurenView`, `AvailabilityRail`); the "Jetzt verfügbar" rail shows free technicians + technician absences as first-class blocks.
- Re-dispatch safety: `_sync_employee_calendar_after_patch` already removes the prior assignee's Google event; push no-ops for unconnected employees — the Job/Dispatch status lifecycle drives event cleanup + link revoke on technician→technician reassignment.

### Verified 2026-06-30 — calendar reality check (the unified calendar is mostly MUST-BUILD)
- **Real-time: does NOT exist.** Admin calendar polls appointments every 30s (`CalendarPage.tsx:181`); absences have 60s staleTime and **no polling** (`:186-191`); Google syncs only on a manual "Synchronisieren" click (`calendar_settings.py` /sync). Only call logs use Supabase Realtime (`CallLogsPage.tsx:88-99`). **Plan:** Supabase Realtime on `appointments` + `employee_absences` (reuse the call-log broadcast pattern, ~1-2 days) + a cron Google pull every 5-15 min (`pull_google_events` is never scheduled).
- **Employee self-calendar: WORKS** end-to-end — `/mein-kalender` Google OAuth (`employee_calendar.py:18-56`), `/meine-abwesenheit` self-service absence + admin approve (`employees.py:795-835`, `EmployeesPage.tsx:1279-1370`). Verified in code + render-verified per memory.
- **Planning board: WORKS but is NOT a calendar** — single-day Kanban (`PlanningBoardPage.tsx:281-290`, `planning_board.py:14-19` 24h window). Cars/tools (`vehicle_id`/`tool_id`) are ON the appointment row but **never rendered on the calendar**; surfacing them = API enrichment + a chip, **no schema change**. No request flow.
- **Admin calendar today** shows confirmed/pending appointments + approved absences + Google-busy on per-employee lanes (`SpurenView.tsx`). MUST-BUILD for the unified view: (1) **tickets-without-appointment rail** (calendar filters out no-`scheduled_at` rows, `CalendarPage.tsx:233` — biggest gap); (2) **office vs technician lane bands + a legend**; (3) **render car/tool + dispatched-technician chips** (data exists, never drawn — dispatched tech only in detail modal `:938-976`); (4) show pending Vorschläge on the hourly lanes (`SpurenView.tsx:70` excludes them); (5) role-tint office vs technician absences (`:287` identical today). Est. ~1-1.5 week focused build, mostly no schema changes.

## 7. Per-vertical visibility (F3, permissions)
- Replace the placeholder Berechtigungen modal (`EmployeesPage.tsx:454`) with real per-employee **department grants** (`employee_departments`).
- A non-admin employee sees only cases/customers/appointments whose `cases.department_id` is in their grant (+ own work). Enforced at query layer (`scope.py`) **and** RLS on the new `department_id` column; keep app-layer stripping as defense-in-depth.
- **Fail-open until an org's `employee_departments` is populated** so nobody loses their tickets at flip. `cases.department_id` backfill is heuristic → admin review pass for coordinator-less / multi-vertical cases.
- All new tables ship org-scoped RLS **with explicit policies** (do not repeat the `0083` RLS-on/no-policy gap).
- **Per-employee menu lock (product owner 2026-06-30) — NOW IN SCOPE (un-deferred):** in the Employees **edit modal**, an admin can **lock specific menu items for an individual employee** (a per-employee `employee_menu_access` / module-lock list). Default stays: an employee already sees what's tied to their assigned tickets; the lock lets an admin *additionally* hide menus (e.g. hide Finanzen/Steuer from a fixing-vertical employee). This is independent of the vertical *data* scope above — it's a UI/menu lock. **Office employees ONLY** — technicians get a fixed very-light portal, so menu-lock config does NOT apply to them.

## 8. Technician CRM portal (real login)
- **Decision:** technicians get a real, **toned-down CRM login** — recommended as a new `users.role='technician'` (extends the `0001` CHECK `('super_admin','org_admin','employee')`) linked to their `employees` row (`worker_kind='technician'`). This reuses OAuth, copilot, invoices, and scoping with no parallel auth system.
- **Onboarding email — mirror the employee flow (product owner 2026-06-30):** technicians receive a **login-credentials / activation email exactly like office employees do today**, then log into the light portal. ⚠️ Email *delivery* is **Amber's track** (Brevo SMTP / activation email, per project convention) — we build the trigger + technician user record + portal; the actual send is coordinated with Amber. Menu-lock restrictions (§7) do NOT apply to technicians — the portal is intentionally fixed and light.
- **Portal surface (scoped strictly to self):**
  - My jobs (assigned visits) — title/time/customer/address/report.
  - My calendar — **synced to their Google account**.
  - My payments + invoices received; **raise a scope-change invoice** (work X agreed, Y added on-site → bill X+Y) via the existing cost-estimate/invoice machinery (`cost_estimates.py`), scoped to their job.
  - Limited dashboard (their ticket/job counts, basics — not the full admin dashboard).
  - **Planning board** (already exists, `0009` + `planning_board.py`: vehicles + tools): which car/tools are available to them, and **request** a car/tool (request flow is NEW).
  - Personal details (self-edit).
  - **Scoped Hey-Kiki copilot** (`copilot.py`, currently `require_org`): "what's pending, which house, address, basic info."
- Standing technician token links (`0064`/`0076`) retained only for one-off read-only job reports; harden with expiry/rotation.

## 9. Dual-role person
- Generally office ≠ technician. For the rare Meister who does both: handled by `worker_kind='both'` on their existing employee row (no second account). "Ugly but reliable" — they appear in both pools; keep it simple, don't build dual-role machinery.

## 10. Data model changes (all additive unless marked)

| # | Change | Safety |
|---|---|---|
| 0086 | `departments(id, org_id, name, kind∈{admin_vertical,trade_vertical}, color, sort_order, is_active)` + `employee_departments(employee_id, department_id, is_owner)` + RLS policies | ADD TABLE |
| 0087 | `employees.worker_kind ∈ {office,technician,both}` (backfill from `is_technician`, keep `is_technician` synced shadow) | ADD COLUMN |
| 0087 | `appointment_categories.description text` (for intent matching). NO person attached — category = duration + work_type only; `default_employee_id` left unused for routing | ADD COLUMN |
| 0088 | `appointments.coordinator_employee_id` (ticket owner); `cases.department_id`; `employee_absences.source ∈ {self,admin}` | ADD COLUMN |
| 0089 | `appointment_jobs` / dispatch table: `(id, org_id, appointment_id, technician_employee_id, work_type, department_id, status∈{suggested,confirmed,dispatched,en_route,done,cancelled}, scheduled_at, duration_minutes, job_link_id, technician_google_event_id, …)` + RLS | ADD TABLE |
| 0090 | `agent_configs.scheduling_two_stage_enabled boolean default false` (per-org kill-switch) | ADD COLUMN |
| 0091 | `employee_visibility` (or reuse `employee_departments`) + **`employee_menu_access` (per-employee menu locks, office only)** + RLS; `technician_job_links` expiry/rotation | ADD TABLE/COLUMN |
| 009x | `users.role` add `'technician'` value (ALTER CHECK); technician CRM scoping | CONSTRAINT change — low-risk, needs note |
| later | customer `preferred_technician_id`; vehicle/tool **request** table | ADD COLUMN/TABLE |
| DEFERRED (destructive, explicit approval) | stop writing employee onto `assigned_employee_id` for visit categories; collapse `is_technician`→`worker_kind`; drop dead `employees.skills text[]`; add missing `0083` RLS policies | each its own gated migration + backfill + rollback |

## 11. Phased plan

**Build order (confirmed 2026-06-30): backend scheduling brain FIRST (Track A = Phases 0–2); unified-calendar UI/design LATER (Track B) — "the backend is the one that must be legit so nothing gets missed." All Track A ships behind the default-OFF flag → no visible change until opted in.**

- **Phase 0 — Reconcile migrations (no schema).** 0085 is confirmed on prod (2026-06-30); new migrations start at **0086**. Two branches both shipped 0084/0085 — still produce a quick applied-state matrix (UAT ledger via MCP; prod via Amber) so 0086+ ordering is unambiguous. No longer a hard blocker.
- **Phase 1 — Additive schema** (table above) on UAT; backend test baseline green.
- **Phase 2 — Scheduling brain** (flag OFF = byte-identical): shared `build_pool` competence + technician filter; assignment ladder; **at-suggestion-time** description-based category matching (sets duration + technician pool); technician-as-suggestion-until-confirm (confirm only locks + notifies); naming policy. Kills F1/F4/F5/F6.
- **Phase 3 — Dual-lane calendar** (F2): `/api/calendar/unified`; lanes; technician Google OAuth + admin-entered fallback.
- **Phase 4 — Technician CRM login + portal** (§8).
- **Phase 5 — Per-vertical visibility** (F3).
- **Phase 6 — Rollout:** pilot `kiki-test-007`; prod flag OFF for all legacy orgs, opt in one at a time; destructive cleanup deferred behind approval.

## 12. Risks / watch-items
- **Migration collision** (0084/0085 dup across branches) — verify ledger before 0086+ (0085 already on prod; not a hard blocker).
- **Calendar real-time + existing surfaces — VERIFIED 2026-06-30 (see §6):** NOT real-time (poll 30s / 60s-no-poll / manual Google); employee self-calendar WORKS; planning board WORKS but is a single-day Kanban, not a calendar. The single unified admin calendar is mostly must-build (~1-1.5wk, mostly no schema).
- **Voice agent / OUTBOUND is LIVE** — technician-suggestion-until-confirm must not fire a real customer call/email naming a not-yet-confirmed technician; pilot on the SAFE agent.
- **`is_technician` ↔ `worker_kind` drift** — keep synced + a test asserting equivalence until the destructive collapse.
- **Visibility fail-open guard** — gate on non-empty `employee_departments` or employees lose tickets at flip.
- **Technician portal PII / payments** — scope strictly to self; harden token expiry before exposing.
- **Feature-flag debt** — two code paths until all orgs migrate; set a completion criterion + flag-removal step.

## 13. Open decisions (have defaults, not blocking)
1. Technician login = new `users.role='technician'` (recommended) vs separate lightweight auth.
2. Scope-change invoicing depth in the field portal — minimal raise vs full cost-estimate editor.
3. Vehicle/tool **request** workflow — approval needed or self-claim.
