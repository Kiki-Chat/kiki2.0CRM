# REMEDIATION PLAN — KikiJarvis CRM → Production-Grade

*Generated 2026-06-17 from the audit findings + product-owner review. Goal: turn the audited gaps into fixes, batched by theme and priority. Severity: **P0** = blocks safe production / security / data-integrity · **P1** = launch-critical correctness/reliability · **P2** = UX/polish. "Verify-first" = confirm current state before building.*

## Priority ladder (recommended order)
1. **Batch 1** Kiki-Zentrale undo/rewind + drift safety (the heart) — P0
2. **Batch 3** Security hardening — P0 (parallel with 1)
3. **Batch 2** Onboarding reliable one-click + verify gate — P0/P1
4. **Batch 4** Agent receptionist-logic correctness — P1
5. **Batch 7** Stripe billing production-readiness — P1
6. **Batch 6** Invoicing & money correctness — P1
7. **Batch 5** Technician + planning board — P1/P2
8. **Batch 8** Open Actions / notifications / dashboard — P2
9. **Batch 9** Cosmetic / data hygiene — P2

---

## BATCH 1 — Kiki-Zentrale: true undo/rewind + drift safety (P0, the heart)

| # | Issue | Why fix | Before | After | Sev | Effect on CRM |
|---|---|---|---|---|---|---|
| 1.1 | Snapshot **restore excludes `platform_settings`** (webhook, override flags) — `_restore_full` only restores `conversation_config` | Rollback can't undo webhook/override changes → silent divergence | Rollback half-restores; webhook/overrides stay broken | Full-state snapshot+restore (incl. platform_settings) | P0 | Reliable recovery; no permanently-broken agents |
| 1.2 | **No user-facing undo/rewind** — snapshots (565 live) only auto-rollback on failed writes | "Undo/rewind" is in-name-only; operator can't revert a bad change | No manual revert; only auto-rollback | "Revert to snapshot N" + change history UI in Kiki-Zentrale | P0 | Operators can safely experiment & recover |
| 1.3 | **Prompt drift** under `prompt_manual_override=True` — config saves silently skip the EL repush | Agent runs a stale prompt forever, no warning | Silent stale prompt | Drift banner + "force resync" button + diff view | P0 | Agent behavior matches configured settings |
| 1.4 | **System-tools sync is best-effort** (swallows exceptions) | A failed transfer-tool sync leaves DB↔EL diverged silently | Silent failure | Surface failure, auto-retry, block "active" until green | P0 | Emergency/transfer numbers always correct on the live agent |
| 1.5 | **hk_ tool sync additive-only** (de-listed tools linger) | Stale/removed tools stay attached to the agent | No cleanup | Reconcile (remove de-listed) on resync | P1 | Agent tool set is exactly what's intended |

## BATCH 2 — Onboarding: reliable one-click provision + verify gate (P0/P1)

| # | Issue | Why fix | Before | After | Sev | Effect on CRM |
|---|---|---|---|---|---|---|
| 2.1 | **No holistic post-provision health-assert** after super-admin creates org+agentID | Onboarding can "succeed" with a half-configured agent | B.1–B.6 run, no final all-green check | "Provision & Verify" gate: assert tools attached + webhook→prod + audio present + prompt rendered + overrides on, before org goes active | P0 | Every onboarded customer's agent works on call #1 |
| 2.2 | Provisioning doesn't seed **post-call summary** config or **outbound scripts** | New orgs miss summaries / have no outbound scripts | Manual/absent | Provisioning seeds post-call + default outbound occasion scripts | P1 | Summaries + follow-up calls work out-of-the-box |
| 2.3 | B.1 **hard-fails (400) if no phone bound** to the EL agent | Onboarding blocks with an opaque error | Cryptic failure | Graceful skip + clear admin guidance ("bind a phone in EL") | P1 | Smooth, self-explanatory onboarding |
| 2.4 | No **per-org agent-health dashboard** for super-admin | Can't see which orgs' agents are misconfigured | Blind | Green/red health board (prompt, tools, webhook, audio, sync status) | P1 | Proactive ops; catch drift before customers do |

## BATCH 3 — Security hardening (P0, production)

| # | Issue | Why fix | Before | After | Sev | Effect on CRM |
|---|---|---|---|---|---|---|
| 3.1 | **20 tables: RLS enabled, no policy** (org_secrets, outbound_calls, oauth_connections, billing_*, …) | Tenant isolation has no DB backstop; one under-scoped query leaks cross-org | App-layer filters only | Add org-scoped RLS policies | P0 | Defense-in-depth tenant isolation |
| 3.2 | **7 tables with no RLS at all** (SEC-003) | Same — no row protection | Unprotected | Enable RLS + policy | P0 | Closes the widest isolation gap |
| 3.3 | `auth_org_id()` / `rls_auto_enable()` **SECURITY DEFINER** callable by anon/auth; `kz_begin_agent_sync` mutable `search_path` | Privilege-escalation surface | Exposed RPCs | Revoke execute / set search_path / SECURITY INVOKER | P1 | Removes RPC abuse vectors |
| 3.4 | **Leaked-password protection DISABLED** (Supabase Auth) | Breached passwords accepted | Off | Enable HaveIBeenPwned check | P1 | Stronger account security, low effort |
| 3.5 | **Technician token portal** (AUTH-029): token has no expiry/rotation/audit | Long-lived unauth link = standing risk | Permanent token, no log | TTL + rotation + access audit | P1 | Field-portal links can't be abused indefinitely |

## BATCH 4 — Agent receptionist-logic correctness (P1)

| # | Issue | Why fix | Before | After | Sev | Effect on CRM |
|---|---|---|---|---|---|---|
| 4.1 | **Identify misses `phone2`** (CUST-014) — only primary phone searched | Returning caller on 2nd number = treated as new | Mis-identification | Lookup includes phone2 | P1 | Correct customer recognition |
| 4.2 | Agent lacks **open-case context** on identify (can't disambiguate "which case") | Caller references a job; agent doesn't know which | Agent asks blindly | Surface customer's open/recent cases to agent on identify (inbound) | P1 | Natural "your bathroom job from Tuesday?" handling |
| 4.3 | `queryKnowledgeBase` is a **stub** (CALL-036/KIKI-032) — returns no-answer | Tool looks live but never answers | Dead tool | Wire to backend KB/price, or remove tool + rely on native EL KB | P1 | No misleading "I'll check" dead-ends |
| 4.4 | **Missed-calls writer not built** (CALL-039) — table schema-only | Missed calls never recorded → no callback | Lost leads | Build writer + surface as Open Action / callback | P1 | No dropped customers |
| 4.5 | Emergency / business-hours / appointment-window logic — *verify-first* | Core receptionist promises; must be provably correct | Untested matrix | Regression test: emergency→forward, human→transfer, outside-hours, windows | P1 | Confidence the receptionist behaves per spec |

## BATCH 5 — Technician & planning board (P1/P2)

| # | Issue | Why fix | Before | After | Sev | Effect on CRM |
|---|---|---|---|---|---|---|
| 5.1 | `activity_area`/`auto_assign` **stored but not dispatched** (EMP-030) | Auto-assignment promised but inert | Manual assign only | Wire auto-assign by category/area | P1 | Faster, correct dispatch |
| 5.2 | **Planning board employee-centric**; vehicles/tools keyed to `assigned_employee_id` | Field work revolves around technicians, not generic employees | Employee view | Technician-centric board (the visiting person + their vehicle/tools) | P1 | Matches real field workflow |
| 5.3 | **Technician data/link integrity** — token-link + submissions storage | Field updates must land in the right place, not scattered | Loose | Structured technician-submission storage + robust job links | P1 | Reliable field-to-office data |
| 5.4 | **Employee vs technician role** not cleanly separated | Two different users (office account vs site visitor) | Conflated | Explicit role/flag + scoped views (office CRM vs portal) | P2 | Clear, correct access per role |

## BATCH 6 — Invoicing & money correctness (P1)

| # | Issue | Why fix | Before | After | Sev | Effect on CRM |
|---|---|---|---|---|---|---|
| 6.1 | **Skonto stored but NOT applied** to totals (INV-033) | Discount shown but not calculated → wrong amounts | Incorrect totals | Apply Skonto to computed totals | P1 | Financially correct invoices |
| 6.2 | **Orphan auto-invoice** on case completion (INV-027, dead code) | Confusing/unreachable path | Dead code | Wire it (auto-invoice on completion) or remove | P2 | Clean, predictable behavior |
| 6.3 | **Invoice auto-fill incomplete** | Non-techy user expects everything pre-filled | Manual re-entry | Prefill all customer/case/line/address/VAT data | P1 | Fewer errors, less typing |
| 6.4 | KVA→invoice / numbering / validity / catalog-dedup partials (INV-002/009/012/030) | Several half-done money flows | Gaps | Complete each | P2 | Consistent quoting→billing |

## BATCH 7 — Stripe billing production-readiness (P1, launch)

| # | Issue | Why fix | Before | After | Sev | Effect on CRM |
|---|---|---|---|---|---|---|
| 7.1 | **Test-key only** — not on live keys | Can't bill real customers | Sandbox | Live keys + deploy (your approval) | P1 | Real revenue |
| 7.2 | **Copilot cost cap NOT enforced** (COP-023) | Monthly cap exists but never blocks → runaway AI spend | No ceiling | Enforce cap on chat/confirm | P1 | Cost control at scale |
| 7.3 | Webhook idempotency + usage metering accuracy + 80% warnings + overage — *verify-first* | Billing must be exact for production | Partly verified | Hardened + reconciliation tests | P1 | Trustworthy billing |
| 7.4 | Trial period (BILL-029, 14-day) — *verify-first* | Trial logic must be correct at signup | Partial | Verify + finalize | P2 | Correct onboarding economics |

## BATCH 8 — Open Actions / notifications / dashboard (P2, usability)

| # | Issue | Why fix | Before | After | Sev | Effect on CRM |
|---|---|---|---|---|---|---|
| 8.1 | Reschedule/cancel → **Open Actions** completeness — *verify-first* | Non-techy user relies on a clear action list | Possibly partial | Verify every reschedule/cancel surfaces as an action | P2 | Nothing slips through |
| 8.2 | **Case notification bar ↔ dashboard pending** consistency | Two surfaces must agree on "what's pending" | Risk of mismatch | Single source of pending → both views | P2 | Trustworthy "to-do" signals |
| 8.3 | **Project tier dormant** (0/32 linked) | People may use it; must work if shown | Unused, untested | Activate with UX, or hide until ready | P2 | No half-working tier confusing users |
| 8.4 | **Customer numbering inconsistent** (KD-/KI-/bare) | Looks unprofessional, breaks sorting | Mixed schemes | Unify to one scheme (back-fill optional) | P2 | Clean, consistent records |

## BATCH 9 — Cosmetic / data hygiene (P2)

| # | Issue | Why fix | Before | After | Sev | Effect on CRM |
|---|---|---|---|---|---|---|
| 9.1 | **Test data leaks into live prompt** (categories "ruskin"/"Pipe isssue", English text in conversation-logic) | Unprofessional agent behavior | Garbage in prompt | Validation + cleanup of org config | P2 | Polished agent |
| 9.2 | Minor: prompt KB stub messaging, Berlin-time edge cases, `voice_id` not in DB | Small reliability/polish | Various | Tidy up | P2 | Overall polish |

---

## Suggested execution
- **Sprint 1 (P0):** Batch 1 + Batch 3 — make the agent's heart recoverable and the data secure.
- **Sprint 2 (P0/P1):** Batch 2 + Batch 4 — reliable onboarding + correct receptionist behavior.
- **Sprint 3 (P1):** Batch 7 + Batch 6 — money correct & billable for launch.
- **Sprint 4 (P1/P2):** Batch 5 + Batch 8 + Batch 9 — field workflow + usability + polish.

Each batch is independently shippable. Recommend starting with **Batch 1.1/1.2** (real undo/rewind) and **Batch 3.1/3.2** (RLS) in parallel.

---

## Implementation status & verification (updated 2026-06-17)

### ✅ Batch 3 — DONE (applied to the live DB, migration `0074`)
Recon proved it materially safer than the audit implied: the **frontend has zero anon-key data calls** (only `auth.*`), so no RLS change can break the app. Applied:
- **16 org-scoped RLS policies** (`<table>_org_all` via `auth_org_id()`) on the deny-all tables that have `org_id`.
- Pinned `kz_begin_agent_sync` `search_path`; revoked `rls_auto_enable` EXECUTE from public/anon/authenticated.
- **Intentionally left deny-all:** `org_secrets`, `oauth_connections` (secret-bearing, least-exposure), `billing_security_events`/`billing_webhook_events` (no `org_id`, backend-only). `auth_org_id()` left unchanged (policies depend on it).
- Advisories dropped ~24 → 6; the 6 remaining are all intentional or the one manual item below.
- **Remaining (manual, your action):** 3.4 leaked-password protection — Supabase Dashboard → Auth → Password settings → enable HaveIBeenPwned (or Management-API `password_hibp_enabled:true`). Not SQL.

### 🔧 Batch 1 — IN PROGRESS (UAT only, no deploy)
Recon finding: snapshots **already store** `platform_settings`, so 1.1 is a restore-side fix (no migration). 1.2 ~70% built. One additive migration `0075` for drift (1.3). Building backend + frontend now.

### Investigation verdicts — all three CONFIRMED, keep in plan (now sharper)
| Item | Verdict | Concrete confirmed gaps |
|---|---|---|
| **4.5** emergency/hours/windows | PARTIAL — core correct + tested | (a) `emergency_extra_windows` + surcharge render paths **untested**; (b) `get_available_slots` constraint logic (buffer/parallel/max-per-day/earliest-clock) **never exercised** — every booking test stubs it to zero → real double-booking risk if broken; (c) outside-hours booking gate is **LLM-instruction-only**, no backend enforcement |
| **7.3/7.4** Stripe | PARTIAL — sig-verify/idempotency/overage solid | (a) **14-day trial is NEVER applied** — the UI sends no `trial_days`, so every checkout goes to Stripe with no trial *(real bug)*; (b) 80% quota-warning path **untested**; (c) `period_start` **timezone mismatch** can silently under-count usage *(real bug)* |
| **8.1** Open Actions | PARTIAL — happy paths work | (a) unmatched reschedule (`FORWARDED_TO_TEAM`) creates an inquiry but **no Open Action → invisible**; (b) the `appointment_cancelled` card's "Bestätigen" calls reject which requires `status=pending`, but the appt is already `cancelled` → **always 409** *(real bug)*; (c) `customer_proposed_at` stamp wrapped in bare `except:pass` (silent failure) |

These three become **B4.5**, **B7.3/7.4**, **B8.1** with the specific fixes above — no rebuilding of what already works.
