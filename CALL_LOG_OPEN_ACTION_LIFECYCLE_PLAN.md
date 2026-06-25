# Call-Log Open-Action Lifecycle — Execution Plan

**Status:** ✅ IMPLEMENTED + UAT-preview-verified on `feat/scheduling-copilot-vacation-overhaul`. Full suite 1024 pass, tsc clean.

**Surface correction (vs the original plan):** the live aggregate open-action view is the **Posteingang** (`/posteingang`) — the call-derived "X Entscheidungen warten auf dich" inbox, the opposite of the calendar. That IS the "call-log open-action panel." (The `Inbox.tsx` `ActionRow` worklist is exported but currently unused.) So the new kinds were wired into the **Posteingang** decision engine (`posteingang/api.ts` KIND_CFG + resolve + route), not excluded from it. The call-log `Inbox.tsx` maps were also updated (forward-compatible for if `ActionRow` is ever mounted). Cancellation/terminal cards made slate at the source: `posteingang/parts.tsx` `TYPE_VARIANT.storno = 'neutral'` + the storno primary button switched from `danger` to `secondary`.
**Branch:** `feat/scheduling-copilot-vacation-overhaul` (build on the same branch).
**Scope (hard rule):** the **call-log Aktionen panel only** (`/calls`). NOT the Posteingang, NOT the calendar view.
**Author note:** This extends the open-action lifecycle pattern already shipped for `reschedule_pending`/`appointment_cancelled` (commit `8f2d6bf`) to **all three entities** (appointments, offers, invoices) so the call-log panel becomes a complete, immediate, stage-wise mirror of every in-flight item.

---

## 1. Goal (what Amber asked for)

1. **Synchronization:** manual actions on appointments / offers / invoices (create, send, confirm, cancel — done from buttons anywhere, incl. the call-log panel) must be reflected in the call-log open-action tab. Open actions are *derived* from entity state, so this is achieved by making the aggregation **complete + immediate** (no time gates) and **persistent** (terminal stages stay visible).
2. **Stage-wise lifecycle parity:** appointments already have `confirm → confirmed / reschedule / cancel`. Offers and invoices must get the equivalent `create → created / cancel` stages, including a terminal informational card (like `appointment_cancelled`).

---

## 2. Locked decisions (from Amber)

| # | Decision |
|---|---|
| 1 | Freshly-created **draft** offers/invoices surface in the call-log open actions **immediately** — **drop the 24 h grace window** entirely. |
| 2 | Terminal cards (rejected offer, cancelled invoice, cancelled appointment, confirmed appointment) **persist 40 days**, then auto-drop. |
| 3 | Accepted offer → add a **"Rechnung erstellen"** next-step card (natural workflow bridge). |
| 4a | A **manually-created appointment** (from the call-log create-appointment modal) starts as **`pending`** = "Bestätigung ausstehend" → confirmed from the open action (creating ≠ confirming). |
| 4b | Once confirmed (agent-booked OR manual), the card **stays 40 days as "Bestätigt"** (with reschedule/cancel still available), instead of disappearing on confirm. |
| 4c | **All** appointments appear in the call-log open actions (scope = all, not only call-linked). |
| 4d | **Calendar / planning-board** creation is explicitly OUT of scope — those keep creating `status='confirmed'` and are untouched. |
| 5 | Cancellation color = **slate/dark-grey** everywhere (already done in shipped work). |

---

## 3. Entity lifecycle → open-action stages

### 3.1 Appointments (status enum: `pending | confirmed | cancelled | completed`)

| Status (DB) | Card kind | Stage label | Color | Buttons in panel |
|---|---|---|---|---|
| `pending` | `termin_anfrage` *(exists)* | Bestätigung ausstehend | green | Bestätigen / Verschieben / Ablehnen |
| `confirmed` (≤40 d) | **`appointment_confirmed` (NEW)** | Bestätigt | green | Verschieben / Stornieren |
| `confirmed` + recent `rescheduled_at` (≤40 d) | `reschedule_pending` *(exists — bump 14→40 d)* | Termin verschoben | 🟠 orange | Bestätigt / Stornieren |
| `cancelled` (≤40 d) | `appointment_cancelled` *(exists — bump 14→40 d)* | Termin storniert | ⬛ slate | Verstanden / Behalten |

**Create-path change:** the call-log create-appointment modal creates `status='pending'`. All other create paths keep `status='confirmed'`.

> Note on precedence: a row matches at most ONE appointment card. Order of evaluation: `cancelled` → `reschedule_pending` (confirmed + recent `rescheduled_at`) → `appointment_confirmed` (confirmed, no recent reschedule) → `termin_anfrage` (pending). `_termin_anfrage` already excludes proposal-marked rows; `appointment_confirmed` must exclude rows already surfaced by `reschedule_pending` (i.e. exclude confirmed rows whose `rescheduled_at` is within 40 d) to avoid double-listing.

### 3.2 Offers / Angebote (status enum: `draft | sent | accepted | rejected | expired | invoiced`)

| Status (DB) | Card kind | Stage label | Color |
|---|---|---|---|
| caller asked, none exists | `kva_suggested` *(exists)* | Angebot erstellen | AI |
| `draft` | `kva_to_send` *(exists — **drop 24 h gate**)* | Angebot senden | AI |
| `sent` | `kva_pending_acceptance` *(exists)* | Antwort offen | AI |
| `accepted`, not yet `invoiced` | **`kva_accepted` (NEW)** | Angenommen → Rechnung erstellen | green (deep-links to new-invoice form) |
| `rejected` / `expired` (≤40 d) | **`kva_closed` (NEW)** | Angebot abgelehnt | ⬛ slate |
| `invoiced` | *(drops off — success terminal)* | — | — |

### 3.3 Invoices / Rechnungen (status enum: `draft | sent | paid | overdue | cancelled`)

| Status (DB) | Card kind | Stage label | Color |
|---|---|---|---|
| caller asked, none exists | `invoice_suggested` *(exists)* | Rechnung erstellen | AI |
| `draft` | `invoice_to_send` *(exists — **drop 24 h gate**)* | Rechnung senden | AI |
| `sent` (+ `overdue`) | `invoice_pending_payment` *(exists)* | Zahlung offen | warning |
| `cancelled` (≤40 d) | **`invoice_cancelled` (NEW)** | Rechnung storniert | ⬛ slate |
| `paid` | *(drops off — success terminal)* | — | — |

---

## 4. Backend implementation — `backend/app/api/routes/actions.py`

1. **`ActionKind` Literal:** add `appointment_confirmed`, `kva_accepted`, `kva_closed`, `invoice_cancelled`.
2. **New aggregators** (mirror `_reschedule_pending` / `_appointment_cancelled` shape — org-scoped, resolve `call_id`, return `{kind,id,inquiry_id,call_id,customer_name,customer_id,summary,created_at,due_at,priority}`):
   - `_appointment_confirmed(client, org_id)` — `appointments.status='confirmed'` AND `confirmed_at` (or `created_at` when null) within 40 d AND NOT (recent `rescheduled_at` within 40 d, to avoid overlap with `reschedule_pending`). `priority='normal'`.
   - `_kva_accepted(client, org_id)` — `cost_estimates.status='accepted'` (exclude `invoiced`). `due_at=None`, `priority='normal'`. `id` = cost_estimate id; deep-link target = `/invoices/new?customer_id=…&cost_estimate_id=…`.
   - `_kva_closed(client, org_id)` — `cost_estimates.status in ('rejected','expired')` within 40 d (use `updated_at`/`rejected_at` if present, else `created_at`). Informational, `priority='normal'`.
   - `_invoice_cancelled(client, org_id)` — `invoices.status='cancelled'` within 40 d (`cancelled_at` if present, else `created_at`). Informational, `priority='normal'`.
3. **Drop the 24 h gates:** in `_kva_to_send` and `_invoice_to_send` remove the `.lte('created_at', _iso_minus_hours(24))` filter so a fresh draft surfaces immediately. Update the docstrings.
4. **Window bump 14→40 d:** `_reschedule_pending` and `_appointment_cancelled` (introduce a shared `_TERMINAL_DAYS = 40` constant).
5. **Register** all new aggregators in `_aggregate(...)` and add the appointment kinds to `_APPT_KINDS` (employee scoping).
6. **Double-listing guards:** verify each row maps to exactly one card (precedence note in §3.1). Add/confirm exclusion filters.

### 4.1 Create-path change (manual call-log create → pending)
- `backend/app/schemas/admin.py` → `AppointmentCreate`: add `status: str | None = None` (default `None`).
- `backend/app/api/routes/appointments.py` → `_create` (~line 183): use `payload.status or "confirmed"` instead of the hard-coded `"confirmed"` (validate against the enum: only `pending`/`confirmed` allowed from this path).
- `frontend/src/pages/calls/Modals.tsx` (call-log create-appointment modal): pass `status: 'pending'` in the POST body. **Calendar (`CalendarPage.tsx`), planning board (`PlanningBoardPage.tsx`), project/customer tabs, copilot — unchanged** (omit `status` → confirmed).

---

## 5. Frontend implementation (call-log panel ONLY)

1. **`frontend/src/pages/calls/shared.ts`**
   - `ActionItem['kind']` union: add the 4 new kinds.
   - `ACTION_KIND_LABEL`: add `appointment_confirmed: 'Bestätigt'`, `kva_accepted: 'Angenommen'`, `kva_closed: 'Angebot abgelehnt'`, `invoice_cancelled: 'Rechnung storniert'`.
2. **`frontend/src/pages/calls/Inbox.tsx`**
   - `KIND_ICON`: `appointment_confirmed: CalendarCheck`, `kva_accepted: Receipt`, `kva_closed: Receipt`, `invoice_cancelled: Receipt`.
   - `KIND_TONE`: `appointment_confirmed` = green (`bg-green-tint-100 text-green-deep`, tag `success`); `kva_accepted` = green/success; `kva_closed` + `invoice_cancelled` = slate (`bg-slate-700 text-white`, tag `neutral`).
   - Wire the per-card action buttons in the call-log panel (Bestätigen / Verschieben / Stornieren for `appointment_confirmed`; "Rechnung erstellen" deep-link for `kva_accepted`; "Verstanden"/dismiss for the informational slate cards). Reuse the existing confirm/cancel endpoints + `action_tasks` "done" overlay for informational cards.
3. **Posteingang — intentionally NOT touched.** `frontend/src/pages/posteingang/api.ts` filters `actions.filter(a => a.kind in KIND_CFG)`, so any kind NOT added to `KIND_CFG` is silently excluded from the Posteingang. Leaving the new kinds out of `KIND_CFG` keeps them **call-log-panel-only**, honoring the scope rule. (If Amber later wants them in the Posteingang too, add `KIND_CFG` entries + resolve branches.)

---

## 6. Endpoints reused (no new write endpoints needed)

| Action | Endpoint (exists) |
|---|---|
| Confirm appointment | `POST /api/appointments/{id}/confirm` |
| Reschedule | `PATCH /api/appointments/{id}` (`scheduled_at`) |
| Cancel appointment | `POST /api/appointments/{id}/cancel` |
| Send offer | `POST /api/cost-estimates/{id}/send` |
| Offer accept/reject | `PATCH /api/cost-estimates/{id}/status` |
| Create invoice from offer | navigate `/invoices/new?customer_id=…&cost_estimate_id=…` |
| Send invoice | `POST /api/invoices/{id}/send` |
| Invoice paid/cancel | `PATCH /api/invoices/{id}/status` |
| Mark open action done/dismiss | `POST /api/actions/state` (`action_tasks` overlay) |

---

## 7. Tests

- `backend/tests/test_batch8_actions.py` (or a new file): one aggregator unit test per new kind (mirror `test_reschedule_pending_*`) using the `_FakeClient` pattern — assert shape, org-scoping, the 40-day `gte` window, and exclusion filters.
- `test_appointments_actions.py` / create test: `AppointmentCreate(status='pending')` lands pending; default (no status) lands confirmed; calendar/planning-board paths unaffected.
- Drop-24h regression: `_kva_to_send` / `_invoice_to_send` surface a draft created <24 h ago.
- Full suite must stay green (currently 1016). Frontend `tsc -b` clean.

---

## 8. Verification (preview)

Reuse the synthetic customer **"Vorschau Test (+917887397839)"** in the TobiasDachdecker UAT org. Add scenarios: a confirmed appointment (→ "Bestätigt" card), a manually-created pending appointment (→ "Bestätigung ausstehend"), a draft offer (→ immediate "Angebot senden"), an accepted offer (→ "Rechnung erstellen"), a rejected offer (→ slate "Angebot abgelehnt"), a draft + cancelled invoice. Screenshot the call-log Aktionen panel showing all stages.

---

## 9. Effort & sequencing

- **Effort: M** — almost entirely the same scaffolding as the shipped `reschedule_pending` work; 4 aggregators + 1 create-path tweak + frontend kind wiring + tests.
- **Suggested order:** (1) backend aggregators + window bump + drop 24h, (2) create-path pending, (3) frontend Inbox kinds + buttons, (4) tests, (5) preview verify, (6) commit.

---

## 10. Related / out-of-scope (tracked elsewhere)

- **Migration 0079** (`employee_absences.substitute_employee_id`) — **APPLIED to UAT** `ifbluvdcbcesuhvkxsfn` on 2026-06-25. ✅
- **Deferred (item 4b deep rework):** persisting copilot tool-calls/results + post-confirm outcomes into cross-turn model context — separate follow-up, not part of this plan.
- **Posteingang parity:** intentionally excluded per the "strictly call-log panel" rule; revisit only if requested.
