# Overnight implementation — prompt-engine optimization + transfers + onboarding

Branch: `feature/prompt-engine-optimization` (off `claude/infallible-lamarr-93d6e2`).
Started 2026-06-22. **No deploys, no live ElevenLabs writes, no real outbound calls** (outbound is LIVE). All changes are code-only, UAT, reversible.

This file is the morning report. Each batch is committed separately so you can review/revert independently.

---

## Scope decisions

**Doing autonomously (code-only, verifiable on branch):**
- A. Onboarding/sync: provision attaches system tools (B.7) + force-resync re-syncs them.
- B. Inbound prompt: delete duplicate-rendered tokens, conditional-render disabled KZ blocks, inline SERVICE_AREA constant, safe dedupes.
- C. Outbound prompt: delete prose tool-list, hoist cross-occasion boilerplate, compress mailbox heuristic, dedupe.
- D. Outbound KZ injection: conditionally inject autonomy + emergency blocks into the outbound override.
- E. Instrumentation: rendered prompt token-count logging.

**Deferred (need live EL writes / live calls / eval — documented, NOT executed):**
- F. Inbound tool-cards → verbose EL tool `description` relocation. Needs patching live EL tool defs + an A/B eval; deleting the cards without that loses guidance. Prepared as a documented migration, not fired.
- G. `transfer_to_agent` self-transfer verification (does the per-call override drop + do `dynamic_variables` survive). Needs ONE controlled live outbound call. Test plan written in `TRANSFER_VERIFICATION_TESTPLAN.md`, not executed.

---

## Progress

### Batch A — onboarding + system-tool sync robustness ✅
- `backend/app/services/agent_config.py` `configure_agent`: added **B.7** — calls `sync_system_tools_for_org(org_id)` so every newly-provisioned org gets `transfer_to_number` / `transfer_to_agent` / `voicemail_detection` from day one (previously only attached on a later Notdienst/Telefon save). Idempotent + best-effort.
- `backend/app/api/routes/kiki_zentrale.py` `_force_resync_bg`: now also calls `sync_system_tools_for_org` so the "Force Resync" drift-recovery button repairs the call-bridge tools, not just the prompt.
- Result: onboarding (super-admin manual OR API) now pushes the FULL agent surface — prompt + hk_ tools + system tools + webhook + audio + overrides whitelist — in one provision. Closes the two sync gaps.

### Batch B1 — inbound prompt: dedup double-rendered tokens ✅
- `agent_prompt_template.txt`: `render_prompt_for_org` fills **every** occurrence of a token (`text.replace`), so `{{KZ_EMERGENCY}}` (lines 120 + 927) and `{{BUSINESS_HOURS}}` (45 + 924) were each emitting their full rendered block **twice**. Removed the duplicate copies from the `# Wissensbasis` footer (the operative copies under `## Notfall-Definition` and `=== Geschäftszeiten ===` remain). Pure win, zero behavior change — verified the template still renders with no orphaned tokens and each block now renders once.
- Emergency block when enabled is ~480 tok; this alone removes ~480 + the rendered hours from every inbound prompt (and therefore from every outbound→handoff leg).

### NOTE on inbound conditional-rendering (disabled-feature blocks) — deliberately conservative
The disabled-feature blocks (emergency/price/autonomy/staff-transfer) currently emit "you don't do X" prose instead of `""`. Making them render nothing is real token savings BUT touches the **safety-critical** inbound prompt (esp. the emergency procedure region, which is fixed template text around the token, not just the token). Per the project's own guardrail ("change one lever at a time, A/B against transcripts"), I am NOT restructuring the emergency region unattended. The dedup above is the safe inbound win; the conditional-render rework is documented as a reviewed follow-up in this file's "Deferred" notes.

_(further batches appended below as completed)_
