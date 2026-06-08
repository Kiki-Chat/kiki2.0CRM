# KikiJarvis Architecture RE-AUDIT — 2026-06-08

**Date:** 2026-06-08
**Branch under review:** `fix/arch-audit-hardening-2026-06-08` (commits `4068fb4` + `6f8c68f`)
**Baseline:** `ARCHITECTURE_AUDIT_2026-06-08.md` (commit `2395f9d`)

> **⮑ Resolution update (same day):** every open item this re-audit identified was subsequently CLOSED on this branch — the **PATCH/UPDATE-path IDOR** (`projects._patch`, `invoices._update`, **and** `cost_estimates._create/_update`, which this re-audit itself had missed), the **two unbounded reads** (`build_customer_timeline` + `project_employees` in `projects._detail` and the list route), and the **603 kB bundle** (`manualChunks` react-vendor split → main chunk 603 kB → 138 kB, warning gone). Verified by 4 new IDOR unit tests + live 422s and a clean build. The findings below are preserved as the point-in-time snapshot.

## Method

Parallel finder agents compared each original audit finding to the current code **and** the fix diff (`2395f9d..HEAD`), proposing per-finding statuses and new-issue lists. Every fix-claim and every new issue was then handed to an **independent adversarial verifier** that re-read the code, checked the git diff, and returned a verdict (`confirmed` / `partly-confirmed` / `refuted`). **Where a verifier refuted or partly-confirmed a finder's claim, this report trusts the verifier over the finder's optimism** — refuted "fixes" are demoted to not-addressed/partially-fixed, and refuted new issues are dropped. Grades are calibrated to the verifier verdicts plus the ground-truth build/test state below.

### Ground truth (stated up front)

- **Backend:** 554 pass / 6 reds — the 6 reds are **pre-existing** on `main`, **not regressions** from these fixes.
- **Frontend:** `tsc` clean; `vite build` OK but **one ~603 kB chunk** ships with a code-split warning.
- **Vitest:** 16 pass / 5 reds — the 5 reds are **pre-existing**, not regressions.

### Grading rubric

- **A** — Dimension is a model of the practice: correctness + security solid, structure clean, no acknowledged debt of consequence.
- **B+ / B** — All correctness/security findings verified-fixed; remaining items are bounded performance polish or acknowledged, low-risk structural debt.
- **B- / C+** — Highest-severity (data-integrity / cross-tenant / event-loop) risks fixed, but real correctness or security gaps remain (even if narrow).
- **C / D** — Latent incident: data loss, IDOR, or a blocking architectural defect is live.

A dimension where all correctness/security findings are verified-fixed but real structural debt (god-files, partial IDOR coverage, an un-split bundle) remains **rises but does not reach A**.

---

## 1. Scorecard with grade movement

| Dimension | Original | New | Δ | Verdict |
|---|---|---|---|---|
| Parallelism & Concurrency | C | **B** | ▲ | Every real serial-query bottleneck + the event-loop block fixed; one claimed fix (`calls._list`) was refuted and stays open; durable-queue debt deferred. |
| Caching | B- | **B+** | ▲ | All five HIGH/MED caching findings verified-fixed (TTL, stampede guard, memoized contexts, JWKS TTL); residual items are latent/dormant by design. |
| Backend Architecture | C- | **B-** | ▲ | Atomicity, config fail-fast, paging fixed; but IDOR fix is **POST-only** (PATCH/UPDATE still vulnerable) and god-files untouched. |
| Frontend Layout / Adaptability | D+ | **B** | ▲▲ | Fully responsive at all breakpoints, all overflow leaks closed; padding scale and form-grid stacking remain inconsistent polish gaps. |
| Frontend Arch / Rendering | B | **B** | = | Context re-renders + listener leaks fixed; held flat by the un-split **603 kB** bundle and two un-migrated toast pages. |
| Data Access & Database | C | **B-** | ▲ | The critical 1000-row truncation bugs are closed via `fetch_all_rows`; one `_detail` read (`project_employees`) + the timeline reads remain unbounded. |

**Overall verdict:** The branch is a **genuine, well-verified improvement** — the dangerous classes of bug (event-loop stalls, silent 1000-row data loss, wide-open webhook secret, multi-write orphans) are fixed and proven. It is **not yet fully "up to the mark"** for a clean merge: two verified correctness gaps survived the fixes (PATCH-path IDOR, unbounded `project_employees`/timeline reads) and one high-impact perf item (the 603 kB bundle) is unaddressed. None of these are release-blocking on their own, but the **PATCH-path IDOR should be closed before deploy**.

---

## 2. What got fixed (verified)

Confirmed resolved by independent verification (`confirmed` verdict unless noted):

**Parallelism & Concurrency**
- `conversation_init` no longer blocks the event loop — now `await run_in_threadpool(init_service, …)`. *(verifier: confirmed)*
- Outbound occasion-email send is bounded by a **5 s** `thread.join(timeout=5)`; the call is placed first, so a slow provider can never block the sweep or call placement. *(confirmed)*
- Serial-query fan-outs parallelized via the new `run_parallel()` helper: `projects._list` (5 reads), `calls._build_timeline`, `customers._detail` (4 reads), `employees._list`, `dashboard._finanzen`. *(all confirmed)*
- ElevenLabs tool-ID cache gained a 3600 s TTL with full `clear()+update()` eviction (no orphaned IDs). *(confirmed)*

**Caching**
- C1 tool-ID cache TTL — confirmed (TTL + full eviction + refresh-on-missing-name).
- C2 `ThemeProvider` context value `useMemo`'d on `[theme]`. *(confirmed)*
- C3 `AdminAuthProvider` passes the memoized binding through directly (no fresh-object rebuild). *(confirmed)*
- C4 `cache.get_or_set()` stampede guard — atomic Redis `SET NX` + bounded poll + fail-open, with passing single-flight and contention tests. *(confirmed)*
- C5 JWKS TTL — hardcoded 1 h removed; now `settings.jwks_ttl_seconds` (default **300 s**, env-overridable). *(confirmed)*

**Backend Architecture**
- Multi-write atomicity — `appointments.book_appointment` and `invoices._create` now compensate (delete the orphan) on mid-write failure; test asserts rollback. *(confirmed)*
- Config fail-fast — `master_webhook_secret` default is now `""`; `validate_runtime_config()` + a `main.py` startup guard raise `RuntimeError` in prod if unset; verifiers reject empty secrets. *(confirmed)*
- `mark-read` reduced from 3 round-trips to 1 (common case) via conditional UPDATE on `read_at IS NULL`, 2 on reopen. *(partly-confirmed — fix is correct; the finder's "chains `.select()`" description was inaccurate, but the behavior matches the claim.)*

**Frontend Layout & Rendering**
- All HIGH overflow leaks closed: call-row `truncate`, Workspace `min-w-0`, Tag `whitespace-normal sm:whitespace-nowrap`. *(all confirmed)*
- Mobile sidebar drawer at `md` (fixed overlay + backdrop + Escape + route-change close + hamburger), with desktop sticky rail. *(confirmed)*
- Responsive table columns (`hidden md:table-cell`) on CustomersPage + CostEstimatesPage. *(confirmed)*
- Modal width `w-[min(92vw,calc(100vw-2rem))]`, FilterPopover right-anchored + viewport-clamped, sidebar dropdown full-width on mobile, CommandPalette centered. *(all confirmed)*
- `useMe()` hook adopted in CallLogsPage + CalendarPage (de-duplicated `['me']` queries, 5-min staleTime). *(confirmed)*
- OAuth popup listener in SettingsPage now has idempotent cleanup + 30 s safety timer. *(confirmed)*

**Data Access**
- The **CRITICAL** CSV-import dedup 1000-row cap is fixed via `fetch_all_rows()` (customers + employees); pagination logic verified to terminate correctly and tested to 2500 rows. *(confirmed)*
- `customers._list` enrichment counts, `projects._list` call-counting + listing, and `gen_customer_number` all page past the 1000-row cap. *(all confirmed)*

---

## 3. What still needs work (prioritized)

Leading with anything Critical/High or a verified regression.

| Issue | Dimension | Severity | Fixed? | Effort | Fix |
|---|---|---|---|---|---|
| **PATCH/UPDATE IDOR still open** — `projects._patch` + `invoices._update` accept client FK ids (customer_id, kva_id, project_id) with **no** `validate_fk_in_org` | Backend Arch | **High** | **partial** (POST fixed, PATCH not) | S | Add `validate_fk_in_org` to the patch/update paths, mirroring `_create`. |
| **603 kB main JS chunk** — `vite.config.ts` has no `manualChunks`; recharts/@fullcalendar/dnd-kit/radix land in the main bundle despite `React.lazy` | Frontend Arch | **High** | **no** | S | Add `build.rollupOptions.output.manualChunks` (vendor / charts / radix split); re-verify chunk size. |
| `project_employees` read in `projects._detail` is still unbounded `.execute()` (silent cap >1000 assigned employees) | Data Access | Medium | **partial** (6 of 7 reads paged) | S | Wrap in `fetch_all_rows()` like the other six. |
| `build_customer_timeline` — 4 parallel reads but **no `.range()` bound**; >1000 rows of any entity silently truncate the timeline | Data Access / Parallelism | Medium | **partial** | S | `.order('created_at', desc=True).range(0, 499)` per read. |
| `post_call` daemon thread is **not durable** — worker restart mid-confirmation leaves the appointment stuck `pending` forever (idempotency prevents *dupes*, not *loss*) | Parallelism / Backend Arch | Medium | **partial** (idempotent, not durable) | M | Persist pending L3 confirmations to a table + scheduled retry job. |
| **`calls._list` enrichment never parallelized** — finder claimed fixed, verifier **refuted**: inquiries→employees still run serially | Parallelism / Data Access | Medium→Low | **no** | S | Parallelize the two independent reads (note: genuine data dependency — employee ids derive from inquiries; speculative restructure for ~100 ms gain). |
| Bare-except sweep incomplete — `post_call._fire_level3_confirmations` swallows per-appt failures with `except: pass` (no `log.exception`) | Backend Arch | Low/Medium | **partial** | S | Log before `pass` so failed confirmations are diagnosable. |
| Input-validation gaps — `extra="forbid"` not on `ProjectCreate`/`VerhaltenUpdate`; CSV mapping whitelist not explicit | Backend Arch | Medium | **no** | M | Set `extra="forbid"`; validate CSV mapping against an allowed-field list. |
| Toast cleanup incomplete — `PlanningBoardPage` + `projectTabs.tsx` still use uncleaned `setTimeout` (unmounted-component leak) | Frontend Arch | Medium→Low | **partial** (6+ pages migrated, 2 remain) | S | Adopt the existing `useToast()` hook. |
| `copilot-widget` — CSS height now responsive, but the JS drag-clamp still hardcodes the 560 px cap (mismatch on smaller viewports) | Frontend Layout | Low | **partial** | S | Make the JS clamp breakpoint-aware to match the CSS staircase. |
| God-files — `kiki_zentrale.py` (1057 lines), no extraction to a services layer | Backend Arch | High (structural) | **no** | L | Extract business logic into `services/`; deferred, not P0. |
| Durable BackgroundTasks queue (agent-config pushes, no retry) | Parallelism | Low/Medium | **no** | L | Durable queue; deferred until volume grows. |
| `run_parallel()` creates a new `ThreadPoolExecutor` per call | Parallelism | Low | new (introduced-by-fix) | S | Measure first; reuse a shared pool or convert helpers to async only if latency shows. |
| `fetch_all_rows()` has no dedicated unit test (correctness-critical) | Data Access | Low | new (introduced-by-fix) | S | *Note:* a verifier later cited a passing `test_fetch_all_rows_pages_past_1000` (2500 rows) — coverage appears to exist; reconcile and close. |
| Dashboard header still block-layout (not `flex-wrap`); padding scale inconsistent (`p-4 md:p-6 lg:p-8` vs fixed `p-8`); 37 `grid-cols-2` form grids un-stacked on mobile | Frontend Layout | Low | mixed (deferred polish) | M | Systematize the responsive padding ramp; stack form grids; wrap dashboard header. |

---

## 4. Per-dimension detail

### Parallelism & Concurrency — **C → B**

**Rationale.** Every *verified* serial-query bottleneck and the false-coroutine event-loop block are fixed; the outbound email is now timeout-bounded. Two of the finder's "fixes" were knocked down by verification: `dashboard.overview` was **never a bug** (already correct at baseline — refuted as a "fix" but harmless) and `calls._list` enrichment was **claimed fixed but is not** (verifier refuted: inquiries→employees still serial). With one genuine hot-route enrichment left serial plus the still-non-durable `post_call` thread, the dimension lands at **B**, not B+.

**Original findings**
- *fixed:* `conversation-init-blocks-loop`, `outbound-dispatch-email-send`, `projects-list-six-serial-queries`, `build-timeline-four-serial-queries`, `serial-customer-enrichment-queries`, `employees-list-three-serial-fetches`, `dashboard-anrufe-finanzen-serial`, `elevenlabs-tool-id-cache-no-ttl`.
- *was-false-positive (as a "fix"):* `dashboard-overview-eight-serial-queries` — verifier confirmed the code is correct **but unchanged since baseline**; the audit had already marked it "verified-good." Not a fix that happened in this cycle.
- *not-addressed (verifier refuted the fix-claim):* `calls-list-serial-enrichment-queries` — `_enrich_calls_with_inquiries` still runs inquiries then employees serially; no `run_parallel`.
- *partially-fixed:* `post-call-daemon-thread-leak` — now idempotent (no duplicate confirmations) but **still not durable** (lost on worker restart).
- *not-addressed (deferred, acknowledged):* `background-tasks-no-persistence`, `elevenlabs-sync-http-client`, `oauth-tokens-sync-network-call`, `shared-lru-cache-client-missing-docstring`, `gunicorn-timeout-30s` (Low — measured p99 2.94 s), `gunicorn-workers-2` (Low).

**Verified new issues**
- **`run_parallel()` per-call pool churn** *(partly-confirmed — real, but an acknowledged tradeoff).* New `ThreadPoolExecutor` per call; fine today, revisit under load (prefer async conversion over pool reuse). **Fix:** measure; share a pool or go async only if latency shows.
- **`post_call` confirmation loss on restart** *(confirmed).* Idempotency stops dupes, not loss; a graceful shutdown mid-confirmation strands an appointment at `pending`. **Fix:** persist pending confirmations + scheduled idempotent retry.

### Caching — **B- → B+**

**Rationale.** All five HIGH/MED findings (C1–C5) are verified-fixed with passing tests and no regressions. The remaining items (C6–C10) are LOW/latent or correct-as-is per the original audit (negative caching is opt-in and unused; `@lru_cache` config is correct for a 12-factor app). B+ rather than A because three small new latent issues exist and the stampede guard is dormant by default.

**Original findings**
- *fixed:* C1 (tool-ID TTL), C2 (ThemeProvider memo), C3 (AdminAuth memo), C4 (stampede guard), C5 (JWKS TTL).
- *partially-fixed (LOW, already near-closed):* C6 optimistic-delete reconciliation, C8 SPA chunk-staleness (ChunkErrorBoundary already shipped).
- *not-addressed (correct as-is / latent, LOW):* C7 mark-read over-invalidation (intentional — must refresh the unread badge), C9 negative caching (infra added, opt-in), C10 `@lru_cache` (documented, correct).

**Verified new issues** (all `confirmed`, all LOW)
- **Stampede `time.sleep` blocks a threadpool thread** up to 500 ms under contention — acceptable (dormant by default, brief window).
- **Per-worker tool-ID cache divergence** — across 2 workers, one may serve a stale tool id for up to 1 h while the other re-fetches. Bounded vs the original *infinite* staleness; use a shared Redis key if zero-staleness is needed.
- **`_NULL` sentinel collision** — theoretical only; no current loader returns the sentinel string or uses `cache_none=True` in prod.

### Backend Architecture — **C- → B-**

**Rationale.** The four correctness/security items moved decisively: atomicity (compensating deletes + test), config fail-fast, paging, and typed error handling are verified-fixed. But the **IDOR fix is incomplete** — the verifier confirmed `validate_fk_in_org` is present on the POST/`_create` paths only; `projects._patch` and `invoices._update` still accept cross-tenant FK ids unvalidated. That is a live (if narrower) security gap, which caps the dimension at **B-**, not B. God-file/structural debt is untouched (acknowledged, deferred).

**Original findings**
- *fixed:* `multi-write-atomicity-gaps`, `config-unsafe-defaults`, all the paging/parallelism items (`1000-row-limit-csv-import-dedup`, `customer-list-unbounded-enrichment-counts`, `projects-list-calls-no-limit`, `customer-timeline-unlimited-fetches`, `conversation-init`, `outbound-dispatch`, `elevenlabs-tool-id-cache`, `employees-list`), `mark-read-duplicate-query` *(partly-confirmed — correct fix, mislabeled mechanism)*.
- *partially-fixed:* `service-role-client-discipline-idor` **(verifier partly-confirmed: POST validated, PATCH/UPDATE NOT)**; `bare-except-swallowed-exceptions` (employees/calls typed; `post_call` still generic); `unvalidated-request-bodies-mass-assignment` (dates + query bounds validated; `extra="forbid"` not added).
- *not-addressed (deferred, acknowledged):* `god-files-business-logic` (High structural debt — `kiki_zentrale.py` 1057 lines).
- *not-addressed (verifier refuted the fix-claim):* `calls-list-serial-enrichment-queries` — same refutation as in Parallelism.

**Verified new issues**
- **PATCH-path IDOR** (folded into `service-role-client-discipline-idor` above) — **the single most important open item.** **Fix:** `validate_fk_in_org` on both update paths.
- **Outbound email re-uses a raw daemon thread** *(introduced-by-fix, Medium, finder confidence medium).* Lower-severity than `post_call` (best-effort, 5 s-bounded) but re-introduces the audited daemon-thread smell. **Fix:** use a pooled `ThreadPoolExecutor.submit() + wait(timeout=)`.
- **CSV mapping whitelist + `extra="forbid"` missing** *(Medium).* Mass-assignment surface. **Fix:** explicit allowed-field whitelist + `extra="forbid"` on input schemas.
- **`_fire_level3_confirmations` swallows per-appt failure silently** *(Medium).* Correct "one bad appt mustn't block others" logic, but no logging. **Fix:** `log.exception` before `pass`.
- **PlanningBoardPage/projectTabs toast leak** + **mobile backdrop missing `role="button"`** — Low; tracked under Frontend.

### Frontend Layout / Padding / Adaptability — **D+ → B**

**Rationale.** Largest jump on the board. The app went from no mobile strategy to **fully responsive and verified usable at 375px with zero page overflow**: drawer sidebar, responsive tables, viewport-clamped modals/popovers/dropdowns, single-pane call-logs cockpit. All HIGH overflow leaks are verified-closed. Held at **B** (not A-) because: the responsive padding ramp is applied inconsistently (CustomersPage responsive, others fixed `p-8`); 37 `grid-cols-2` form grids stay 2-up on phones (cramped, not overflowing — deferred); the Dashboard header is still block-layout (verifier `partly-confirmed`: 6 of 7 headers got `flex-wrap`); and the CopilotWidget JS clamp is only partially responsive.

**Original findings**
- *fixed:* call-row truncate, Workspace `min-w-0`, Tag wrap, sidebar mobile drawer, responsive table columns, Modal width, sidebar dropdown width, CommandPalette centering, FilterPopover anchoring, EmployeesPage overflow scroll, CustomersPage max-width/padding, call-logs single-pane mobile.
- *partially-fixed:* `topbar-padding-inconsistent` (responsive but 3-step ramp, LOW); `copilot-widget-fixed-dimensions` **(verifier partly-confirmed: CSS staircase fixed; JS drag-clamp still hardcodes 560 px → mispositions on small viewports)**; `page-headers-flex-wrap` **(verifier partly-confirmed: 6/7 — Dashboard header still block-layout)**.
- *not-addressed (deferred, LOW):* `grid-cols-2-form-stacking`.

**Verified new issues** (all introduced-by-fix, LOW)
- Responsive padding scale inconsistent across list/form pages.
- Topbar 3-step padding ramp (jarring 8 px jump at `sm`).
- EmployeesPage horizontal-scroll table has no scroll affordance on narrow phones.
- *(The rightOpen-toggle "edge case" was self-refuted by the finder — the desktop branch always renders the toggle when `isWide`; no action.)*

### Frontend Architecture / Rendering — **B → B (unchanged)**

**Rationale.** Real wins (memoized Theme/Admin contexts, idempotent OAuth-listener cleanup, `useMe()` de-dup, useToast across 6+ pages) keep the foundations strong, but two gaps hold the grade flat: (1) the **603 kB main chunk** — `vite.config.ts` has no `manualChunks`, so heavy vendor libs land in the main bundle despite `React.lazy` page splitting (this is the ground-truth code-split warning, and it's a HIGH-severity rendering/perf finding); and (2) two pages still leak `setTimeout` toasts. Both are narrow (one config file, two pages) but real, so the dimension neither rises nor falls.

**Original findings**
- *fixed:* `oauth-listener-leak-SettingsPage`, `theme-provider-context-rebuild`, `admin-auth-provider-fresh-object`, `me-query-duplicated`, and the full set of responsive items mirrored from the Layout dimension.
- *partially-fixed:* `uncleaned-setTimeout-toast-pattern-6-pages` (6+ migrated; PlanningBoardPage + projectTabs remain).
- *not-addressed:* `code-splitting-603kb-chunk` **(High)**, `missing-optimistic-update-patterns` (Medium — list pages still invalidate rather than `onMutate`-snapshot).

**Verified new issues** (both `confirmed`)
- **603 kB bundle / no `manualChunks`** — *the highest-leverage frontend item.* **Fix:** vendor/charts/radix `manualChunks` split; re-verify chunk size.
- **PlanningBoardPage + projectTabs uncleaned `setTimeout`** — unmounted-component leak; the fix (`useToast`) already exists elsewhere.

### Data Access & Database — **C → B-**

**Rationale.** The critical class of bug — PostgREST's silent 1000-row cap corrupting CSV dedup, counts, and number generation — is closed with a correct, tested `fetch_all_rows()`. That alone clears the C. It stops short of B because the verifier found the paging rollout **incomplete in two verified spots**: the 7th read in `projects._detail` (`project_employees`) is still a bare `.execute()`, and `build_customer_timeline`'s four reads are parallelized but **unbounded** (silent truncation >1000 per entity). Neither corrupts persisted data, but both can silently drop rows from a response — a correctness gap, hence **B-**.

**Original findings**
- *fixed:* CSV dedup 1000-cap (CRITICAL), `customers._list` counts, `projects._list` call-counting + listing pagination, `gen_customer_number` (verifier praised the implementation as better than the audit's suggestion).
- *partially-fixed:* `build_customer_timeline` (parallel, not bounded); `projects._detail` **(verifier partly-confirmed: 6 reads paged, `project_employees` still unbounded)**; `calls._list serial enrichment` (batched via `in_()`, not parallel — genuine data dependency limits the win).
- *was-false-positive:* `gen_invoice/project/inquiry_number over-fetching` **(verifier partly-confirmed: these were never broken — already `count="exact"` at baseline; only `gen_customer_number` legitimately needed the fix it received).**
- *fixed:* `mark-read 3→1`.

**Verified new issues**
- **`build_customer_timeline` four unbounded reads** *(confirmed).* **Fix:** `.order(...).range(0, 499)` per read.
- **`calls._list` inquiries→employees serial** *(partly-confirmed — real, but a true data dependency; bounded ~100 ms payoff at page size ≤50).*
- **`fetch_all_rows` one round-trip per 1000 rows** *(confirmed, LOW, acceptable).* Correct by design; revisit only if large re-imports become a hot path.

---

## 5. Regressions from the fixes

Reviewed from the regression-hunter lens plus every `introduced_by_fix=true` issue across the other dimensions.

- **REFUTED — AdminAuthProvider "type unsafety."** The finder flagged assigning `AuthContextValue` (superset, has `signInWithMagicLink`) to `AdminAuthContextValue` (subset) as a type-safety regression. The verifier **refuted** it: TypeScript structural typing permits a wider type where a narrower one is expected, all required members are present, and `tsc --noEmit` passes clean. **Dropped — not a regression.**
- **CONFIRMED (Low) — `Topbar.onOpenNav` called without null-check.** Optional prop invoked directly (`onClick={onOpenNav}`); strict mode is off so `tsc` doesn't catch it. Mitigated — AppLayout always passes it — but fragile. **Fix:** `onClick={() => onOpenNav?.()}` or make the prop required.
- **CONFIRMED (Low) — `CallDetail.onBack` called without null-check.** Same pattern; React tolerates `undefined` onClick at runtime, so no crash today, but it's a type-contract contradiction. **Fix:** optional-chain or require the prop.
- **CONFIRMED (Low) — cache stampede fallthrough leaves a dangling lock.** A poller that times out and loads anyway never deletes the lock (only the holder does), so it lingers up to `_LOCK_TTL`=10 s. Fail-safe today (auto-expiry), but would deadlock if the TTL were removed. **Fix:** log on give-up; optionally mark the lock "dead" so later pollers skip the wait.
- **Introduced-by-fix smells (non-crashing):** `run_parallel()` per-call pool churn (Low), outbound daemon-thread re-introduction (Medium), per-worker tool-ID divergence (Low), `_NULL` sentinel (Low), responsive-padding/Topbar-ramp inconsistencies (Low). All covered in their dimensions above.

**Bottom line:** **No regression survived verification as a runtime defect.** The only "serious" proposed regression (the AdminAuthProvider type issue) was refuted. What remains are three Low type-safety/semantic nits and a handful of efficiency/consistency smells — all non-blocking. Ground-truth confirms it: backend 554 pass (6 reds pre-existing), `tsc` clean, vitest 16 pass (5 reds pre-existing). That is a clean regression result and worth stating plainly.

---

## 6. Verdict & recommended next actions

**Is it up to the mark?** **Mostly — and clearly better — but not a clean "yes" for an unconditional merge to `main`.** The fixes are real and independently verified: the dangerous bug classes (event-loop stalls, silent 1000-row data loss, wide-open webhook secret, multi-write orphans, re-render cascades, mobile unusability) are closed. No verified regressions. But three verified gaps remain, two of them correctness/security.

**Before merging to `main`:**
1. **Close the PATCH-path IDOR** (High, S) — add `validate_fk_in_org` to `projects._patch` and `invoices._update`. This is the only *security* gap left open and is the single most important item.
2. **Bound the unbounded reads** (Medium, S each) — wrap `project_employees` in `projects._detail` with `fetch_all_rows()`, and add `.order(...).range(0, 499)` to the four `build_customer_timeline` reads. These prevent silent row-dropping in responses.

**Before deploy / fast-follow (not merge-blocking):**
3. **Split the 603 kB bundle** (High perf, S) — add `manualChunks` to `vite.config.ts`; this is the ground-truth build warning and the biggest remaining frontend lever.
4. Migrate the last two toast pages to `useToast()`; optional-chain the two unsafe prop handlers; add `log.exception` before the `_fire_level3_confirmations` `pass`.

**Deferred / backlog (acknowledged, not for this branch):**
5. `post_call` durable confirmation queue; god-file extraction (`kiki_zentrale.py`); `extra="forbid"` + CSV mapping whitelist; durable BackgroundTasks; `run_parallel` pool reuse / async conversion; responsive-padding systematization + form-grid stacking.

**Recommendation:** land items **1–2 on this branch**, then merge. Items **3–4** as an immediate fast-follow. The branch represents a strong, honestly-verified hardening pass — do not inflate to A-grades on any dimension, but it is firmly merge-worthy once the PATCH IDOR is closed.
