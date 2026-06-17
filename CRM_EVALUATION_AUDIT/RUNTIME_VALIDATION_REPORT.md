# RUNTIME VALIDATION REPORT — KikiJarvis CRM

**Date:** 2026-06-17
**Validator:** Audit runtime track (live verification against the controlled test environment)
**Scope:** Non-destructive runtime validation of business rules against the live database, the deployed backend/frontend, and the ElevenLabs voice agent — confined to the **kiki-test-007** sandbox org.

This report supplies the **runtime evidence** layer for the static audit. Where the static `BUSINESS_RULES.md` / `BUSINESS_RULE_COVERAGE.md` mark a rule `CODE-ONLY`, an entry here either promotes it to **RUNTIME-CONFIRMED** or records why it remains **UNVERIFIED**.

---

## 1. Environment

| Item | Value |
|---|---|
| Supabase project | `ifbluvdcbcesuhvkxsfn` (kikiJarvis, ACTIVE_HEALTHY, ap-northeast-1, Postgres 17) |
| Test org | kiki-test-007 · `c4dbf596-86fd-4484-88d9-095b2c082afb` · "Kiki Chat GmbH" · `+4925197593899` |
| Voice agent (SAFE) | `agent_5001ksahz3w7fhx90j71xr800py4` · `agent_provisioned_at = 2026-06-03` |
| Deployed backend | https://backend-production-3f88a.up.railway.app |
| Deployed frontend | https://frontend-production-4bdf.up.railway.app |
| Mail test inbox | `dixitrahul825@gmail.com` |
| Call test number | `+917879997839` (live-call target; space ≥ 2 min apart) |

**Method:** Supabase MCP (read + one reversible write round-trip), Supabase security advisors, ElevenLabs MCP (read-only agent config), and HTTP probes against the deployed stack. No production customer data, no schema changes, no ElevenLabs writes, no live calls/emails were issued from this session.

---

## 2. Deployed-stack reachability — ✅ PASS

| Probe | Result |
|---|---|
| `GET /health` (backend) | `{"status":"ok"}` |
| `GET /openapi.json` path count | **221 paths** live (e.g. `/api/dashboard/overview`, `/api/heykiki/provision`, …) |
| `GET /` (frontend) | **HTTP 200** (SPA served) |

The deployed system is live and the full route surface (221 paths) is present, consistent with the route inventory in `REPOSITORY_MAP.md`.

---

## 3. Data-model & pipeline validation (kiki-test-007) — ✅ PASS

Live row counts confirm the **Call → Inquiry (ANF) → Case (FL) → Project (PR)** pipeline and its linkage columns.

| Entity | Total | Key linkage |
|---|---|---|
| Inquiries | 76 | 76 numbered · 51 linked to a call · **50 linked to a case** · 6 `emergency_flag=true` |
| Cases | 32 | 32 numbered · **0 linked to a project** |
| Projects | 1 | (status `planning`) |
| Customers | 17 | mixed numbering schemes (see §4) |
| Calls | 52 | 4 soft-deleted (`deleted_at`) · 1 spam · 48 linked to an inquiry |
| Appointments | 33 | 27 confirmed · 6 cancelled |

**Findings**
- **RC-1 — Pipeline linkage works up to Case, but the Case→Project link is unused.** 50/76 inquiries carry a `case_id`; **0/32 cases carry a `project_id`**, and only one project row exists. This corroborates that the migration-0073 Case↔Project split is freshly live and the Project layer is not yet populated in practice. *Promotes the CASE/PROJ linkage rules to RUNTIME-CONFIRMED (linkage exists); flags the Project tier as effectively dormant.*
- **RC-2 — Emergency flagging is operative.** 6 inquiries have `emergency_flag=true`, confirming the post-2026-06-09 bilingual content fallback actually sets the flag (contrast the earlier "emergencies never flagged" defect).

---

## 4. Numbering schemes — ✅ RUNTIME-CONFIRMED (with one inconsistency)

Org-code-embedded sequential numbering (the "Option A / K-org-code" scheme) is confirmed live:

| Entity | Live format | Range observed |
|---|---|---|
| Inquiry | `ANF-KC007-####` | `ANF-KC007-0001 … 0076` |
| Case | `FL-KC007-####` | `FL-KC007-0001 … 0032` |
| Project | `PR-KC007-####` | `PR-KC007-0001` |
| Customer | **MIXED** | `KD-#####` (8), `KI-######` (4), bare numeric `101001/105156` (4) |

**RC-3 — Customer numbering is inconsistent.** Three different `customer_number` formats coexist in one org (`KD-`, `KI-`, and bare numeric), reflecting imported-vs-generated provenance. ANF/FL/PR numbering is uniform; customer numbering is not. *Recorded as an AMBIGUOUS/PARTIALLY_IMPLEMENTED data-quality observation, not a crash.*

---

## 5. Status machines — observed values

The status enums claimed by code are confirmed against real rows:

| Entity | Observed statuses (counts) |
|---|---|
| Cases | `active` (27), `planning` (4), `completed` (1) |
| Inquiries | `open` (46), `in_progress` (22), `completed` (5), `deleted` (3) |
| Appointments | `confirmed` (27), `cancelled` (6) |
| Calls | `completed` (52) |
| Projects | `planning` (1) |

**RC-4 — Inquiry soft-delete is status-based.** `deleted` is a first-class `status` value (3 rows), not only a timestamp column. **RC-5 — Appointment lifecycle columns exist** (`confirmed_at`, `rejected_at`, `cancelled_at`, `rescheduled_at`, `reschedule_expires_at`, `alternative_*`, `customer_proposed_*`) but the live test data only exercises `confirmed`/`cancelled`; the proposal/reschedule states are **UNVERIFIED at runtime** (no rows in those states) though present in schema and code.

---

## 6. Case auto-grouping — ✅ RUNTIME-CONFIRMED

`inquiries.case_source` + `case_confidence` confirm AI-driven grouping with provenance:

| `case_source` | Inquiries | Have a case | Avg confidence |
|---|---|---|---|
| `ai_confirmed` | 37 | 37 | 0.87 |
| `ai` | 10 | 10 | 0.97 |
| `human` | 3 | 3 | 1.00 |
| (null / ungrouped) | 26 | 0 | — |

50 inquiries grouped (37+10+3) exactly matches the `with_case=50` count from §3. The grouper assigns a confidence score and distinguishes AI-suggested (`ai`), AI-confirmed (`ai_confirmed`), and human provenance.

---

## 7. Outbound calling — ✅ RUNTIME-CONFIRMED

All five `outbound_calls` rows target the test number and span the full occasion taxonomy:

| Occasion | `anlass_typ` | Status | Target |
|---|---|---|---|
| appointment_reschedule | TERMIN_VERSCHIEBUNG | placed | +917879997839 |
| kva_followup | KVA_NACHFASSEN | placed | +917879997839 |
| appointment_reminder | TERMIN_ERINNERUNG | placed | +917879997839 |
| appointment_cancellation | TERMIN_ABSAGE | placed | +917879997839 |
| appointment_confirmation | TERMIN_BESTAETIGUNG | placed | +917879997839 |

The outbound occasion model and the test-number override are confirmed live. **Live (re)dispatch was not issued from this session** (see §10).

---

## 8. Write → persist → retrieve → revert round-trip — ✅ PASS

To satisfy the "change the value, save, verify persistence, retrieve again" requirement on a reversible field:

1. `UPDATE customers SET notes='AUDIT_ROUNDTRIP_2026-06-17' WHERE id=6798d6d8… (Familie Hoffmann)` → `RETURNING` confirmed the write.
2. Independent `SELECT` in a separate statement returned the persisted value → **durability confirmed**.
3. `UPDATE … SET notes=NULL` → reverted to original. Final state matches pre-test.

**RC-6 (incidental) — `customers.updated_at` is app-maintained, not DB-trigger-maintained:** the raw `UPDATE` left `updated_at` unchanged (`2026-06-14`). Any rule that assumes `updated_at` reflects the last write must be satisfied by the application layer, not the database.

---

## 9. ElevenLabs voice-agent sync — ⚠️ PARTIAL (prompt confirmed; tools/webhook/audio not verifiable via MCP)

Read-only fetch of the SAFE agent (`agent_5001…`):

| Aspect | Result |
|---|---|
| System prompt | **66,209 chars**, rendered from `backend/app/services/agent_prompt_template.txt` |
| Placeholder substitution | All `{{COMPANY_*}}` / `{{KZ_*}}` substituted to "Kiki Chat GmbH"; `{{system__*}}` runtime vars correctly left intact; **no stale template defaults** (no "Muster Heizungsbau" / "Husmann & Dreier") |
| `first_message` | `"Hallo, hier ist Kiki. Wie kann ich helfen?"` |

**RC-7 — MCP tool limitation:** ElevenLabs `get_agent_config` returns a **simplified 9-key view** (no `client_events`, no `tools[]`, no webhook). Therefore **audio-event presence, hk_ tool registration, and the conversation-init webhook URL are UNVERIFIED via MCP** in this session — they require the full ElevenLabs REST API or dashboard. (Prior UAT recorded in `SESSION_HANDOVER.md` confirmed `audio` in `client_events`, ~10–11 `hk_` tools attached, and the prod webhook; the agent has 565 `agent_config_snapshots` + 564 `agent_writes_audit` rows, evidencing an active snapshot/verify/rollback/audit safety layer.)

**RC-8 — Test-data hygiene in the rendered prompt:** because the prompt is dynamically composed from org data, test garbage leaks into it: appointment categories `"ruskin"` and `"Pipe isssue"` (typo), and English test text inside the German `KZ_CONVERSATION_LOGIC` block. These are sandbox data-quality issues, not engine defects, but they do reach the live agent prompt.

---

## 10. Items NOT executable from this environment

This audit worktree has **no backend `.env`** (Supabase/ElevenLabs/Brevo secrets absent), so the Python helper scripts and a local backend cannot run here, and the external mail inbox cannot be read. The following are therefore documented with ready-to-run procedures rather than executed:

| Item | Why deferred | Ready-to-run |
|---|---|---|
| Live outbound call to `+917879997839` | needs backend secrets; real-world side effect | `cd backend && PYTHONPATH=. ./.venv/bin/python ../scripts/fire_test_call.py` (dry-run prints first, then one live `appointment_reminder`; space ≥ 2 min between calls, log timestamps) |
| Email trigger + receipt confirmation | can trigger via app, but the `dixitrahul825@gmail.com` inbox is not reachable from here | trigger an occasion/activation email in-app, then confirm receipt in that inbox manually |
| Full ElevenLabs sync round-trip (tools/webhook/audio) | MCP returns a simplified view | `cd backend && ./.venv/bin/python ../scripts/force_sync_test_agent.py` then dump the agent via the EL REST API and diff |
| Interactive UI click-through | no local backend + prod CORS won't allow a local origin | run `frontend` dev server with `VITE_API_URL=<prod backend>` **after** adding the local origin to backend `CORS_ORIGINS`, or drive the deployed frontend directly; login `kikitest01@gmail.com` |

---

## 11. Security observations surfaced at runtime

From Supabase `get_advisors(security)` (cross-references `SECURITY_OBSERVATION_REPORT.md`):

- **20 tables: RLS enabled but no policy** (incl. `org_secrets`, `outbound_calls`, `oauth_connections`, `billing_*`, `tools`, `vehicles`, `text_modules`, `missed_calls`, `employee_absences`, `case_links`, `technician_job_links`, `action_tasks`). Net effect = **deny-all** to PostgREST anon/authenticated roles (secure-by-default), **but** the backend uses the `service_role` (bypasses RLS), so tenant isolation for these tables rests entirely on **application-layer `org_id` filters with no DB-policy backstop**. (INFO level, but architecturally significant.)
- **WARN** — `auth_org_id()` and `rls_auto_enable()` are `SECURITY DEFINER` functions executable by `authenticated`/`anon` via `/rest/v1/rpc/…`; `kz_begin_agent_sync` has a mutable `search_path`.
- **WARN** — Supabase Auth **leaked-password protection is disabled**.

---

## 12. Runtime validation summary

| # | Check | Verdict |
|---|---|---|
| RC-1 | Call→Inquiry→Case linkage (Project tier dormant) | ✅ confirmed |
| RC-2 | Emergency flagging operative | ✅ confirmed |
| RC-3 | Customer numbering inconsistent | ⚠️ observation |
| RC-4 | Inquiry soft-delete is status-based | ✅ confirmed |
| RC-5 | Appointment proposal/reschedule states | ⚠️ unverified (no live rows) |
| RC-6 | `updated_at` app-maintained | ⚠️ observation |
| RC-7 | ElevenLabs prompt render correct; tools/webhook/audio | ✅ prompt / ⚠️ rest unverified via MCP |
| RC-8 | Test-data hygiene leaks into agent prompt | ⚠️ observation |
| §2 | Deployed stack live (221 OpenAPI paths) | ✅ confirmed |
| §6 | AI case grouping with confidence/provenance | ✅ confirmed |
| §7 | Outbound occasion taxonomy | ✅ confirmed |
| §8 | DB write/persist/revert round-trip | ✅ pass |
| §11 | RLS-no-policy + auth advisors | ⚠️ security observations |

**Net:** the core pipeline, numbering, status machines, emergency flagging, case grouping, outbound model, and DB persistence are **runtime-confirmed**. The Project tier is dormant, customer numbering is inconsistent, and the ElevenLabs tool/webhook/audio sync plus appointment-proposal lifecycle remain **UNVERIFIED** pending the backend-configured procedures in §10.
