# ElevenLabs Sync Audit — Kiki-Zentrale Voice Agent

**Domain:** Kiki-Zentrale — Voice-Agent Configuration & ElevenLabs Sync
**Evidence base:** `CRM_EVALUATION_AUDIT/_data/kiki_deep.json` (syncMatrix, elevenlabsObservations, driftRisks, configSettings) + `CRM_EVALUATION_AUDIT/_data/rules/KIKI.json` (37 KIKI rules) + runtime evidence `CRM_EVALUATION_AUDIT/_data/elevenlabs_runtime.json` and `CRM_EVALUATION_AUDIT/_data/runtime_db.json`
**Audited agent:** `agent_5001ksahz3w7fhx90j71xr800py4` (org `kiki-test-007` / "Kiki Chat GmbH", provisioned 2026-06-03)
**Date:** 2026-06-17

---

## 1. Executive Summary

Kiki-Zentrale is the configuration console that drives a per-org ElevenLabs Conversational-AI voice agent. Operators change settings (prompt, voice, behavior, knowledge, emergency/phone, scheduling) and the backend reconciles those changes onto the live ElevenLabs agent. This audit maps **what actually syncs to ElevenLabs**, **what can overwrite existing agent state**, **the safety layer that protects every write**, and **the drift/staleness risks** that remain.

**Headline findings:**

- The write path is **defense-in-depth**. Every ElevenLabs PATCH passes through `patch_agent_safely`, which enforces a cross-org guard, a pre-write snapshot, an audio-event assertion, additive array merges, post-write verification with auto-rollback, and a full audit row. Of 37 codified KIKI rules, **36 are classified `WELL_IMPLEMENTED`** and 1 is `PARTIALLY_IMPLEMENTED` (KIKI-032, an intentional stub).
- **Most surfaces sync FULL**; two sync **PARTIAL** by design (`hk_* tool_ids` additive-only, `scheduling.business_hours` JSONB), and the audio client-event is protected so strongly it can only ever be **added, never removed**.
- The two **highest-severity drift risks** are operational, not safety-layer defects: (1) when `prompt_manual_override=True`, every config save **silently skips** the prompt repush, so the live agent can run a stale prompt indefinitely; (2) `sync_system_tools_for_org()` is **best-effort and swallows exceptions**, so a failed transfer-tool sync can leave DB and ElevenLabs diverged.
- **The ElevenLabs MCP cannot verify the full agent.** `get_agent_config` returns a flat 9-key view with **no `tools[]`, no `client_events[]`, and no webhook URL**. Tool registration, the `audio` client-event, and the prod webhook target are therefore **UNVERIFIED — requires runtime** (full ElevenLabs REST API or dashboard). Prior UAT recorded in `SESSION_HANDOVER` confirmed audio + 10–11 hk_ tools + prod webhook, but that is not re-verifiable from this session's payload.

---

## 2. Sync Matrix — What Syncs and What Can Overwrite

Legend for **Syncs**: **FULL** = change is reconciled onto ElevenLabs on save (immediate or background repush). **PARTIAL** = syncs additively or only partially (gaps noted). **NONE** = stored but never pushed. **UNKNOWN** = cannot be confirmed from available evidence.

| Surface | Syncs | Storage of record | Overwrite risk | Evidence |
|---|---|---|---|---|
| **Master Prompt** | FULL | EL `conversation_config.agent.prompt.prompt` (text **not** stored in DB; DB holds only the `prompt_manual_override` gate) | **LOW** — `prompt_manual_override` gate blocks auto-render from trampling hand-edits; first-run guard (`agent_provisioned_at`) blocks reprovision from overwriting customer edits | `agent_config.py:rerender_and_push_for_org()`; KIKI-007, KIKI-013 |
| **Voice ID** | FULL | EL only (`conversation_config.tts.voice_id`) — **no DB copy** | **MEDIUM** — no DB twin; readable only via `/agent-health` or `_el_read_state()`. If the EL agent is replaced, the voice setting is lost | `kiki_zentrale.py:_el_patch()`; *UNVERIFIED OBSERVATION: no `voice_id` column found in `agent_configs`/`organizations`* |
| **Language** | FULL | EL only (`conversation_config.agent.language`) | **LOW** — immediate EL PATCH on `PATCH /verhalten` | `kiki_zentrale.py:_el_patch()`; KIKI-025 |
| **First Message (stored)** | FULL | EL `conversation_config.agent.first_message`; per-call override available | **LOW** — synced immediately on `PATCH /verhalten`; per-call time-based variant injected via conversation-init | `kiki_zentrale.py:_el_patch()`; `conversation_init.py:_pick_welcome_message()`; KIKI-035 |
| **Persona Name (agent name)** | FULL | EL only (`agents.name`) — **no DB twin** | **LOW** — immediate EL PATCH on save; EL-only field with no DB twin that could drift | `patch_agent_safely(field_patches={name})`; KIKI-025 |
| **Instructions — Autonomy Levels (Termine/KVA)** | FULL | `agent_configs.appointments_level/kva_level/...` → rendered into prompt | **LOW** — DB write + background prompt repush | `render_autonomy_block()` → `rerender_and_push_for_org()`; KIKI-017 |
| **Instructions — Scheduling Rules** (lead time, buffer, parallel slots) | FULL | `agent_configs.(lead_time_*, buffer_minutes, …)` → prompt | **LOW** — DB + background repush | `render_scheduling_rules_block()`; KIKI-018 |
| **Instructions — Required Fields / Leitfaden** | FULL | `agent_required_fields` table → prompt | **LOW** — DB + background repush; concurrent-save guard | `render_required_fields_block()`; KIKI-023, KIKI-024, KIKI-029 |
| **Instructions — Appointment Categories** | FULL | `appointment_categories` table → prompt | **LOW** — DB + background repush | `render_appointment_categories_block()` |
| **Instructions — Conversation Logic (Wenn/Dann)** | FULL | `agent_configs.conversation_logic` (JSON) → prompt Schritt 1a | **LOW** — DB + repush. **RISK:** render-time compile failure **silently drops** the Schritt 1a block (returns `""`) with no user-visible error | `render_conversation_logic_block()`; KIKI-027 |
| **Emergency Configuration** | FULL | `agent_configs.emergency_*` → prompt + `transfer_to_number` built-in tool | **LOW** — DB + prompt repush + `transfer_to_number` tool sync | `render_emergency_block()` + `build_transfer_tool()`; KIKI-009, KIKI-010, KIKI-011 |
| **Phone / Forwarding Numbers** | FULL | `agent_configs.(forwarding_number, …)`, `organizations.existing_business_number` → prompt + transfer tool | **LOW** — DB + prompt repush + transfer-tool sync (best-effort, see drift) | `render_staff_transfer_block()` + `build_transfer_tool()` |
| **hk_* Tool IDs (≈11 tools)** | **PARTIAL** | EL `conversation_config.agent.prompt.tool_ids` (DB cache only, `_HK_TOOL_ID_CACHE`) | **LOW (additive)** — additive merge only; existing tool_ids never removed by provisioning. **RISK:** a tool deleted from the workspace **stays on the agent** until next reprovisioning | `configure_agent` B.2 `merge_arrays=[TOOL_IDS_PATH]`; KIKI-006 |
| **client_events: audio** | FULL | EL `conversation_config.conversation.client_events` | **NONE** — audio assertion **blocks any write that would remove it**; additive merge always adds it back | `assert_audio_event()` + `_compute_final_client_events()`; KIKI-003, KIKI-006 |
| **Knowledge Resources (URL/PDF)** | FULL | EL `knowledge_base[]` + Supabase Storage; `knowledge_resources` table tracks metadata | **LOW** — additive attach; remove is explicit. **RISK:** `elevenlabs_doc_id` can go stale if the EL doc is deleted out-of-band | `push_/remove_knowledge_resource_from_elevenlabs()`; KIKI-021, KIKI-030, KIKI-031 |
| **Price List KB Doc** | FULL | EL `knowledge_base` (text doc "Preisliste (Richtpreise)"); `agent_configs.price_list_doc_id` tracking | **MEDIUM** — reconcile-by-name heals orphans, **but** concurrent syncs can race on the GET→PATCH window (documented open risk) | `sync_price_list_kb()` `price_knowledge.py:85`; KIKI-019, KIKI-020 |
| **Conversation Initiation Webhook** | FULL | EL `platform_settings.workspace_overrides.conversation_initiation_client_data_webhook.url` + enabled flag (no DB; derived from `settings.backend_public_url`) | **LOW** — idempotent; `configure_agent` checks `cur_url`/`cur_enabled` before PATCH; **preserves existing `request_headers`** | `configure_agent` B.4 `agent_config.py:1205-1242`; KIKI-012, KIKI-036 |
| **Transfer to Number (built_in_tools)** | FULL | EL `conversation_config.agent.prompt.built_in_tools.transfer_to_number` | **LOW** — pushed on every Notdienst/Phone save. **RISK:** sync is **best-effort (swallows exceptions)** → silent DB↔EL divergence | `sync_system_tools_for_org()` → `build_transfer_tool()`; KIKI-011 |
| **Voicemail Detection (built_in_tools)** | FULL | EL `conversation_config.agent.prompt.built_in_tools.voicemail_detection` | **LOW** — always included in system-tools sync; hardened description hardcoded | `build_voicemail_tool()`; KIKI-033 |
| **Path A Override Flags** (`platform_settings.overrides`) | FULL | EL `platform_settings.overrides.conversation_config_override.agent.{first_message, language, prompt}` | **LOW** — idempotent; `override_flags_ok()` checked before write; post-verify confirms all three | `configure_agent` B.6 `agent_config.py:1263-1294`; KIKI-037 |
| **`agent_configs.scheduling` → business_hours** | **PARTIAL** | `agent_configs.scheduling` (JSONB) rendered into prompt `=== Geschäftszeiten ===` block | **MEDIUM** — JSONB not directly surfaced in the Kiki-Zentrale UI mapping; changes trigger prompt repush but the scheduling route is out of the Kiki-Zentrale scope | `_render_business_hours()`; `_fetch_kz_config()` selects `scheduling` |

### Surfaces that do NOT sync or are not stored
- **Master prompt text is never stored in the DB** — only the `prompt_manual_override` gate flag lives in `agent_configs`. ElevenLabs is the single source of truth for the rendered prompt body.
- **Voice ID and Persona Name have no DB twin** — EL-only. There is no automated recovery path if the EL agent is recreated (see §5 voice_id risk).

---

## 3. Safety Layer — Snapshot / Verify / Rollback / Audit

Every write to the ElevenLabs agent flows through **`patch_agent_safely()`** (`elevenlabs_agent.py`). The layers fire in this order; any failing guard aborts the write **before** the PATCH is sent, so a blocked write leaves no partial state.

| Stage | Rule | What it does | Failure behavior | Source |
|---|---|---|---|---|
| **1. Cross-org guard** | **KIKI-001** | DB-only check that the supplied `agent_id` equals the calling org's stored `organizations.elevenlabs_agent_id` | `CrossOrgAgentWriteError`; **no snapshot, PATCH, or audit row** is created | `elevenlabs_agent.py:276-289` |
| **2. Pre-write snapshot** | **KIKI-002** | `GET /v1/convai/agents/{id}` full config saved into `agent_config_snapshots`; snapshot id carried into the audit row | No-op short-circuit if the diff shows no changes; INSERT error aborts | `elevenlabs_agent.py:320-333` |
| **3. Audio-event assertion** | **KIKI-003** | Two-stage guard: early (explicit non-merge replacement) + final (merged client_events) **before** PATCH; ensures `audio` is present | `SilentAgentRiskError`; no PATCH or snapshot written | `elevenlabs_agent.py:111-117, 293-308` |
| **4. Additive array merge** | **KIKI-006** | `merge_arrays` paths union incoming with current (order-preserving, deduped) instead of replacing — protects `tool_ids` and `client_events` | n/a (mechanism) | `elevenlabs_agent.py:158-197` |
| **5. PATCH + post-write verify** | **KIKI-004** | Re-GET confirms: agent reachable, `audio` still present, all changed leaves applied (arrays superset / dicts subset / scalars equal), **tools array did not shrink** | On any mismatch → `_restore_full()` PATCHes the snapshot back; audit row stamped `rolled_back=True` | `elevenlabs_agent.py:349-411` |
| **6. Audit row** | **KIKI-005** | Every call (success / fail / rollback) writes `agent_writes_audit`: org_id, agent_id, actor_id, endpoint_label, snapshot_id, fields_changed, EL response status/excerpt, rolled_back (+ rolled_back_at/by) | n/a (always written) | `elevenlabs_agent.py:455-473` |
| **Manual rollback** | **KIKI-015** | `rollback_to_snapshot()` looks up the snapshot by **id AND org_id** (tenant-scoped); restore uses `merge_arrays=[]` (exact restore, not additive); marks the snapshot's non-rollback audit rows `rolled_back=True` | Snapshot not found / wrong tenant → `ElevenLabsWriteError` (safe no-op) | `elevenlabs_agent.py:476-518` |

### Concurrency & status protections
- **KIKI-014 — Concurrent-save serialization:** `kz_begin_agent_sync` atomically increments `agent_sync_seq` and flips status to `pending`; the background repush re-checks under a per-org lock and returns `superseded` if a newer save exists — preventing a slow stale push from landing an OLD rendered prompt.
- **KIKI-026 — Sync-stale coercion:** `GET /sync-status` coerces a `pending` status older than 300 s to `failed (timeout)` (read-only) so the loader banner cannot spin forever after a mid-push backend crash.

### Snapshot scope caveat (drift risk, not a defect)
- **KIKI-002 snapshots capture `conversation_config` + `name` only.** `platform_settings` (webhook URL, override flags, workspace_overrides) is **NOT captured** and therefore **NOT restored** on rollback. A failed B.4/B.6 step cannot be rolled back via snapshot — recovery relies on re-running `configure_agent` (idempotent) or direct EL UI access. (driftRisks: *Snapshot Restore Does Not Cover platform_settings*, severity MEDIUM.)

---

## 4. Surface-by-Surface Sync Verdict

### Prompt — **FULL** (overwrite risk LOW)
Rendered per-org from `agent_prompt_template.txt` + config tables, pushed on config changes via background repush. Two strong overwrite guards: **KIKI-007** (first-run-only prompt write gated by `agent_provisioned_at`) and **KIKI-013** (`prompt_manual_override` suppresses auto-render). **KIKI-008** enforces the template token contract — unfilled `{{...}}` (non-`{{system__`), legacy `wkp_shared_` names, and demo-identity residue (Husmann/Dreier/Buxtehude/Stader/04161) all raise `RuntimeError` before the prompt reaches a customer agent.
- **Runtime evidence (this session):** prompt length 66,209 chars, `looksRenderedFromTemplate=true`, **all 15 `{{COMPANY_*}}`/`{{KZ_*}}` placeholders substituted to "Kiki Chat GmbH"; only the 5 expected `{{system__*}}` runtime vars remain.** No stale demo names found.

### Voice — **FULL** (overwrite risk MEDIUM)
`voice_id` syncs immediately to EL but has **no DB twin**. **Runtime evidence:** `voice_id = v3V1d2rk6528UrLKRuy8`, settings `{stability:0.5, similarity_boost:0.8, temperature:0.3}`. **`model_id` is `null` in the flat MCP payload** — the TTS model tier cannot be confirmed. *Whether the persisted EL voice matches the operator's last save is UNVERIFIED — requires runtime read-back via `/agent-health` or EL REST.*

### Instructions / Behavior (Verhalten) — **FULL** (overwrite risk LOW)
Autonomy levels (KIKI-017), scheduling rules (KIKI-018), required fields/Leitfaden (KIKI-023/024/029), appointment categories, conversation logic (KIKI-027), emergency (KIKI-009/010/011) and phone all write DB + trigger a background prompt repush. **KIKI-025** enforces **EL-first write order** for persona/voice/language so a failed EL PATCH never leaves a DB-only divergence.

### Knowledge — **FULL** (overwrite risk LOW–MEDIUM)
URL/PDF resources attach additively and remove explicitly, scoped by org (KIKI-021), with a 20 MB PDF cap (KIKI-030) and URL duplicate guard (KIKI-031). The **price-list KB** reconciles by name (KIKI-020) to heal orphans. **KIKI-032 is the one `PARTIALLY_IMPLEMENTED` rule:** `hk_queryKnowledgeBase` routes to a backend stub that always returns `{success:True, answer:None}` — **actual RAG is performed natively by ElevenLabs** against the attached KB docs, not the backend webhook. This is intentional, not a bug.

### Tools — **PARTIAL** (overwrite risk LOW, additive)
`hk_* tool_ids` merge additively onto the agent (KIKI-006); existing IDs are never removed by provisioning. **Gap:** no ongoing cleanup — a tool deleted from the workspace remains on the agent until reprovisioning. System built-in tools (`transfer_to_number`, `voicemail_detection`) push on every relevant save; voicemail detection uses a hardened description (KIKI-033) to stop false fires on live humans.
- **UNVERIFIED — requires runtime:** the MCP `get_agent_config` returned **`tools.count = 0` / `tools.names = []`**. The hk_ tool set is referenced by name inside the prompt but **not confirmed as registered tool configs** in the retrieved payload. Tool registration must be verified via the full EL REST API or dashboard.

### Conversation Settings — **FULL** (overwrite risk LOW)
First message (KIKI-035 time-based override), language, and the B.6 Path A override whitelist (KIKI-037) all sync FULL and idempotently.

### client_events — **FULL** (overwrite risk NONE for `audio`)
The `audio` client-event is the most strongly protected surface: **KIKI-003** blocks any write that would remove it and **KIKI-006** always merges it back.
- **UNVERIFIED — requires runtime:** the flat MCP payload returned **`clientEvents = null` and `audioEventPresent = false`**. This is an **MCP payload limitation, not evidence of a silent agent** — the flat 9-key view omits the `client_events[]` array entirely. Audio-event presence on the live agent must be checked via full EL REST/dashboard. (Prior UAT in `SESSION_HANDOVER` recorded audio present.)

### Webhook — **FULL** (overwrite risk LOW)
The conversation-initiation webhook is set once at provisioning (B.4), idempotent on re-run, and **preserves existing `request_headers`** including the `X-HeyKiki-Secret` (KIKI-036). At call connect, `POST /conversation-init` looks up the caller in `customers` (org-scoped) and returns dynamic variables + optional first-message override (KIKI-012). Tool/webhook auth is resolved by `X-HeyKiki-Secret` with an `_agentId` fallback (KIKI-016).
- **UNVERIFIED — requires runtime:** `webhookUrl = null` and `webhookPointsAtProd = null` in the retrieved config. **Whether the agent points at the prod Railway backend (`https://backend-production-3f88a.up.railway.app`) or a stale/localhost URL is not confirmable from the MCP payload** and must be checked via full EL REST/dashboard.

---

## 5. Drift & Stale-State Risks

Ranked by severity from `kiki_deep.json:driftRisks`. The two HIGH risks are operational behaviors, not safety-layer defects.

| # | Area | Severity | Risk | Mitigation | Source |
|---|---|---|---|---|---|
| 1 | **Prompt vs. EL drift on manual override** | **HIGH** | With `prompt_manual_override=True`, **every** Kiki-Zentrale config save (required fields, categories, emergency, scheduling) **silently skips** the EL prompt repush. The agent keeps running the stale hand-edited prompt even when config would materially change behavior (e.g. emergency disabled but prompt still instructs transfer). | **None automated.** Operator must re-edit the prompt or clear the override flag. The Kiki-Zentrale UI should warn about this state. | `agent_config.py:1595-1600` |
| 2 | **System-tools sync best-effort failure** | **HIGH** | `sync_system_tools_for_org()` swallows exceptions and only logs a warning. A failed sync after a Notdienst/Phone save leaves EL `built_in_tools` stale while the DB is already updated → agent may use **old transfer targets**. | The sync-status banner reports `agent_sync_status='failed'` for the triggering save; operator can retry via `POST /sync-status/retry`. | `agent_config.py:1474-1478`; `kiki_zentrale.py:98-103` |
| 3 | **hk_* tool-ID cache staleness** | MEDIUM | A tool renamed/deleted in the EL workspace stays in `_HK_TOOL_ID_CACHE` for up to the 3600 s TTL; within that window a provisioning call may merge a stale id that no longer exists in the workspace. | Cache refresh triggers on any required-name miss with full eviction (clear+update); TTL ensures eventual convergence. | `agent_config.py:112-176` |
| 4 | **Concurrent price-list KB sync race** | MEDIUM | Two concurrent `sync_price_list_kb` calls for the same org (toggle + catalog save) hit the GET→PATCH window without a lock; both may create fresh text docs, one PATCH wins, the other doc is orphaned. | Reconcile-by-name on the next sync removes orphans; `price_list_doc_id` may transiently reference the losing doc. | `price_knowledge.py:85-86` |
| 5 | **Snapshot restore omits `platform_settings`** | MEDIUM | `_restore_full()` restores only `conversation_config + name`. Webhook URL, override flags, and workspace_overrides are **not** snapshotted → a failed B.4/B.6 step cannot be rolled back via snapshot. | B.4/B.6 are additive/idempotent — re-running `configure_agent` resets them; manual `platform_settings` rollback needs direct EL UI. | `elevenlabs_agent.py:447-452` |
| 6 | **EL-side edits between snapshot and rollback** | MEDIUM | If a tradesperson manually edits the EL agent between snapshot and rollback, the rollback overwrites those manual changes. | `agent_writes_audit` shows what changed and when; manual coordination required. | `elevenlabs_agent.py:476-518` |
| 7 | **Conversation-logic compile failure drops Schritt 1a** | MEDIUM | A `conversation_logic` tree that fails to compile at render time makes `render_conversation_logic_block()` swallow the exception and return `""` → the Schritt 1a block **vanishes** from the live prompt with no user-visible error. | Validation runs at save time; the residual risk is a schema change that breaks already-stored data. | `agent_config.py:607-609` |
| 8 | **`voice_id` not persisted in DB** | LOW | Voice is stored only in EL. If the EL agent is deleted/recreated or an account migration occurs, the voice setting is lost with no DB record. | *UNVERIFIED OBSERVATION:* may be re-readable from EL GET and re-applied; no automated recovery exists. | *UNVERIFIED — based on `_el_patch()` `kiki_zentrale.py:330-349`* |
| 9 | **Process-local repush lock** | LOW | `_REPUSH_LOCKS` is a process-local `defaultdict(threading.Lock)`. The last-write-wins serialization for overlapping saves holds only within one process; across processes two saves can race. | `agent_sync_seq` DB RPC provides last-write-wins at the status-banner level; overwrite risk is process-scoped. **Note:** memory context indicates a single Railway process today, so the multi-process window is not currently open. | `agent_config.py:1546-1547` |

### Runtime data-quality drift (from `elevenlabs_runtime.json` / `runtime_db.json`)
These are **content** drift, not sync-mechanism drift — the sync faithfully pushed test/garbage data into the live agent:
- **Appointment-category test garbage:** `"ruskin"` (33 min, note "rusk to the bond") and `"Pipe isssue"` [sic, triple-s] (60 min, English note) — manual kiki-test-007 entries with typos in an otherwise German prompt.
- **`KZ_CONVERSATION_LOGIC` mixed-language test text:** English branching instructions ("Wenn a supplier is calling", "What is your client number") embedded in the German prompt.
- **Org contact email = `dixitrahul825@gmail.com`** — the designated mail test account, not a real business email.

> These appear because the agent is the **kiki-test-007 test org**; they confirm the sync pipeline is faithfully reflecting DB/config state (not a sync defect), but would be unacceptable on a real customer agent.

---

## 6. UNVERIFIED — Requires Runtime (Live Round-Trip)

The ElevenLabs MCP `get_agent_config` returns a **flat 9-key view** (`agent_id, name, language, first_message, prompt, temperature, voice_id, stability, similarity_boost`) — it omits `tools[]`, `client_events[]`, `conversation_config` nesting, and webhook config. The following therefore **cannot be confirmed from this session's evidence** and require a live round-trip against the full ElevenLabs REST API or dashboard:

| Item | What the MCP payload showed | What must be verified live |
|---|---|---|
| **hk_* tool registration** | `tools.count = 0`, `tools.names = []` | That ~10–11 hk_ tools are actually registered as agent tool configs (not just named in the prompt) |
| **`audio` client-event presence** | `clientEvents = null`, `audioEventPresent = false` | That the `audio` client-event is present on the live agent (omission here is an MCP limitation, not a silent agent) |
| **Webhook target** | `webhookUrl = null`, `webhookPointsAtProd = null` | That the conversation-init webhook points at the **prod Railway backend**, not localhost/stale |
| **TTS model tier** | `voice.modelId = null` | The actual TTS `model_id` configured on the agent |
| **Voice persisted vs. last save** | `voice_id` present, no DB twin | Round-trip read-back to confirm EL voice matches the operator's last-saved value |
| **Live call behavior** | not executable from this worktree (no backend `.env`) | Fire-test-call (`scripts/fire_test_call.py`) and force-resync (`scripts/force_sync_test_agent.py`) require prod env |

Prior UAT recorded in `SESSION_HANDOVER` confirmed **audio present + 10–11 hk_ tools + prod webhook**, but that evidence is external to this session's payload and is not independently re-verifiable here.

---

## 7. Appendix — KIKI Rule Index (referenced in this audit)

| Rule | Name | Classification | Conf. |
|---|---|---|---|
| KIKI-001 | Cross-Org Agent Write Guard | WELL_IMPLEMENTED | 98 |
| KIKI-002 | Pre-Write Snapshot | WELL_IMPLEMENTED | 97 |
| KIKI-003 | Audio Event Assertion (Silent Agent Guard) | WELL_IMPLEMENTED | 98 |
| KIKI-004 | Post-Write Verification and Auto-Rollback | WELL_IMPLEMENTED | 97 |
| KIKI-005 | Agent Write Audit | WELL_IMPLEMENTED | 97 |
| KIKI-006 | Additive Array Merge for tool_ids and client_events | WELL_IMPLEMENTED | 96 |
| KIKI-007 | Prompt Write Gated by agent_provisioned_at | WELL_IMPLEMENTED | 95 |
| KIKI-008 | Prompt Template Token Contract Enforcement | WELL_IMPLEMENTED | 95 |
| KIKI-012 | Conversation Initiation Webhook — Caller Lookup / Dynamic Vars | WELL_IMPLEMENTED | 90 |
| KIKI-013 | Prompt Manual Override Flag — Auto-Render Suppression | WELL_IMPLEMENTED | 92 |
| KIKI-014 | Concurrent Save Serialization via agent_sync_seq | WELL_IMPLEMENTED | 88 |
| KIKI-015 | Snapshot-Scoped Rollback (org tenancy guard) | WELL_IMPLEMENTED | 93 |
| KIKI-016 | Tool Resolution Auth (X-HeyKiki-Secret or _agentId Fallback) | WELL_IMPLEMENTED | 92 |
| KIKI-017 | Autonomy-Level Prompt Rendering (Termine and KVA) | WELL_IMPLEMENTED | — |
| KIKI-018 | Scheduling Rules Rendering — appointments_enabled Gate | WELL_IMPLEMENTED | — |
| KIKI-020 | Price List KB Reconcile-by-Name | WELL_IMPLEMENTED | 88 |
| KIKI-021 | Knowledge Resource Org Scoping | WELL_IMPLEMENTED | 93 |
| KIKI-025 | EL-First Write Order for Verhalten (Persona/Voice/Language) | WELL_IMPLEMENTED | 90 |
| KIKI-026 | Sync-Stale Coercion (pending → failed after 300 s) | WELL_IMPLEMENTED | 88 |
| KIKI-027 | Conversation Logic Compiled Output Cap | WELL_IMPLEMENTED | 85 |
| KIKI-030 | PDF Knowledge Resource 20 MB Upload Limit | WELL_IMPLEMENTED | — |
| KIKI-031 | Knowledge URL Duplicate Guard | WELL_IMPLEMENTED | 88 |
| KIKI-032 | queryKnowledgeBase Tool — Native EL KB, Not Backend Lookup | **PARTIALLY_IMPLEMENTED** | 95 |
| KIKI-033 | Voicemail Detection Tool — Hardened Description | WELL_IMPLEMENTED | 88 |
| KIKI-035 | Welcoming Message Time-Based Override | WELL_IMPLEMENTED | 87 |
| KIKI-036 | B.4 Webhook Provisioning — Preserves request_headers | WELL_IMPLEMENTED | 90 |
| KIKI-037 | B.6 Path A Conversation Config Override Whitelist | WELL_IMPLEMENTED | 90 |

*KIKI.json codifies 37 rules total; 36 `WELL_IMPLEMENTED`, 1 `PARTIALLY_IMPLEMENTED` (KIKI-032). Rules not listed above (KIKI-009/010/011/019/022/023/024/028/029/034) govern emergency E.164 validation, transfer dedup, price-info guards, admin gating, locked/stale required-field guards, AI-generation rate limiting, and org-disabled gating — adjacent to but outside the prompt/voice/knowledge/tools/webhook sync surfaces audited here.*

---

*Sources: `CRM_EVALUATION_AUDIT/_data/kiki_deep.json`, `CRM_EVALUATION_AUDIT/_data/rules/KIKI.json`, `CRM_EVALUATION_AUDIT/_data/elevenlabs_runtime.json`, `CRM_EVALUATION_AUDIT/_data/runtime_db.json`. Findings labeled "UNVERIFIED — requires runtime" depend on a live ElevenLabs round-trip (full REST API or dashboard) and could not be confirmed from the flat MCP payload available this session. No rules were invented; all rule IDs are preserved verbatim.*
