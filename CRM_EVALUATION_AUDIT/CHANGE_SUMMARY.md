# CHANGE SUMMARY — Before → After (this session)

*Concise per-area. **[int]** = internal/code-or-DB (invisible to customer). **[ext]** = externally observable (UI/agent/email/invoice). Branch `claude/optimistic-wright-553e50`. Batches 1–9 are LIVE in prod; the pay-upfront block is committed but HELD for your test → merge → migrate.*

## Batch 1 — Kiki-Zentrale undo/rewind & drift
- **[int]** Rollback restored only the prompt/voice (conversation_config) → **now also restores the webhook + override flags** (real recovery).
- **[ext]** No manual undo → **"Stände" tab: revert to any past snapshot** + change history.
- **[ext]** Hand-edited prompt silently drifted from settings → **amber drift banner + "Mit Einstellungen synchronisieren"**.
- **[int]** Transfer-tool sync failures were swallowed → **surfaced** (`tools_synced` flag, retry).

## Batch 2 — Onboarding reliability
- **[ext]** No check that a new org's agent was fully set up → **super-admin "Agent-Zustand" board + 7-point verify gate** (tools, webhook=prod, audio, prompt, overrides, phone).
- **[int]** Provisioning hard-failed (400) if no phone was bound → **graceful, with a clear message**.

## Batch 3 — Security (DB) **[int]**
- 20 tables had RLS on but **no policy**; one function had a mutable search_path; an internal function was RPC-callable → **16 org-scoped RLS policies added, search_path pinned, function locked down** (4 secret/system tables kept deny-all on purpose). Advisories ~24 → 6 (all intentional).

## Batch 4 — Receptionist correctness
- **[ext]** Returning caller on their **2nd number** was treated as new → **phone2 now matched**.
- **[ext]** Agent couldn't say "which job?" → **caller's open cases are surfaced to the agent on identify**.
- **[ext]** `queryKnowledgeBase` returned a dead "no answer" stub → **real price/Preisliste lookup + honest fallback**.
- **[ext]** Missed calls vanished → **recorded + shown as an Open Action (callback)**.
- **[ext]** **Bug fixed:** earliest-appointment-time was skipped when "now" was a weekend → could offer too-early slots; now correct.

## Batch 5 — Technician & planning board
- **[ext]** Employee `activity_area`/`auto_assign` did nothing → **post-call auto-assignment by area now works**.
- **[ext]** Planning board people-filter was all employees → **"Techniker" filter + cards show the assigned technician**.
- **[int/ext]** Technician portal links never expired/audited → **30-day expiry, first-view/IP audit, admin token-rotation, rate-limited** (existing links unaffected). Dispatch now **requires an actual technician**.

## Batch 6 — Invoicing & money
- **[ext]** Skonto was saved but **never shown** → **"abzgl. X% Skonto" + "Zahlbetrag bei Zahlung in N Tagen"** on the invoice/PDF (amount due unchanged).
- **[ext]** New invoices were near-empty → **auto-fill customer (name/Nr/USt-IdNr/address) + case Betreff + all KVA fields**.
- **[int]** Auto-invoice-on-completion was dead code → **wired (draft-only, OFF by default toggle)**.
- **[ext]** Could double-invoice a KVA → **blocked (409)**; expired KVA could still be accepted → **blocked (409)**; catalog re-import **doubled** the list → **upsert by article-number** (updates, no doubling); per-doc-type numbering fixed.

## Batch 7 — Billing/copilot
- **[int]** Copilot AI spend was **unbounded** (a monthly cap existed but was never enforced) → **enforced on chat + confirm (429 at cap, $25 default)**.
- **[int]** Usage metering **under-counted ~2 h/month** (UTC-vs-Berlin period boundary) → **fixed**; the 80%-usage warning now has tests.

## Batch 8 — Open Actions / dashboard
- **[ext]** The "Termin storniert" card's button **always errored (409)** → **now acknowledges cleanly**.
- **[ext]** A reschedule the system couldn't auto-match was **invisible** → **shows as a "Terminänderung zuordnen" Open Action**.
- **[int]** A failed reschedule-proposal stamp was silently swallowed → **logged**.
- **[int]** Customer numbers could drift / go blank → **single `KI-` formatter + CSV/PATCH guards**.

## Batch 9 — Hygiene **[int]**
- Free-text fields that render into the agent prompt were unbounded → **trim + length caps** (so junk/over-long text can't reach the live prompt).

## Pay-upfront strategy (this turn — held for your test)
- **[int]** 14-day trial was **default-ON** on every checkout → **trial removed** (no `trial_period_days` ever).
- **[int]** CRM always re-rendered the agent on provision (would **clobber an n8n-built agent**) → **bind-only mode** (`agent_externally_managed`): stores agent_id + number, runs verify, **skips** configure_agent. New super-admin `bind-agent` endpoint for re-binding.
- **[int]** A paid customer was never tied to their org by phone → **email + mobile webhook tie**: on `checkout.session.completed`, if not already linked, auto-link the org when **email AND mobile both match** (email-only → queued for super-admin review).
- **[ext]** No self-serve plan **upgrade/downgrade** exists (confirmed) — the Stripe billing portal already blocks plan change; no change needed.

## What stays EXTERNAL (not CRM code)
- **[ext]** Marketing website: onboarding form, collects company + **email + mobile + plan**, takes the upfront Stripe payment, redirects to the CRM.
- **[ext]** **n8n**: creates the ElevenLabs agent + the 11 `hk_` tools + the German prompt + buys/assigns the phone number, sets the conversation-init webhook to the **prod backend URL + `X-HeyKiki-Secret`**, then calls the CRM provision/bind (it already holds the master secret).
- **[ext]** Stripe dashboard: LIVE product/price catalog (run `ensure_catalog()` once with the live key), Stripe Tax registration, webhook endpoint + signing secret pointed at the prod backend.
- **[ext]** Supabase dashboard: enable leaked-password protection (audit item 3.4).
