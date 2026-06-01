# Overnight session — 2026-06-01 (autonomous)

Amber asleep. Full autonomy. This file is my running log + reasoning + morning report.
Baseline before any change: **288 backend tests pass** (HEAD `9715518`), frontend `tsc -b` clean (per handover).

Rollback anchor for the whole session: `git reset --hard 9715518` (pre-session HEAD).

---

## STATUS BOARD (top of morning report)

| Item | Scope | Status |
|------|-------|--------|
| 1 | FK hardening (cross-org FK validation) | ✅ DONE + DEPLOYED (`dba1a58`) |
| 2 | Silent-failure hardening (crypto.decrypt, list_connections) | ✅ DONE + DEPLOYED (`baaa3c7`) |
| 3 | Frontend role-UX (hide admin-only controls) | ✅ DONE + DEPLOYED (`86a9eb3`) |
| 4 | Redis cache + observability (BUILD-ONLY) | ✅ BUILT + TESTED — NOT deployed (dormant in tree; awaits your env vars) |

**Final suite status:** hermetic suite `pytest -m "not live"` = **317 passed, 6 deselected** (green). The 6 `live` tests hit the real ElevenLabs API; `test_live_knowledge_push_remove` flaked once on a full run then **passed on re-run** (transient API timing, not a code regression — confirmed it's unrelated to the Item-1 `org_id` change, which it exercises and passes). Git: `f4b4914` = `origin/main`, tree clean. Prod backend `/health` 200 (items 1+2), prod frontend `/` 200 (item 3); item 4 not deployed.

---

## ITEM 1 — FK hardening  ✅ DONE + DEPLOYED

### Diagnosis (read-first)
Canonical pattern = `inquiries._assign` (routes/inquiries.py:96) + `projects.add_project_employee`
(routes/projects.py:534): before writing, (a) confirm the *target* row is in the caller's
org (404 if not), and (b) confirm any FK id in the body is *also* in the caller's org (422 if
not). The Wave-2 isolation audit found NO read leaks; the remaining gaps are write paths that
accept a foreign-key id from the request body without the (b) check → a caller can plant
another org's id on a row in their own org (dangling cross-tenant pointer; integrity, not leak).

Flagged write paths confirmed by reading the code:
- `routes/inquiries.py::_create` — sets `customer_id`, `project_id` unchecked.
- `routes/inquiries.py::_update` — sets `project_id`, `assigned_employee_id` unchecked
  (the dedicated `/assign` route validates employee, but the generic PATCH does not).
- `routes/appointments.py::_create` — sets `customer_id`, `project_id`, `assigned_employee_id`,
  `inquiry_id` unchecked.
- `routes/appointments.py::_patch` — `AppointmentPatch` allows `assigned_employee_id`,
  `vehicle_id`, `tool_id` (NOT customer/project/inquiry) — unchecked.
- `routes/documents.py::_upload` — sets `customer_id` unchecked.
- `routes/employees.py::_create_absence` — sets `employee_id` unchecked.

Service-layer defense-in-depth (belt-and-suspenders; routes already org-check before calling,
but the service helpers look up sensitive rows by id ALONE):
- `services/elevenlabs_agent.py::push_knowledge_resource_to_elevenlabs(resource_id)` —
  `knowledge_resources` lookup by id only; org_id read FROM the row.
- `…::remove_knowledge_resource_from_elevenlabs(resource_id)` — same.
- `…::rollback_to_snapshot(snapshot_id)` — `agent_config_snapshots` lookup by id only; then
  passes the snapshot's own org+agent into `patch_agent_safely`, so the existing cross-org
  guard there is a tautology for this path → rollback has NO service-level org check today.
- `routes/kiki_zentrale.py::reindex_knowledge_resource` — flagged; the route DOES org-check
  the resource first, so threading org_id through the two `ea.*` helpers covers it.

### Design decisions
1. **Shared helper** `services/common.py::validate_fk_in_org(client, *, table, fk_id, org_id,
   label, require_active=False)` — null/"" fk_id is a no-op (clearing an optional FK stays
   allowed); otherwise 422 `"{label} gehört nicht zu dieser Organisation."` (matches the
   existing `_assign` German message). `require_active=True` adds `.eq("deleted", False)` — used
   only for `employees` (the only flagged table with a boolean soft-delete; inquiries use a
   `status='deleted'` value, not a column, so they must NOT get that filter).
2. **Scope beyond the literal list (justified):** I also validate `inquiry_id` on appointment
   create and `vehicle_id`/`tool_id` on appointment patch, and `assigned_employee_id` on
   inquiry update. Same class of risk, brief says "apply it consistently," and I verified
   `vehicles`/`tools`/`inquiries`/`customers`/`projects`/`employees` are all org-scoped tables.
   Strictly strengthens isolation; valid same-org ids and nulls are unaffected.
3. **Service helpers get a REQUIRED `org_id` kwarg** (not optional) so no caller can skip the
   filter — the strongest belt-and-suspenders. All callers are in `kiki_zentrale.py` (6 sites)
   + 2 test files; all updated. Cross-org id → lookup returns nothing → behaves as not-found
   (push/remove become safe no-ops on a foreign id; rollback raises "snapshot not found").
4. **Why 422 not 404 for body FKs:** matches `_assign` — the *target* row exists (404 reserved
   for "target not in your org"); the *referenced* FK is the bad input (422, unprocessable).

### Files changed (Item 1)
- `backend/app/services/common.py` — NEW `validate_fk_in_org(...)` helper.
- `backend/app/api/routes/inquiries.py` — `_create` validates customer_id+project_id; `_update` validates project_id+assigned_employee_id.
- `backend/app/api/routes/appointments.py` — `_create` validates customer_id+project_id+inquiry_id+assigned_employee_id; `_patch` validates assigned_employee_id+vehicle_id+tool_id.
- `backend/app/api/routes/documents.py` — `_upload` validates customer_id.
- `backend/app/api/routes/employees.py` — `_create_absence` validates employee_id.
- `backend/app/services/elevenlabs_agent.py` — `push_/remove_knowledge_resource_*` + `rollback_to_snapshot` gained a REQUIRED `org_id` kwarg + `.eq("org_id", …)` lookup filter.
- `backend/app/api/routes/kiki_zentrale.py` — 6 call sites pass `org_id=user.org_id`.
- `backend/tests/test_elevenlabs_{safety,live}.py` — call sites updated for the new kwarg.
- `backend/tests/test_fk_hardening.py` — NEW, 16 tests.

**Tests:** new file 16/16; full suite **304 passed** (288 baseline + 16). No migrations (FK columns already exist).

**Rollback point (Item 1):** pre-session HEAD `9715518`. Undo on prod: `git revert dba1a58 && git push && railway up backend --path-as-root --service backend --ci`, or redeploy the prior backend build in the Railway dashboard.

**Deploy + verify (Item 1):** committed `dba1a58` → pushed origin/main → `railway up backend --path-as-root --service backend --ci` → build SUCCESS, active deployment (UTC `2026-05-31T21:18:59Z` = ~02:49 IST 06-01; prior deploys now REMOVED). Verified live: `GET /health` → **200 `{"status":"ok"}`**; `/openapi.json` = **152 paths** (unchanged — Item 1 adds no routes, only in-handler validation).
- **Verification honesty:** the cross-org→422 behavior is proven by the 16 hermetic tests, NOT exercised against prod (that would need two orgs + a prod JWT + a real write — violates the no-customer-data rule). Live proof for a code-only/no-route change = deploy SUCCESS from the pushed commit + `/health` 200.

---

## ITEM 2 — silent-failure hardening

### Diagnosis (read-first)
- `core/crypto.py::decrypt()` caught `InvalidToken` and returned `None` SILENTLY.
  A wrong/rotated `SETTINGS_ENC_KEY` makes EVERY stored credential fail to decrypt
  → every `get_valid_access_token` / SMTP-password read silently looks like "no
  token", with nothing in the logs pointing at the key. 7 callers rely on the
  `None`-on-failure contract (oauth_tokens ×3, email_send ×3, oauth route state).
- `oauth_tokens.list_connections()` returned `connected: True` from row-existence
  alone — a cosmetic green even when the stored token is unreadable/unusable.

### Design decisions (conservative — don't break working connections)
1. **decrypt() now LOGS** the `InvalidToken` failure at WARNING (module logger)
   with a clear "likely wrong/rotated SETTINGS_ENC_KEY (affects ALL credentials)"
   message, then returns `None` as before — the return contract is unchanged so
   no caller breaks; only the silence is removed. The ciphertext is never logged.
2. **list_connections() reflects real usability**, not row-existence:
   `connected` is true only if the access OR refresh token actually decrypts; it
   adds a `status` field (`ok` | `token_unreadable` | `no_token`). A healthy
   connection (the norm — tokens decrypt) is UNCHANGED (`connected:true`). Only a
   genuinely broken row flips to `connected:false` + `status:"token_unreadable"`,
   which is more accurate (that connection was already unusable) and gives the UI
   the correct "reconnect" path. Still returns NO token material.
   - **Why not a live provider ping?** The brief says "where feasible / at minimum
     surface decrypt failure." A network call per provider on a status endpoint
     would be slow, rate-limit-prone, and could have side effects — out of scope.
     Decryptability is the feasible, side-effect-free liveness signal and catches
     the exact failure mode named in the brief (key rotation). Expiry-based
     liveness is deliberately NOT folded into `connected` (avoids false-negatives
     on the expired-access-but-valid-refresh case) — noted as a possible future.
3. **Frontend untouched** (Item 2 = backend deploy only). The extra `status` field
   is ignored by the current `OAuthConnection` type at runtime; `connected:false`
   on a broken grant renders the existing "connect" affordance — correct UX.

### Files changed (Item 2)
- `backend/app/core/crypto.py` — `decrypt()` logs InvalidToken (module logger), same `None` return.
- `backend/app/services/oauth_tokens.py` — `list_connections()` decrypts to test usability, adds `status`.
- `backend/tests/test_crypto.py` — NEW (3 tests: roundtrip, silent-None on empty, logged-warning on garbage).
- `backend/tests/test_oauth_connections.py` — updated leak test for new shape + 2 new (token_unreadable, no_token).

**Tests:** full suite **309 passed** (304 + 5 new). No migrations.

**Rollback point (Item 2):** `dba1a58` (post-Item-1). Undo: `git revert baaa3c7 && git push && railway up backend --path-as-root --service backend --ci`.

**Deploy + verify (Item 2):** committed `baaa3c7` → pushed origin/main → `railway up backend` → build SUCCESS, active deployment UTC `2026-05-31T21:27:10Z` (Item-1 deploy now REMOVING). `GET /health` → **200 `{"status":"ok"}`**. Decrypt-logging + connection-status behavior proven by the 5 hermetic tests (a live key-rotation test on prod is not safe/feasible).

---

## ITEM 3 — frontend role-UX (hide admin-only controls from employees)

### Diagnosis (read-first)
Role comes from `GET /api/me` (`role` ∈ org_admin | super_admin | employee). Only
`SettingsPage` checked it (restricted panel since `9715518`); every other admin
surface rendered its mutation controls to everyone and relied on the backend 403.
Inventoried surfaces (Explore agent): EmployeesPage, KikiZentralePage,
Invoices(+form), CostEstimates(+form), Catalog (4 tabs), the sidebar nav, and the
profile dropdown's "Firmeneinstellungen".

### Design decisions
1. **Shared hook** `lib/useMe.ts` → `{ me, role, isAdmin, isLoading }`
   (`isAdmin = org_admin || super_admin`). Wraps the existing shared `['me']`
   query (same key ProtectedRoute primes), so no extra fetch. Backend stays the
   source of truth — this is cosmetic; **no backend gate was loosened**.
2. **Page-gate** the wholly-admin surfaces (restricted "Nur für Administratoren"
   panel, mirroring SettingsPage) + hide their nav links: **EmployeesPage** and
   **KikiZentralePage**.
   - *EmployeesPage judgment call:* it's mixed — the absence tabs use `require_org`,
     but `list_all_absences` is an all-employees management view and employee
     self-service absences ("Part C") were **deferred** (commit `63d6459`); the
     roster also exposes sensitive HR data (hourly rates, vacation balances). So I
     treat the whole page as admin-only for now. **If Amber wants employee
     self-service absences, that's the deferred Part C — carve the absence tabs
     out of the gate then.**
3. **Hide only the mutations** on the read-valuable pages (employees keep read
   access; backend GETs are `require_org`): **Invoices**, **CostEstimates**,
   **Catalog** (all 4 tabs) — create/import/edit/delete/duplicate/status/send all
   behind `{isAdmin && …}`; PDF preview/download + CSV export stay. Invoice
   `StatusSelect` gained a `readOnly` mode (employees see the status badge, can't
   change it). Form pages (Invoice/CostEstimate) hide save/send for deep-link
   safety (employees can still view via the list's PDF preview).
4. **Sidebar/nav**: added `adminOnly` to `NavLeaf` (marks `/employees`); Sidebar
   filters admin-only leaves/empty groups, and gates the Kiki-Zentrale link +
   "Firmeneinstellungen" dropdown item on `isAdmin`.

### Files changed (Item 3)
- `frontend/src/lib/useMe.ts` — NEW shared hook.
- `frontend/src/components/layout/nav.ts` — `adminOnly` flag on `/employees`.
- `frontend/src/components/layout/Sidebar.tsx` — filter nav by role; gate Kiki-Zentrale + Settings dropdown.
- `frontend/src/pages/EmployeesPage.tsx`, `KikiZentralePage.tsx` — page-level restricted panel.
- `frontend/src/pages/InvoicesPage.tsx` — gate create + row mutations; `StatusSelect` readOnly mode.
- `frontend/src/pages/CostEstimatesPage.tsx` — gate create + row mutations.
- `frontend/src/pages/CatalogPage.tsx` — gate create/import + per-row edit/delete across all 4 tabs.
- `frontend/src/pages/InvoiceFormPage.tsx`, `CostEstimateFormPage.tsx` — gate save/send footer.

### Tests / verification
- **Build:** `npm run build` (`tsc -b` + vite) → **green** (only the pre-existing 1.75 MB chunk-size warning). No frontend test runner exists (didn't add one overnight).
- **Live A/B render proof** (preview MCP, logged in as `kikitest01` org_admin against local backend; role flipped via React Query `['me']` cache injection — no auth/data mutation):
  - Sidebar: admin → Mitarbeiter + Kiki-Zentrale present; employee → both gone.
  - `/invoices`: admin → "+ Neue Rechnung" + 3 status-selects + 8 action icons; employee → create hidden, 0 selects (read-only badge), 0 action icons, 6 preview/download icons kept.
  - `/catalog` (employee): "Neue Position"/"CSV Import" hidden, "CSV Export" kept, 0 row edit/delete icons.
  - `/kiki-zentrale` + `/employees` (employee): "Nur für Administratoren" restricted panel, no forms/create.
  - 0 console errors. Cache restored to org_admin afterward.

**Rollback point (Item 3):** `baaa3c7` (post-Item-2). Undo: `git revert 86a9eb3` + `railway up frontend …`.

**Deploy + verify (Item 3):** committed `86a9eb3` → pushed origin/main → `railway up frontend --path-as-root --service frontend --ci` → build SUCCESS, active deployment UTC `2026-05-31T21:50:27Z` (prior REMOVED). `GET /` → **200**, `/admin` → **200**. New bundle `index-CtFaU-vW.js` (hash differs from the local build's `index-BrN3tGUu.js` because Railway rebuilds with the prod `VITE_API_URL` baked in; CSS hash `index-DG8T93hD.css` matches). **Confirmed my code is live:** the deployed bundle contains the Item-3-unique restricted-panel string "Mitarbeiterverwaltung ist nur für Administratoren".

---

## ITEM 4 — Redis cache + observability (BUILD-ONLY — NOT DEPLOYED)

> ⚠️ This item is committed to the tree (review-ready) but **NOT deployed** and
> **no live Redis was provisioned**. It is INERT in production until Amber sets
> the env vars below. See "Provisioning + deploy" at the end of this section.

### Safety model (why this is safe to merge but waits to enable)
The flagged risk is cross-org stale-data. Three structural guarantees:
1. **Disabled by default.** `REDIS_URL` empty (the default) ⇒ the cache layer is a
   no-op: every `get_or_set` just calls the loader, every `invalidate` is a no-op.
   So merging + a future deploy changes NOTHING until Redis is configured.
   Observability middleware is likewise gated by `OBSERVABILITY_ENABLED` (default
   off). Both ship dormant.
2. **Org-scoped keys ONLY.** The cache public API *requires* `org_id` and namespaces
   every key as `kj:org:{org_id}:{name}`. There is no API to read/write a key
   without an org_id ⇒ one org's cache can never be served to another. A falsy
   org_id short-circuits to "disabled" (never caches globally).
3. **Fail-open.** Any Redis error (down, timeout, bad reply) is logged and treated
   as a miss/no-op — a cache problem never breaks a request or serves wrong data.

### Caching strategy (proposed)
- **What's cached (reference, wired + dormant):** `me._org_name(org_id)` — the
  white-label company name read on every page load (sidebar + /api/me). Single
  writer (`PATCH /api/settings/general`), so invalidation is unambiguous. TTL 300s.
  This is the *pattern reference*; it's tiny but demonstrates read-cache +
  write-invalidation + org-keying end-to-end.
- **Recommended next targets (NOT wired — enable under supervision, each needs the
  listed invalidation):**
  - `GET /api/settings` (org + email/pds config + usage) — TTL 120s; invalidate on
    every `/api/settings/*` write (general/design/google-reviews/logo/ai-suggestions/
    email-config/pds-config). Higher write-surface ⇒ wire carefully.
  - `appointment_categories` list — TTL 300s; invalidate on category create/update/delete.
  - `catalog` / `text-modules` / `vehicles` / `tools` lists — TTL 120–300s; invalidate
    on the matching create/update/delete.
  - **Do NOT cache dashboard aggregations** without short TTL + accept-staleness sign-off:
    the numbers change on every call/inquiry/appointment; stale = wrong KPIs.
- **Invalidation rule:** every write that changes a cached entity calls
  `cache.invalidate(org_id, name)` (or `cache.invalidate_org(org_id)` for a blanket
  per-org flush). Keep the read-key and its invalidation in the same review.
- **Keying:** `kj:org:{org_id}:{name}` (prefix configurable via `CACHE_PREFIX` to
  separate staging/prod if they ever share a Redis). JSON-serialized values.

### Observability / logging approach (proposed)
- `core/logging_config.py::configure_logging()` — JSON-line formatter (one object
  per log: ts, level, logger, msg, request_id + any extras) so logs are greppable
  and traceable per request.
- `core/observability.py::RequestContextMiddleware` — assigns/reads an
  `X-Request-ID` per request (contextvar so every log line in that request carries
  it), times the request, logs method/path/status/duration_ms, echoes
  `X-Request-ID` back. Auth/session/request paths log with the shared request_id so
  a bug is traceable end-to-end.
- Both are wired into `main.py` **gated by `OBSERVABILITY_ENABLED`** (default off).

### Files (Item 4)
- `backend/app/core/cache.py` — NEW org-scoped cache (disabled-by-default, fail-open, injectable client).
- `backend/app/core/logging_config.py` — NEW JSON-line formatter (ts/level/logger/msg/request_id + access extras).
- `backend/app/core/observability.py` — NEW request-context middleware + `request_id` contextvar.
- `backend/app/core/config.py` — `redis_url`, `cache_prefix`, `cache_default_ttl`, `observability_enabled` (all credential-free defaults).
- `backend/app/main.py` — register middleware + JSON logging **only if `observability_enabled`** (default off).
- `backend/app/api/routes/me.py` — `_org_name` reads through `cache.get_or_set` (reference target).
- `backend/app/api/routes/settings.py` — `_update_org` calls `cache.invalidate(org_id, "org_name")`.
- `backend/requirements.txt` — `redis==5.2.1` (lazy-imported only when REDIS_URL set).
- `backend/tests/test_cache.py` (8) + `backend/tests/test_observability.py` (6) — NEW.
- `REDIS_OBSERVABILITY_SETUP.md` — NEW provisioning + deploy + rollback doc.

### Tests / verification (hermetic — no live Redis, no deploy)
- Full suite **323 passed** (309 + 14 new). Cross-org isolation test included.
- Integration sanity (local, not deployed): `OBSERVABILITY_ENABLED=1` → app boots, `RequestContextMiddleware` registered, `GET /health` 200 + `X-Request-ID` header, JSON access log emitted with `request_id`. Cache with `REDIS_URL` set but `redis` lib absent → init fails open ("caching disabled"), `enabled()=False`, `get_or_set` runs the loader. **No deploy, no Redis provisioned, no credentials committed.**

### Provisioning + deploy steps (for Amber) — full detail in `REDIS_OBSERVABILITY_SETUP.md`
1. **Observability (safe, independent of Redis):** set backend env `OBSERVABILITY_ENABLED=1` → redeploy backend → verify `/health` 200 + `X-Request-ID` + JSON logs.
2. **Redis:** Railway → add Redis DB → on backend service set `REDIS_URL=${{Redis.REDIS_URL}}` (reference var, never literal) → redeploy. Reference cache (`org_name`) activates; verify rename-company invalidates immediately.
3. **Roll out more targets one at a time**, each with its invalidation wired (settings, appointment_categories, catalog/text-modules/vehicles/tools). **Don't cache dashboard KPIs** (volatile).
- **Disable/rollback:** unset `REDIS_URL` (cache dormant) / `OBSERVABILITY_ENABLED=0` (middleware off) / `git revert 2e80b19`.

**Why it waits (one-way-door avoidance):** caching is correct only with complete invalidation; the reference target is single-writer (safe), the higher-value targets are multi-writer. Enabling them is your call after reviewing the invalidation wiring. The layer ships **dormant** so merging it changes nothing in prod until you set the env vars.

---
---

# FOLLOW-UP SESSION — 2026-06-01 (daytime) — Item A + Item B

| Item | Scope | Status |
|------|-------|--------|
| A | Employee absence self-service + admin approval | ✅ DONE + DEPLOYED (`310019f`, backend+frontend) |
| B | Enable + verify the Redis cache (Item 4's layer) | ✅ DONE — ENABLED + verified live on prod |

## ITEM A — absence self-service + approval (DEPLOYED)
**Read-first (workflow + direct):** the existing absence surface was ALL admin (create-for-any-employee, all-employees calendar, stub "Anträge" tab); `employee_absences` had NO status column; **and a real gap** — `POST /{employee_id}/absences` (require_org) took employee_id from the URL, so any org member could file an absence for any colleague.

**Migration (ADDITIVE, applied + flagged):** `0035_employee_absence_status.sql` — `employee_absences` += `status` ('pending'|'approved'|'rejected', default 'approved' so existing/admin rows stay in effect), `reviewed_by`, `reviewed_at`, + `(org_id,status)` index. Inert under old code.

**Backend (`employees.py`, `schemas/admin.py`, `tests/test_absence_workflow.py`):**
- `POST/GET /api/employees/me/absences` (require_org) — employee applies for / lists their OWN absence; employee_id resolved from the caller's user (NEVER the request); apply → 'pending'.
- `GET /absences/pending` + `POST /absences/{id}/approve|reject` (require_org_admin) — admin review; stamps status + reviewed_by/at; org-scoped (cross-org → 404).
- Tightened `POST /{employee_id}/absences`, `GET /absences`, `GET /{employee_id}/absences` → require_org_admin (closes the cross-user gap; admin-created = approved).
- Roster `GET /api/employees` now **strips HR fields** (hourly_rate, vacation balances, email, access_role…) for non-admins — keeps names/colors for assignment dropdowns/calendars but no colleague HR data.
- Presence calc counts only APPROVED absences. **+11 tests; suite 328 passed.**

**Frontend:** new `MyAbsencePage` (`/meine-abwesenheit`, nav-visible to all) — apply modal + own-requests list with status badges. `EmployeesPage` Anträge tab implemented (pending list + Genehmigen/Ablehnen). EmployeesPage stays admin-only (HR data never employee-visible). `tsc -b`+vite green.

**Gating decision:** chose a **dedicated employee page** over carving into EmployeesPage — same outcome (employees self-serve absences; HR data + management stay admin-only) with structurally guaranteed HR-data isolation.

**Deploy + verify:** committed `310019f` → pushed → `railway up backend` (4 new routes live, /health 200, 156 paths) → `railway up frontend` (bundle `index-BhFIoBJe.js`, `/meine-abwesenheit` 200, Item-A string in bundle). **Live end-to-end on kiki-test-007** (reversible test employee, since cleaned up): employee applied → 'Ausstehend' → admin Anträge → Genehmigen → DB `approved`+reviewer stamped → employee view 'Genehmigt'. Hermetic tests cover can't-approve / can't-see-HR / cross-org-404.

**Rollback (Item A):** `git revert 310019f` + redeploy backend+frontend. Migration 0035 is additive/inert under old code (no down-migration needed).

## ITEM B — Redis cache ENABLED + verified (PROD)
**Stale-data audit (required pre-flight):** ONLY cached value = `org_name` (in `me._org_name`). ONLY writer of `organizations.name` = `settings._update_org`, which invalidates. Grepped every `organizations.update` site — super_admin (agent_provisioned_at), kiki_zentrale (existing_business_number), agent_config (phone/provisioned_at), settings logo (logo_url) — **none touch `name`**. ⇒ nothing cached can go stale.

**Enabled:** provisioned Railway Redis (service `Redis`), set backend `REDIS_URL=${{Redis.REDIS_URL}}` (reference, not literal) + `OBSERVABILITY_ENABLED=1`; Railway auto-redeployed (SUCCESS 07:54:08Z).

**Live verification (prod, Redis connected):**
- **Connected + serving:** direct DB name change (bypassing invalidation) → `GET /api/me` returned the OLD cached value ⇒ cache genuinely serving from Redis.
- **Write-then-read-fresh:** API `PATCH /settings/general {name}` (invalidates) → `GET /api/me` returned the NEW value ⇒ invalidation works. Original name restored (DB confirmed clean).
- **Cross-org:** keys `kj:org:{org_id}:org_name`; structurally impossible to bleed + hermetic test. (No two-org live dump — would need the secret REDIS_URL / a 2nd org login.)
- **Fail-open:** hermetic RaisingRedis test + local "redis lib absent → disabled, loader runs"; not induced on prod.
- **Observability:** `X-Request-ID` header live on prod; JSON logs with request_id.

**No code change for Item B** (enable+verify of `2e80b19`). **Rollback (Item B):** unset `REDIS_URL` (cache dormant, instant) and/or `OBSERVABILITY_ENABLED=0`.

**CLEANUP DONE:** the duplicate unused Redis `Redis-N6Fl` (`ca9950c3-…`) was **deleted** (`railway service delete --service ca9950c3… --yes`, on Amber's explicit approval). Only the in-use `Redis` (`a6737691-…`) remains; the cache was **re-verified connected after deletion** (post-delete stale-probe still served the cached value; org name restored, DB clean).
