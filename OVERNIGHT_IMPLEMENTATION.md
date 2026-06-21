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

_(further batches appended below as completed)_
