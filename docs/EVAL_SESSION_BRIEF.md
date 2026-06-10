# EVAL SESSION BRIEF — "Measure first, fix second"

> Written 2026-06-10 at the end of the Kiki-Zentrale improvements session
> (branch `improvements-kiki-zentral` = `main`, both at the same commit).
> This file IS the plan for the next session. The session has ONE motive:
> **evaluate the CRM and the agent with real data, and produce a prioritized,
> evidence-backed fix list.** No speculative fixes — numbers first.

---

## 0. Context the session should load (in this order)

1. `SESSION_HANDOVER.md` — "Recent changes" section (top ~6 bullets cover
   everything shipped 2026-06-09/10: Kiki-Zentrale batch, Hey-Kiki panel,
   live form-takeover, chat sessions, system-tool management).
2. `ARCHITECTURE_REAUDIT_2026-06-08.md` — last audit baseline + method
   (parallel finder agents + independent adversarial verifiers; trust the
   verifier over the finder).
3. `docs/PROMPT_SIZE_STRATEGY_2026-06-04.md` — the prompt-reduction levers.
   **Second-opinion amendments agreed 2026-06-10:**
   - Skip MCP (lever A as written). ElevenLabs already passes each `hk_*`
     tool's schema+description to the LLM natively — the prompt's tool cards
     are duplicates. The win = move guidance into the EL tool descriptions
     (managed in code via `sync_system_tools_for_org` / tool config) and
     delete the cards.
   - `hk_queryKnowledgeBase` (backend `app/services/knowledge.py`) is a STUB
     that always answers "no information". The native EL knowledge base
     (attached docs, `usage_mode: auto` — used by the price list,
     `app/services/price_knowledge.py`) actually works. Fix or remove the
     stub BEFORE any KB-offload work.
   - Rendered prompt for the test org measured 2026-06-10: **~63.7k chars
     (~16k tokens)** — grew with Leitfaden offer-steps, Gesprächslogik
     "Schritt 1a", price-info rules. Reduction is more urgent, not less.
4. Memory auto-loads the operating constraints; the load-bearing ones:
   - Local backend = **PROD Supabase** (migrations 0056–0062 already live);
     test data ONLY in org kiki-test-007 (login kikitest01@gmail.com /
     KikiTest2026!, agent `agent_5001ksahz3w7fhx90j71xr800py4`).
   - Outbound is LIVE — anything that dials/emails reaches real customers.
   - No `railway up` / no deploy without explicit approval.
   - Backend has no hot reload (restart uvicorn); real FE check = `tsc -b`
     + `npm run build`; additive migrations pre-authorized via Supabase MCP.
   - Communicate in English; product UI stays German.
   - 5 backend test failures are PRE-EXISTING (payment-reminder cycles ×3,
     autonomy-render ×2) — fixing them is in scope for this session (P0).

## 1. Phase plan

### P0 — Instrumentation + hygiene (do first, small)
- [ ] Log rendered prompt size per org on every push: one line in
      `agent_config.rerender_and_push_for_org` (chars + ~tokens + org_id).
- [ ] Fix or delete the 5 permanently-red backend tests (signal hygiene —
      verify intent against git history before deleting).
- [ ] Inventory "dead/duplicative agent surface": the `hk_queryKnowledgeBase`
      stub; prompt tool-cards vs. the live EL tool descriptions (fetch the
      agent config via `ea.get_agent_config` and diff).
- Output: numbers in logs + a short DEAD_SURFACE list in the report.

### P1 — Agent/prompt eval harness (the core)
- [ ] Build a transcript corpus from REAL data: `calls` table already stores
      transcripts + summaries per org. Pull 15–25 calls covering:
      identification (known/unknown caller), booking (category match,
      Vorlaufzeit respected), emergency (keyword → transfer offer, NO
      booking), price questions (toggle on/off), off-topic/jailbreak attempts.
- [ ] Define a scoring rubric per scenario (pass/fail + notes): correct tool
      called? forbidden action avoided? German-only? no invented data?
- [ ] Replay mechanism: prefer ElevenLabs' agent **simulate/test-run API**
      (check current docs for the endpoint; they ship agent-testing
      features); fallback = scripted text-mode conversations against the
      agent. Store scenario + expected outcome as fixtures in
      `backend/tests/agent_evals/` so every future prompt change re-runs them.
- [ ] Baseline run BEFORE any prompt change; record pass-rate + per-turn
      latency + prompt tokens. THEN (only if time remains) apply prompt
      lever 1 (dedup/concision, `agent_prompt_template.txt`) and re-run —
      ship only if the eval holds.
- Output: `docs/AGENT_EVAL_BASELINE.md` with the rubric, corpus, scores.

### P2 — CRM functional + security eval (parallel agents, audit method)
- [ ] Seed the **business-rules registry**: `docs/rules/*.md`, one file per
      domain (termine, notdienst, preise, leitfaden, autonomie,
      gespraechslogik, outbound, copilot). Each rule: ID, one-sentence German
      statement, enforcing code (file:function), surfacing UI, covering test,
      prompt block. Distill from SESSION_HANDOVER history + this session's
      commits — do NOT invent rules; mark unknowns `[VERIFY WITH AMBER]`.
- [ ] Adversarial pass over everything built since the 06-08 audit (it has
      never been audited): Kiki-Zentrale batch endpoints (leitfaden,
      conversation-logic, sync-status), copilot panel + /confirm (note:
      /confirm accepts arbitrary args — bounded by org/role scoping, verify
      that bound holds for the NEW tools create_employee/create_project),
      live-fill protocol, price-KB sync, transfer-tool sync. Use the
      finder→adversarial-verifier pattern from the re-audit; trust verifiers.
- [ ] Known gaps to confirm + size (don't fix yet): no rate limiting
      (copilot/chat = OpenAI spend, login), non-durable background work
      (repush, price-KB sync, L3 confirmations), no error tracking (Sentry),
      `VITE_COPILOT_ENABLED` missing from `frontend/Dockerfile` (prod build
      would silently drop the Hey-Kiki button).
- Output: findings folded into the report with verifier verdicts.

### P3 — The deliverable
- [ ] `docs/EVAL_REPORT_<date>.md`: every finding with **evidence** (log
      line, failing eval, code ref), severity, effort (S/M/L), and a single
      ranked DO-NEXT list (impact ÷ effort). Explicitly mark what to IGNORE
      and why — that's half the value.
- [ ] Append a dated SESSION_HANDOVER bullet; commit + push (branch + main
      stay in sync); NO deploy.

## 2. Hard rules for the session
- Measure before changing. The ONLY behavior-affecting code changes allowed
  are P0 instrumentation + red-test fixes; prompt lever 1 only if the eval
  harness exists and passes baseline first.
- Live agent experiments only against kiki-test-007's agent (the safe-write
  layer snapshots + audits every push; rollback exists).
- NO real phone calls placed by the session (text simulation only) — live
  call checks remain Amber's manual step.
- If the Supabase MCP is unreachable (it flaked on 2026-06-10), DDL waits;
  everything in this plan works without new DDL.

## 3. Kickoff prompt (paste this to start the session)

> Read `docs/EVAL_SESSION_BRIEF.md` and follow it as the session plan.
> The mission is evaluation with real data, not fixing: instrument prompt
> size (P0), build the agent eval harness from real transcripts and run the
> baseline (P1), seed the business-rules registry and run the adversarial
> audit over everything built since 2026-06-08 (P2), and produce the ranked
> evidence-backed EVAL_REPORT (P3). Ask me before anything that changes
> user-visible behavior. Work on branch `improvements-kiki-zentral`, keep
> `main` in sync, no deployment.
