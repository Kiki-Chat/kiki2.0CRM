# FUNCTIONAL AUDIT REPORT — KikiJarvis CRM

*Generated 2026-06-17. Synthesizes all audit evidence: 436 business rules across 14 domains (`_data/rules/*.json`), 25 security observations (`_data/security.json`), 12 workflow traces (`_data/workflows.json`), the repository map (`_data/repo_map.json`), the Kiki/ElevenLabs deep dive (`_data/kiki_deep.json`), and the live runtime track (`RUNTIME_VALIDATION_REPORT.md`).*

---

## 1. Scope & Method

Two complementary tracks:

1. **Static code analysis** — every backend route family, service, agent tool, migration, and frontend page was read; rules were extracted with `path:line` evidence and classified (`CLEAR`/`WELL_IMPLEMENTED`/`PARTIALLY_IMPLEMENTED`/`AMBIGUOUS`/`MISSING`/`UNDEFINED`/`ORPHAN`/`DEPRECATED`).
2. **Live runtime validation** — against the deployed stack + the `kiki-test-007` sandbox (Supabase `ifbluvdcbcesuhvkxsfn`), covering DB state, persistence round-trips, the ElevenLabs agent config, and Supabase security advisors. See `RUNTIME_VALIDATION_REPORT.md`.

**Headline:** Coverage Score **94%** (410/436 rules `CLEAR`/`WELL_IMPLEMENTED`). 22 rules `PARTIALLY_IMPLEMENTED`, 2 `AMBIGUOUS`, 1 `MISSING`, 1 `ORPHAN`. No orphan features; every rule traces to a module/API/table. This is a mature, production-deployed system; the findings below are refinements, not structural defects.

## 2. System Overview

KikiJarvis is a **multi-tenant, AI-voice-fronted CRM for German trade businesses**. An inbound call is answered by **Kiki** (an ElevenLabs German voice agent) which identifies/creates the caller and writes structured records live. A FastAPI + Supabase backend (**221 live OpenAPI paths**; 265 route operations) and a German-only React 19 admin app sit behind it. The spine is **Call → Inquiry (ANF) → Case (FL) → Project (PR) → Invoice → Payment**, with appointments, KVA, outbound follow-ups, Stripe billing, and per-org agent configuration (Kiki-Zentrale).

## 3. Domain-by-Domain Findings

| Domain | Rules | Clear% | Avg conf | Verdict |
|---|---|---|---|---|
| **AUTH** | 32 | 94% | 97 | Strong. JWT/Supabase auth, org-scoping, role gating. Watch: `AUTH-028` admin set-password & `AUTH-029` technician token portal are `PARTIAL`. |
| **CUST** | 25 | 88% | 96 | Solid dedup by mobile (`CUST-001`). Issues: `CUST-014` `AMBIGUOUS` — phone lookup only checks the **primary** phone column (misses `phone2`); `CUST-004` name-only fallback & `CUST-012` type classification partial. |
| **INQ** | 20 | 100% | 96 | Clean. ANF numbering, emergency flag, call→inquiry creation all clear (runtime-confirmed). |
| **CASE** | 25 | 96% | 93 | FL numbering + AI grouping (`case_source`/confidence) confirmed. `CASE-004` status lifecycle partial. |
| **PROJ** | 28 | 96% | 98 | PR numbering clear. `PROJ-025` required-fields enforced **UI-only**. **Tier dormant at runtime** (0/32 cases linked). |
| **APPT** | 46 | 100% | 98 | Largest, fully clear: slot availability, lead time, Google sync, dispatch, reschedule/cancel. |
| **EMP** | 31 | 90% | 96 | Good. Gaps: `EMP-030` `activity_area`/`auto_assign` **stored but not runtime-dispatched**; `EMP-015` absence status app-layer-only; `EMP-027` 28-day vacation default `AMBIGUOUS`. |
| **INV** | 33 | 82% | 97 | Lowest clear%. `INV-027` **`ORPHAN` — auto-invoice-on-case-completion is dead code**; `INV-033` Skonto **stored but not applied to totals**; `INV-009/012/002/030` partial (KVA→invoice, validity, numbering, catalog-import dedup). |
| **BILL** | 34 | 97% | 97 | Strong Stripe integration. `BILL-029` 14-day trial partial. Still test-key-only until live keys + deploy. |
| **COMM** | 25 | 100% | 96 | Brevo email + notifications clear; gated by `OUTBOUND_TEST_SCOPE_ONLY`. |
| **OUT** | 28 | 89% | 96 | Occasion taxonomy confirmed (5 types, runtime). `OUT-009` scope guard, `OUT-016/017` (maintenance-due, missed-callback selection) partial. |
| **CALL** | 40 | 95% | 95 | Conversation-init webhook + post-call clear. `CALL-036` **queryKnowledgeBase returns a no-answer stub**; `CALL-039` **missed-calls table schema-only (writer not built)**. |
| **COP** | 32 | 91% | 95 | Well-guarded propose-then-confirm. `COP-023` **`MISSING` — monthly cost cap not enforced**; `COP-013` scope guard & `COP-020` live-fill partial. |
| **KIKI** | 37 | 97% | 91 | Strong safety layer (snapshot/verify/rollback/audit). Operational drift risks documented in `KIKI_CENTRAL_AUDIT.md`. |

## 4. Cross-Cutting Risks & Ambiguities (need product decisions)

1. **Project tier is dormant** — the migration-0073 Case→Project split is live but unused (0/32 cases → project). Decide whether Projects are an active workflow tier or vestigial. (`PROJ` §, runtime §3)
2. **Inconsistent customer numbering** — `KD-`, `KI-`, and bare-numeric formats coexist in one org. Pick one canonical scheme. (`CUST` §, runtime §4)
3. **Stale-prompt drift under `prompt_manual_override`** — HIGH: config saves silently skip the EL repush; the agent can run a stale prompt indefinitely with no UI warning. (`KIKI_CENTRAL_AUDIT.md` §4)
4. **Best-effort system-tools sync** — HIGH: a swallowed exception leaves transfer targets diverged between DB and the live agent. (`KIKI` §4)
5. **Copilot has no enforced spend cap** — `COP-023`: the monthly cost cap is defined but not enforced at chat/confirm.
6. **Dead/partial features to triage** — `INV-027` orphan auto-invoice, `INV-033` Skonto-not-applied, `EMP-030` auto-dispatch-not-wired, `CALL-039` missed-calls-writer-missing, `CALL-036`/`KIKI-032` KB-stub. Decide: build, document-as-deferred, or remove.
7. **`phone2` not searched** — `CUST-014`: identify-by-phone misses the secondary number; a returning caller on their 2nd number won't be recognized.

## 5. Security Headlines (observations only — see SECURITY_OBSERVATION_REPORT.md)

- **20 tables: RLS enabled, no policy** (runtime-verified via Supabase advisors) — incl. `org_secrets`, `outbound_calls`, `oauth_connections`, `billing_*`. Deny-all to PostgREST, but the backend's service role bypasses RLS, so **tenant isolation depends entirely on app-layer `org_id` filters** with no DB backstop.
- `SECURITY DEFINER` functions (`auth_org_id()`, `rls_auto_enable()`) executable by authenticated/anon; `kz_begin_agent_sync` has a mutable `search_path`.
- Supabase Auth **leaked-password protection disabled**.
- 25 static observations catalogued (severity-graded) in the security report.

## 6. Prioritized Top-15 Observations

| # | Observation | Where | Priority |
|---|---|---|---|
| 1 | Prompt drift under `prompt_manual_override` (no UI warning) | KIKI §4 | **HIGH** |
| 2 | System-tools sync best-effort → silent DB↔EL divergence | KIKI §4 | **HIGH** |
| 3 | 20 RLS-no-policy tables (+7 with no RLS) → app-layer-only tenant isolation | SEC / runtime | **HIGH** |
| 4 | Copilot monthly cost cap not enforced (`COP-023`) | COP | **HIGH** |
| 5 | `CUST-014` phone2 not searched on identify | CUST | MEDIUM |
| 6 | `INV-033` Skonto stored but not applied to totals | INV | MEDIUM |
| 7 | `INV-027` orphan auto-invoice (dead code) | INV | MEDIUM |
| 8 | `EMP-030` activity_area/auto_assign not runtime-dispatched | EMP | MEDIUM |
| 9 | `CALL-039` missed-calls writer not built | CALL | MEDIUM |
| 10 | `CALL-036`/`KIKI-032` queryKnowledgeBase is a stub | CALL/KIKI | MEDIUM |
| 11 | Project tier dormant (0/32 linked) | PROJ | MEDIUM (product) |
| 12 | Inconsistent customer numbering | CUST | MEDIUM (product) |
| 13 | Leaked-password protection disabled | SEC | MEDIUM |
| 14 | Price-list KB concurrent-sync race (GET→PATCH) | KIKI §4 | LOW |
| 15 | `voice_id` not persisted in DB | KIKI §4 | LOW |

*All runtime-confirmable items were validated against `kiki-test-007`; live phone/email triggers and full ElevenLabs tool/webhook verification remain documented procedures in `RUNTIME_VALIDATION_REPORT.md` §10.*
