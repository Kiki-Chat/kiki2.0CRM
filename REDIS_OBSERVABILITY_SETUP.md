# Redis cache + observability — provisioning & deploy (Item 4)

> **Status: BUILT, NOT DEPLOYED, NOT PROVISIONED.** This layer is committed to the
> tree but ships **dormant**: it does nothing in production until you set the env
> vars below. Built overnight 2026-06-01; left for your supervision because
> caching on a multi-tenant system risks cross-org stale data if mis-wired.

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
- Code: `git revert <item4-sha>` if you want it out of the tree entirely.

## Tests
`backend/tests/test_cache.py` (cross-org isolation, get_or_set, invalidation,
per-org flush, fail-open, disabled no-op) and `backend/tests/test_observability.py`
(request-id generate/echo, access log, JSON formatter). All hermetic — no live
Redis needed.
