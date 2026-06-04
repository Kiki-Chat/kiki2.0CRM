# KikiJarvis — Performance & Smoothness Plan

**Goal:** make the app feel fast and smooth (no choppy deletes, no laggy lists/settings), with fewer moving parts — based on **measured facts**, not guesses.

> **Date:** 2026-06-05 · **Author:** engineering analysis pass
> All numbers below are measured (Railway HTTP logs, `curl` timing, Supabase advisors, code inspection). Where something is an estimate or unverified, it says so.

---

## 0. TL;DR

The app is slow for four compounding reasons, **none of which is "the code is too monolithic"**:

1. **Too many DB round-trips per click** (a customer list = ~9 *sequential* queries).
2. **Each round-trip is expensive** (~180 ms: ~70 ms network + ~110 ms Supabase-side), and it's paid serially.
3. **Missing database indexes** (~45 foreign keys unindexed) — harmless at today's 17 prod customers, **catastrophic after the 5,206-row import**.
4. **The frontend waits for the server before doing anything** (no optimistic updates) and **re-fetches on every navigation** (`staleTime: 0`).

**Measured prod reality:** the Railway backend's own response time is **p50 = 774 ms, p95 = 2,058 ms** (217 real requests) — and that's *before* the India→Singapore browser hop (~84 ms each way) and rendering.

**The five highest-leverage fixes (all low-risk, no infra move):**

| # | Fix | Why | Effort |
|---|-----|-----|--------|
| 1 | Add the ~45 missing FK indexes | Prevents the 5k import from making everything multi-second | S (additive migration) |
| 2 | Run a request's independent queries **in parallel** (`asyncio.gather`) | 9×180 ms (1.6 s) → ~180–360 ms | S–M |
| 3 | Turn on the **already-built Redis cache** for hot reads (employees, settings, counts) | Skip repeated Supabase round-trips entirely | S |
| 4 | **Optimistic UI** for delete/status/assign + raise `staleTime` | Kills the "choppy" feel; deletes feel instant | M |
| 5 | Collapse fan-out (e.g. 5 type-count queries → 1 `GROUP BY`) | Fewer round-trips per page | S |

> **Scope (set by Amber):** **infrastructure, region, and the Supabase/Railway plans are OUT OF SCOPE here — you own those** (paid EU plans already in hand; they remove the cross-region network hops and ease the per-query platform overhead). **This doc is only the code-level optimization** — the part that makes the site stop feeling crappy and that the EU/plan move does **not** fix: query **fan-out**, **no parallelism**, **missing indexes**, **`staleTime: 0`**, and **no optimistic UI**.

---

## 1. How prod actually works (corrected mental model)

I initially mis-stated this. Here is the real topology:

```
  ┌─────────────────┐     clicks / HTTP      ┌──────────────────────────────┐    queries     ┌─────────────────────┐
  │  Browser         │  ───── ~84 ms ─────▶   │  RAILWAY (Singapore)          │  ── ~70 ms ──▶ │  SUPABASE (Tokyo)    │
  │  (India MacBook) │  ◀──── ~84 ms ─────    │  • frontend (static)          │  ◀─ +~110 ms ─ │  Postgres 17 +       │
  │  = just a screen │                        │  • backend (gunicorn, 2 wkrs) │   per query    │  PostgREST REST API  │
  └─────────────────┘                         └──────────────────────────────┘                └─────────────────────┘
```

- The **MacBook is only a browser** in prod. It renders and sends clicks. It does **no data work**. (My earlier India→Tokyo measurement was the *dev* path, where the backend runs locally on the Mac — irrelevant to prod.)
- **Railway (Singapore)** hosts both the frontend service and the backend service.
- **Supabase (Tokyo, `ap-northeast-1`)** is the database. The backend talks to it over the **PostgREST REST API** (via `supabase-py`), not a direct Postgres socket.
- So a single user action in prod = `browser→Railway (84 ms)` + `backend does N×(~180 ms) queries` + `Railway→browser (84 ms)` + render.

**Three different countries, two long network hops, multiplied by query count.** That's the structural cost *of the current dev setup*.

### 1.1 Network / region — out of scope (owned by Amber)

The dev numbers are inflated by a three-region split (India → Singapore → Tokyo). **You're handling that via the paid EU plans (users + Railway + Supabase all EU), so it's excluded here.** One fact to keep in mind, because the EU move does **not** fix it: of the ~180 ms/query, only ~70 ms is network (which EU co-location removes); **~110 ms is Supabase server-side and persists.** So even all-EU, a 9-query page is ~1 s until the **code fixes** in this doc land. **Those code fixes are the whole point of this doc.**

---

## 2. Measured evidence (the facts)

### 2.1 Real prod backend latency — Railway HTTP logs (217 requests, `backend-production-3f88a`)
| percentile | response time |
|---|---|
| **p50** | **774 ms** |
| p90 | 1,686 ms |
| p95 | 2,058 ms |
| p99 | 2,937 ms |

> Half of all prod API calls already exceed **0.77 s** server-side. This is at only **17 prod customers** — it will get worse with the 5,206-customer import (see §2.4).

### 2.2 Cost of one query (warm, reused connection — `curl` decomposition)
| component | time | notes |
|---|---|---|
| Network round-trip | **~70 ms** | TCP connect India↔Tokyo (1 RTT) — *the only part that's "distance"* |
| Supabase-side | **~110 ms** | PostgREST + edge gateway + serialize (Postgres exec itself is <5 ms on tiny tables) — **paid regardless of where the backend is** |
| **Total / query** | **~180 ms** | warm; a *cold* connection adds ~120 ms of TCP+TLS |

> **Key point:** distance is only ~70 ms; the bigger cost is the **~110 ms Supabase server-side** overhead, paid in *every* environment (EU included). The code lever is to issue **fewer queries** (fan-out cuts + caching) and run them **in parallel** — that's the work below.

### 2.3 Query fan-out per endpoint (from code inspection)
| endpoint | sequential queries | ≈ server time (×180 ms) |
|---|---|---|
| `GET /api/customers` (list) | ~9 (1 list + 3 count-loops + **5 separate type-count queries**) | **~1.6 s** |
| `GET /api/calls` (list) | 3 (calls + inquiry enrichment + employees) | ~0.5 s |
| `GET /api/dashboard/overview` | ~5 | ~0.9 s |
| **delete a call** | ~10 (2 writes + refetch `['calls']` (3) + needless refetch `['dashboard']` (5)) | **~1–2 s** |

- **`asyncio.gather` usage across the backend: 0.** Independent queries inside one request run **strictly one-after-another**. This is the single biggest single-request lever.
- `run_in_threadpool` calls across routes: **238** — every sync Supabase call is correctly offloaded, but still awaited serially.

### 2.4 Database health — Supabase performance advisors
- **~45 foreign keys have NO covering index**, including the exact columns the hot queries filter on:
  - `inquiries.call_id` (used in **every** call-log load + timeline), `inquiries.customer_id`, `inquiries.assigned_employee_id`
  - `calls.customer_id`, `appointments.customer_id` / `inquiry_id` / `assigned_employee_id`, `cost_estimates.customer_id` / `inquiry_id`, `documents.customer_id`, `employees.user_id`, …
  - → **sequential table scans**. Cheap at 17 customers; **linear blow-up at 5,206**.
- `users` RLS policy `users_same_org` re-evaluates `auth.*()` **per row** (wrap in `(select auth.…())`).
- 1 duplicate index (`idx_cost_estimates_org` == `idx_kva_org`) and ~15 unused indexes (minor cleanup).
- Advisor reference: <https://supabase.com/docs/guides/database/database-linter?lint=0001_unindexed_foreign_keys>

### 2.5 Backend runtime & workers (from `backend/Dockerfile` + code)
- `gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 2 --timeout 30` → **2 worker processes**, always-on (no scale-to-zero). Good baseline, but only 2.
- Each worker = 1 asyncio event loop + AnyIO threadpool (~40 threads) → concurrency ceiling ≈ **2 × 40 = ~80** simultaneous blocking DB ops. Fine for a small team; the bottleneck is **per-request latency, not concurrency**.
- **`--timeout 30`**: any single request >30 s is killed. The CSV import is **bulk-chunked** (1 dedup read + chunked inserts ≈ ~2 s for 5k) so it's *safe* today — but any future slow endpoint must stay under 30 s or move to a background job.
- **Redis cache layer exists** (`app/core/cache.py`) — org-scoped, fail-open, safe — but is **dormant/barely used** (only `me.py`). It's off unless `REDIS_URL` is set. **Free, safe speedup sitting unused.**
- Background work today: **20 FastAPI `BackgroundTasks`** (fire-and-forget after response — emails, follow-ups) + 2 threads. **No durable queue** (no Celery/RQ/arq). Fine for now.

### 2.6 Frontend (from `main.tsx`, page code)
- `QueryClient` sets only `refetchOnWindowFocus: false` → **`staleTime` defaults to 0** → every query refetches on every mount/navigation.
- **Optimistic updates: ~1** in the whole app (`PlanningBoardPage`). Everything else = *mutate → wait → invalidate → refetch → then UI updates*.
- **No route code-splitting:** `App.tsx` eagerly imports all **22** page components → one large JS bundle → slower first paint (downloaded from Singapore).

---

## 3. Root causes, ranked

1. **Query fan-out × per-query latency — dominant *today*.** 9 sequential queries × ~180 ms ≈ 1.6 s. Region-independent multiplier you control in code.
2. **No intra-request parallelism.** The fan-out is *serial*; running independent queries together would cut most of it.
3. **Unindexed foreign keys — a time bomb on the 5k import.** Today's tables are tiny so seq-scans are cheap; after import they aren't.
4. **No optimistic UI + `staleTime: 0`.** The "choppy" feel: every action and every navigation waits for Tokyo. (Includes the delete-selection race below.)
5. **Three-region topology + ~110 ms Supabase REST overhead.** Structural; the heaviest to change.
6. **Minor:** no code-splitting (first load), duplicate/unused indexes, RLS per-row re-eval.

**It is NOT "an over-complicated monolith."** The stack (FastAPI + React Query + Supabase) is standard and appropriately sized. The slowness is untuned data access.

### The specific "delete is choppy / stays on transcript" bug
1. Delete fires `DELETE` (2 writes) → on success invalidates `['calls']` **and** `['dashboard','overview']` → both refetch from Tokyo before the row leaves. ~1–2 s with the row just sitting there (no optimistic removal).
2. "Stays on the transcript until refresh": clearing the selection on success races the auto-select effect, which re-picks the just-deleted call from the **stale** `['calls']` cache (the refetch hasn't returned yet). Fix = optimistically remove the row from the cache so the list and auto-select are correct instantly.

---

## 4. The fix plan (by area)

### A. Database — indexes & linter (do first; protects the import)
- **A1. Add covering indexes for the ~45 unindexed FKs**, prioritising the hot ones: `inquiries(call_id)`, `inquiries(customer_id)`, `inquiries(assigned_employee_id)`, `calls(customer_id)`, `appointments(customer_id)`, `appointments(inquiry_id)`, `cost_estimates(customer_id)`, `cost_estimates(inquiry_id)`, `documents(customer_id)`, `employees(user_id)`. → Additive migration, **pre-authorized**, low-risk, **urgent before the 5,206-row import**.
- **A2.** Drop the duplicate index (`idx_kva_org`), prune confirmed-unused indexes.
- **A3.** Rewrite the `users_same_org` RLS policy to `(select auth.…())` (affects frontend's direct Supabase reads).
- **Expected impact:** keeps every `WHERE customer_id/call_id/inquiry_id = …` an index lookup instead of a full scan → flat latency as data grows (the difference between "fine at 5k" and "unusable at 5k").

### B. Backend query efficiency
- **B1. Parallelize independent queries in a request** with `asyncio.gather` (the count-loops, enrichment fetches, dashboard sections). `customers._list`'s list + 3 count-loops + 5 type-counts can run concurrently → ~max(180 ms) instead of ~1.6 s.
- **B2. Collapse fan-out:** the 5 separate `_type_count` queries → **one** `GROUP BY customer_type` query; fold the inquiry/appointment/document counts into fewer calls.
- **B3. Turn on the Redis cache (`cache.py`) for hot, slow-changing reads** — `['employees']`, `['settings']`, org/agent config, business hours, customer type-counts — with short TTLs (30–120 s) + invalidate-on-write. The safe, org-scoped layer **already exists**; it just needs `REDIS_URL` set (Railway Redis service is already provisioned) and `get_or_set(...)` wrapped around those loaders.
- **B4. Stop over-invalidating:** a call delete shouldn't force a full `['dashboard','overview']` refetch.
- **Expected impact:** customer list ~1.6 s → ~300–400 ms cold, near-instant warm (cache).

### C. Workers & concurrency (your question — answered with facts)
"Workers" helps in **three distinct ways**; only one of them fixes single-click latency:

- **C1. Intra-request parallelism (the big one for *click* latency).** Today the 2 gunicorn workers and their threadpools are **underused per request** — a request does its 9 queries serially. Running them with `asyncio.gather` uses the threadpool concurrently → the *same* workers do the *same* work in a fraction of the wall-clock time. **This is "using workers efficiently" and it's a code change, not more servers.** (Same as B1.)
- **C2. Web concurrency (for *many employees at once*).** `-w 2` → ~80 concurrent blocking ops. Adequate for a small team now; bump to `-w 4` (and/or Railway replicas) when the team/usage grows. **Not the current bottleneck** — don't over-invest here yet.
- **C3. Durable background jobs (for *heavy/slow* work, keeps requests snappy).** Move fire-and-forget and long work off the request path:
  - Already background (good): post-call follow-ups, emails — via FastAPI `BackgroundTasks`. Caveat: these are **ephemeral** (lost if the worker restarts) and run *inside* the web worker.
  - Consider a **Redis-backed queue (RQ or arq) + a separate Railway "worker" service** for: the CSV import (so a huge file can't ever hit the 30 s timeout), post-call processing, calendar sync, outbound dispatch. This makes user requests return instantly and survives restarts/retries. *Add only when these jobs grow* — today the import is bulk and safe, so this is **medium priority**, not urgent.
- **C4. Connection efficiency (strategic).** The ~110 ms/query is mostly PostgREST overhead. A **direct Postgres connection via the Supabase pooler (Supavisor) using `asyncpg`** for the hot read paths would cut per-query time to ~5–20 ms — but it means rewriting those queries off `supabase-py`. **High effort/high reward; do it only for the few hottest endpoints, later.**

> **Honest expectation-setting:** adding more web workers (C2) will *not* fix the choppy single-click feel — that's latency, fixed by B1/B3/A1 and optimistic UI. Workers matter for concurrency and offloading heavy jobs.

### D. Frontend (smoothness / perceived speed)
- **D1. Optimistic updates** for delete / status-change / assign: update the React Query cache immediately (`onMutate` + `setQueryData`), then reconcile on settle. → the UI reacts in **0 ms**; the server round-trip happens invisibly.
- **D2. Fix the delete-selection race:** optimistically remove the deleted call from `['calls']` so the list updates and auto-select picks the *correct* next call instantly (no "stuck on transcript").
- **D3. Set a real `staleTime`** (e.g. 30–60 s) globally + per-list, so navigating between pages doesn't re-hit Tokyo for data you just loaded. Keep `keepPreviousData` on paginated lists (customers already has it; add to calls).
- **D4. Code-split routes** with `React.lazy` + `Suspense` → smaller initial bundle, faster first paint (especially over the India→Singapore hop).
- **D5. Loading skeletons / transitions** on the slow panels so content fades in instead of snapping — masks remaining latency and removes the "cheap website" feel.

### E. Infrastructure / region / plan — OUT OF SCOPE (owned by Amber)
Network distance, EU co-location, the Supabase compute tier, and the Railway/Supabase plans are **yours to handle** (paid EU plans already purchased). They remove the cross-region hops and ease the ~110 ms platform overhead — but they do **not** fix fan-out, parallelism, indexes, or optimistic UI. Everything that matters in *this* doc is **§4.A–D (code + DB)**.

---

## 5. Phased rollout (priority · risk · impact)

| Phase | Items | Risk | Effort | Expected impact |
|---|---|---|---|---|
| **P1 — now, no infra change** | A1 (FK indexes), A2/A3 (linter), B2 (collapse type-counts), D1+D2 (optimistic delete + race), D3 (`staleTime`) | Low | S–M | Deletes feel instant; lists snappier; **import-safe** |
| **P2 — code, slightly bigger** | B1/C1 (parallelize queries with `gather`), B3 (turn on Redis cache for hot reads), B4 (stop over-invalidating), D4/D5 (code-split + skeletons) | Low–Med | M | Customer list ~1.6 s → ~300–400 ms; smooth perceived UX |
| **P3 — scale & offload (when usage grows)** | C2 (more workers/replicas), C3 (durable queue + worker service for import/post-call) | Med | M | Holds up under many concurrent employees + big jobs |
| **P4 — later, code-only** | C4 (direct Postgres/`asyncpg` for the hottest reads, bypasses PostgREST) | Med–High | M–L | Cuts the residual ~110 ms per query |

**Recommended order:** **P1 → P2** (both code-only — do these now), then P3/P4 after measuring. The priority ranking of what actually makes it smooth: **FK indexes (A1) → fan-out + parallelism + cache (B1/B2/B3) → optimistic UI (D1–D3)**. *Infra / region / plan is your separate track and is excluded here.*

---

## 6. What NOT to do (avoid complications)
- **Don't rewrite into microservices / a "less monolithic" architecture.** The monolith isn't the problem; it's not even complex. A rewrite adds risk and fixes nothing here.
- **Don't just add web workers** and expect the click-lag to go away — it won't (it's latency, not concurrency).
- **Don't move only the backend region** — the DB is the far hop; move both or neither.
- **Don't add a heavy job queue today** — the import is already bulk and safe; add the queue when post-call/sync/import volume actually demands it.
- **Don't drop indexes the linter flags as "unused"** without checking — some back the very queries we're about to add/parallelize.

---

## 7. Open questions to verify (code/DB only — infra is Amber's track)
- [ ] **Enable the Redis cache:** make sure `REDIS_URL` is set so `app/core/cache.py` activates (required for §9.6 to do anything).
- [ ] Re-run `get_advisors(type="performance")` **after the FK-index migration** (§9.1) to confirm the unindexed-FK list shrank.
- [ ] Confirm the dedup read in `csv_import.import_customers` (single `select`) isn't capped at 1,000 rows by PostgREST — a **correctness** concern for dedup on a large base (separate from perf).

---

### Appendix — measurement commands (reproducible)
- Per-query decomposition: `curl -w 'connect=%{time_connect} ttfb=%{time_starttransfer}' …/rest/v1/<table>?select=id&limit=1` (warm via `--next`).
- Prod backend latency: Railway → `http_response_time` (or service metrics).
- DB advisors: Supabase MCP `get_advisors(type="performance")`.
- Fan-out: `grep -c '\.execute()'` per route + read the `_list`/`_overview` functions.

---

## 8. Scope reminder

**This doc = code-level optimization only.** Server plans, EU region, and any migration are **owned by Amber and intentionally excluded** — the paid EU plans handle network distance + most of the per-query platform overhead. Everything here (indexes, fan-out, parallelism, caching, optimistic UI, code-split) is **region/plan-independent**: it makes the site feel smooth regardless of where it runs, and it's the part the plan upgrade does *not* fix. Build it on dev; it carries over unchanged.

---

## 9. Implementation guide (file-level — execute in a fresh session, no prior context needed)

> Order: **P1 first** (low-risk, high-value), then **P2**. Each item = exact file(s) + change + how to verify. Conventions to honor (from project memory): backend has **no hot-reload** (restart uvicorn after edits); additive migrations are **pre-authorized** via Supabase MCP; frontend "done" = typecheck + login-gated preview proof; keep `backend/tests/` green; UI is **German-only**.

### 9.1 · P1.A — FK index migration (DO FIRST — protects the 5,206-row import)
New file `supabase/migrations/0044_perf_fk_indexes.sql`; apply via Supabase MCP `apply_migration` (project `ifbluvdcbcesuhvkxsfn`). Additive/safe. Ready to paste:

```sql
-- 0044_perf_fk_indexes.sql — cover the FKs the linter flagged (hot ones first).
create index if not exists idx_inquiries_call_id           on public.inquiries(call_id);
create index if not exists idx_inquiries_customer_id       on public.inquiries(customer_id);
create index if not exists idx_inquiries_assigned_emp      on public.inquiries(assigned_employee_id);
create index if not exists idx_calls_customer_id           on public.calls(customer_id);
create index if not exists idx_appointments_customer_id    on public.appointments(customer_id);
create index if not exists idx_appointments_inquiry_id     on public.appointments(inquiry_id);
create index if not exists idx_appointments_assigned_emp   on public.appointments(assigned_employee_id);
create index if not exists idx_cost_estimates_customer_id  on public.cost_estimates(customer_id);
create index if not exists idx_cost_estimates_inquiry_id   on public.cost_estimates(inquiry_id);
create index if not exists idx_documents_customer_id       on public.documents(customer_id);
create index if not exists idx_documents_inquiry_id        on public.documents(inquiry_id);
create index if not exists idx_employees_user_id           on public.employees(user_id);
create index if not exists idx_invoices_customer_id        on public.invoices(customer_id);
create index if not exists idx_projects_customer_id        on public.projects(customer_id);
create index if not exists idx_project_employees_employee  on public.project_employees(employee_id);
create index if not exists idx_missed_calls_customer_id    on public.missed_calls(customer_id);
create index if not exists idx_maintenance_plans_customer  on public.maintenance_plans(customer_id);
create index if not exists idx_time_entries_customer_id    on public.time_entries(customer_id);
create index if not exists idx_time_entries_employee_id    on public.time_entries(employee_id);
create index if not exists idx_time_entries_inquiry_id     on public.time_entries(inquiry_id);
create index if not exists idx_vehicles_assigned_emp       on public.vehicles(assigned_employee_id);
create index if not exists idx_tools_assigned_emp          on public.tools(assigned_employee_id);
create index if not exists idx_appointments_tool_id        on public.appointments(tool_id);
create index if not exists idx_appointments_vehicle_id     on public.appointments(vehicle_id);
create index if not exists idx_invoices_cost_estimate_id   on public.invoices(cost_estimate_id);
create index if not exists idx_catalog_items_supplier_id   on public.catalog_items(supplier_id);
-- + created_by / actor_id / conversation_id / user_id / org_id columns on the
--   audit + copilot tables (low traffic; copy the pattern). Full list: get_advisors.
-- Cleanup (advisor WARNs):
drop index if exists public.idx_kva_org;   -- identical to idx_cost_estimates_org
-- RLS: change policy users_same_org to wrap auth.<fn>() in (select auth.<fn>()).
```
**Verify:** re-run Supabase `get_advisors(type="performance")` → `unindexed_foreign_keys` count drops sharply.

### 9.2 · P1.B — Optimistic delete + selection-race fix
Files: `frontend/src/pages/calls/CallDetail.tsx`, `frontend/src/pages/CallLogsPage.tsx`.
- `deleteCall` mutation in `CallDetail.tsx`: add `onMutate` → snapshot `['calls']`, then `qc.setQueryData(['calls'], old => ({ ...old, calls: old.calls.filter(c => c.id !== callId) }))`; `onError` → restore snapshot. Keep `onDeleted` (clears selection). **Remove** the `['dashboard','overview']` invalidation here (item B4).
- With the row gone from the cache immediately, `CallLogsPage.tsx`'s existing `setSelectedId(null)` → auto-select now picks the correct next call. If still racy, hold a `deletedIdRef` and exclude it in the auto-select effect (`calls.find(c => c.id !== deletedIdRef.current)`).
**Verify (login-gated):** delete → row vanishes instantly, detail jumps to next call, no refresh.

### 9.3 · P1.C — staleTime
File: `frontend/src/main.tsx`. `defaultOptions.queries` → add `staleTime: 30_000`. Stops refetch-on-navigation. (Lists already keep `keepPreviousData` where it matters; add to `['calls']` if desired.)

### 9.4 · P1.D — Collapse customer type-counts (5 round-trips → 1)
File: `backend/app/api/routes/customers.py` `_list` (the 5 `_type_count(...)` calls). PostgREST can't cleanly `GROUP BY` via supabase-py → simplest correct fix: a Postgres **RPC** `customer_type_counts(p_org uuid)` returning `(customer_type, n)` grouped, called once. (Alternative: one `select customer_type` for the org + `Counter` in Python — re-reads rows, fine at small scale.) Document which you chose.

### 9.5 · P2.A — Parallelize independent queries (`asyncio.gather`) — biggest single-request win
Files: `backend/app/api/routes/customers.py` (`_list`), `calls.py` (`_list`/`_enrich_calls_with_inquiries`), `dashboard.py` (`_overview`).
- Today these `_list` helpers are **sync**, called via `run_in_threadpool`, and their internal queries run **serially**. Restructure so independent queries run concurrently: in the **async route handler**, `await asyncio.gather(run_in_threadpool(fn_a), run_in_threadpool(fn_b), ...)`, or make the helper `async` and gather inside it.
- Example (customers): run the main list query, the count-loops, and the type-counts (post-9.4: just 1) concurrently → wall-clock ≈ slowest single query (~one round-trip) instead of the sum.
**Verify:** endpoint timing drops to ~1 round-trip; `pytest -k "customer or call or dashboard"` green.

### 9.6 · P2.B — Turn on the Redis cache (built + dormant)
- Set `REDIS_URL` on the backend service (Railway Redis already provisioned). `app/core/cache.py` is **fail-open + org-scoped** (safe).
- Wrap hot, slow-changing loaders in `cache.get_or_set(org_id, name, loader, ttl)`: `['employees']` (`employees.py` list), settings GET, agent/Kiki config, business hours, customer type-counts. **Invalidate** the matching key on the corresponding write (e.g. employee create/update → invalidate `employees`).
**Verify:** 2nd hit of a cached endpoint is near-instant; fail-open works when `REDIS_URL` unset (no behavior change).

### 9.7 · P2.C — Code-split routes
File: `frontend/src/App.tsx`. Convert the 22 eager `import …Page` to `const …Page = lazy(() => import('./pages/…'))` and wrap `<Routes>` in `<Suspense fallback={…}>`. Smaller initial bundle → faster first paint.

---

## 10. Status / what's NOT yet done (as of this doc)
- This plan is **analysis + an implementation spec only** — **no P1/P2 optimization code has been written yet.** (The earlier bug-fix batches 1–8 are separate and already committed on `main`: `5524404`, `55bb09c`.)
- Recommended next session: implement **§9.1 → 9.4 (P1)** first, verify, commit; then **§9.5 → 9.7 (P2)**. All are **code-only** — no infra / region / plan dependencies (that's your separate track).
