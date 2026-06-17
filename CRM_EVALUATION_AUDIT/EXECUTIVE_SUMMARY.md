# Executive Summary — KikiJarvis CRM Functional Audit

**Date:** 2026-06-17
**Audience:** Executives and product owners (engineering leads will action the detail in the companion reports)
**Audit type:** Static business-rule analysis across the whole codebase, plus a separate live runtime-validation track
**Scope:** All 14 business-rule domains — **436 rules across 123 features** — and the Kiki / ElevenLabs voice-agent layer

> **Fidelity note.** Every number, rule ID, classification, and severity below is taken from the audit evidence under `CRM_EVALUATION_AUDIT/_data/` and the generated companion reports (`BUSINESS_RULE_COVERAGE.md`, `SECURITY_OBSERVATION_REPORT.md`, `RUNTIME_VALIDATION_REPORT.md`). No rule was invented; rule IDs are preserved verbatim. Anything confirmable only by exercising the live system is labelled **UNVERIFIED — requires runtime**.

---

## 1. What KikiJarvis Is

KikiJarvis is an **AI-voice-agent-fronted, multi-tenant CRM for German trade businesses** (Heizung & Sanitär / Handwerker). An inbound phone call is answered by **Kiki**, a German-speaking ElevenLabs voice agent that identifies or creates the caller, captures the request, books appointments, and writes structured records straight into the CRM during the live call. Behind the agent sits a **FastAPI + Supabase (Postgres)** backend and a **German-only React 19 / TypeScript** admin app where staff manage customers, employees, technicians, vehicles, appointments, cost estimates (KVA), invoices, outbound follow-up calls, and per-org agent configuration — all scoped to one **Organisation** and gated by per-capability autonomy levels. The system is **live in production on Railway**: the deployed backend is healthy (`{"status":"ok"}`, **221 OpenAPI routes**), the frontend returns HTTP 200, and the reference test org `kiki-test-007` ("Kiki Chat GmbH") carries real exercised data.

---

## 2. The Pipeline

A single inbound call flows the whole way through the CRM. The spine — **Call → Inquiry (ANF) → Case (FL) → Project (PR) → Invoice → Payment** — and its org-code numbering are **runtime-confirmed** in the test org `KC007`.

| Stage | Entity | Number format | What happens |
|---|---|---|---|
| 1 | **Call** | — | Inbound call answered by the Kiki voice agent; the central CRM event (52 calls in `KC007`). |
| 2 | **Customer** | `KD-…` / `KI-…` / numeric | Agent identifies or creates the caller; phone deduplicated to E.164 (17 in `KC007`). |
| 3 | **Inquiry (ANF-)** | `ANF-KC007-0001…0076` | The captured service request, linked to the call and customer (76 in `KC007`; 6 emergency-flagged). |
| 4 | **Case (FL-)** | `FL-KC007-0001…0032` | Related inquiries auto-grouped into one matter (the threaded UI view is a *Vorgang*); 50/76 inquiries grouped at avg. confidence 0.87–1.00. |
| 5 | **Project (PR-)** | `PR-KC007-0001` | Optional top-layer roll-up above cases. **Dormant in practice: 0 of 32 cases carry a `project_id`; 1 project row exists.** |
| 6 | **Invoice** | — | Project / case completion drafts an invoice from the cost estimate. |
| 7 | **Payment** | — | Manual send; overdue invoices can trigger a payment-reminder **outbound** call. |

Branching off the spine: **Appointments** (Termine — 27 confirmed / 6 cancelled in `KC007`) and **Outbound follow-ups** (Anlässe). All five outbound occasion types — reschedule, KVA follow-up, reminder, cancellation, confirmation — were **confirmed placed at runtime**.

### The Kiki voice-agent layer

KikiJarvis is the **system of record**; the ElevenLabs agent (`agent_5001…`) holds a **rendered, deployed copy** kept in step by an explicit **push-on-demand sync** routine — not a live two-way binding. The runtime read confirms the create → persist → version → render → deploy path is healthy: a reversible DB write round-trip **passed cleanly**, the configuration is heavily versioned (**565 config snapshots, 564 write-audit rows**, evidencing a snapshot → verify → rollback → audit safety layer), and the live **66,209-character** prompt rendered with **zero unsubstituted placeholders** and no stale template defaults. Two weak points: **retrieval observability** — the ElevenLabs MCP returned a thin 9-key view, so tool registration, audio events, and the webhook URL are **UNVERIFIED from this read** — and **inbound data quality** (sandbox test garbage such as `ruskin` and `Pipe isssue` [sic] renders live into the prompt).

---

## 3. Headline Numbers

| Metric | Value | Source |
|---|---|---|
| Business-rule domains | **14** (AUTH, CUST, INQ, CASE, PROJ, APPT, EMP, INV, BILL, COMM, OUT, CALL, COP, KIKI) | coverage |
| Features discovered | **123** | coverage |
| Business rules catalogued | **436** | coverage |
| **Coverage Score (Clearly Defined)** | **94%** — 410 / 436 `CLEAR` or `WELL_IMPLEMENTED` | coverage |
| Partially implemented | **5%** — 22 / 436 | coverage |
| Ambiguous / Missing / Orphan | **1%** — 4 / 436 | coverage |
| Domains with live runtime confirmation | **9 of 14** (~281 rules, 64%) | runtime |
| Security observations | **25** (0 Critical · 2 High · 10 Medium · 10 Low · 3 Info) | security |
| Deployed health | backend `ok`, **221** OpenAPI routes, frontend HTTP 200 | runtime |
| Live agent prompt | **66,209 chars**, 0 unsubstituted placeholders | runtime |

### Rule classification breakdown

| Classification | Count | Share |
|---|---:|---:|
| `WELL_IMPLEMENTED` | 307 | 70% |
| `CLEAR` | 103 | 24% |
| `PARTIALLY_IMPLEMENTED` | 22 | 5% |
| `AMBIGUOUS` | 2 | <1% |
| `MISSING` | 1 | <1% |
| `ORPHAN` | 1 | <1% |
| **Total** | **436** | 100% |

### Security observations by severity

| CRITICAL | HIGH | MEDIUM | LOW | INFO | Total |
|---:|---:|---:|---:|---:|---:|
| 0 | 2 | 10 | 10 | 3 | **25** |

The two **HIGH** findings: **SEC-003** — 7 tables ship with no Row-Level Security at all (incl. `oauth_connections`, which holds Fernet-encrypted OAuth tokens); and **SEC-006** — the Stripe webhook secret is not enforced at startup when billing is enabled with a test key, leaving forged-event exposure. No Critical findings.

### Runtime confirmations (9 of 14 domains exercised live)

Confirmed against live data: pipeline linkage, org-code numbering (ANF/FL/PR), status machines, emergency flagging, AI case grouping with confidence/provenance, the outbound occasion taxonomy, a DB write→persist→revert round-trip, and the rendered ElevenLabs prompt. **Code-only this round** (validated statically): EMP, INV, BILL, COMM, COP.

---

## 4. Biggest Ambiguities & Risks

1. **Project tier is dormant.** The `Case → Project` link is freshly live (migration 0073) but unused in practice: **0 of 32 cases carry a `project_id`** and only 1 project row exists. The pipeline operates end-to-end through Case today; the Project layer is built but not yet adopted. *Product decision: confirm intended rollout vs. de-scope.*

2. **Customer numbering is inconsistent.** Three `customer_number` formats coexist in one org — `KD-…`, `KI-…`, and bare numeric (`101001`) — reflecting imported-vs-generated provenance. ANF/FL/PR numbering is uniform; customer numbering is not. A data-quality / normalization decision, not a crash.

3. **ElevenLabs tools / webhook / audio are UNVERIFIED via MCP.** The ElevenLabs MCP returns a simplified 9-key config, so live **hk_ tool registration, audio-event presence, and the conversation-init webhook URL could not be confirmed this session** (prior UAT recorded audio + ~10–11 tools + a prod webhook). **UNVERIFIED — requires runtime** via the full ElevenLabs REST API.

4. **Tenant isolation has no database backstop.** The backend uses the Supabase `service_role` key, which **bypasses RLS**, so tenant separation rests entirely on application-layer `org_id` filters. Runtime advisors confirm **20 tables have RLS enabled but no policy** (deny-all to anon/authenticated, but no DB-policy backstop), and **7 tables have no RLS at all** (SEC-003, HIGH). Secure as written; one under-scoped query or a leaked anon key has no second line of defence.

5. **Supabase Auth leaked-password protection is DISABLED.** A runtime advisor flags that breached-password screening is off — a low-effort hardening gap surfaced live.

6. **Appointment proposal/reschedule lifecycle is unverified at runtime.** The schema and code support proposal/reschedule states, but the test data only exercises `confirmed`/`cancelled`, so those states remain **UNVERIFIED (no live rows)**.

---

## 5. The Audit Deliverables (15)

The audit ships as 15 documents. Fourteen are written from the static evidence; **`RUNTIME_VALIDATION_REPORT.md` is produced by a separate runtime track** that exercises the live system.

| # | Deliverable | One-line description |
|---:|---|---|
| 1 | **EXECUTIVE_SUMMARY.md** | This document — decision-oriented overview of the CRM, the pipeline, headline numbers, and top risks. |
| 2 | **AUDIT_REPORT.md** | The core functional audit narrative — scope, two-track method, per-domain findings, conclusions. |
| 3 | **BUSINESS_RULES.md** | Authoritative catalogue of all 436 rules across 14 domains, with triggers, validations, actions, and effects. |
| 4 | **BUSINESS_RULE_COVERAGE.md** | Coverage scoring (94% Clearly Defined) by classification, domain, and feature, plus runtime coverage. |
| 5 | **FEATURE_TO_RULE_MATRIX.md** | Maps each of the 123 features to its governing rule IDs, modules, APIs, tables, and observed risks. |
| 6 | **TRACEABILITY_MATRIX.md** | Every rule traced to code / API / table with `path:line` source anchors and classification. |
| 7 | **WORKFLOW_DIAGRAMS.md** | End-to-end workflow traces as Mermaid flowcharts (pipeline, outbound, agent config, email chain, etc.). |
| 8 | **SECURITY_OBSERVATION_REPORT.md** | The 25 security observations (2 High / 10 Medium / 10 Low / 3 Info) plus live Supabase advisor findings; observations only, no fixes. |
| 9 | **KIKI_CENTRAL_AUDIT.md** | Kiki-Zentrale configuration audit — agent authoring, persistence, versioning, render, and the ElevenLabs sync round-trip. |
| 10 | **AI_COPILOT_RULEBOOK.md** | Governance contract for the AI copilot: what it may do, must never do, and what needs human approval. |
| 11 | **INTEGRATION_DEPENDENCY_MAP.md** | External integrations (ElevenLabs, Supabase, Stripe, Brevo, Google/Microsoft/Calendly, OpenAI, Twilio, PDS, Redis, n8n, Sentry), their auth, env vars, and failure modes. |
| 12 | **REPOSITORY_MAP.md** | Repository structure, backend/frontend modules, DB tables, dependency edges, and data flows. |
| 13 | **CRM_GLOSSARY.md** | Official glossary / onboarding dictionary mapping German UI labels to English concepts and the pipeline. |
| 14 | **RUNTIME_VALIDATION_REPORT.md** | **Separate runtime track** — live DB snapshot, numbering, status machines, write round-trip, security advisors, agent-prompt render. |
| 15 | **README.md** | Index / reading guide tying the deliverable set together. *(Planned.)* |

---

*Generated faithfully from the audit evidence under `CRM_EVALUATION_AUDIT/_data/` and the companion reports. Rule IDs, classifications, confidence values, and severities reproduced verbatim; runtime-only items labelled `UNVERIFIED — requires runtime`. No rules or findings were invented.*
