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

1. **Product decision (yours):** should an **L1 ("don't book") org's** outbound
   appointment-reminder be allowed to book/reschedule at all, or only capture intent via
   `hk_createInquiry`? (Inbound L1 = don't book. Consistency says outbound L1 shouldn't
   either — but that changes what a reminder call can do.)
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

---

## Workstream 5 — Tools (the WorkPilot question)

- **Decided:** keep the 11 `hk_` tools, **merge none** (cancel+change merge would risk an
  enum mis-pick HARD-cancelling a real appointment vs the reversible proposal `change` does).
- **Optional net-new (your go):**
  - `hk_searchCustomerProjects` over the PR- layer — customers asking "wie läuft mein
    Bauvorhaben?" currently can't be answered (`hk_searchCustomerInquiries` only sees
    inquiries). Backend: a thin service + route (code-only) + an EL tool def (live write).
  - `hk_sendKVA` — let the agent send an existing estimate mid-call (today only autonomy
    sends). Backend exists (`cost_estimates` send); needs a tool wrapper + EL tool def.
- **Build-first (not just a tool):** dunning (Mahnung) + maintenance-status — need backend
  capability before a tool makes sense.
