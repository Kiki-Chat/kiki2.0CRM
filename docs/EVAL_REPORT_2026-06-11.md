# EVAL REPORT — 2026-06-11

> "Measure first, fix second." This session evaluated the CRM and the voice agent
> with real data and produced this ranked, evidence-backed list. **No behavior
> was changed** beyond the P0 items the brief allowed (prompt-size log line,
> 5 stale-red test fixes). Branch `improvements-kiki-zentral`, no deploy.

## Method
- **P0**: prompt-size telemetry on every push; 5 red tests fixed (all were stale fixtures, prod code correct — suite now 614/614 green); dead-surface inventory from the live EL agent config + workspace tools.
- **P1**: eval harness (`backend/tests/agent_evals/`) — 12 scenarios replayed via the ElevenLabs simulate-conversation API (all tools mocked, zero side effects) + 23 REAL transcripts graded by two independent LLM judges. Full detail: `docs/AGENT_EVAL_BASELINE.md`.
- **P2**: business-rules registry (`docs/rules/`, 98 rules, 8 domains) + adversarial audit of everything built since the 06-08 audit: 8 parallel finders → 1 independent adversarial verifier per finding (instructed to refute). **39 findings confirmed (3 high / 24 medium / 12 low), 0 fully refuted** — verifiers did push back by downgrading several severities and killing parts of claims; every verdict carries an end-to-end code trace.
- Notable clean result: the **copilot `/confirm` org/role bound held** under adversarial review — including the new `create_employee`/`create_project` tools. No findings on that surface.

## The numbers
| Metric | Value |
|---|---|
| Prompt (test org) | **64,352 chars ≈ 16.1k tokens**; tool cards ≈ 26% of it |
| Replay baseline | **11/12 pass** (single real fail: price leak) |
| Real-call grading (23 calls) | **11 PASS / 7 PARTIAL / 5 FAIL** |
| Per-turn latency (real) | median 4s, mean 5.7s, p90 11s |
| Backend tests | 614 passed / 0 failed (was 609/5) |
| Rules registry | 98 rules: 62 enforced, 20 prompt-only, 14 partial |

---

## DO-NEXT (ranked by impact ÷ effort)

### 1. Detach the orphaned price doc + harden `sync_price_list_kb` — **S, live bug right now**
**Evidence (three independent sources):** replay scenario quoted **"189 Euro"** with `price_info_enabled=false`; a real call (06-09) recited "49 €/75 €"; live state shows doc `VfqW6SCundFX7pnSbsUL` ("Preisliste (Richtpreise)", `usage_mode: auto`) **still attached** to the test agent while the toggle is off and `price_list_doc_id` is set.
**Root cause chain (audit-confirmed):** `_detach_and_delete` swallows EL errors, then its `finally` **unconditionally nulls `price_list_doc_id`** → the doc becomes untracked and no code path can ever remove it (`price_knowledge.py:139`). Plus: create/attach/DB-update has no compensation (orphan docs accumulate), and 5 fire-and-forget triggers can race (duplicate attached docs).
**Fix shape:** immediate manual detach for the test org; reconcile by `DOC_NAME` (not just stored id) on every sync; only clear the column after confirmed detach.

### 2. Phantom capture — agent claims "Anliegen aufgenommen" without calling any tool — **M, top real-call defect**
**Evidence:** 3 of 23 real calls hard-failed (#17, #19, #20): caller reports a broken device / no warm water / second concern, agent says "ich nehme Ihr Anliegen direkt auf … wir melden uns", **`hk_createInquiry` is never called**, the call ends, the data is lost. The same canned closing fires even when nothing was captured, so the failure is invisible.
**Fix shape:** (a) prompt: forbid the closing claim unless a write tool succeeded in-call; (b) backend detection: post-call check "agent text claims capture AND no write-tool call in transcript" → flag the call log for staff. Re-run the eval harness after the prompt change (it now exists for exactly this).

### 3. Reschedule machinery hardening — **M; 2 of the 3 high findings live here**
- **HIGH — non-atomic expiry sweep** (`outbound_dispatch.py:752`): SELECT-then-UPDATE with no conditional guard or claim step (unlike `run_due_retries`); racing an admin approve can **cancel a just-confirmed appointment and double-notify a real customer**.
- **HIGH — misleading "Ablehnen"** (`AppointmentCard.tsx:624`): the card says declining "verwirft nur den Vorschlag", but with `replace_intent=true` the backend **cancels the appointment and calls/emails the customer**; the card can't know — `reschedule_replace_intent` is missing from both select lists (`appointments.py:479-516`).
- approve-proposal has **no status gate** and `_cancel` doesn't clear proposal fields → a cancelled appointment can be resurrected to "confirmed" + confirmation call.
- decline-with-replace and L3 expiry **never delete the Google Calendar event**; approve never moves it → field staff on Google see the wrong time.
- L3 expiry cancellation calls **bypass outbound time windows** (can dial at night).
**Fix shape:** conditional UPDATEs (`.not_.is_("customer_proposed_at","null")` + expiry re-check), status gates, add `reschedule_replace_intent` to the selects + branch the card copy, Google-sync on the two new cancel paths, route expiry notifications through the window gate.

### 4. Dead `forwarding_number` fallback in emergency transfer — **S**
`_fetch_kz_config` never SELECTs `forwarding_number`, yet `build_transfer_tool` and `render_emergency_block` fall back to it (`agent_config.py:1321`, `:794`). A legacy org with only `forwarding_number` set gets **no transfer tool and a prompt saying "leite NICHT weiter"** — silently. One-line fix (add the column to the SELECT) + check prod rows for affected orgs.

### 5. `/cases/propose` skips the AI cost cap — **S**
`within_cap` is enforced only in the offline runners; the live endpoint (`cases.py:34`, employee-callable) makes embeddings + gpt-4o calls with no cap, no rate limit. Add the `within_cap` gate (mirrors apply_run.py:32).

### 6. Numbering integrity: K-codes and case numbers — **S/M**
- `gen_case_number` is COUNT+1 with **no unique constraint** (migration 0057 index is non-unique) → concurrent creates mint duplicate K-numbers; deletes cause re-issuance. Same pattern in `gen_inquiry_number`.
- `get_org_code` swallows the unique-violation and **returns the colliding org code anyway** (`common.py:362`).
**Fix shape:** unique index (additive migration, pre-authorized) + retry-on-conflict in the generators.

### 7. Password-reset redirect allowlist — **S, config-only, Amber's dashboard**
The reset flow redirects to `${origin}/set-password` — a **different URL** than the magic link's bare origin entry. If `/set-password` (or a wildcard) is not in Supabase Auth → Redirect URLs, the recovery link silently falls back to the Site URL (localhost default) carrying a live recovery token. SESSION_HANDOVER already lists this as pending; commit 95d13d1's message wrongly claims the magic-link entry covers it. **Action: add the entry in the dashboard (no code).**

### 8. Prompt reduction, now gated by the eval harness — **M, big leverage**
16.1k tokens per turn; the ~26% tool-card block duplicates the native EL tool descriptions that already reach the LLM. The agreed plan (move guidance into EL tool descriptions via code, delete cards) is now safe to execute: run baseline → change → re-run; ship only if 11/12 holds. p90 turn latency of 11s should also improve. **Not done this session — behavior-affecting, needs your go.**

### 9. Fix-or-remove the `hk_queryKnowledgeBase` stub — **S**
Attached to every agent, prompt says "rufe es IMMER zuerst auf", its EL description claims it searches PDFs/URLs/prices — but the backend always answers "no information" (`knowledge.py:11`), contradicting the working native KB beside it. Either route it to the native KB content or detach the tool + prompt block. Also: legacy `hk_transferCall` still exists in the workspace alongside `transfer_to_number` — one transfer surface should go.

### 10. Operational gaps (confirmed, sized) — **M each, schedule deliberately**
- **No rate limiting anywhere** (login, copilot/chat = OpenAI spend). Confirmed by grep; medium-term: slowapi on auth + LLM endpoints.
- **No error tracking** (no Sentry). The audit found a dozen swallowed-exception paths whose only trace is a `logger.warning` — Sentry would have surfaced the price-KB divergence months earlier.
- **Non-durable background work**: repush, price-KB sync, L3 confirmations all die with the process. Acceptable short-term; revisit with a queue when load grows.

## Smaller confirmed items (fix opportunistically, not urgent)
- PATCH `/verhalten`: DB write commits, then an EL failure skips repush AND sync banner — silent divergence (`kiki_zentrale.py:486-512`). Same family: `/leitfaden` no_prices guard fires after row writes (low).
- Live-fill: 60s fallback timer can **double-execute a confirmed write**; payload unconsumed when the form route is already mounted (falls back to API write the user doesn't see); first-substring customer matching diverges from the backend path.
- system-tool sync: staff-transfer dedupe can remove the transfer tool entirely while the prompt still references it; `_restore_full` rollback unverified; transfer numbers persisted with zero validation.
- copilot sessions: reload silently drops messages past 200 rows; list capped at 30, no pagination; non-UUID id → 500; turn ordering ties.
- `move_inquiry_case` allows filing an inquiry into ANOTHER customer's case (org-internal only, reversible — low).
- Sync supabase calls on the event loop in `begin_sync` (use `run_in_threadpool`).

## IGNORE (deliberately — and why)
- **`agent_sync_seq` stale-push race** (audit-confirmed, medium): real but needs two saves racing within seconds AND a stalled EL call; the banner machinery works for the 99% case. Revisit only if divergence is ever observed.
- **Expiry-sweep `limit(200)` starvation, empty-case orphans, copilot 30-chat cap, created_at tie ordering** (lows): real, cheap, but none affects customers; batch them into a hygiene PR someday — do not schedule individually.
- **Wholesale "prompt-only → enforced" hardening** of the 20 prompt-only rules: the eval shows tool ROUTING is reliably good; enforcement effort should go to the specific failures above (phantom capture, prices), not blanket guards.
- **Voicemail `{{voicemailMessage}}` on inbound** (low): cosmetic; inbound never plays voicemail.
- **The 5 "red" tests**: already fixed this session — they were stale fixtures, not signal.
- **`VITE_COPILOT_ENABLED` Dockerfile gap from the brief: already closed** (line 15 of `frontend/Dockerfile`) — no action.

## VERIFY WITH AMBER (from the rules registry, `docs/rules/README.md`)
1. **AUT-05** — at KVA L1+enabled, the server would still create a draft (only the prompt blocks it). Hard-block server-side?
2. **AUT-09 / OUT-11 / OUT-07** — reschedule-proposal flow, expiry sweep, and short-hangup retry have no test coverage. Intended?
3. **OUT-09** — `enforce_call_scope` doesn't guard the autonomous sweep (moot while LIVE; matters if the test-scope flag returns).
4. **COP-14** — copilot has no L1–L3 gating, only the confirm gate. Intentional?

## Artifacts
- `docs/AGENT_EVAL_BASELINE.md` — rubric, both baselines, failure patterns.
- `backend/tests/agent_evals/` — re-runnable harness + fixtures + baseline results.
- `docs/rules/` — 98-rule registry + README index.
- Full audit JSON (39 verified findings, verbatim traces): session task output; the top items are reproduced above with file:line.
