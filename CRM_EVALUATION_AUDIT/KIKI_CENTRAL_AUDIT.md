# KIKI-ZENTRALE AUDIT — Voice-Agent Configuration Subsystem

*Generated 2026-06-17 from `_data/kiki_deep.json` + `_data/rules/KIKI.json` (37 rules) + runtime evidence. Kiki-Zentrale is the per-org console that configures the ElevenLabs Conversational-AI voice agent ("Kiki"). This audit maps every configurable setting, where it is stored, what syncs to ElevenLabs, the write-safety layer, and the drift/staleness risks that remain.*

Companion: [ELEVENLABS_SYNC_AUDIT.md](ELEVENLABS_SYNC_AUDIT.md) (sync mechanics) · KIKI-prefixed rules in [BUSINESS_RULES.md](BUSINESS_RULES.md).

---

## 1. Overview & the write-safety layer

Operators change settings in Kiki-Zentrale; the backend reconciles those changes onto the live ElevenLabs agent. Of **37 codified KIKI rules, 36 are `WELL_IMPLEMENTED`** and 1 (`KIKI-032`, the knowledge-base stub) is `PARTIALLY_IMPLEMENTED`. The defining strength of the subsystem is that **every ElevenLabs write passes through `patch_agent_safely()`** (`elevenlabs_agent.py`), which enforces:

1. **Cross-org guard** — refuses to write to an agent that doesn't belong to the org.
2. **Pre-write snapshot** — captures `conversation_config` + `name` into `agent_config_snapshots` (**565 rows live** in the test DB).
3. **Audio-event assertion** — `assert_audio_event()` blocks any write that would drop the `audio` client-event (silent agent otherwise).
4. **Additive array merges** — `tool_ids`, `client_events` etc. are merged, never blind-overwritten.
5. **Post-write verify + auto-rollback** — `_verify()` re-reads the agent; on mismatch it restores the snapshot.
6. **Full audit row** — every write logged to `agent_writes_audit` (**564 rows live**).

This is genuine defense-in-depth and the reason the subsystem rates highly. The residual risks (§4) are **operational** (stale-prompt gates, best-effort tool sync) rather than safety-layer defects.

---

## 2. Configuration Settings Inventory (19)

| Setting | UI Source (API) | Storage of record | DB Table | External Sync | Runtime Impact |
|---|---|---|---|---|---|
| **Persona Name** | `PATCH /verhalten` | ElevenLabs `agents.name` | — (no DB twin) | Immediate EL PATCH | Agent display name; no prompt effect |
| **First Message** | `PATCH /verhalten` | EL `agent.first_message` (+ per-call override) | `agent_configs.welcome_message(s)` | FULL; per-call variant via `/conversation-init` | Greeting spoken on connect |
| **Voice ID** | `PATCH /verhalten`, `GET /voices` | EL `tts.voice_id` | — (no DB copy) | FULL; EL-only | TTS voice on all calls |
| **Language** | `PATCH /verhalten` | EL `agent.language` | — | FULL; EL-only | Agent language model |
| **Master Prompt** | auto-rendered from template+config; super-admin hand-edit via `PATCH /prompt` | EL `agent.prompt.prompt` (text NOT in DB) | `agent_configs.prompt_manual_override` (gate flag) | FULL on config change (background repush); **SKIPPED when `prompt_manual_override=True`** | Entire system prompt; drives all behavior |
| **hk_* Tool IDs (11)** | provisioning / sync-agent-config (no UI) | EL `agent.prompt.tool_ids` | — (cache only) | **PARTIAL** — additive merge on provisioning; no ongoing cleanup | Which tool webhooks the agent can call |
| **Knowledge Base (URL/PDF)** | `PATCH /knowledge-resources/*` | EL `knowledge_base[]` + Supabase Storage | `knowledge_resources` | FULL; add/remove immediate; reindex = remove+recreate | Native RAG source for company answers |
| **Price List KB** | `PATCH /price-info` + catalog changes | EL `knowledge_base` (text doc "Preisliste") | `agent_configs.price_list_doc_id`, `price_info_enabled` | FULL reconcile-by-name; **PARTIAL** (concurrent race) | ON ⇒ agent quotes Richtpreise; OFF ⇒ cannot |
| **Conversation-Init Webhook** | provisioning B.4 (no UI) | EL `platform_settings…webhook.url` | — (from `backend_public_url`) | FULL; set once, idempotent | Fires per call; delivers dynamic vars + first-msg override |
| **client_events: audio** | provisioning B.5 (no UI) | EL `conversation.client_events` | — | FULL; **additive — never removed** (assertion-guarded) | Required for any audio output |
| **Autonomy Levels** (appointments/kva) | `PATCH /verhalten` | `agent_configs.appointments_level, kva_level, …` | `agent_configs` | FULL; DB + background prompt repush | Whether/how agent books appts & drafts KVA (L1–L3) |
| **Emergency Config** | `PATCH /emergency` | `agent_configs.emergency_*` | `agent_configs` | FULL; DB + prompt repush + `transfer_to_number` tool | Notdienst keywords, transfer target, surcharge notice |
| **Phone / Forwarding** | `PATCH /phone` | `agent_configs.forwarding_number`, `organizations.existing_business_number` | `agent_configs`, `organizations` | FULL; DB + prompt repush + transfer tool | Staff-transfer + emergency fallback numbers |
| **Transfer-to-Number** (built-in) | derived from emergency+phone | EL `built_in_tools.transfer_to_number` | `agent_configs` (source) | FULL; pushed after every Notdienst/Telefon save | Native EL call-transfer bridge |
| **Voicemail Detection** (built-in) | system-tools sync (no UI) | EL `built_in_tools.voicemail_detection` | — | FULL; always included | Stops mis-flagging humans as voicemail |
| **Scheduling Rules** (lead time, buffer, slots) | `PATCH /scheduling-rules` | `agent_configs.(lead_time_*, buffer_minutes, parallel_slots, …)` | `agent_configs` | FULL; DB + background repush | Booking-window constraints in prompt |
| **Required Fields / Leitfaden** | `PATCH /leitfaden`, `…/required-fields/*` | `agent_required_fields` (ordered) | `agent_required_fields` | FULL; DB + background repush | Ordered fields/offers the agent must collect |
| **Appointment Categories** | `…/appointment-categories` | `appointment_categories` | `appointment_categories` | FULL; DB + background repush | Bookable categories + durations/assignees |
| **Conversation Logic (Wenn/Dann)** | `PATCH /conversation-logic` | `agent_configs.conversation_logic` (JSON) | `agent_configs` | FULL; **render compile-fail silently → `''`** | Org-specific Schritt-1a rules in prompt |

**Storage-of-record observation:** four high-value settings live **only in ElevenLabs with no DB twin** — Persona Name, Voice ID, Language, and the Master Prompt text. If the EL agent is replaced or the account migrated, those settings are not recoverable from the CRM database (see drift risk *voice_id Not Persisted*, §4).

---

## 3. Sync Matrix (14 surfaces)

| Surface | Syncs | Overwrite risk | Evidence |
|---|---|---|---|
| Master Prompt | FULL | LOW — `prompt_manual_override` + first-run `agent_provisioned_at` guards | `agent_config.py:rerender_and_push_for_org()` |
| hk_* Tool IDs | **PARTIAL** | LOW — additive only; **deleted workspace tool lingers on agent until reprovision** | `configure_agent` B.2 `merge_arrays=[TOOL_IDS_PATH]` |
| client_events (audio) | FULL | **NONE** — assertion guarantees re-add | `assert_audio_event()` + `_compute_final_client_events()` |
| Voice ID | FULL | **MEDIUM** — no DB copy; lost if EL agent replaced | *UNVERIFIED: no `voice_id` column in schema* |
| First Message (stored) | FULL | LOW — per-call override available | `_el_patch()`, `conversation_init._pick_welcome_message()` |
| Conversation-Init Webhook | FULL | LOW — idempotent (checks url/enabled first) | `agent_config.py:1205-1242` |
| Knowledge Resources | FULL | LOW — additive; **`elevenlabs_doc_id` can go stale if EL doc deleted out-of-band** | `push/remove_knowledge_resource_to_elevenlabs()` |
| Price List KB | FULL | **MEDIUM** — reconcile-by-name heals; **GET→PATCH window not serialized** | `price_knowledge.py:85-86` |
| Transfer-to-Number | FULL | LOW — **best-effort: swallows exceptions → silent DB↔EL divergence** | `sync_system_tools_for_org()` |
| Voicemail Detection | FULL | LOW — hardcoded config | `build_voicemail_tool()` |
| Path-A Override Flags | FULL | LOW — idempotent, post-verified | `agent_config.py:1263-1294` |
| Language | FULL | LOW — immediate PATCH | `_el_patch()` |
| Business Hours (`scheduling` JSONB) | **PARTIAL** | MEDIUM — rendered into prompt but not surfaced in the KZ UI mapping | `_render_business_hours()` |
| Conversation Logic | FULL | LOW — **compile-fail silently drops Schritt 1a** | `render_conversation_logic_block()` |

---

## 4. Drift / Stale / Lost / Orphan risks (9)

> **HIGH — Prompt drift under manual override.** When `prompt_manual_override=True`, **every** config save (required fields, categories, emergency, scheduling) **silently skips the EL prompt repush**. The agent keeps running the stale hand-edited prompt even when config changes would materially change behavior (e.g. emergency disabled in DB but prompt still instructs transfer). *No automated mitigation; the KZ UI should warn about this state.* (`agent_config.py:1595-1600`)

> **HIGH — System-tools sync is best-effort.** `sync_system_tools_for_org()` swallows exceptions and only logs a warning. A failed sync after a Notdienst/Phone save leaves the agent's `built_in_tools` (transfer targets) stale while the DB is already updated. *Partial mitigation: `agent_sync_status='failed'` banner + `POST /sync-status/retry`.* (`agent_config.py:1474-1478`)

> **MEDIUM — hk_ tool-ID cache staleness.** A renamed/deleted workspace tool stays in `_HK_TOOL_ID_CACHE` for up to 3600 s; a provisioning call in that window may merge a stale id. *Mitigation: refresh-on-miss + full eviction; eventual convergence.* (`agent_config.py:112-176`)

> **MEDIUM — Concurrent price-list KB sync race.** Two concurrent `sync_price_list_kb` calls (toggle + catalog save) race on the GET→PATCH window; both may create text docs, one orphaned. *Mitigation: reconcile-by-name on next sync.* (`price_knowledge.py:85-86`)

> **MEDIUM — Snapshot restore omits `platform_settings`.** `_restore_full()` restores only `conversation_config` + `name`; webhook URL / override flags / workspace_overrides are **not** captured, so a failed B.4/B.6 step can't be rolled back via snapshot. *Mitigation: those steps are additive/idempotent; re-run `sync-agent-config`.* (`elevenlabs_agent.py:447-452`)

> **MEDIUM — EL-side edits between snapshot and rollback.** If a tradesperson edits the EL agent between snapshot and rollback, the rollback overwrites their manual changes. *Mitigation: `agent_writes_audit` trail; manual coordination.* (`elevenlabs_agent.py:476-518`)

> **MEDIUM — Conversation-logic compile failure silently drops Schritt 1a.** Corrupt/incompatible `conversation_logic` makes `render_conversation_logic_block()` return `''` with no user-visible error. *Mitigation: validated at save; risk is schema evolution.* (`agent_config.py:607-609`)

> **LOW — `voice_id` not persisted in DB.** Stored only in ElevenLabs; lost on EL agent recreation/migration, no automated recovery. (`kiki_zentrale.py:330-349`)

> **LOW — Process-local repush lock.** `_REPUSH_LOCKS` serializes overlapping saves only within one process; across processes two saves can race. *Mitigation: `agent_sync_seq` DB RPC gives last-write-wins at the banner level.* (`agent_config.py:1546-1547`)

---

## 5. ElevenLabs platform behaviors the code relies on (9)

These are empirically-derived API contracts encoded in the codebase. Most are `UNVERIFIED OBSERVATION` (depend on live EL behavior) except where noted:

- EL **deep-merges nested `conversation_config`** on PATCH — a surgical `first_message` patch preserves tools + prompt. (`elevenlabs_agent.py:219-230`)
- `built_in_tools` entries must be sent as **complete objects**; a leaf patch returns `400 Field required` → `_widen_built_in_tool_changes()`. (`elevenlabs_agent.py:314-430`)
- Webhook PATCH **requires `request_headers`** even if empty. (`agent_config.py:1207-1231`)
- `/knowledge-base/text` creates a text KB doc returning `{id, chunk_count, chunks}`. (`elevenlabs_agent.py:568-579`)
- KB `DELETE …?force=true`: 404 treated as success. (`elevenlabs_agent.py:603-609`)
- Phone lookup `/convai/phone-numbers` may bind multiple phones to one agent (picks first, warns). (`agent_config.py:237-259`)
- **[CODE-VERIFIED]** The agent's RAG uses the **native EL knowledge base** (`usage_mode=auto`), **NOT** the `hk_queryKnowledgeBase` webhook, which is a static fallback stub. (`services/knowledge.py:1-17`) — this is `KIKI-032` / `CALL-036`.
- `GET /v1/convai/tools` returns either `{tools:[{tool_config:{name,…}, id,…}]}` or a plain list; the code handles both shapes. (`agent_config.py:154-164`)
- EL validates PATCH bodies at the agent level; incomplete known-field objects return 400 → the post-write verify is necessary. (`elevenlabs_agent.py:373-411`)

---

## 6. Persistence, retrieval & versioning

- **Persistence:** config tables (`agent_configs`, `agent_required_fields`, `appointment_categories`, `knowledge_resources`) are the DB source of record; the live prompt is **re-derived** from them on each save (the prompt text itself is not stored — only the `prompt_manual_override` gate).
- **Retrieval:** `_fetch_kz_config()` / `render_prompt_for_org()` rebuild the prompt deterministically from template + config. `_el_read_state()` / `GET /agent-health` read back the live EL agent for EL-only fields.
- **Versioning:** there is no semantic version field, but `agent_config_snapshots` (565 rows) + `agent_writes_audit` (564 rows) provide a **complete pre/post write history** that functions as point-in-time versioning and the rollback source. `agent_provisioned_at` acts as a first-run guard.

---

## 7. Runtime cross-check (see RUNTIME_VALIDATION_REPORT.md §9)

| Aspect | Runtime verdict |
|---|---|
| Prompt render | ✅ **Confirmed** — 66,209 chars, all `{{COMPANY_*}}`/`{{KZ_*}}` substituted to "Kiki Chat GmbH", `{{system__*}}` runtime vars correctly left |
| `first_message` | ✅ `"Hallo, hier ist Kiki. Wie kann ich helfen?"` |
| Tool registration / webhook / `audio` event | ⚠️ **UNVERIFIED — requires runtime** (ElevenLabs MCP returns a simplified 9-key view; use the full EL REST API/dashboard) |
| Safety layer activity | ✅ 565 snapshots + 564 audit rows live (very active) |
| Test-data hygiene | ⚠️ org-data leaks into the rendered prompt: test categories "ruskin"/"Pipe isssue", English text in `KZ_CONVERSATION_LOGIC` |
