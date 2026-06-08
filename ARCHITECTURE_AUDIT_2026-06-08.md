# KikiJarvis — Architecture & Performance Audit

**Date:** 2026-06-08
**Author:** Lead engineering audit pass
**Stack:** FastAPI + supabase-py (sync client) + Postgres (Supabase, Tokyo) · React + Vite + TailwindCSS + React Query · deployed on Railway (Singapore) · German-only UI.

## Scope & Method

This report covers six dimensions: **Parallelism & Concurrency**, **Caching**, **Backend Architecture**, **Frontend Layout/Padding/Adaptability**, **Frontend Architecture/Rendering**, and **Data Access & Database**. Findings were produced by parallel "finder" passes over the actual codebase, then each finding was **adversarially verified** against the real source — every finding here carries a `verdict` (confirmed / partly-confirmed) with a recalibrated severity. Where a verifier weakened or refuted a claim, I have down-ranked or dropped it and say so explicitly. I trust the verification over the original claim throughout. This document is written as a **fix guide**: every finding teaches *why* the problem is bad and *why* the fix works, because the goal (per the brief) is to fix things with reasoning, not just check boxes.

This report **extends and deepens** the existing `PERFORMANCE_PLAN.md` (2026-06-05). It does not duplicate it. Section 3 below states precisely what it confirms, corrects, and adds.

---

## 1. Executive Summary

### 1.1 Health Scorecard

| Dimension | Grade | One-line verdict |
|---|---|---|
| Parallelism & Concurrency | **C** | Good `asyncio.gather` patterns exist in 3 hot routes, but blocking-in-async, serial fan-out, an unmanaged daemon thread, and durability-free BackgroundTasks remain. |
| Caching | **B−** | Architecture is mostly sound (30s `staleTime`, fail-open Redis), but a few real staleness/correctness traps: un-TTL'd tool-ID cache, missing `useMemo` on context values, no stampede guard. |
| Backend Architecture | **C−** | Works and is correctly org-scoped, but multi-write operations have **no transactional atomicity**, business logic lives in 1000-line route files, FK-in-org validation is applied inconsistently, and config ships unsafe defaults. |
| Frontend Layout / Padding / Adaptability | **D+** | **The weakest area.** No mobile strategy at all: fixed-pixel sidebar, non-responsive tables/modals/widgets, missing `truncate`/`min-w-0` causing overflow leaks, and an ad-hoc padding scale. |
| Frontend Architecture / Rendering | **B** | Solid foundations (code-split, clean auth separation, sensible React Query config). Issues are re-render hotspots and a recurring uncleaned-`setTimeout` leak pattern. |
| Data Access & Database | **C** | FK indexes shipped (good), but **PostgREST's silent 1000-row cap** causes genuine correctness bugs in CSV dedup, number generation, and count enrichment at scale. |

### 1.2 Highest-Leverage Fixes

| Fix | Why it matters | Severity | Effort |
|---|---|---|---|
| Paginate the CSV-import dedup read (`csv_import.py:330`) | Silent **data corruption**: >1000 existing customers → duplicates slip through; violates the documented "re-running the file imports nothing new" contract. | Critical | S |
| Wrap multi-step writes in compensating transactions (appointments, invoices) | Step-1-succeeds/step-2-fails leaves **orphaned inquiries and broken KVA↔invoice links** — data integrity, not perf. | High | M |
| Fix the unbounded count/timeline reads (customers, projects, customer-timeline) | Silent **wrong numbers** in the UI ("2 calls" when there are 50) past 1000 rows. | High | M |
| Replace the `post_call` daemon thread with coordinated/durable work | Unmanaged thread runs **real outbound calls/emails** with no dedup → duplicate customer contacts; lost on restart. | High | M |
| `useMemo` the Theme (and Admin) context value | App-wide re-render cascade on every navigation/query update from a single missing memo. | High→Med | S |
| Make the layout responsive (sidebar drawer + responsive tables/modals/widget) | The app is **unusable on tablets/phones**: sidebar eats 64% of a phone, tables illegible, widget overflows viewport. | High | M |
| Remove the unsafe `master_webhook_secret = "change-me"` default + fail-fast on startup | Anyone who knows the default string can POST to webhook endpoints if the env var is unset. | High | S |
| Wrap `outbound_dispatch` email send in a 5s timeout | A slow email provider blocks **live outbound dispatch** of dozens of calls. | High | M |

---

## 2. (reserved — see Section 1)

## 3. Relationship to PERFORMANCE_PLAN.md (2026-06-05)

`PERFORMANCE_PLAN.md` is an excellent, measured, code-level perf doc. This audit is **broader** (it adds correctness, architecture, security, layout) and **deeper** on the dimensions it shares. Concretely:

**What this report CONFIRMS from the plan:**
- The fan-out / no-parallelism thesis is real and still partly unfixed. The plan named `customers`, `calls`, `dashboard` as the parallelism wins; this audit confirms `customers._list` and `dashboard.overview` now use `asyncio.gather` correctly, but extends the list of *still-serial* endpoints the plan did not enumerate: `calls._build_timeline` (4 serial), `customers._detail` (4 serial), `projects._list` (6–7 serial), `employees._list` (2 serial), `invoices`/`cost_estimates` enrichment, `calls._list` enrichment, and `dashboard._anrufe`/`_finanzen`.
- The 1000-row PostgREST correctness concern flagged as an *open question* (plan §7, §2.4) is **now confirmed as multiple live bugs** — see Data Access D1–D4.
- The "delete is choppy" race and over-invalidation (plan §3, §4.B4) are confirmed (Caching C5), though the optimistic-delete code now present has **changed the shape** of the residual risk (see correction below).

**What this report CORRECTS (current code already moved past the plan):**
- **`staleTime: 0` is FIXED.** The plan (line 109) says staleTime defaults to 0. The code now sets `staleTime: 30_000` globally (`main.tsx:11-19`) with sensible per-query overrides (`/api/me` 5min, calls 10s). **Update the plan.** (Finding `react-query-stale-time-30s-good`.)
- **Route code-splitting is FIXED.** The plan (line 111) says "22 eager page imports." `App.tsx` now lazy-loads all pages via `React.lazy` + `Suspense` + a `ChunkErrorBoundary`. (The exact count is 21 lazy + 2 eager structural pages, not 22.) (Finding `bundle-split-correct-22-pages`.)
- **FK indexes shipped.** Migration `0044` (and per the data-access summary, `0046`) added the ~45 FK covering indexes the plan prioritized in §4.A1. The data-access dimension confirms these address the index gap. The remaining DB issues are the **read-cap correctness bugs**, which indexes do not fix.
- **The optimistic-delete race is narrower than the plan implies.** The plan describes the row reappearing from stale cache; the verifier found the current `CallDetail.tsx` mutation already uses matching `['calls']` keys for cancel/setData/invalidate, so the practical window is small (Caching C5, downgraded to Medium).

**What is NET-NEW here (absent from the plan):**
- All of **Backend Architecture** (atomicity gaps, god files, FK-in-org IDOR discipline, unsafe config defaults, error swallowing).
- All of **Frontend Layout** (no mobile strategy, padding scale, overflow leaks) — the plan touched only loading-skeletons in passing.
- **Parallelism correctness/safety** beyond perf: the `post_call` daemon thread (race + lost-on-restart), BackgroundTasks durability, and several sync-network-in-async-via-background-task paths.
- The **caching staleness/leak** analysis (tool-ID cache, JWKS TTL, stampede, negative caching, SPA chunk-staleness).

---

# 4. Detailed Findings by Dimension

> Severities below are the **verdict-adjusted** values, not the original claims. Findings the verifier refuted or strongly down-ranked are noted and demoted.

---

## 4.1 Parallelism & Concurrency  *(Priority 1)*

**The shape of the problem.** Each gunicorn worker is one asyncio event loop plus an AnyIO threadpool. The Supabase client is **synchronous**, so the correct pattern is: async route handler → `await run_in_threadpool(sync_db_fn)`. Two structural anti-patterns recur: (a) **blocking work running directly in the async path** (no threadpool), which stalls the *entire* worker's event loop; and (b) **independent queries awaited serially** instead of via `asyncio.gather`, which wastes the concurrency the threadpool already offers. A third, more dangerous pattern is **uncoordinated background work** (a raw daemon thread, and fire-and-forget BackgroundTasks) that can run real-world side effects with no dedup, retry, or durability.

### [HIGH] `conversation_init` blocks the event loop on every inbound call — `conversation_init.py:10-15`
**What's wrong.** The handler is `async def` but calls `init_service(org_id, caller_id)` directly. `init_service` (`services/conversation_init.py:79-111`) is fully synchronous and runs two Supabase queries (customer lookup + agent-config welcome message). No `await`, no `run_in_threadpool`.
**Why it's bad.** An `async def` that does blocking I/O is a *false* coroutine — it never yields to the event loop. With only 2 workers, while those ~20–50ms of DB I/O run, that worker handles **nothing else**. This fires at *call connect* for every inbound call, so 10 concurrent calls serialize behind each other and produce cascading latency right at the moment the caller is waiting for the agent to greet them.
**How to fix.** `return await run_in_threadpool(init_service, org.org_id, payload.caller_id)`. The fix works because `run_in_threadpool` moves the blocking call onto a thread, letting the event loop service other requests during the DB round-trips; the Supabase `httpx.Client` is thread-safe so no extra locking is needed. This is the codebase's own established pattern (used in `post_call.py`, `tool_assets.py`, `catalog.py`, `deps.py`).
**Effort / Confidence:** S / High.

### [HIGH] `outbound_dispatch` sends email synchronously inside live dispatch — `outbound_dispatch.py:139-168` (call site 327)
**What's wrong.** `_maybe_send_occasion_email` calls `send_email()` (a blocking SMTP/HTTP call with **20–30s** provider timeouts per `email_send.py`) with no timeout of its own. It runs *after* the call is placed but still on the dispatch path; in the sweep (`run_due_outbound`, loop ~433-489) every record waits on it.
**Why it's bad.** Outbound is **LIVE** (per memory: `OUTBOUND_TEST_SCOPE_ONLY=0`). A slow provider doesn't just delay one email — it serializes the entire sweep: 50 records × ~25s could turn a seconds-long sweep into 15–25 minutes, delaying real customer calls. The email is explicitly documented as "NEVER fatal," so making it block the dispatch is the wrong trade.
**How to fix.** Add a hard 5s timeout at the call site (`concurrent.futures` future with `.result(timeout=5)`, or thread the call and abandon on timeout). It works because the call is already placed before the email runs (line 301-307), the generic `except` at line 165 already swallows failures, and most sends finish in <1s or fail fast on the scope check — so a 5s ceiling loses nothing and protects throughput. Medium-term, move email to a durable queue.
**Effort / Confidence:** M / High.

### [HIGH] `post_call` spawns an unmanaged daemon thread that runs real outbound side effects — `services/post_call.py:24-104` (thread at 104)
**What's wrong.** `threading.Thread(target=_run, daemon=True).start()` launches a fire-and-forget thread that mutates the DB (`UPDATE appointments SET status='confirmed'`) and sends emails/calls via `notify_appointment_outcome()`. No coordination with the HTTP response, no timeout, **no dedup lock**.
**Why it's bad.** Two overlapping post-call requests can spawn two threads that both confirm the *same* appointment → the customer gets **duplicate confirmations** (email + call) — and this is the OUTBOUND, real-customer path. On worker restart, in-flight threads are lost and the L3 appointment stays pending forever, silently. Daemon threads also accumulate with no backpressure if `_fire_level3_confirmations` is slow.
**How to fix.** Don't spawn raw threads. Short-term: pass the route's `BackgroundTasks` (already imported in `post_call.py:28`) into the service as an optional param so the work runs *after* the response, coordinated with it. Robust fix: persist pending L3 confirmations to a table and process them via a scheduled job, so they survive restarts and a `UNIQUE` constraint kills the duplicate-confirmation race. The fix works because durability + idempotency are exactly what an at-most-once daemon thread lacks.
**Effort / Confidence:** M / High.

### [HIGH] `projects._list` runs 6–7 independent queries serially — `projects.py:76-97`
**What's wrong.** The `rows()` helper is called 5× back-to-back (inquiries, appointments, cost_estimates, invoices, project_employees), then customers and calls in a second loop. All depend only on `pids`/`cids` from the initial projects query — none depends on another.
**Why it's bad.** ~7 × ~180ms ≈ 70–140ms of pure serial round-trips, blocking one threadpool thread the whole time. The planning board feels sluggish, and it gets linearly worse with project count.
**How to fix.** Make `_list` async and `await asyncio.gather(*[run_in_threadpool(q) for q in queries])` for the independent fetches. It works because the threadpool can run all 7 concurrently; wall-clock collapses to ≈ the slowest single query. Preserve the `.data or []` guards inside each. (Do **not** nest a second `ThreadPoolExecutor` inside the already-threadpooled sync function — that risks pool starvation; convert to async instead.)
**Effort / Confidence:** M / High.

### [HIGH] `calls._build_timeline` runs 4 serial queries on the cockpit hot path — `calls.py:426-540`
**What's wrong.** Serial SELECTs: calls → inquiries → appointments → cost_estimates. The inquiries query needs `call_id` (a real barrier), but appointments and cost_estimates depend only on `inquiry_ids` and are mutually independent.
**Why it's bad.** 40–80ms per timeline open, blocking a scarce threadpool thread. Opening several call "Verlauf" tabs quickly exhausts the pool and later requests queue. `build_customer_timeline` (lines 543-610) has the identical 4-serial pattern — fix both.
**How to fix.** After the inquiries barrier, gather appointments + cost_estimates concurrently (`asyncio.gather` with `run_in_threadpool`, or migrate this path to the installed async Supabase client). It works because you only pay one extra round-trip instead of three.
**Effort / Confidence:** M / High.

### [HIGH] `customers._detail` runs 5 serial enrichment queries — `customers.py:163-219`
**What's wrong.** `_detail` (sync, wrapped in `run_in_threadpool`) fetches inquiries → appointments → calls → cost_estimates one after another. Note the contrast: `_list` in the *same file* (140-144) already parallelizes correctly — so the pattern is known, just not applied here.
**Why it's bad.** Customer detail is a hot case-management page; 5 serial queries = 50–100ms instead of ~20ms parallel. (Verifier raised this from Medium to High precisely because the correct pattern sits a few lines away.)
**How to fix.** Make `_detail` async, extract the 4 fetches into separate sync functions, `asyncio.gather` them. Same justification as `_list`, which already proves it works here.
**Effort / Confidence:** S / High.

### [MED] `employees._list` runs 2 independent fetches serially — `employees.py:43-129`
**What's wrong.** Users fetch (62-71) then absences fetch (78-92); both depend only on the employee list, not on each other.
**Why it's bad.** The roster powers assignment dropdowns and presence indicators; 20–40ms of avoidable serial latency that grows with headcount.
**How to fix.** Convert to async, `asyncio.gather(run_in_threadpool(users), run_in_threadpool(absences))`. Pure win — no logic change.
**Effort / Confidence:** S / High (verifier confirmed approach).

### [MED] `dashboard._anrufe` / `_finanzen` fetch serially while `overview` does it right — `dashboard.py:202-402`
**What's wrong.** `overview` (175-184) is the good example: `asyncio.gather` over 8 queries. But `_anrufe` and `_finanzen` are **sync** functions that fetch their 2 independent queries (e.g. invoices + cost_estimates at 300-308) serially.
**Why it's bad.** The Anrufe/Finanzen tabs each pay ~40-60ms instead of ~20-30ms.
**How to fix — careful.** The verifier flagged the naive fix as unsafe: you **cannot** call `asyncio.gather` *inside* these sync functions. Instead, convert `_anrufe`/`_finanzen` to `async def` and gather internally, then `await` at the endpoint. The reasoning: gather needs a running loop, which only exists in the async layer, not inside a threadpool-executed sync function.
**Effort / Confidence:** S / Medium.

### [MED] `invoices`/`cost_estimates` enrichment is serial — `invoices.py:76-107`, `cost_estimates.py:58-94`
**What's wrong.** `cost_estimates._list` fetches customers (77-80) then inquiries (84-88) serially though they're independent. (`invoices._list` has only one enrichment fetch, so the verifier *partly-confirmed* — no parallelism opportunity there; the real case is cost_estimates.)
**Why it's bad.** Avoidable latency in the accounting UI.
**How to fix — note the gotcha.** The verifier warns `asyncio.gather` won't work as-written because the client is sync. Use a `ThreadPoolExecutor` to run the two fetches in parallel within the sync function, **or** convert to async + gather, **or** best: use a PostgREST relational select to fetch related rows in one round-trip. Pick one and apply consistently.
**Effort / Confidence:** S / Medium.

### [MED] ElevenLabs / OAuth sync HTTP calls block via background tasks — `elevenlabs_agent.py:92-99`, `oauth_tokens.py:14`
**What's wrong.** Both use `httpx.Client` (sync). The *direct* route calls are correctly wrapped (`patch_agent_safely` is awaited via `run_in_threadpool`, OAuth refresh runs inside threadpooled sync functions). The real gap: `_repush_bg` is added as a `BackgroundTask` **without** threadpool wrapping (`kiki_zentrale.py` lines 430, 540, 563, 593, 613, 647, 789, …), and it transitively calls blocking `get_agent_config()`. OAuth additionally has a **thundering-herd** risk: concurrent requests on an expired token all refresh at once (no lock).
**Why it's bad.** Background tasks run in the event-loop context after the response; an unwrapped blocking 100–300ms ElevenLabs round-trip there stalls the loop. Concurrent OAuth refreshes waste provider calls and serialize.
**How to fix.** Wrap background pushes: create an async wrapper that does `await run_in_threadpool(_repush_bg, …)` and add *that* as the task. For OAuth, add a per-`(org, provider)` lock around refresh so only one request refreshes and the rest await the result. Works because the blocking work leaves the loop, and the lock collapses N refreshes to 1.
**Effort / Confidence:** S–M / Medium.

### [MED] BackgroundTasks used for billing/config workflows with no durable retry — `post_call.py:28`, `stripe_webhook.py`, `kiki_zentrale.py:70-88`
**What's wrong.** Stripe usage reporting, webhook processing, agent-config pushes, and provisioning backfill all run as in-process `BackgroundTasks` — lost on worker crash/restart, no retry, no monitoring.
**Why it's bad — but calibrated down.** The verifier **down-ranked this from High to Medium**: the billing paths already persist to DB *before* queueing (`billing_usage_reports.call_id` / `billing_webhook_events.stripe_event_id` are UNIQUE), so they're idempotent and replayable; and the "outbound calls" claim was overstated (outbound uses `run_in_threadpool`, not BackgroundTasks). So it's ~3 workflows, not 5, and the highest-value ones are partly protected.
**How to fix — tiered, not uniform.** Don't move everything to a queue. For billing: add monitoring/alerting on rows that stay "pending" >30min and rely on the existing DB ledger for replay. For agent-config pushes: lower-risk, keep as BackgroundTasks but log failures at ERROR. Redis already exists (lazy-imported by `cache.py`) if a real queue is later warranted. The reasoning: durability investment should track failure *blast radius*, and the revenue-critical paths already have the idempotency keys that make replay safe.
**Effort / Confidence:** L (if full queue) / High.

### [MED] Shared `@lru_cache` Supabase client — thread-safety is assumed, not asserted — `supabase_client.py:8-16`
**What's wrong.** One cached `supabase.Client` (wrapping `httpx.Client`) is shared across all threadpool threads. `httpx.Client` is *not documented as* freely mutate-safe, though it is safe for concurrent request execution.
**Why it's bad — but bounded.** Verifier note: the real concern is `httpx.Client` not `lru_cache`; the 2-worker deployment limits contention to within-worker threadpool use, and one async path (`deps.py:43` `get_current_user`) calls it *without* threadpool wrapping. Catastrophic if the assumption ever breaks (cross-org leak), but low probability today.
**How to fix.** Ensure *all* client access goes through `run_in_threadpool` (fix the `deps.py` async path), keep the multi-worker isolation, and add a docstring stating the thread-safety contract with a link to httpx docs. The reasoning: the shared client is a real perf win (connection reuse) — the fix is to make the safety invariant explicit and enforced, not to abandon the cache.
**Effort / Confidence:** S / Medium.

### [DEMOTED] gunicorn `--timeout 30` and `-w 2`
The verifier **down-ranked both**. Measured prod p99 is 2.94s — nowhere near 30s, and `PERFORMANCE_PLAN.md` already shows the import is bulk-chunked and safe. The timeout bump is *defensive scaffolding*, not a fix; the worker count is explicitly a P3 (later) scaling lever and won't touch single-click latency. **Action:** leave both as-is; fix the serial queries (above) first, then re-measure. Bump timeout only if p99 approaches 30s; bump workers only when team size grows. (Findings `gunicorn-timeout-30s` → Medium, `gunicorn-workers-2` → Low.)

---

## 4.2 Caching  *(Priority 2 — examined strictly: staleness, leaks, memory, invalidation)*

**The lens.** A cache is only correct if four things hold: (1) **staleness bound** — how long can it serve old data, and is that acceptable for the data's volatility and security; (2) **invalidation** — every write that changes the source must clear the key; (3) **memory** — bounded size, no unbounded growth, no leaked timers/listeners; (4) **stampede** — concurrent misses don't all hit the source. Each finding below is graded against these.

### [HIGH] ElevenLabs tool-ID cache has no TTL and serves stale IDs for the process lifetime — `agent_config.py:107,158-180`
**What's wrong.** `_HK_TOOL_ID_CACHE` is a module dict populated on first miss and **never refreshed**. `_resolve_hk_tool_ids` only re-fetches when a *required name is absent* from the cache (line 166) — it cannot detect that a *cached* tool was **deleted/renamed** in the ElevenLabs workspace. The docstring (lines 42-46) claims "no stale-cache risk," which the verifier confirmed is **false**.
**Why it's bad (staleness + invalidation failure).** If an operator deletes/recreates an `hk_*` tool in the workspace, the cache keeps the dead tool ID for the entire worker lifetime; agent provisioning then patches the agent with a dead ID (line ~1010). Conversely a new tool needed but never cached forces failures until restart. This is the textbook "cache with no invalidation path for source-side mutation."
**How to fix.** Add a TTL: store a `_timestamp` alongside the dict, re-fetch when `now - ts > 3600` *or* on a missing required name; on re-fetch `clear()` then `update()` to evict orphans. Keep the timestamp under a reserved key so it can't collide with a tool name. It works because a bounded staleness window (1h) plus full-replace-on-refresh guarantees the cache converges to the workspace truth. Optionally expose `clear_cache()` for ops after a known tool change.
**Effort / Confidence:** M / High.

### [HIGH→MED] ThemeProvider rebuilds its context value every render — `lib/theme.tsx:22-25`
**What's wrong.** `value={{ theme, toggle: () => … }}` is a fresh object literal each render. (This appears twice in the JSON — `theme-provider-context-rebuild` and `theme-context-object-allocation` — **same finding, unified here.**)
**Why it's bad (memory/CPU via re-render thrash).** Context consumers re-render on *reference* change, not value change. Because `ThemeProvider` wraps the whole app, any parent re-render hands every `useTheme()` consumer a new object and re-renders it. Verifier scoped the real blast radius to current consumers (Topbar in the sticky header, settings modal, settings page) — hence Medium not High — but Topbar re-renders on every layout state change, so it's a genuine, cheap-to-fix waste.
**How to fix.** `const value = useMemo(() => ({ theme, toggle: () => setTheme(t => t === 'light' ? 'dark' : 'light') }), [theme])`. Works because identity is now stable until `theme` actually changes; consumers re-render only on real theme flips.
**Effort / Confidence:** S / High.

### [MED] AdminAuthProvider wraps an already-memoized binding in a fresh object — `admin/AdminAuthProvider.tsx:26-35`
**What's wrong.** `useSupabaseAuthBinding` already returns a `useMemo`'d `binding`, but the provider destructures it into a *new* object literal each render, throwing away the memoization.
**Why it's bad.** Every admin-tree consumer re-renders whenever the provider renders, defeating the upstream memo. AdminAuthProvider wraps all admin routes.
**How to fix.** Pass it through directly: `const value: AdminAuthContextValue = binding;`. It type-checks (the admin interface is a structural subset of the auth binding) and preserves the stable reference.
**Effort / Confidence:** S / High.

### [MED] `cache.get_or_set()` has no stampede protection — `core/cache.py:112-128`
**What's wrong.** On a miss, every concurrent request calls `loader()` independently. No lock, no soft-expiry.
**Why it's bad (stampede).** When a hot key expires (default TTL 300s, used on every `/api/me` for `org_identity`), all in-flight requests hammer Supabase simultaneously — a thundering herd at ~180ms/query, a latency spike every TTL window. Note this only bites when `REDIS_URL` is set (cache currently off by default).
**How to fix.** Use Redis `SET key val NX EX ttl` to atomically claim a "loading" lock — only the winner refreshes; others briefly serve stale or wait. The reasoning: a single atomic claim collapses N concurrent loads to 1 without a separate lock service.
**Effort / Confidence:** M / Medium.

### [MED] JWKS cache TTL is a hardcoded 1 hour — `core/security.py:12,20-29`
**What's wrong.** `_JWKS_TTL = 3600`, not configurable. The force-refresh fallback (line 55) only triggers when a `kid` is *absent*, giving zero protection for a *rotated-but-still-present* or *revoked* key inside the window.
**Why it's bad (security staleness).** On a leaked/rotated key, the backend keeps accepting old-key-signed tokens for up to an hour — violates zero-trust and slows incident response.
**How to fix.** Lower to `300` (5 min) and make it configurable: add `jwks_ttl_seconds` to `Settings`, read it in `security.py`, document the security rationale inline. Reasoning: a 5-min window bounds the exposure to a single refresh interval at negligible cost; configurability lets ops tighten further per environment.
**Effort / Confidence:** S / High.

### [MED→LOW] Optimistic delete cache reconciliation — `pages/calls/CallDetail.tsx:65-81`
**What's wrong (corrected).** The original claim was a key-mismatch race. The verifier found `cancelQueries`, `setQueryData`, and `invalidateQueries` all use the **same** `['calls']` key, and `onDeleted()` unmounts the detail view immediately, so the practical window is small. **Down-ranked to Low.**
**Why it's bad.** A theoretical race remains if a concurrent refetch lands between optimistic update and server response.
**How to fix.** Don't move invalidate into `onError`-only (that would skip the post-success refresh) and don't add a redundant `onSuccess` (onSettled covers it). The genuinely useful hardening is a small `staleTime` on the calls query and/or request dedup. This supersedes `PERFORMANCE_PLAN.md`'s sharper framing of the same bug — the optimistic code that landed since the plan already closed most of the gap.
**Effort / Confidence:** S / Medium.

### [MED→LOW] Over-invalidation on mark-read — `pages/CallLogsPage.tsx:94-100`
**What's wrong (corrected).** Original claim: mark-read needlessly refetches the whole dashboard. The verifier found two *distinct* query keys: `['dashboard','overview']` (the **lightweight sidebar unread badge**, AppLayout) vs `['dashboard-overview']` (the **heavy 8-query DashboardPage**). mark-read invalidates only the *light* one — and it **must**, because the backend overview *does* include `unread_calls`. **The proposed fix (remove the invalidation) would break the sidebar badge.** Down-ranked to Low.
**Why it's bad.** Minimal — the expensive multi-query dashboard is never invalidated here.
**How to fix.** Leave it. If anything, *add* `['dashboard-overview']` invalidation if you want the main page's unread KPI to stay in sync. Reasoning: invalidation must follow data dependency, and `unread_calls` genuinely depends on read state.
**Effort / Confidence:** S / High (the fix is "don't do the naive fix").

### [MED] SPA chunk-staleness after redeploy — `frontend/Dockerfile:20-27`
**What's wrong.** `serve -s dist` ships sensible defaults (`no-cache` on index.html), but a returning tab can still hold an old `index.html` referencing hashed chunks that no longer exist post-deploy → dynamic `import()` rejects → white screen.
**Why it's bad — but already largely solved.** The verifier found this *was* a real prod incident and the team **already shipped `ChunkErrorBoundary`** (commit 254f94e) that auto-reloads (sessionStorage-guarded) on chunk-load failure. That is the correct, server-agnostic fix and supersedes the proposed Cache-Control tweak.
**How to fix.** Nothing critical. Optional defensive hardening: add a `serve.json` documenting `index.html` = `no-cache, must-revalidate` and chunks = `immutable, max-age=31536000`. Reasoning: the error boundary handles the runtime failure; explicit headers just make the intent inspectable.
**Effort / Confidence:** S / Medium.

### [LOW] Negative results never cached — `core/cache.py:125-128`
`if value is not None: set(...)` means a `None` (not-found) is re-queried every time. Verifier: **latent**, not active — the only current loader (`me.py`) never returns `None`. Fix when a high-traffic 404 path appears: wrap in a sentinel `{'value': None}` so the outer object is cacheable. Effort S / Confidence (low impact today).

### [LOW] `@lru_cache` on `get_settings()` and `get_service_client()` — `config.py:153-158`, `supabase_client.py:8-16`
Both cache indefinitely; a runtime env change (e.g. enabling Redis, rotating the service key) won't be picked up without restart. Verifier: correct behavior for a 12-factor app — **do nothing but document it** in the runbook ("credential/env changes require a redeploy"). Adding a docstring on the client cache's thread-safety contract is the one worthwhile touch.

---

## 4.3 Backend Architecture  *(Priority 3)*

**The theme.** The backend *works* and is correctly multi-tenant (org_id filtered everywhere), but it leans on three fragile assumptions: that multi-step writes won't fail mid-way, that every developer will remember to validate client-supplied FK IDs, and that env vars will always be overridden in prod. Each assumption is a latent incident.

### [CRITICAL→HIGH] Multi-step writes have no transactional atomicity — `services/appointments.py:302-385`, `invoices.py:116-127`, `provisioning.py:143-202`
**What's wrong.** `book_appointment` inserts an inquiry, then an appointment — no rollback if step 2 fails. `invoices._create` inserts the invoice, then updates the cost_estimate back-link — no rollback if the update fails. Only `provisioning.py` (188-202) has compensating cleanup. supabase-py has no transaction; each `.execute()` is a separate HTTP call. (Note: the schema's `cost_estimates.invoice_id` is a *bare uuid with no FK constraint* — `0010_cost_estimates.sql:20` — so the DB won't even catch a bad back-link.)
**Why it's bad.** A network blip or validation error between the two writes leaves the DB in a partial state: an **orphaned inquiry** with no appointment (admin sees a phantom open inquiry), or an invoice whose KVA still shows "draft" with no `invoice_id` (the KVA→invoice conversion *appears* broken to the user). This is data integrity, not perf — silent, and it accumulates. (Verifier confirmed the code paths and adjusted to High; projects._create is a single atomic insert, so it's *not* affected — the original claim there was scope, not a bug.)
**How to fix.** Wrap each 2-step flow in try/except with a compensating action, copying the pattern provisioning already uses: `try: inquiry = insert(...); appt = insert(...) except: delete inquiry; raise`. For invoices, do the cost_estimate update inside the same try and reset on failure. Reasoning: in the absence of DB transactions, application-level compensation is the only way to keep the two writes all-or-nothing; deferring to async eventual-consistency is wrong here because users expect synchronous confirmation.
**Effort / Confidence:** M / High.

### [HIGH] Client-supplied FK IDs not validated against the caller's org (IDOR vector) — `projects.py:162-180`, `invoices.py:116-127` (contrast: `appointments.py:106-112` does it right)
**What's wrong.** The backend uses the **service-role** key (bypasses RLS) and relies on manual `.eq('org_id', …)`. But `projects._create` inserts `payload.customer_id` with no check that the customer belongs to the org, and `invoices._create` updates `cost_estimates` by `payload.kva_id` with no org check. `appointments._create` correctly calls `validate_fk_in_org` for all FKs — the helper *exists and is used*, just not everywhere.
**Why it's bad.** Service-role bypasses RLS, so the DB won't stop a cross-tenant link. A malicious org-A client can create a project pointing at org-B's customer, or flip org-B's cost-estimate via the invoice update — an IDOR that pollutes another tenant's data and breaks their audit trail. Even where the `org_id` filter currently saves you, normalizing "trust the client's FK" makes the *next* developer omit the filter and open a real leak.
**How to fix.** Call `validate_fk_in_org(client, 'customers', payload.customer_id, org_id, 'Kunde')` (and for `kva_id`, `project_id`) before every insert/update that accepts a client-supplied FK. It's the same idempotent helper appointments uses; it raises a clean 422 if the row isn't in the org. Reasoning: validate FKs *independently* of the main filter so security doesn't depend on remembering to scope every query. Also add the query-param filters in `calls.py:164-171` / `projects.py:151-158` (verifier down-ranked the list-filter case to Medium since `org_id` is applied unconditionally there — the **write paths are the High-severity part**).
**Effort / Confidence:** M / High.

### [HIGH] Unsafe config defaults ship "production-ready" — `core/config.py:14,85-86,114-119`
**What's wrong.** `master_webhook_secret = "change-me"` (default), `brevo_smtp_from_address` hardcoded to a specific domain, and outbound test defaults (`OUTBOUND_TEST_SCOPE_ONLY=True`, a test number, a developer email). No startup validation.
**Why it's bad — calibrated.** The verifier confirmed `master_webhook_secret` is the real danger: it authenticates `/api/post-call` and `/api/provision` (`deps.py:124-140`); if the env var is unset, **anyone who knows the literal string "change-me" can post to those endpoints.** It **partly-confirmed** the rest and *corrected* the outbound framing: `OUTBOUND_TEST_SCOPE_ONLY=True` is a **safety feature** (out-of-scope orgs are *refused*, not silently misdirected) — so the "customers silently get no calls" claim is overstated; the risk is service-degradation, not silent leakage.
**How to fix.** (1) Remove the `master_webhook_secret` default and **fail-fast on startup** if unset in prod — the reasoning is that a fallback secret is strictly worse than a crash, because a crash is loud and a fallback secret is a silent open door. (2) Move `brevo_smtp_from_address` to env with a dev-only fallback. (3) Don't over-engineer the outbound flag; just log its state at startup (INFO) so operators can see the scope mode. The outbound scope guard is otherwise well-designed.
**Effort / Confidence:** S / High.

### [HIGH] Business logic embedded in 1000-line route files — `kiki_zentrale.py:243-1057`, `appointments.py:102-556`, `dashboard.py:98-400`, `calls.py:40-128`
**What's wrong.** Routes mix HTTP handling + query building + multi-step business workflows + error handling. `kiki_zentrale.py` is 1057 lines with 36 endpoints, 34 `get_service_client()` calls, multi-step knowledge-upload→Supabase→ElevenLabs sequences with no transactional safety, phone validation, category reordering, etc.
**Why it's bad.** Logic that lives in route handlers can't be unit-tested without invoking HTTP; common patterns get copy-pasted instead of reused; and when a workflow fails mid-way there's no single place to add a rollback (this is the *same root* as the atomicity gap above — the two reinforce each other). Schema/org-scoping changes ripple across many routes.
**How to fix.** Extract to the existing `services/` layer: `services/kiki_zentrale.py` (grouped by domain), `services/dashboard_calculations.py` (period windowing + aggregations), enrich `services/appointments.py` with the confirm/reject orchestration. Routes become 5–10 line adapters: parse → call service → return. Reasoning: thin routes + fat services is what makes the atomicity wrappers, FK validation, and tests have *one* home each. This is a large but low-risk, incremental refactor (one domain at a time) — the public API doesn't change.
**Effort / Confidence:** L / High.

### [HIGH] Duplicated query+enrich and org-scoping logic — `appointments.py`, `calls.py`, `employees.py`, `projects.py`; `deps.py:61-85` + inline `_get`/`_detail` helpers
**What's wrong.** Every list endpoint reimplements fetch→extract-FK-ids→batch-fetch→map-back. Every detail endpoint reimplements `.eq('org_id',…).eq('id',…).limit(1)` (the verifier counted **221** `.eq("org_id"` calls across 23 files; the core lookup pattern ~10×). Role checks are re-done inline in some routes (`settings.py:368`, `kiki_zentrale.py:54`) despite a `require_org_admin` dependency existing.
**Why it's bad.** DRY violation with a security edge: when a scoping rule changes, every copy must change in lockstep — miss one and you've got an IDOR. Bugs in enrichment fallbacks get replicated; N+1-prevention strategy (`in_()` vs repeated selects) is applied inconsistently.
**How to fix.** Two reusable primitives in `services/common.py`: `verify_resource_org(client, table, id, org_id, label) -> row | 404` for lookups, and `batch_fetch_map(client, org_id, table, ids, id_field, fields) -> dict` for enrichment (the verifier correctly notes a single `batch_enrich` over-simplifies — routes enrich 2–6 tables and projects aggregates counts, so expose the *primitive* and compose). Use `require_org_admin` as a dependency instead of inline role checks. Reasoning: one tested helper beats 20 hand-rolled copies, and centralizing scoping is the only durable defense against the "forgot one route" IDOR.
**Effort / Confidence:** M / High.

### [HIGH] Bare `except` clauses swallow failures — `kiki_zentrale.py:83,293-294,737-738`, `employees.py:184-253`, `cost_estimates.py:168-169`, `provisioning.py:189-201`
**What's wrong.** Many `except Exception` blocks log at WARNING (or not at all) and continue. Examples the verifier confirmed line-for-line: `_el_read_state` returns `reachable=False` with **no logging** (can't tell an EL outage from an auth/key leak); employee invite creates the auth user but on email failure only appends a warning (admin doesn't know to resend); `_render_org_logo` silently swallows; provisioning rollback `pass`es on cleanup failures.
**Why it's bad.** Silent failures make incidents undiagnosable. A half-completed employee invite shows "created" while the person never got a login link. Background-push failures at WARNING slip past ERROR-level alerting. Indistinguishable error types mean operators retry identically and fail identically.
**How to fix.** Replace bare catches with typed handling: re-raise `HTTPException`; return structured `{success, error_code, error_message}` for `TimeoutError`/`ConnectionError`; log at **ERROR** for anything affecting user-visible state (auth, email, rollback) and WARNING only for truly best-effort (logo in a PDF). For the employee invite, add explicit semantics: on email failure either roll back the auth user or set a "needs-resend" flag. Reasoning: the log level *is* the alerting contract, and swallowing the exception type discards the one signal ops need to act differently.
**Effort / Confidence:** M / High.

### [MED] Incomplete input validation — `kiki_zentrale.py:386-397`, `employees.py:288-293` (CSV mapping), `dashboard.py:277-286` (dates)
**What's wrong (corrected scope).** Verifier partly-confirmed. `VerhaltenUpdate` uses `extra: "ignore"` (not `"forbid"`) — silently drops unknown fields rather than rejecting them. The CSV import `mapping` is `json.loads`'d but the parsed dict is **never validated against allowed fields**, so unknown keys pass silently. `dashboard` validates `period` but `from_date`/`to_date` are free strings; `_parse` returns `None` on bad input, so `from_date="2025-13-45"` **silently falls back to a default window** — the user thinks they filtered Jan–Mar but got last-30-days.
**Why it's bad.** Mass-assignment latent risk; CSV mapping to a protected column (`org_id`) could corrupt; silent date fallback produces *wrong reports with no error*.
**How to fix.** Set `extra: "forbid"` on update schemas; whitelist CSV mapping targets against the actual `import_employees` field set (not `AppointmentCreate` as the original suggested — verifier corrected this); validate dates with `datetime.fromisoformat()` and raise 422 instead of silently dropping. Reasoning: fail loud on bad input beats silently returning plausible-but-wrong data.
**Effort / Confidence:** S / Medium.

### [MED] Query params unvalidated — `calls.py:164-171` (limit/offset), `dashboard.py:277-286` (dates)
`limit`/`offset` have no bounds — `limit=99999` could OOM/timeout. Use `Query(50, ge=1, le=1000)`. (Verifier corrected the invoices search-injection claim: **that parameter doesn't exist** — skip it. And warned the proposed date regex is too strict — accept date-only too.) Effort S / High.

### [MED] Layering inconsistency / external-call error handling — multiple files
Routes both call `get_service_client()` directly *and* via services (`appointments.py` route vs `services/appointments.py`). Verifier **down-ranked to Low**: these are *different code paths for different use-cases* (REST CRUD vs agent tools), not duplicated logic, and all paths are correctly org-scoped — so it's a tidiness issue, addressed naturally by the god-file extraction above. Separately, external-call error handling is **partly-confirmed**: `calls.py:283-301` returns a generic 502 with no service name / timeout classification, and `transfer.py:74-76` swallows silently — but the verifier **refuted** the email-fallback claim (each Brevo/SMTP/OAuth tier *does* log). Fix: classify `httpx.TimeoutError`→504, `RequestError`→502-with-service-name on the ElevenLabs fetch; surface transfer failure reasons.

### [LOW] Dead-code / dormant columns — `routes/tools/`, dormant `kiki_level`
Verifier **corrected**: the tool routes are **not** 501 stubs — they're live, org-scoped, and every agent gets all 11 `hk_*` tools, so **don't remove them**; just fix the misleading `main.py:96` comment. The genuine item is the dormant `kiki_level` column (superseded by `appointments_level` et al., migration 0044) read via fallback in `appointments.py:88-90`, `cost_estimates.py`, `post_call.py` — keep the defensive fallback but add a dated cleanup plan (backfill, then a future migration to drop). Effort S.

### [LOW] Leaky error messages / circular-import risk
`employees.py:185-252` embeds raw exception text (`f"… ({exc})"`) in client-facing warnings, leaking schema; log full exception server-side, return generic client text. (Verifier *refuted* the `validate_fk_in_org` leak — its messages are clean.) Circular-import risk is **partly-confirmed but latent** — no actual cycle today; the lazy import in `calls.py:220` is intentional and *correct* (not a smell). Just document "routes may import services; services must never import routes."

---

## 4.4 Frontend Layout, Padding & Adaptability  *(Priority 4 — first-class, detailed)*

**This is the weakest dimension and the one the user most cares about.** The core finding: **there is no mobile/tablet strategy at all.** The app is built desktop-only — fixed pixel widths, zero responsive column hiding, modals/dropdowns/widgets that exceed small viewports, and several places where text can overflow its container and force horizontal scroll of an entire pane ("leaking"). On top of that sits a secondary, lower-severity problem: an **ad-hoc padding scale** (p-5/p-6/p-7/p-8/p-9 used interchangeably) that makes the desktop UI feel subtly unpolished. I treat *overflow leaks* and *responsiveness* as the real priority, and *padding consistency* as polish.

### Group A — Overflow leaks (content escapes its container) — fix these first

These are the literal "leaking" the user worries about: a single long string breaks an entire pane's width.

### [HIGH] Call row summary has no `truncate` — one long string breaks the list — `pages/calls/Inbox.tsx:174`
**What's wrong.** `<div className="text-[13.5px] font-bold … text-text">{item.summary}</div>` — no `truncate`/`line-clamp`. Note the parent has `min-w-0 flex-1` (line 164), which *enables* shrink but only works if the child opts in with `truncate`. The sibling `CallRow` (lines 111/116) and the timestamp (172) *do* use `truncate` — so this one is an oversight.
**Why it's bad.** A long unbroken string (URL, long customer name) makes the row exceed its container; because the list pane only allows `overflow-y-auto`, the overflow forces the **entire list to scroll horizontally** — you can't see other rows. One bad data row breaks the whole pane.
**How to fix.** Add `truncate` to line 174 and to the customer name (line 177). For two-line summaries use `line-clamp-2`. Reasoning: `truncate` (= `overflow:hidden; text-overflow:ellipsis; white-space:nowrap`) lets the flex child shrink to its container and ellipsize instead of pushing width.
**Effort / Confidence:** S / High.

### [MED] CallLogs Workspace pane missing `min-w-0` — won't shrink on resize — `pages/calls/Workspace.tsx:453`
**What's wrong.** The resizable 3-pane layout: left pane persists its width via localStorage; the Workspace pane has `flex h-full min-h-0 flex-col` but **no `min-w-0`**.
**Why it's bad.** A flex item's default `min-width:auto` refuses to shrink below its content's intrinsic width. Drag the left pane wide and the Workspace can't compress — it pushes the left pane off-screen or forces horizontal scroll. The resize feature silently breaks.
**How to fix.** Add `min-w-0` to line 453 and ensure children use `truncate`/`overflow-x-auto`. Reasoning: `min-w-0` overrides the auto minimum so flex can actually do its job. (Same root cause as the call-row leak — see cross-cutting theme.)
**Effort / Confidence:** M / Medium.

### [MED] Tag `whitespace-nowrap` overflows on mobile — `components/ui/Tag.tsx:29`
**What's wrong.** Tags force single-line; real labels like "Hausverwaltung" (15 chars) and "In Bearbeitung" can't wrap in narrow flex containers.
**Why it's bad.** In a tight column or on a phone the tag overflows or clips. Verifier raised to Medium because these are *real* German labels in the app.
**How to fix.** `whitespace-normal sm:whitespace-nowrap` — wrap on mobile, single-line on desktop. Flex containers already wrap items, so no layout break. Prefer this over a `truncate` variant, which would hide meaning.
**Effort / Confidence:** S / High.

### Group B — Responsiveness (the app must work on tablet/phone)

### [HIGH] Sidebar is a fixed-pixel column with no mobile drawer — `components/layout/Sidebar.tsx:97`
**What's wrong.** `style={{ width: collapsed ? 64 : 240 }}` — inline pixels, `flex-shrink-0`, **always rendered**, no responsive hide. (Verifier adjusted Critical→High but confirmed the impact.)
**Why it's bad.** On a 375px phone the expanded sidebar takes 240px = **64% of the screen**, crushing content into 36%. The collapse toggle only switches 64↔240 — neither is a mobile pattern. The app is effectively unusable on phones/tablets. Tellingly, `CustomersPage` already branches on a 768px breakpoint for *content*, proving the breakpoint awareness exists — it just wasn't applied to layout.
**How to fix.** Desktop: `hidden md:flex md:w-64` (use **md: = 768px**, matching the app's existing breakpoint — *not* `lg:` as the original fix said, the verifier corrected this). Mobile: a fixed overlay drawer in a Portal at `z-50` (above the `z-50` dropdowns — verifier corrected z-30→z-50), with click-outside + Escape handlers and auto-close on route change. Topbar shows a hamburger on mobile, the collapse chevron on desktop. Reasoning: a drawer is the standard mobile pattern because it reclaims the full content width while keeping nav one tap away.
**Effort / Confidence:** M / High.

### [HIGH] Data tables show 8–9 columns at all breakpoints — `pages/CustomersPage.tsx:388`, `pages/CostEstimatesPage.tsx:210`
**What's wrong.** Both tables render 9 columns with **zero** responsive hiding (`hidden md:table-cell` absent). At 768px each column is ~60px effective — Email/Phone/Address are illegible.
**Why it's bad.** Tablet users can't read the table; there's no graceful degradation. (CustomersPage at least has a responsive *card* view `md:grid-cols-2 xl:grid-cols-3`; CostEstimatesPage has **no** card fallback at all.)
**How to fix.** Add `hidden md:table-cell` (md = 768px, verified against the app's Tailwind config) to non-essential `<th>`/`<td>` (Email, Phone, Address), leaving Name/Type/Actions on mobile. Give CostEstimatesPage a card fallback. Reasoning: progressive disclosure — show identity + actions on small screens, full detail on wide ones.
**Effort / Confidence:** M / High.

### [HIGH] Copilot widget has fixed dimensions that exceed mobile — `components/copilot/CopilotWidget.tsx` (panel at line ~273, wrapper clamp at ~258)
**What's wrong (corrected).** Verifier found it's `h-[560px] max-h-[80vh] w-[370px] max-w-[calc(100vw-2.5rem)]` — so width *is* partly clamped, and a close button *does* exist (original claim it didn't was **refuted**). The real bug: the hardcoded `h-[560px]` **overrides** `max-h-[80vh]` (an explicit height wins over a max), and the JS wrapper clamps height in a *second* place (line 258), so the two disagree.
**Why it's bad.** On short phones the panel can exceed the usable viewport; on a 375px phone the 370px width is 98.7% of screen. Two sources of truth for height drift apart.
**How to fix — three places.** Replace `h-[560px]` with a responsive stack `h-[280px] sm:h-[400px] md:h-[480px] lg:h-[560px] max-h-[75vh]`; update the JS clamp (line 258) to `Math.min(480, innerHeight*0.75)` to match; verify the `PANEL_W` fallback. Reasoning: a single responsive height that the JS mirrors removes the override conflict and keeps the panel inside the viewport at every size.
**Effort / Confidence:** M / High.

### [HIGH] Modal width has no safe margin on tiny screens — `components/ui/Modal.tsx:25`
**What's wrong.** `w-[92vw] max-w-lg p-4`. On a 280px phone, 92vw=257px minus padding leaves ~232px content.
**Why it's bad.** Form fields and button rows overflow horizontally; old/small phones get internal horizontal scroll.
**How to fix.** `w-[min(92vw,calc(100vw-2rem))] sm:max-w-lg` (guarantees a 1rem safe margin), and make padding/fonts responsive on **all three** Modal regions (header/body/footer): `px-4 sm:px-6`, add `text-base sm:text-lg` to the title. Reasoning: `min()` caps width against both constraints; responsive padding reclaims the most space exactly where it's tightest.
**Effort / Confidence:** S / High.

### [HIGH] Sidebar profile dropdown is `w-56` on phones — `components/layout/Sidebar.tsx:216`
**What's wrong.** Radix `DropdownMenu.Content` is `w-56` (224px) unconditionally; rendered in a Portal so it's not parent-constrained.
**Why it's bad.** On a 280px phone that's 80% of the screen, leaving ~28px margins; Settings/Logout are awkward to tap.
**How to fix.** `w-[calc(100vw-2rem)] sm:w-56` — full-width-minus-margins on mobile, fixed on tablet+. Verify the Portal container doesn't constrain `100vw`.
**Effort / Confidence:** S / High.

### [MED] CommandPalette top offset can crowd short viewports — `components/layout/CommandPalette.tsx:99`
**What's wrong (corrected).** Original: `pt-[12vh]` clips results and "results not scrollable." Verifier **refuted** the scroll claim — the list has `max-h-[320px] overflow-y-auto` and scrolls internally; on a 600px viewport it fits with room to spare. Real issue only at <400px height. Down-ranked to Medium.
**How to fix.** Simplest robust fix: replace `items-start pt-[12vh]` with `items-center justify-center` so flex centering adapts to any height; optionally `max-h-[calc(100vh-2rem)]` on the wrapper. Reasoning: centering removes the fixed top offset that doesn't scale.
**Effort / Confidence:** S / Medium.

### Group C — Padding & scale consistency (polish; mostly Low after verification)

The verifier consistently **down-ranked** these and warned that several "obvious" fixes (e.g. just deleting a `p-5`) can *change* visual proportions. Treat this group as a single deliberate task: **define one spacing scale and apply it**, with visual verification — not blind class edits.

### [MED] Topbar `px-7` vs page `p-8` misaligns under the sticky header — `components/layout/Topbar.tsx:16`
Content under the sticky topbar is offset 4px from page content. Fix: unify to `px-8` (or `px-5 sm:px-7 lg:px-8` if mobile compactness is wanted — the verifier noted the original `px-4 sm:px-6 lg:px-8` skips a step). Effort S / High.

### [MED] Customers/CustomerDetail use arbitrary `max-w-[1440px]` with fixed `p-8` — `CustomersPage.tsx:232`, `CustomerDetailPage.tsx:138`
1440px isn't a Tailwind standard and there's no responsive padding. Fix: `max-w-7xl` (or `max-w-6xl`) + `p-4 md:p-6 lg:p-8`. Reasoning: standard tokens + responsive padding give predictable spacing tablet→desktop. Effort S / Medium.

### [LOW] Other padding mismatches (grouped)
- **KpiCard `p-5` vs Card `p-6`** (`KpiCard.tsx:22`) — verifier: do **not** blindly remove `p-5` (changes the flex/icon proportion); decide a unified card padding and apply across Card/KpiCard/Panel/DashKpi together, with visual check.
- **Dashboard hero `p-7 sm:p-9` vs page `p-8`** (`DashboardPage.tsx:185`) — the scale isn't "ad-hoc" (it's Tailwind's 4px steps); the real issue is mobile (28px) < page (32px) then jumps to 36px. Fix: `p-8 sm:p-10` keeps the hero emphasis while aligning the mobile baseline.
- **Accordion content has no horizontal padding** (`Accordion.tsx:41`, `pb-4` only) — add `px-4` to both trigger and content. (Component is currently unused — preventive.)
- **Footer `px-4 py-2` vs page `p-8`** (`AppLayout.tsx:72`) — cramped, 2px wrapped-line gap. Fix `px-8 py-4` + `gap-y-1`.
- **Button padding scale** (`Button.tsx:14` vs inline buttons) — verifier corrected: the real problem is **adoption** (many buttons are defined inline, bypassing the component), not just missing size variants. Add `sm/md/lg` size props *and* migrate inline buttons to the component; otherwise variants won't help.
- **Modal footer not `flex-shrink-0`** (`Modal.tsx:35`) — verifier corrected: footer is already outside the scroll body (it won't "disappear"), but lacks `flex-shrink-0` so it can compress when space is tight. Add `flex-shrink-0`; `sticky` is unnecessary.

---

## 4.5 Frontend Architecture / Rendering  *(Priority 5)*

**The theme.** Foundations are good — the verifier *confirmed* code-splitting, the 30s `staleTime`, and clean dual-client auth separation. The issues are (a) a few **context re-render hotspots** (covered in Caching: Theme + Admin providers) and (b) a **recurring uncleaned-`setTimeout` leak** in the toast pattern across many pages.

### [MED] Uncleaned `setTimeout` toast pattern across 6+ pages — `CatalogPage.tsx:107`, `CostEstimatesPage.tsx:69`, `InvoicesPage.tsx:69`, `EmployeesPage.tsx:115`, `MyAbsencePage.tsx:51`, `KikiZentralePage.tsx:54` (and `SettingsPage.tsx:158`)
**What's wrong.** `const flash = (m) => { setToast(m); setTimeout(() => setToast(null), 4000) }`. Fire-and-forget; the timer is never cleared on unmount. (This unifies the JSON's `uncleanedtimeout-catalogpage` and `multiple-settimeout-toast-patterns` — **same pattern, one fix.**)
**Why it's bad.** Navigate away within the 4–6s window and the timer fires `setToast` on an **unmounted component** → React's "setState on unmounted component" warning and a small leak. Bulk operations (CSV import, multi-delete) queue many timers. (Verifier corrected the cited "good example": `CostEstimateFormPage:185-198` is a *debounce-with-cleanup for PDF preview*, a different use-case — no page currently does the toast cleanup right, so this is a new pattern to introduce.)
**How to fix.** A shared `useToast()` hook that owns the timer in a `useEffect`: `useEffect(() => { if (!toast) return; const id = setTimeout(() => setToast(null), 4000); return () => clearTimeout(id); }, [toast])`; `flash` just sets state. Reasoning: tying the timer to the component lifecycle via the effect's cleanup guarantees it's cancelled on unmount or when a new toast supersedes it — and a single hook removes the 6× duplication.
**Effort / Confidence:** M / High.

### [MED] OAuth popup adds a `window` message listener with no guaranteed cleanup — `SettingsPage.tsx:807`
**What's wrong.** `window.addEventListener('message', onMessage)` is removed only on message-received or fetch-failure. If the user closes the popup before a message arrives (and the fetch *succeeded*), the listener leaks; each retry stacks another.
**Why it's bad.** Listeners accumulate, each closing over a stale popup; repeated OAuth attempts pile up handlers → leak + potential stale-closure behavior.
**How to fix.** Add an idempotent `cleanup()` guarded by a `cleaned` flag, plus a safety `setTimeout` (e.g. 30s) that calls cleanup + `popup.close()`; call cleanup from onMessage, the catch, and the timeout. Reasoning: a single idempotent teardown reachable from *every* exit path is the only way to guarantee removal regardless of how the flow ends.
**Effort / Confidence:** M / Medium.

### [MED] Most mutations only `invalidateQueries` instead of optimistic update — `pages/*`
**What's wrong.** CustomersPage, EmployeesPage, InvoicesPage use `onSuccess: invalidateQueries`. Only `PlanningBoardPage` does true optimistic updates (`onMutate` + snapshot/rollback). This is the same gap `PERFORMANCE_PLAN.md` D1/D2 flagged — **still largely true.**
**Why it's bad.** Every quick action (toggle status, mark-read) waits a full server round-trip (~200–500ms) before the UI moves, and a list invalidation refetches all N items to reflect one change → the "choppy" feel.
**How to fix — verifier corrected the example.** The original "`onSuccess` + `setQueryData`" is **wrong** (the round-trip already happened). Use the `PlanningBoardPage` pattern: `onMutate` updates the cache *before* the request, `onError` rolls back from a snapshot, `onSettled` reconciles. Reasoning: optimistic UI must mutate the cache *ahead* of the server so the UI reacts in 0ms; the snapshot/rollback keeps it correct on failure.
**Effort / Confidence:** M / High.

### [LOW] `'me'` query duplicated instead of `useMe()` — `CallLogsPage.tsx:53-56`, `CalendarPage.tsx:110`
Both inline `useQuery({ queryKey: ['me'], … })` instead of the `useMe()` hook, missing its 5-min `staleTime`. 13+ other pages already use the hook. Fix: `const { me } = useMe()`. Pure DRY + consistency win. Effort S.

### [LOW] UI components not memoized — `components/ui/KpiCard.tsx`, Card, Button, Tag
Pure presentational components re-render when parents pass new inline handlers (e.g. DashboardPage's grid of KpiCards with inline `onClick`). Verifier (Low/confirmed) adds the necessary nuance: `React.memo` alone won't help unless the parent also wraps handlers in `useCallback` — otherwise the new function reference defeats the memo. Low ROI; do KpiCard/Card first if at all.

### [CONFIRMED-GOOD] Auth separation, staleTime, code-splitting
Two Supabase clients with distinct `storageKey`s (`heykiki-customer-auth` / `heykiki-admin-auth`), shared `useSupabaseAuthBinding`, no redirect loops — **clean and intentional**, no action beyond the AdminAuthProvider memo (Caching). `staleTime: 30_000` and `React.lazy` splitting are both correct. These are strengths; preserve them.

---

## 4.6 Data Access & Database  *(Priority 6 — but contains the single most urgent correctness bug)*

**The theme — and the unifying root cause.** PostgREST silently caps a plain `.select().execute()` at **1000 rows**. The codebase *knows* this (comments in `customers.py:86`, the 0046/0044 work, the SESSION_HANDOVER incident note), and uses `count="exact"` / `.range()` correctly in *some* places — but several hot reads still do an unbounded `.execute().data`. At today's 17 prod customers these are invisible; after the documented **5,206-row import** they become **silent wrong answers and silent data corruption**. FK indexes (shipped via 0044/0046) fixed the *speed* axis the PERFORMANCE_PLAN prioritized; they do **nothing** for this *correctness* axis. Several "serial query" items here also overlap with Parallelism — they're cross-referenced, not repeated.

### [CRITICAL] CSV import dedup read is capped at 1000 rows — `services/csv_import.py:330-338` (and `import_employees`, ~474)
**What's wrong.** `import_customers` fetches *all* existing customers for dedup via a single `.select(...).eq("org_id",…).neq("status","deleted").execute().data` — no `.range()`/pagination. Only the first 1000 register into the `seen_emails`/`seen_mobiles`/`seen_landline_names` sets.
**Why it's bad — this is data corruption, not perf.** For any org with >1000 existing customers, rows 1001+ are never seen as "existing," so re-importing the same file **creates duplicate customer records** — directly violating the documented contract "re-running the same file imports nothing new." After the 5,206-row import, a second import would treat 4,206+ rows as new. Silent: no error, no warning. The PERFORMANCE_PLAN explicitly listed *verifying this* as an open question (§7); it is now a confirmed live bug.
**How to fix.** Paginate the dedup read with the codebase's own proven pattern (`customers.py _export_csv:278-287`): loop `for offset in range(0, total, 1000): .range(offset, offset+999)` and accumulate into the dedup sets *before* processing CSV rows. The insert path already chunks, so this is additive and side-effect-free. Reasoning: dedup is only correct if it sees *every* existing row; pagination is the only way past the 1000-row cap when you need the rows themselves (not just a count).
**Effort / Confidence:** S / High.

### [HIGH] `customers._list` count-enrichment is capped at 1000 — silent undercount — `customers.py:120-153`
**What's wrong.** For the displayed page it fetches inquiry/appointment/document rows via `.in_('customer_id', ids).execute().data` and counts them in Python (`Counter`) — unbounded.
**Why it's bad.** If any enrichment table has >1000 matching rows, the list shows "Inquiries: 2" when there are 50 — and sorting/filtering by those counts is unreliable. A silent correctness bug on large orgs. (The same file's *type-count* queries correctly use `count="exact"` — so the right tool is already in hand.)
**How to fix.** Use `count="exact"` (which reads the total from the `Content-Range` header and is *not* row-capped) per customer, or a single `GROUP BY customer_id` RPC, instead of fetching rows to count them. Verify the supabase-py builder actually supports the chosen `count`/`group_by` form (verifier flagged this). Reasoning: never fetch rows just to count them — counting via the header is both correct past 1000 and far cheaper.
**Effort / Confidence:** M / High.

### [HIGH] `projects._list` call-counting fetches all calls unbounded — `projects.py:96`
**What's wrong.** `client.table('calls').select('customer_id').in_('customer_id', cids).execute().data` then sums in Python — capped at 1000. The same file (`:212`) already uses `count="exact"` correctly for a per-customer count.
**Why it's bad.** Project view shows wrong call counts past 1000 total calls — silent reporting bug feeding resource-planning decisions.
**How to fix.** Per-customer `count="exact"` (matching line 212's pattern) or a `GROUP BY` RPC. Same reasoning as customers count.
**Effort / Confidence:** M / High.

### [HIGH] `build_customer_timeline` fetches 4 tables with no limit — silent truncation — `calls.py:558-607`
**What's wrong.** Four unlimited selects (calls, inquiries, appointments, cost_estimates) scoped to a customer.
**Why it's bad.** A long-history customer's "Verlauf" shows only ~1000 events; the oldest silently vanish — violating "unified timeline shows all." Also wasteful: the UI sorts newest-first and renders a fraction.
**How to fix.** `.order('created_at', desc=True).range(0, limit-1)` on each (limit ~500), so you fetch the *most recent* events efficiently rather than truncating arbitrarily. The function already sorts after fetch; pull recent at query time. Reasoning: bound the read to what's rendered, ordered, so truncation (if any) drops the *least* relevant data, not random data.
**Effort / Confidence:** S / High.

### [HIGH] `projects._list`/`_detail` fetch entire tables, no pagination — `projects.py:70,205-209`
**What's wrong.** `_list` fetches all projects (`:70`) unbounded; `_detail` does five unbounded related fetches (`:205-209`). The same file uses `.limit(10)` for `activity()` — so the pattern is known.
**Why it's bad.** O(n²)-ish behavior: 2000 projects × per-detail unbounded relations. Slow and silently truncated at 1000.
**How to fix.** Add pagination to `_list` (`.range(offset, offset+limit-1)`, like `customers.py:83` / `calls.py:141`) and limit related fetches in `_detail` (`.order('created_at', desc=True).limit(100)`). Reasoning: consistent pagination caps both latency and the truncation risk.
**Effort / Confidence:** S / Medium.

### [HIGH] `calls._list` enrichment runs serially — `calls.py:130-147` (+ `_enrich_calls_with_inquiries`)
**What's wrong.** Sync `_list` fetches calls, then `_enrich_calls_with_inquiries` runs inquiries (63-73) then employees (90-99) serially. **This is the data-access view of the same issue tracked under Parallelism** — the calls list = calls → inquiries → employees ≈ 540ms serial.
**Why it's bad / How to fix.** See Parallelism §4.1: make the enrichment async and `asyncio.gather` the two independent inner queries, matching `customers._list`/`dashboard.overview`. Cross-referenced to avoid double-counting.
**Effort / Confidence:** S / High.

### [MED→LOW] Number-generation functions — `common.py:298-328`, `invoices.py:17-26`, `projects.py:11-20`
**What's wrong (largely corrected).** The original claimed *all four* generators fetch all rows and could mint duplicate numbers past 1000. The verifier **refuted 3 of 4**: `gen_inquiry_number`, `gen_invoice_number`, `gen_project_number` already use `count="exact"` (HEAD-only, **not** row-capped). Only `gen_customer_number` (`common.py:310-328`) still fetches rows and takes max+1 — a real but lower-severity risk at 4,853 customers (it can hit the cap and reuse a number). **Down-ranked to Low** overall.
**How to fix.** For `gen_customer_number`: `.order('customer_number', desc=True).limit(1)` to read just the max, instead of fetching all rows. Reasoning: a single ordered row gives the max without iterating, immune to the 1000-cap.
**Effort / Confidence:** S / High.

### [MED] `mark-read` issues 3 queries for one idempotent update — `calls.py:239-269`
**What's wrong.** SELECT read_at → conditional UPDATE (result discarded) → re-SELECT for the response. On re-opens (read_at already set) all 3 still run.
**Why it's bad.** ~540ms (3 round-trips) on every call open; the final re-SELECT is pure waste — the data is already available.
**How to fix.** Chain `.select("id, read_at")` onto the UPDATE so it returns the new row in one round-trip; if read_at was already set, return the initial SELECT. 3 queries → 1 (re-open) or 2 (first read). PostgREST supports `.select()` on UPDATE, so it's safe.
**Effort / Confidence:** S / High.

### [MED→LOW] `SELECT *` over-fetching large JSONB — `cost_estimates.py:151,213,341`, `invoices.py:141,212,334,418`, others
**What's wrong (corrected scope).** `SELECT *` on tables with large `line_items jsonb`. Verifier **partly-confirmed and down-ranked to Low**: list views already select explicit columns; the `*` is on **detail/PDF/duplicate** paths that *genuinely need* `line_items` (e.g. PDF generation reads it directly) — so blanket replacement would **break** those renders.
**How to fix — targeted, not blanket.** Keep `*` on detail/PDF/dup. The real win is the **validation-only loads** in the send routes (`send_estimate`/`send_invoice` existence checks) — change those to `.select("id").limit(1)`. Reasoning: only trim columns where the extra data is provably unused; over-eager trimming here causes correctness regressions.
**Effort / Confidence:** M / Medium.

---

## 5. Cross-Cutting Themes

1. **The sync Supabase client is the gravitational center of the backend's parallelism story.** It forces the `run_in_threadpool` discipline, makes naive `asyncio.gather` *wrong* inside sync helpers, and means "parallelize this" almost always = "make the helper `async`, gather `run_in_threadpool` calls." The codebase already does this right in 3 places (`customers._list`, `dashboard.overview`, the calls reference); the fix everywhere else is to copy that exact shape. A longer-term lever (per PERFORMANCE_PLAN §C4) is `asyncpg` for the hottest reads.

2. **PostgREST's silent 1000-row cap is one root cause behind five findings** (CSV dedup, customer counts, project counts, customer-timeline, customer-number gen). The rule to internalize: **count via `count="exact"` (header-based, uncapped); fetch rows only with `.range()` pagination.** This is correctness, not perf — and indexes don't help it.

3. **`min-w-0` + `truncate` is one root cause behind the layout "leaks"** (call-row overflow, Workspace pane non-shrink, tags). Flex children default to `min-width:auto` and won't shrink below content; any pane with dynamic text needs `min-w-0` on the flex container and `truncate`/`line-clamp` on the text. Audit *every* flex row that renders user data for this pair.

4. **Missing memoization of provider context values** is one root cause behind frontend re-render waste (Theme + Admin providers). Any `Context.Provider value={{…}}` literal should be `useMemo`'d; any provider wrapping an already-memoized hook result should pass it through unchanged.

5. **Fire-and-forget side effects with no durability or dedup** recur across the backend: the `post_call` daemon thread, BackgroundTasks for billing/config, unwrapped background ElevenLabs pushes. The unifying fix posture: coordinate with the response (`BackgroundTasks`), make idempotent (UNIQUE keys — billing already does this), and persist when the blast radius is real-world (customer calls/emails, revenue).

6. **"Trust the client's FK" + "no transaction" compound into data-integrity risk.** The IDOR (unvalidated FK-in-org) and the atomicity gaps share a home: business logic sprawled across god-files with no service-layer chokepoint to centralize validation and compensation. Extracting services (4.3) is the structural enabler for fixing both cleanly.

---

## 6. Prioritized Roadmap

### P0 — Correctness / data-loss / leak risks (do first)
| Item | Finding IDs | Effort |
|---|---|---|
| Paginate CSV-import dedup read (+ employees) | `1000-row-limit-csv-import-dedup` | S |
| Compensating transactions for appointment + invoice multi-writes; add FK on `cost_estimates.invoice_id` | `multi-write-atomicity-gaps` | M |
| Remove `master_webhook_secret="change-me"` default; fail-fast on startup if unset | `config-unsafe-defaults` | S |
| Validate client-supplied FK-in-org on write paths (projects, invoices) | `service-role-client-discipline`, `idor-customer_id-parameter` | M |
| Replace `post_call` daemon thread with coordinated + idempotent work | `post-call-daemon-thread-leak` | M |
| Fix unbounded count/timeline reads (customers, projects, customer-timeline) | `customer-list-unbounded-enrichment-counts`, `projects-list-calls-no-limit`, `customer-timeline-unlimited-fetches` | M |

### P1 — High-leverage perf / UX
| Item | Finding IDs | Effort |
|---|---|---|
| Wrap `conversation_init` in `run_in_threadpool` | `conversation-init-blocks-loop` | S |
| 5s timeout on outbound-dispatch email send | `outbound-dispatch-email-send-sync-network-call` | M |
| Parallelize serial fan-out (projects, timeline, customer-detail, calls-enrich, employees, dashboard tabs) | `projects-list-six-serial-queries`, `build-timeline-four-serial-queries`, `serial-customer-enrichment-queries`, `calls-list-serial-enrichment-queries`, `employees-list-three-serial-fetches`, `dashboard-overview-eight-serial-queries` | S–M |
| Responsive layout: sidebar drawer, responsive tables, modal/dropdown/widget sizing, overflow `truncate`/`min-w-0` | `sidebar-fixed-width-no-mobile`, `tables-no-responsive-columns`, `modal-width-on-mobile`, `sidebar-dropdown-width-mobile`, `copilot-widget-fixed-dimensions`, `call-row-text-no-truncate`, `call-logs-right-pane-min-width`, `tag-nowrap-overflow` | M |
| `useMemo` Theme + AdminAuth context values | `theme-provider-context-rebuild`/`theme-context-object-allocation`, `admin-auth-provider-fresh-object` | S |
| TTL the ElevenLabs tool-ID cache | `elevenlabs-tool-id-cache-no-ttl` | M |
| `mark-read` 3→1 query | `mark-read-duplicate-query` | S |
| Optimistic updates for high-frequency mutations (use `onMutate`) | `missing-optimistic-update-patterns` | M |

### P2 — Structural / maintainability
| Item | Finding IDs | Effort |
|---|---|---|
| Extract business logic from god-files into `services/` | `god-files-business-logic`, `layering-inconsistency-routes-call-supabase` | L |
| Centralize lookup + enrichment helpers; use `require_org_admin` dependency | `repeated-query-enrich-patterns`, `duplicated-auth-org-scoping-logic` | M |
| Typed exception handling + structured errors; ERROR-level logging | `bare-except-swallowed-exceptions`, `missing-error-on-external-calls`, `leaky-error-messages` | M |
| Shared `useToast()` hook (cleanup); fix OAuth listener leak | `multiple-settimeout-toast-patterns`/`uncleanedtimeout-catalogpage`, `settingspage-oauth-listener-leak` | M |
| Input/param validation (`extra:"forbid"`, date `fromisoformat`, `limit` bounds, CSV-mapping whitelist) | `unvalidated-request-bodies-mass-assignment`, `no-input-validation-query-params` | S |
| Lower JWKS TTL to 5min + make configurable | `jwks-cache-excessive-ttl` | S |
| Redis stampede guard (`SET NX`); document client thread-safety | `cache-stampede-no-lock`, `supabase-client-thread-safety-assumption`, `shared-lru-cache-client-missing-docstring` | M |
| Pagination on projects list/detail | `no-pagination-customers-all-table-scans` | S |
| Tiered BackgroundTasks durability (monitor billing; ERROR-log config pushes); wrap background EL/OAuth pushes | `background-tasks-no-persistence-no-retry`, `elevenlabs-sync-http-client`, `oauth-tokens-sync-network-call` | M–L |
| Padding scale unification (Topbar, max-width, cards, footer, button adoption) | `topbar-padding-inconsistent`, `customers-arbitrary-max-width`, `kpi-card-padding-mismatch`, `dashboard-hero-padding-breakpoint-inconsistent`, `page-footer-cramped-padding`, `button-padding-scale-inconsistent`, `accordion-content-padding`, `modal-footer-sticky` | S–M |

### P3 — Later / low-impact
| Item | Finding IDs | Effort |
|---|---|---|
| `gen_customer_number` ordered-limit-1 | `gen-number-functions-1000-row-cap` | S |
| Targeted `SELECT *` trimming (validation-load paths only) | `select-star-over-fetching` | M |
| `useMe()` de-duplication; `React.memo` + `useCallback` on grid UI | `calllogspage-redundant-me-query`, `calendarpage-me-query-duplicate`, `applayoutcomponent-not-memoized` | S |
| CommandPalette centering | `command-palette-top-position` | S |
| Negative caching, settings/client cache docs | `negative-caching-none-never-cached`, `get-settings-lru-cache-immutable`, `supabase-service-client-lru-cache` | S |
| Dead-comment cleanup + dormant `kiki_level` cleanup plan; circular-import doc | `dead-code-501-tools`, `circular-imports-risk` | S |
| Defensive SPA `serve.json` (boundary already handles runtime) | `frontend-spa-cache-control-missing` | S |
| Worker/timeout scaling (only when usage grows) | `gunicorn-workers-2-too-few`, `gunicorn-timeout-30s-blocking-requests` | S |
| **No action (verified-good):** auth separation, staleTime, code-splitting, optimistic-delete shape, mark-read over-invalidation | `admin-vs-customer-auth-separation-solid`, `react-query-stale-time-30s-good`, `bundle-split-correct-22-pages`, `call-delete-query-key-mismatch`, `over-invalidation-dashboard-overview` | — |

---

## 7. Appendix — How to Verify Each Fix

**Backend correctness (P0 data-access):**
- *CSV dedup:* in `kiki-test-007` (pre-authorized test org, 4,853 customers > 1000), import a known file twice; assert the second import inserts 0 new rows. Add a unit test asserting the dedup read paginates past 1000.
- *Atomicity:* monkeypatch the second write (appointment insert / cost_estimate update) to raise; assert no orphaned inquiry/invoice remains (the existing test suite for these flows + a new failure-injection test).
- *Unbounded counts:* seed >1000 inquiries for one test customer; assert the list/timeline/project count matches the true total (use `count="exact"` as the oracle).
- *FK-in-org IDOR:* attempt `projects._create` / `invoices._create` with a customer/kva_id from a *different* org; assert HTTP 422, no row written.

**Backend parallelism:** time the endpoint before/after (`curl -w '%{time_total}'`); a 4-serial route should drop from ~4× to ~1× round-trip. Run `pytest -k "customer or call or dashboard or project"` green. Remember **no hot-reload** — restart uvicorn after edits, then re-check the live `/openapi.json` route.

**Backend config/security:** unset `MASTER_WEBHOOK_SECRET` in a test env → assert the app refuses to start. Lower JWKS TTL → assert `_JWKS_TTL` reads from settings.

**Caching:** *Theme/Admin memo* — add a render counter (or React DevTools Profiler) to a consumer; navigate and confirm it no longer re-renders on unrelated parent renders. *Tool-ID TTL* — delete a workspace tool, wait past TTL, confirm a fresh fetch repopulates. *Stampede* — fire N concurrent requests at a just-expired key; confirm only 1 loader call (log the `SET NX` acquisition).

**Frontend layout (per UI-done definition: build-clean + live preview proof):** use the preview MCP to render at **375px, 768px, 1280px**. Confirm: sidebar becomes a drawer <768px; tables hide Email/Phone/Address <768px; modal has ≥1rem side margin at 280px; long call-summary truncates with ellipsis (no horizontal pane scroll); copilot widget stays inside the viewport on a short phone. Screenshot each breakpoint.

**Frontend leaks:** mount a page, fire a toast, navigate away within the window; confirm no "setState on unmounted component" warning in the console. For OAuth, open/close the popup repeatedly; confirm `getEventListeners(window).message` count stays at 0 after cleanup.

**Frontend optimistic UI:** throttle the network (DevTools), perform a status toggle; the row should update at 0ms and reconcile on settle; force a 500 and confirm rollback.

**DB indexes (already shipped):** re-run Supabase `get_advisors(type="performance")`; confirm `unindexed_foreign_keys` stays low after any new FK columns are added.
