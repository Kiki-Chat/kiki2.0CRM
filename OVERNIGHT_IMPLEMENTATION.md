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

### Batch C — outbound prompt cuts ✅
- `outbound_occasions.py` `_BASE_OUTBOUND`: replaced the 8-line "## Verfügbare Werkzeuge" prose tool list with a 1-line pointer (it never actually whitelisted — no `tool_ids` override is sent, and ElevenLabs already injects each attached tool's schema; kept the two real outbound steers: `transfer_to_agent` for off-topic, don't re-identify). Compressed the verbose Mailbox heuristic (the platform enforces voicemail detection).
- Base outbound prompt: ~1,277 → ~1,069 tokens (~16%); `{company}/{kunden_name}/{task_block}` slots verified intact.
- **Deferred C2** (task-block tail trimming): only one task block ships per call, so the cross-occasion boilerplate saving is ~15–25 tok/call — not worth the per-occasion regression risk unattended. Documented for review.

### Batch D (partial) — outbound emergency escalation (ADDITIVE, gated) ✅
- `outbound_occasions.py`: added a `{anlass_regeln}` slot to `_BASE_OUTBOUND` + `assemble_system_prompt`, and `_render_outbound_emergency(cfg)`. `build_call_content` now injects a concise emergency-escalation note **only when the org has the Notdienst enabled** (`emergency_enabled`), using the org's configured keywords + Notdienst number; falls back to an urgent `hk_createInquiry` when no number is set. Defensive: any config-fetch failure (or no DB, e.g. unit tests) → empty block → unchanged base behaviour.
- **Why:** closes a real safety gap — previously an emergency surfacing DURING any outbound call (reminder/payment/review) was not escalated, even though `transfer_to_number` is attached on the outbound leg. Worded conservatively (confirm once, escalate only on clear emergency).
- Verified by rendering all 3 states (off → base unchanged; on+number → transfer_to_number; on+no-number → urgent inquiry). Full backend suite: **968 passed, 0 failed**.
- **Deferred D-autonomy** (make outbound respect L1/L3 autonomy wording): needs a per-occasion design decision (e.g. should an L1 "don't book" org's reminder be allowed to book at all?) + reconciling the hardcoded L2 Leitplanken line + avoiding contradictions with non-booking occasion task blocks (kva_followup etc.). Spec in `DEFERRED_SPECS.md` — needs your product call, NOT shipped unattended.

_(further batches appended below as completed)_
