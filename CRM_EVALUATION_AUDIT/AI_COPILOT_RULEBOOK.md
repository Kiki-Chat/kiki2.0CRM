# AI COPILOT RULEBOOK — Operating the KikiJarvis CRM Safely

*Generated 2026-06-17 from `_data/rules/COP.json` (32 rules) + all domain rules + `_data/kiki_deep.json` + `_data/security.json` + runtime evidence. This rulebook defines what an AI Copilot may and may not do when operating the KikiJarvis CRM. Every constraint is grounded in a rule ID. The existing in-CRM Copilot already implements most of this; an external AI operator MUST obey it.*

> **Golden rule (`COP-006`, `COP-007`):** the Copilot **proposes** write/sensitive/dangerous actions and **never auto-executes** them. A separate confirm step executes **exactly one** write tool per call. The confirm button is the sole autonomy mechanism (`COP-027`) — autonomy levels L1–L3 gate the *voice agent*, not the Copilot.

---

## 1. Allowed Actions (read + propose)

- **Read any org-scoped data** the caller's role permits — every tool read is org-scoped (`COP-004`) and role-gated (`COP-005`).
- **Propose writes** that are surfaced as action cards for human confirmation: create/update customer, inquiry, case, appointment, cost estimate (KVA), invoice, employee, org profile (`COP-006`, `COP-025`, `COP-028`, `COP-029`).
- **Navigate the UI** via the client-side navigation tool, restricted to a fixed route whitelist (`COP-011`); navigate-to-affected-page before/after a write (`COP-021`).
- **Explain settings** read-only, matched by German keyword (`COP-030`).
- **Escalate** unresolved problems via `report_problem` → email + `copilot_escalations` (`COP-014`).
- **Resolve a customer** before any customer-linked action (`COP-012`).

## 2. Forbidden Actions (hard stops)

- **❌ Never auto-execute a write.** All writes are proposal-then-confirm (`COP-006`). The confirm endpoint runs at most one write tool (`COP-007`).
- **❌ Never place an outbound call or send a customer email as a casual side-effect.** Outbound calls + emails are **LIVE to real customers** once `OUTBOUND_TEST_SCOPE_ONLY=0` (`OUT-009`; reference: outbound is in production per project memory). Treat any outbound/email trigger as a real-world action requiring explicit human intent.
- **❌ Never write directly to the ElevenLabs voice agent** outside the Kiki-Zentrale safe path — `patch_agent_safely()` and the snapshot/verify/rollback layer must not be bypassed; a raw write can **overwrite live prod agent state** (`KIKI` §, drift risks).
- **❌ Never run a non-additive DB migration** (DROP/ALTER/destructive) without explicit human approval. Additive `ADD COLUMN/INDEX/TABLE` is pre-authorized; everything else is not.
- **❌ Never assume DB-level tenant isolation.** 20 tables have **RLS enabled but no policy** (`org_secrets`, `outbound_calls`, `oauth_connections`, `billing_*`, `tools`, `vehicles`, …); the backend bypasses RLS via the service role (`COP-031`). Tenant isolation rests on **app-layer `org_id` filters** — every query MUST be org-scoped; a missing filter has no DB backstop (see `SECURITY_OBSERVATION_REPORT.md`).
- **❌ Never execute admin-only tools as an employee** — admin tools are invisible and unexecutable to employees (`COP-005`).
- **❌ Never replay a historical action card** — cards reopened from history are marked cancelled / non-reconfirmable (`COP-018`).

## 3. Approval-Required Actions

| Action | Mechanism |
|---|---|
| Any write tool (customer/inquiry/case/appt/KVA/invoice/employee/org) | Human clicks **confirm** on the proposed action card (`COP-006`, `COP-007`) |
| Rescheduling a **confirmed** appointment | Allowed, but **triggers a customer notification** — confirm intent (`COP-026`) |
| Creating an employee | Always created **without login access**; the login invite is a separate manual step (`COP-025`) |
| Outbound calls / customer emails | Explicit human intent; LIVE to customers (`OUT-009`, `COMM` §) |
| ElevenLabs config changes | Via Kiki-Zentrale safe path only (`KIKI` §) |
| Non-additive migrations / deploys | Explicit human approval (project policy) |

## 4. Business Constraints

- **Startup gates:** Copilot requires `COPILOT_ENABLED` (`COP-001`) and a live OpenAI client each turn (`COP-002`); all endpoints require org-member auth (`COP-003`).
- **Bounded agency:** the agentic loop is capped at **5 steps** (`COP-009`); client history is sanitized to user/assistant roles, max 20 turns (`COP-008`).
- **Rate limit:** **20 Copilot turns / org / minute** (`COP-010`).
- **Cost:** every OpenAI call logs tokens + cost (`COP-022`). ⚠️ **`COP-023` [MISSING]:** a monthly cost cap exists in config but is **NOT enforced** on Copilot chat/confirm — there is currently no spend ceiling at runtime. An external operator must self-limit.
- **VAT is exclusive** on all money documents (`INV` §); KVA/invoice require ≥1 position (`COP-029`).
- **Timezone:** all displayed timestamps are Europe/Berlin; the system prompt is Berlin-anchored (`COP-024`).

## 5. Entity Relationships & Status Definitions

**Pipeline (runtime-confirmed):** `Call → Inquiry (ANF-) → Case (FL-) → Project (PR-) → Invoice → Payment`, with appointments + cost estimates (KVA) attaching at the Inquiry/Case level. Numbering is org-code-embedded: `ANF-KC007-####`, `FL-KC007-####`, `PR-KC007-####` (`INQ`/`CASE`/`PROJ` §). **Note:** the Case→Project tier is live but **dormant** (0/32 cases linked to a project in the test org) — do not assume a project exists for a case.

**Status machines (observed live values — do not invent statuses):**

| Entity | Valid statuses |
|---|---|
| Inquiry | `open`, `in_progress`, `completed`, `deleted` (soft-delete is a status) |
| Case | `active`, `planning`, `completed` |
| Project | `planning` (others exist in code) |
| Appointment | `confirmed`, `cancelled` (+ schema lifecycle: rejected/rescheduled/proposal states) |
| Call | `completed` (+ `is_spam`, `deleted_at` soft-delete) |

**Case grouping:** inquiries are grouped into cases by AI with provenance `case_source ∈ {ai, ai_confirmed, human}` and a `case_confidence` score (`CASE` §) — never silently re-group across that provenance.

## 6. Role Restrictions

- **Roles:** `org_admin`, `employee`, and a **standalone super-admin** (separate app/login — not a feature inside the customer app). (`AUTH` §)
- **Client split:** customer portal uses `heykiki-customer-auth`; admin app uses `heykiki-admin-auth` (`AUTH` §).
- Admin-only Copilot tools are hidden + unexecutable for employees (`COP-005`); org-scoping is enforced on every read (`COP-004`).
- `update_org_profile` is restricted to a safe-fields whitelist (`COP-028`).

## 7. Decision Boundaries

- **Scope guard (`COP-013` [PARTIALLY_IMPLEMENTED]):** the Copilot refuses non-CRM requests — but this is **prompt-only**, not hard-enforced. An external operator must treat out-of-scope refusal as a policy it enforces itself.
- **Customer ambiguity:** resolve to a single, exact-unique customer before acting; on ambiguity, fail to server-side resolution rather than guessing (`COP-012`; cf. live-fill `liveFill.ts`).
- **Live form-fill (`COP-020`):** payloads are one-shot, `sessionStorage`, 2-minute TTL — do not re-consume.

## 8. Operational Limits

| Limit | Value | Rule |
|---|---|---|
| Agentic steps per turn | 5 | `COP-009` |
| Chat turns | 20 / org / min | `COP-010` |
| Client history retained | 20 turns (user/assistant only) | `COP-008` |
| History view | newest 200 messages, chronological | `COP-017` |
| Conversation list page | ≤100 (default 30), newest-first | `COP-019` |
| Writes per confirm | exactly 1 | `COP-007` |
| Monthly cost cap | **not enforced** ⚠️ | `COP-023` |
| Every confirmed write | audited in `copilot_action_audit` | `COP-015` |

## 9. Machine-readable constraint summary

```json
{
  "write_policy": "propose_then_confirm",
  "writes_per_confirm": 1,
  "auto_execute_writes": false,
  "agentic_max_steps": 5,
  "rate_limit_turns_per_org_per_min": 20,
  "history_max_turns": 20,
  "monthly_cost_cap_enforced": false,
  "tenant_isolation": "app_layer_org_id_filter_only (20 tables have RLS-no-policy; 7 more have no RLS at all)",
  "forbidden": [
    "auto_execute_any_write",
    "place_outbound_call_or_email_without_explicit_intent",
    "direct_elevenlabs_agent_write_outside_safe_path",
    "non_additive_db_migration_without_approval",
    "cross_org_data_access",
    "employee_execute_admin_tools",
    "replay_historical_action_card"
  ],
  "approval_required": [
    "all_write_tools",
    "reschedule_confirmed_appointment",
    "outbound_calls_and_customer_emails",
    "elevenlabs_config_changes",
    "deploys_and_non_additive_migrations"
  ],
  "pipeline": ["Call","Inquiry(ANF)","Case(FL)","Project(PR)","Invoice","Payment"],
  "status_machines": {
    "inquiry": ["open","in_progress","completed","deleted"],
    "case": ["active","planning","completed"],
    "appointment": ["confirmed","cancelled"]
  },
  "numbering": "ANF/FL/PR-<ORGCODE>-#### sequential",
  "vat": "exclusive",
  "timezone_display": "Europe/Berlin"
}
```
