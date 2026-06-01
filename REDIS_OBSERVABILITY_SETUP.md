# Redis cache + observability — provisioning & deploy (Item 4)

> **Status: ENABLED IN PRODUCTION 2026-06-01 (Item B).** Redis is provisioned
> (Railway service `Redis`), the backend has `REDIS_URL=${{Redis.REDIS_URL}}` +
> `OBSERVABILITY_ENABLED=1`, and it was verified live (see "Item B verification"
> below). The steps below are retained as the reference/runbook.
>
> **Cleanup DONE:** my provisioning retries had created a second, unused Redis
> service `Redis-N6Fl`; it was **deleted** (`railway service delete`, on your
> explicit approval). Only the in-use `Redis` (`a6737691-…`, referenced by the
> backend's `${{Redis.REDIS_URL}}`) remains — and the cache was **re-verified
> connected after the deletion** (stale-probe still served the cached value).
>
> ## Item B verification (2026-06-01, live on prod, Redis connected)
> - **Connected + serving:** changed `organizations.name` for kiki-test-007
>   directly in the DB (bypassing invalidation) → `GET /api/me` returned the OLD
>   cached name → the cache is genuinely serving from Redis (not hitting DB).
> - **Write-then-read-fresh:** `PATCH /api/settings/general {name}` (the sole
>   writer, which calls `cache.invalidate(org_id,"org_name")`) → `GET /api/me`
>   returned the NEW name immediately → invalidation works. Restored the original
>   name afterward (DB confirmed clean).
> - **Cross-org:** every key is `kj:org:{org_id}:org_name`; the live read returned
>   THIS org's value for THIS org's key. Cross-org bleed is structurally impossible
>   (org_id in every key) + covered by the hermetic isolation test. (A two-org live
>   dump would need the secret REDIS_URL / a second org login — not done.)
> - **Fail-open:** covered by the hermetic RaisingRedis test + the local
>   "redis lib absent → caching disabled, loader runs" check; not induced on prod.
> - **Observability:** `GET /health` now returns an `X-Request-ID` header and logs
>   are JSON lines carrying `request_id`.
>
> **Stale-data audit (what's cached + invalidation map):** the ONLY cached value is
> `org_name` (read in `me._org_name`). The ONLY writer of `organizations.name` is
> `settings._update_org` (PATCH /settings/general), which invalidates it. Verified
> by grep that no other path (super_admin, kiki_zentrale, agent_config, settings
> logo, provisioning) writes `name`. So nothing cached can be served stale.

---

> **Original (pre-Item-B) status — BUILT, NOT DEPLOYED, NOT PROVISIONED** — kept for history:
> This layer was committed dormant overnight 2026-06-01 (Item 4); Item B enabled it.

## What it is
- **`app/core/cache.py`** — an org-scoped Redis cache. Every key is
  `kj:org:{org_id}:{name}`; the API *requires* `org_id`, so one tenant's cache can
  never be served to another. Disabled (pure no-op) until `REDIS_URL` is set;
  fail-open (any Redis error → cache miss, request never breaks).
- **`app/core/logging_config.py` + `app/core/observability.py`** — JSON-line logs
  + a request-context middleware (per-request `X-Request-ID`, timing, access log).
  Off until `OBSERVABILITY_ENABLED=1`.
- **Reference cache usage (dormant):** `me._org_name` is cached; `settings._update_org`
  invalidates it. This is the *pattern*; no other route is cached yet.

## Why it waits for you
Caching is correct only if invalidation is complete. The reference target
(`org_name`, one writer) is safe, but the higher-value targets below each have
multiple writers — enabling them means wiring an `invalidate(...)` at *every*
write. Stale data is the failure mode. Review the targets, then enable
incrementally.

## To provision + enable (under your supervision)

### 1. Provision Redis on Railway
- Railway dashboard → project `kikijarvis-backend` → **New → Database → Add Redis**
  (or "Deploy Redis" template). Railway creates a Redis service with a private
  `REDIS_URL` variable.
- On the **backend** service → Variables → add a reference variable
  `REDIS_URL` = `${{Redis.REDIS_URL}}` (Railway's private networking; do NOT paste
  the URL literally and never commit it — it carries a password).

### 2. Turn on observability (independent of Redis; safe to do first)
- Backend service → Variables → `OBSERVABILITY_ENABLED` = `1`.
- Redeploy backend (`railway up backend --path-as-root --service backend --ci`).
- Verify: `GET /health` returns 200 with an `X-Request-ID` response header, and
  the Railway logs are now JSON lines carrying `request_id`.

### 3. Turn on caching (after Redis is provisioned)
- With `REDIS_URL` set, redeploy backend. The `redis` package is already in
  `requirements.txt`.
- Verify: hit any page twice; the second `/api/me` should not re-query the org row
  (watch logs). Rename the company via Settings → confirm the new name shows
  immediately (invalidation works).
- Optional knobs: `CACHE_PREFIX` (default `kj`), `CACHE_DEFAULT_TTL` (default 300s).

### 4. Roll out more cache targets (one at a time, each with invalidation)
Recommended order + the writes that MUST invalidate:
- `GET /api/settings` (TTL 120s) — invalidate on every `/api/settings/*` write
  (general/design/google-reviews/logo/ai-suggestions/email-config/pds-config) **and**
  on super-admin org edits.
- `appointment_categories` list (TTL 300s) — invalidate on category create/update/delete.
- `catalog` / `text-modules` / `vehicles` / `tools` lists — invalidate on the matching writes.
- **Do not cache dashboard KPIs** without a short TTL + accepting some staleness.

## Rollback / disable
- Caching: unset `REDIS_URL` (or remove the Redis service) → layer goes dormant
  instantly; no code change.
- Observability: set `OBSERVABILITY_ENABLED=0` → middleware not registered.
- Code: `git revert 2e80b19` if you want it out of the tree entirely.

## Tests
`backend/tests/test_cache.py` (cross-org isolation, get_or_set, invalidation,
per-org flush, fail-open, disabled no-op) and `backend/tests/test_observability.py`
(request-id generate/echo, access log, JSON formatter). All hermetic — no live
Redis needed.
