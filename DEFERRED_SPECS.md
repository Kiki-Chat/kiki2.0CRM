# Deferred specs — ready to apply after your review

These are the changes I did **not** ship unattended because they either (a) change
inbound/outbound prompt **behaviour** on the safety-critical surface, (b) need a
**product decision**, or (c) require **live ElevenLabs writes / a live call**.
Each is specified to the file/line so it's a quick approve-and-apply.

Branch state already shipped (safe): onboarding system-tool sync, inbound token
dedup, outbound prompt cuts, additive outbound emergency escalation. Full suite
968 passed.

---

## B2 — Inbound: conditional-render disabled KZ blocks (token win for feature-off orgs)

**Goal:** when a feature is OFF for an org, its block renders **nothing** instead of
"you don't do X" prose. Saves ~200–600 tok for feature-off orgs on *every* inbound
call (and every outbound→handoff leg).

**Pattern (copy the two that already do it right):** `render_problem_description_block`
(agent_config.py:639) and `render_conversation_logic_block` (607) return `""` when off
and have **no template heading** — the token sits bare, so it vanishes cleanly. Apply
the same to the others: **move the heading text INTO the renderer's enabled-branch
output, delete the literal heading from the template, return `""` when disabled.**

| Block | Renderer | Template heading to move into renderer | Risk |
|---|---|---|---|
| Price | `render_price_info_block` (419) | `# Preise` (Wissensbasis) | low |
| Staff transfer | `render_staff_transfer_block` (834) | `## Weiterleitung an einen Mitarbeiter` (937) | low |
| Autonomy | `render_autonomy_block` (860) | `## Autonomie-Hinweis` (620) | low–med (keep the L1 "don't book" line — it's load-bearing) |
| Appointment categories | `render_appointment_categories_block` (653) | `## Termin-Kategorien` (800) — also gate on `appointments_enabled`/`scheduling_enabled` so message-only orgs emit nothing | low |
| **Emergency** | `render_emergency_block` (752) | `## Notfall-Definition` (119) **+ the fixed `## Vorgehen bei bestätigtem Notfall` procedure (template 122-138)** | **HIGH — safety-critical; needs transcript A/B before merge** |

**Verification:** render `render_prompt_for_org(name, org_id=None)` (all-disabled) and a
mock all-enabled cfg; assert no orphaned headings and the existing `{{…}}` guard still
passes. **Do emergency last and only with a transcript A/B** (it's what every inbound
call + every outbound handoff runs).

> **⚠️ 2026-06-22 — reassessed; B2 is NOT a quick change, do NOT ship partial.** Two
> blockers found on inspection: (1) most "disabled" branches are **active instructions**,
> not dead prose — price-off = "don't quote prices", autonomy-L1 = "don't book",
> scheduling-off = "don't book". Removing them *changes behaviour*. The genuinely-dead
> ones are only: the appointment-categories section when booking is off, and the emergency
> procedure when emergency is off. (2) Sections **cross-reference** each other: the Schritt-3
> booking pre-gate says *"siehe Abschnitt ## Termin-Kategorien"* (template:411), so removing
> the categories section leaves a **dangling reference**. → B2 done right needs a
> **region-conditional template engine** (honour the existing `<!-- MARKER -->…<!-- /MARKER -->`
> comments to strip a whole feature region + its cross-refs when off) + transcript A/B. That's
> a feature, not a token tweak. **B1 dedup stays the shipped safe inbound win.**

> **✅ 2026-06-22 — region engine now BUILT.** `_apply_feature_regions` +
> `<!-- FEAT:name -->` markers (agent_config.py), with the **byte-identical-when-ON**
> guarantee + a regression test. First region: **Notdienst** (emergency). Extending to the
> next features is now mechanical *where the region is cleanly separable*, plus a small
> reword where it's woven:
> - **Notdienst (within-hours sentence):** lines ~100-104 mix the core "normal flow" sentence
>   with the emergency nuance in one paragraph. Reword into two sentences, wrap the emergency
>   one in `FEAT:notdienst`. (The standalone procedure + outside-hours exception are already
>   gated.)
> - **Booking off:** wrap the Schritt-3 booking choreography + `## Termin-Kategorien` **together**
>   in `FEAT:booking` (gated on `appointments_enabled`/`scheduling_enabled`) so the pre-gate's
>   cross-reference goes with it; `render_scheduling_rules_block` already emits the authoritative
>   "don't book, take inquiry" instruction, so nothing is lost. Update the `# Ziel` step-5
>   reference to Schritt 3 in the same pass.
> - Each new region: add markers + one entry to the `features` map; the byte-identical-ON test
>   pattern (`tests/test_dynamic_prompt.py::test_notdienst_region_gated_in_real_template`)
>   protects it. Do one region per commit, eyeball the OFF render, A/B if behaviourally risky.

---

## B4 — Inbound: dedupe cross-section repeats (regression-sensitive)

Same rule stated in multiple places — collapse to one, keeping all load-bearing text:

- **Closing logic ×3:** `## Abschluss` (template 494-515) ≈ `# Guardrails` (598-614) ≈
  `end_call` card (782-798). Keep the verbatim closing scripts in `## Abschluss`; in
  Guardrails/end_call keep only a one-line pointer.
- **`identifyCustomer` re-call logic ×2:** Schritt 2 (321-378) and the tool card (654-662).
- **Booking choreography ×2:** Schritt 3 (447-492) and the `hk_bookAppointment` card.
  Keep the conversational sequence in Schritt 3; the param mechanics belong on the tool
  (see F).
- **Email rules ×2:** `## E-Mail-Erhebung` (623) and `# E-Mail-Versand` (808) + the per-tool
  `email` notes. Consolidate into one.
- **Datumsklarheit (892-902)** duplicates weekday rules already in Guardrails (588-591).

Each is behaviour-sensitive → apply one at a time, A/B against transcripts.

---

## D-autonomy — Outbound: respect the org's autonomy level (needs your product call)

Today outbound hardcodes L2 reservation phrasing (`_BASE_OUTBOUND` Leitplanken). To make
it respect the org's autonomy:

1. **Product decision — RESOLVED 2026-06-22 (Amber): L1 outbound = DON'T BOOK, match
   inbound.** An L1 org's outbound reminder only confirms / captures intent via
   `hk_createInquiry`; it must NOT call `hk_bookAppointment` / `hk_changeAppointment` /
   `hk_getAvailableAppointments`. The injected Termine line for L1 must say exactly that
   (reuse `render_autonomy_block`'s L1 branch, which already does). L2 = reserve (current
   wording), L3 = book directly.
2. **Occasion-aware injection:** inject the **Termine** autonomy line only for
   booking-capable occasions (appointment_reminder, maintenance_due, missed_callback, the
   3 click occasions). Do **not** inject the **KVA** autonomy line — no outbound occasion
   drafts KVAs, and it would contradict `kva_followup`'s task block ("du versendest KEINE
   Dokumente").
3. **Reconcile the contradiction:** change the hardcoded Leitplanken booking sentence to
   defer to the injected autonomy line (otherwise L3 "buche verbindlich" conflicts with
   "Ich reserviere…").

Reuse `render_autonomy_block(cfg)` (agent_config.py:860) via the `{anlass_regeln}` slot
that's now in `_BASE_OUTBOUND`. Mechanically small once (1) is decided.

---

## F — Tool cards → verbose ElevenLabs tool descriptions (needs LIVE EL writes + eval)

The inbound `# Werkzeuge` cards (template 623-806, ~3.5–6k tok) re-document each tool's
params in prose. Moving that onto the EL tool `description` fields improves selection
reliability, but **does not by itself cut per-turn tokens** (EL serializes tool schemas
every turn) — the win is **deleting the prompt cards after** the descriptions own the
guidance, plus tighter wording. Order (do NOT delete cards first):

1. Author rich English descriptions on each `hk_` tool in the EL workspace (live write).
   Port the two high-value logic chunks: `hk_identifyCustomer` re-call protocol (call again
   with `kundennummer`/`adresse`/`nachname`) and `hk_draftCostEstimate` fuzzy-match rule
   (≥1 content word; generic words don't match).
2. **A/B eval** against recorded transcripts that tool-calling quality holds.
3. Only then delete the corresponding prompt cards, leaving one-line orchestration pointers
   + the cross-tool sequencing rules (EL guidance: don't rely on descriptions alone).

This is the Phase-3 structural win; it touches the live agent so it can't run unattended.

### Paste-ready description text (the two highest-value ones)

**`hk_identifyCustomer` → Description field (EL workspace):**
> Identifiziert den Anrufer. PFLICHT als allererste Aktion jedes Gesprächs — ohne Parameter
> (nutzt die Caller-ID). ERNEUT aufrufen, sobald der Anrufer im Gespräch weitere Hinweise
> nennt: mit `telefonnummer` bei einem weitergeleiteten Anruf, sobald er seine eigene Nummer
> nennt; mit `kundennummer`, wenn er eine Kundennummer nennt; mit `adresse` (+ `nachname` bei
> mehreren Treffern) zur Adress-Identifikation, wenn Telefon/Kundennummer nicht greifen; mit
> nur `nachname` bei Rückruf auf einen offenen Gegenvorschlag. Liefert Name, Adresse, E-Mail,
> kommende Termine und offene Vorgänge des Bestandskunden.

**`hk_draftCostEstimate` → `positions` parameter description (EL workspace):**
> Liste der besprochenen Positionen. Leite sie SELBST aus dem Anliegen ab — frage den Anrufer
> NICHT "Wofür genau?". Jede `artikel`-/`description`-Position MUSS mindestens ein inhaltliches
> Vollwort enthalten (Gewerk oder Bauteil, z. B. "Heizung", "Dach", "Rohr", "Fenster") — rein
> generische Begriffe ("Reparatur", "Wartung", "Arbeitsstunde") matchen serverseitig NICHT.
> GUT: "Heizung Fehlerdiagnose vor Ort"; SCHLECHT: "Reparatur". Erfinde KEINE Preise.

(Author in English or German — the LLM handles both; German keeps it consistent with the rest.
Do NOT delete the matching prompt cards until an A/B confirms tool-calling holds.)

---

## Test calls / G — how to trigger (and the number caveat)

- **Number flag:** you wrote `+91787997839` (9 digits after +91); a valid IN mobile is 10
  digits and the established runtime-test target is **`+917879997839`**. Confirm the exact
  digits before any real dial.
- **Offline eye-test (safe, ready now):** `python backend/scripts/preview_outbound.py` prints
  the assembled outbound prompt for baseline / emergency-on / autonomy-L1 / both — so you can
  read exactly what each call would send, including the new blocks. No DB, no EL, no call.
- **Real call (your trigger, after confirming the number + a running backend):** dispatch one
  outbound occasion to the test number with dummy data via the existing pipeline
  (`send_single_outbound` → `place_outbound_call`). I did not place a live call: outbound is
  LIVE telephony and the number looked malformed. The `transfer_to_agent` handoff checks are in
  `TRANSFER_VERIFICATION_TESTPLAN.md`.

---

## Workstream 5 — Tools (the WorkPilot question)

- **Decided:** keep the 11 `hk_` tools, **merge none** (cancel+change merge would risk an
  enum mis-pick HARD-cancelling a real appointment vs the reversible proposal `change` does).
- **`hk_searchCustomerProjects` — DECLINED (Amber):** projects are internal/tradesman-facing,
  not for clients. Not building it.
- **`hk_sendKVA` — BUILT (backend, branch, 6 tests).** Emails an existing KVA; **gated to the
  fully-automatic KVA level (L3)** per Amber. Route `POST /api/elevenlabs/tools/send-cost-estimate`
  → `cost_estimates.send_cost_estimate`. **Remaining LIVE step (do with Amber):**
  1. Create the tool in the EL workspace, name `hk_sendKVA`, webhook → that route, params
     `costEstimateId` / `number` / `customerId` (all optional). Suggested description:
     *"Versendet einen bestehenden Kostenvoranschlag per E-Mail an den Kunden. Nutze dies, wenn
     der Anrufer ausdrücklich um Zusendung per E-Mail bittet. Sage NIE, du hättest etwas
     gesendet, ohne dieses Tool aufgerufen zu haben."*
  2. Add `"hk_sendKVA"` to `HK_TOOL_NAMES` (agent_config.py) so provisioning/repush attach it.
  3. Add a one-line prompt pointer in the KVA/Werkzeuge section (only meaningful at L3).
- **Build-first (not just a tool):** dunning (Mahnung) + maintenance-status — need backend
  capability before a tool makes sense.
