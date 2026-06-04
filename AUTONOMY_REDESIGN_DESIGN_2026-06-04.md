# Autonomy Redesign — Design for sign-off (topics 19, 21, 22)

> Status: **design only — no code written yet.** Awaiting go-ahead.

## 1. What exists today
- **One global level** `agent_configs.kiki_level` (1/2/3) drives everything.
- A descriptive 4-row matrix in the UI: **Termine, KVAs, Notdienst, Termin verschieben** ([VerhaltenSection.tsx](frontend/src/components/kiki/VerhaltenSection.tsx)).
- The level is read in 5 places:
  - `render_autonomy_block(kiki_level)` → the `{{KZ_AUTONOMY}}` prompt token ([agent_config.py:639](backend/app/services/agent_config.py)).
  - Appointment booking status (pending vs final) — `_get_kiki_level` ([appointments.py:66](backend/app/services/appointments.py)).
  - Post-call auto-confirm only if level==3 ([post_call.py:47](backend/app/services/post_call.py)).
  - KVA auto-send — reads `kva_automation_enabled` + `kiki_level` ([cost_estimates.py:498](backend/app/services/cost_estimates.py)).
  - Copilot help text ([copilot/tools.py:146](backend/app/services/copilot/tools.py)).
- Separate **KVA-Automatisierung** toggle/section (topic 21 wants this removed).
- Agent tools today: appointments + KVA only — **no** `hk_createProject` / `hk_createInvoice`.

## 2. The new model
**Four independent capabilities, each with its own ON/OFF toggle + its own level (1/2/3):**

| Capability | German label | Driven by |
|---|---|---|
| Appointments | **Termine** | **In-call** (agent prompt + `hk_bookAppointment`) |
| Cost estimates | **KVA** | **In-call** (agent prompt + `hk_draftCostEstimate`) |
| Projects / board | **Projekte & Plantafel** | **Back-office** (backend automation) |
| Invoices | **Rechnungen** | **Back-office** (backend automation) |

**Removed from the autonomy matrix:**
- **Notdienst** → not an autonomy level. Emergency stays a pure **forward-to-emergency-number** (already in the emergency block — the board does not intervene).
- **Termin verschieben** → folded into **Termine** (reschedule follows the appointments level).

Each capability is independent, so any permutation works (e.g. Termine L1, KVA L2, Rechnungen L3).

## 3. Capability × Level semantics

| | **Stufe 1 — Anfrage** | **Stufe 2 — Halbautomatisch** | **Stufe 3 — Vollautomatisch** |
|---|---|---|---|
| **Termine** (in-call) | Agent only records the request (`hk_createInquiry`); **does not offer or book** slots | Agent books a **reservation/pending**; team confirms (agent says "Bestätigung folgt") | Agent books **final** and confirms to the caller in the call |
| **KVA** (in-call) | Agent **does not offer or draft** a KVA; just records the wish | Agent **drafts** the KVA; team reviews & sends | Agent drafts and it's **auto-sent** to the customer (needs email) |
| **Projekte** (back-office) | No project created | On appointment confirm → project / board entry created as **draft** for review | Project / board entry **auto-created & finalized** on confirm |
| **Rechnungen** (back-office) | No invoice | On job/KVA completion → invoice **drafted** for review | Invoice **auto-generated & sent** |

**If a capability's toggle is OFF** → it behaves as "not available" (e.g. KVA off = agent never mentions KVAs). **Level 1 = the prompt is stripped of all suggest/offer/book language for that capability** (your topic-19 requirement).

## 4. Why the in-call vs back-office split
- The ElevenLabs agent can only do what its **tools** allow, and there are no project/invoice tools. Creating an invoice mid-call also makes no business sense (invoices come after the job).
- So **Termine + KVA** = the **prompt** changes (this is exactly your "we'll just use appointments and KVA for the prompt level").
- **Projekte + Rechnungen** = **backend automation** triggered by events (appointment confirmed, KVA accepted, job done), gated by their toggle + level. They are **not** in the agent prompt — which also **shrinks the prompt** (helps topic 23).

## 5. Schema migration (additive → pre-authorized)
Migration `0043_autonomy_per_capability.sql` — `ALTER TABLE agent_configs ADD COLUMN …`:
- `appointments_enabled bool default true`, `appointments_level int default 2 check (1..3)`
- `kva_enabled bool default true`, `kva_level int default 2`
- `projects_enabled bool default false`, `projects_level int default 2`
- `invoices_enabled bool default false`, `invoices_level int default 2`

**Backfill from existing data:** `appointments_level = kiki_level`, `kva_level = kiki_level`, `kva_enabled = (kva_automation_enabled OR kiki_level >= 2)`. Projects/invoices start **OFF** (new capabilities).

`kiki_level` and `kva_automation_enabled` are **left in place but dormant** (keeps the migration additive/reversible). A later cleanup migration can drop them once everything reads the new columns.

## 6. Prompt changes ([agent_config.py](backend/app/services/agent_config.py))
- Replace `render_autonomy_block(kiki_level)` with `render_autonomy_block(cfg)` that emits **two sub-blocks** into `{{KZ_AUTONOMY}}`:
  - **Termine** sub-block per `appointments_enabled` + `appointments_level`.
  - **KVA** sub-block per `kva_enabled` + `kva_level` (this replaces the autonomy sentence currently baked into the `hk_draftCostEstimate` tool card).
- Projekte/Rechnungen contribute **nothing** to the prompt.
- Emergency-forward wording stays in `render_emergency_block` (unchanged).

## 7. UI changes ([VerhaltenSection.tsx](frontend/src/components/kiki/VerhaltenSection.tsx))
- Replace the single level selector + static matrix with **four capability rows**, each = a **toggle** + a **Stufe 1/2/3** segmented control + a one-line description of what that level does for that capability.
- Keep Persona / Stimme / first_message / Begrüßung cards unchanged.
- **Remove** the standalone **KVA-Automatisierung** nav item + section (topic 21) — its behavior now lives in the KVA capability.

## 8. Backend logic changes
- `appointments.py` — booking status from `appointments_level` (L2 pending, L3 final); respect `appointments_enabled`.
- `post_call.py` — auto-confirm when `appointments_level == 3`.
- `cost_estimates.py` — KVA send from `kva_level` (drop the `kva_automation_enabled` dependency).
- `VerhaltenUpdate` ([kiki_zentrale.py:86](backend/app/api/routes/kiki_zentrale.py)) + `KzConfig` ([kikiApi.ts](frontend/src/lib/kikiApi.ts)) gain the 8 fields.
- `copilot/tools.py:146` help text updated.

## 9. Phasing
- **Phase 1 (now):** schema + UI (all 4 toggles/levels) + prompt (Termine, KVA) + remove KVA-Automatisierung + drop Notdienst/Reschedule from the matrix + wire booking/post-call/cost-estimate to the new columns. This fully delivers the **prompt-facing** intent of 19/21/22.
- **Phase 2 (follow-up):** the **back-office automation** for **Projekte** (auto-create project/board entry on confirm) and **Rechnungen** (auto-draft/send invoice on completion). In Phase 1 these toggles are saved but their automation is stubbed/"coming".

## 10. Decisions I need from you (before go-ahead)
1. **Projekte + Rechnungen = back-office automation, Phase 2** (config now, automation later) — agree? Or do you want their automation built in Phase 1 too?
2. **Level semantics table in §3** — correct as written? (Especially: Termine L2 = pending/team-confirms, L3 = final; KVA L3 auto-send needs a customer email.)
3. **Defaults**: Termine + KVA default **ON** at today's `kiki_level`; Projekte + Rechnungen default **OFF**. OK?
4. Keep `kiki_level`/`kva_automation_enabled` **dormant** now and drop them in a later cleanup migration — OK? (keeps this migration purely additive)

(Required-field priority = topic 8, and emergency-forward semantics, are related prompt items I'll handle as their own steps — not part of this migration.)
