# SECURITY OBSERVATION REPORT — KikiJarvis CRM

*Observations only — no fixes proposed (per audit scope). Generated 2026-06-17 from static analysis; the final section adds live Supabase advisor findings. Confirm before acting.*

## Severity Summary

| CRITICAL | HIGH | MEDIUM | LOW | INFO | Total |
|---|---|---|---|---|---|
| 0 | 2 | 10 | 10 | 3 | 25 |

## Observations (sorted by severity)

| ID | Title | Category | Severity | Affected Files | Conf | Verified |
|---|---|---|---|---|---|---|
| `SEC-003` | 7 tables missing RLS entirely — direct Supabase-JS access would be unrestricted | BrokenAccessControl | **HIGH** | supabase/migrations/0028_oauth_connections.sql<br>supabase/migrations/0029_outbound_calls.sql<br>supabase/migrations/0031_maintenance_plans.sql<br>supabase/migrations/0032_missed_calls.sql<br>supabase/migrations/0034_oauth_purpose_links.sql<br>supabase/migrations/0054_action_tasks.sql<br>supabase/migrations/0055_vorgang_threading.sql | 97 | CODE-ONLY |
| `SEC-006` | Stripe webhook secret not checked at startup in production when billing is enabled | AuthN | **HIGH** | backend/app/core/config.py:198-211<br>backend/app/services/stripe_webhook.py:73 | 75 | RUNTIME-NEEDED |
| `SEC-001` | Timing-unsafe shared-secret comparison in webhook gates | AuthN | **MEDIUM** | backend/app/api/deps.py:131<br>backend/app/api/deps.py:141 | 80 | CODE-ONLY |
| `SEC-002` | resolve_tool_org does not check org disabled_at — disabled orgs can still receive calls | AuthZ | **MEDIUM** | backend/app/api/deps.py:154-177<br>backend/app/api/deps.py:180-206 | 95 | CODE-ONLY |
| `SEC-004` | copilot_conversations and copilot_messages tables created without RLS in migration 0062 | BrokenAccessControl | **MEDIUM** | supabase/migrations/0062_copilot_conversations.sql:1-33 | 70 | CODE-ONLY |
| `SEC-005` | Customer search query parameter interpolated directly into PostgREST filter string — PostgREST injection risk | Injection | **MEDIUM** | backend/app/api/routes/customers.py:84-86<br>backend/app/api/routes/customers.py:347-349<br>backend/app/api/routes/catalog.py:33 | 65 | RUNTIME-NEEDED |
| `SEC-008` | Public technician photo upload has no rate limiting and no file content validation | RateLimit | **MEDIUM** | backend/app/api/routes/public_jobs.py:45-58<br>backend/app/services/technician_jobs.py:255-307 | 90 | CODE-ONLY |
| `SEC-009` | Technician portal tokens never expire | AuthN | **MEDIUM** | supabase/migrations/0066_technician_phone_portal.sql:9-17<br>backend/app/services/technician_jobs.py:74-149 | 95 | CODE-ONLY |
| `SEC-010` | ElevenLabs conversation-init org resolution falls back to unguessable agent_id — weak auth for agent-id-only deployments | AuthN | **MEDIUM** | backend/app/api/deps.py:154-177<br>backend/app/api/deps.py:180-206 | 80 | CODE-ONLY |
| `SEC-015` | Billing checkout (plan subscribe) accessible to plain employees — privilege escalation | PrivEsc | **MEDIUM** | backend/app/api/routes/billing.py:288-292<br>backend/app/api/routes/billing.py:338-340 | 85 | CODE-ONLY |
| `SEC-016` | Authentication failures produce no audit log entries | AuditLogging | **MEDIUM** | backend/app/api/deps.py:22-43<br>backend/app/api/deps.py:123-145<br>backend/app/api/deps.py:199-206 | 95 | CODE-ONLY |
| `SEC-024` | require_org calls get_service_client() directly (not in threadpool) for disabled-org check | Concurrency | **MEDIUM** | backend/app/api/deps.py:66-90 | 88 | CODE-ONLY |
| `SEC-007` | JWKS fetched synchronously with blocking httpx.get in JWT verification hot path | Concurrency | **LOW** | backend/app/core/security.py:19-30<br>backend/app/core/security.py:33-61 | 70 | RUNTIME-NEEDED |
| `SEC-011` | In-process rate limiter lost on restart and bypassed by horizontal scale | RateLimit | **LOW** | backend/app/services/ratelimit.py:1-50<br>backend/app/api/routes/copilot.py:160<br>backend/app/api/routes/kiki_zentrale.py:961-962<br>backend/app/api/routes/cases.py:146-147 | 90 | CODE-ONLY |
| `SEC-012` | FastAPI /docs and /openapi.json publicly accessible with no authentication | ExposedAPI | **LOW** | backend/app/main.py:84 | 98 | CODE-ONLY |
| `SEC-013` | delete_organization uses require_org (not require_org_admin) as outer Depends with inline role check | AuthZ | **LOW** | backend/app/api/routes/settings.py:373-378 | 85 | CODE-ONLY |
| `SEC-014` | _require_admin in kiki_zentrale rejects super_admin — inconsistent role model | AuthZ | **LOW** | backend/app/api/routes/kiki_zentrale.py:55-59<br>backend/app/api/deps.py:115 | 90 | CODE-ONLY |
| `SEC-017` | CORS policy uses env-configured origin list but allows credentials — misconfiguration risk | CORS | **LOW** | backend/app/main.py:112-118<br>backend/app/core/config.py:31 | 60 | RUNTIME-NEEDED |
| `SEC-018` | JWKS cache is a module-level global with no thread lock — potential race on first population | RaceCondition | **LOW** | backend/app/core/security.py:12-30 | 75 | RUNTIME-NEEDED |
| `SEC-020` | No input length validation on free-text fields in customer search and job report submission | MissingValidation | **LOW** | backend/app/api/routes/customers.py:300-308<br>backend/app/services/technician_jobs.py:326-333 | 72 | CODE-ONLY |
| `SEC-022` | Crypto decrypt failure is silent None — callers may proceed without credentials | SecretHandling | **LOW** | backend/app/core/crypto.py:45-66 | 85 | CODE-ONLY |
| `SEC-025` | Photo upload path stored in Supabase storage is not validated to remain within org scope | DataIntegrity | **LOW** | backend/app/services/technician_jobs.py:267-270 | 40 | RUNTIME-NEEDED |
| `SEC-019` | Sensitive field `smtp_password` visible in API request body schema via /openapi.json | DataExposure | **INFO** | backend/app/api/routes/settings.py:75<br>backend/app/api/routes/settings.py:259-273 | 80 | CODE-ONLY |
| `SEC-021` | Service-role Supabase key is a singleton cached globally — key rotation requires restart | SecretHandling | **INFO** | backend/app/db/supabase_client.py:9-54 | 90 | CODE-ONLY |
| `SEC-023` | No per-user (user_id) scoping in rate limiter — org-level only | RateLimit | **INFO** | backend/app/services/ratelimit.py:24-44 | 75 | CODE-ONLY |

## Detail

### `SEC-003` — 7 tables missing RLS entirely — direct Supabase-JS access would be unrestricted  ·  HIGH / BrokenAccessControl

Seven tables have no Row Level Security enabled at the Supabase layer: oauth_connections, outbound_calls, maintenance_plans, missed_calls, oauth_purpose_links, action_tasks, case_links. The service-role backend key bypasses RLS, so backend-mediated access is correctly scoped. However, if the anon or authenticated Supabase keys were ever used client-side (inadvertent exposure of SUPABASE_ANON_KEY, misconfigured frontend), these tables would be fully readable and writable by any authenticated user across all organizations. oauth_connections is particularly sensitive as it contains Fernet-encrypted OAuth access and refresh tokens.

- **Affected:** supabase/migrations/0028_oauth_connections.sql, supabase/migrations/0029_outbound_calls.sql, supabase/migrations/0031_maintenance_plans.sql, supabase/migrations/0032_missed_calls.sql, supabase/migrations/0034_oauth_purpose_links.sql, supabase/migrations/0054_action_tasks.sql, supabase/migrations/0055_vorgang_threading.sql
- **Evidence:** Python scan of all migrations confirms zero `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` statements for these 7 tables in any migration file.
- **Confidence:** 97 · **Verified:** CODE-ONLY

### `SEC-006` — Stripe webhook secret not checked at startup in production when billing is enabled  ·  HIGH / AuthN

When STRIPE_BILLING_ENABLED=1 and STRIPE_WEBHOOK_SECRET is empty, the Stripe webhook endpoint is mounted and active. stripe.Webhook.construct_event() called with an empty `settings.stripe_webhook_secret` will raise a ValueError (or silently accept all requests depending on stripe-python version behavior). validate_runtime_config only checks STRIPE_WEBHOOK_SECRET when STRIPE_SECRET_KEY starts with 'sk_live'. Using a test key with an empty webhook secret leaves the webhook unprotected. An attacker can send forged Stripe events (e.g., subscription.created, invoice.paid) to manipulate org billing state.

- **Affected:** backend/app/core/config.py:198-211, backend/app/services/stripe_webhook.py:73
- **Evidence:** config.py:198 — the `STRIPE_WEBHOOK_SECRET` validation only triggers when `stripe_secret_key.startswith('sk_live')`. With a test key and empty secret, `stripe.Webhook.construct_event(raw_body, sig_header, '')` behavior depends on the stripe-python library version.
- **Confidence:** 75 · **Verified:** RUNTIME-NEEDED

### `SEC-001` — Timing-unsafe shared-secret comparison in webhook gates  ·  MEDIUM / AuthN

Both verify_post_call_secret and verify_master_secret compare secrets using Python's `in` (set membership) and `!=` operators respectively. These are not constant-time operations. An attacker who can time many requests could theoretically extract the secret character by character via a timing side-channel. The risk is partially mitigated by network jitter in a cloud deployment, but best practice is secrets.compare_digest.

- **Affected:** backend/app/api/deps.py:131, backend/app/api/deps.py:141
- **Evidence:** Line 131: `if not x_heykiki_secret or x_heykiki_secret not in allowed:` — set membership is not constant-time. Line 141: `if not x_heykiki_secret or x_heykiki_secret != settings.master_webhook_secret:` — string inequality is not constant-time.
- **Confidence:** 80 · **Verified:** CODE-ONLY

### `SEC-002` — resolve_tool_org does not check org disabled_at — disabled orgs can still receive calls  ·  MEDIUM / AuthZ

require_org (line 73–90 deps.py) checks organizations.disabled_at and blocks access for disabled orgs. However, resolve_tool_org (line 180–206) only looks up org_id via org_secrets or elevenlabs_agent_id and never consults disabled_at. Consequently, an org that has been disabled via the super-admin panel will still receive and process ElevenLabs inbound calls, create inquiries, book appointments, etc.

- **Affected:** backend/app/api/deps.py:154-177, backend/app/api/deps.py:180-206
- **Evidence:** `_lookup_org_id` queries only `org_secrets` and `organizations.elevenlabs_agent_id` with no `disabled_at` filter. The `require_org` function at line 78 does fetch and enforce `disabled_at`, but this code path is never called from ElevenLabs tool webhooks.
- **Confidence:** 95 · **Verified:** CODE-ONLY

### `SEC-004` — copilot_conversations and copilot_messages tables created without RLS in migration 0062  ·  MEDIUM / BrokenAccessControl

Migration 0062_copilot_conversations.sql creates copilot_conversations and copilot_messages with `create table if not exists` but adds no `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`. Migration 0042 does create these tables WITH RLS, so on an existing DB the 0062 migration is a no-op and RLS from 0042 applies. However, on a fresh database where 0042 ran first and 0062 ran second (both use IF NOT EXISTS so the second create is skipped), RLS is in place. The risk is low for existing setups but the 0062 migration is misleading and lacks RLS defensively.

- **Affected:** supabase/migrations/0062_copilot_conversations.sql:1-33
- **Evidence:** 0062 creates both tables with `create table if not exists` but has no `enable row level security`. 0042 does enable RLS for these tables, so production instances are protected. But the 0062 migration is a maintenance hazard.
- **Confidence:** 70 · **Verified:** CODE-ONLY

### `SEC-005` — Customer search query parameter interpolated directly into PostgREST filter string — PostgREST injection risk  ·  MEDIUM / Injection

The search query parameter `q` from customer list and export endpoints is interpolated directly into a PostgREST filter string using an f-string: `f"full_name.ilike.%{q}%,..."`. PostgREST parses this filter string server-side. A maliciously crafted `q` value containing PostgREST filter syntax (commas, parentheses, operators) could manipulate the filter predicate. For example, `q=test%,or(id.neq.null` might inject an `or(id.neq.null)` clause depending on PostgREST parsing. The same pattern appears in catalog search.

- **Affected:** backend/app/api/routes/customers.py:84-86, backend/app/api/routes/customers.py:347-349, backend/app/api/routes/catalog.py:33
- **Evidence:** `query.or_(f"full_name.ilike.%{q}%,phone.ilike.%{q}%,email.ilike.%{q}%,customer_number.ilike.%{q}%")` — the value of `q` is inserted verbatim into a PostgREST filter expression without sanitization or escaping of PostgREST metacharacters (comma, parenthesis, `.`, `*`).
- **Confidence:** 65 · **Verified:** RUNTIME-NEEDED

### `SEC-008` — Public technician photo upload has no rate limiting and no file content validation  ·  MEDIUM / RateLimit

The unauthenticated POST /api/public/jobs/{token}/photos endpoint accepts file uploads with no rate limiting. Although the token is required, once a valid token is obtained (e.g., by a technician), any party with the token can upload up to 30 photos of 10 MB each (300 MB total per job link). There is no rate limiting per token or per IP. Additionally, MIME type validation relies solely on the client-supplied content-type header (`file.content_type`), which is trivially spoofable — an attacker could upload a PHP/HTML file with `content-type: image/jpeg` and the service stores it in Supabase storage with the spoofed MIME type.

- **Affected:** backend/app/api/routes/public_jobs.py:45-58, backend/app/services/technician_jobs.py:255-307
- **Evidence:** technician_jobs.py:260 — `if not (mime_type or '').startswith('image/'):` — mime_type comes from the client's Content-Type header (file.content_type in the route), not from magic-byte inspection of the file content.
- **Confidence:** 90 · **Verified:** CODE-ONLY

### `SEC-009` — Technician portal tokens never expire  ·  MEDIUM / AuthN

The technician_portal_token (stored in employees.technician_portal_token) is a standing token with no expiry mechanism. Once issued, the token grants permanent access to the technician's full job history. There is no rotation endpoint, no last-used tracking, and no revocation mechanism beyond manually NULLing the column. If a token is compromised (e.g., forwarded screenshot), the attacker retains indefinite access to the technician's job list including customer names, addresses, and phone numbers.

- **Affected:** supabase/migrations/0066_technician_phone_portal.sql:9-17, backend/app/services/technician_jobs.py:74-149
- **Evidence:** Migration 0066 adds `technician_portal_token text` with no `expires_at` column. `get_technician_portal` at line 74 returns customer names, addresses, and appointment details with no expiry check. No rotation or revocation endpoint exists in the codebase.
- **Confidence:** 95 · **Verified:** CODE-ONLY

### `SEC-010` — ElevenLabs conversation-init org resolution falls back to unguessable agent_id — weak auth for agent-id-only deployments  ·  MEDIUM / AuthN

resolve_tool_org (deps.py:180) first attempts X-HeyKiki-Secret header auth, then falls back to resolving org_id from the `_agentId` / `agent_id` field in the request body. ElevenLabs agent IDs are not secret — they are embeddable in phone configs and may appear in ElevenLabs platform logs. An attacker who knows an org's ElevenLabs agent ID can make unauthenticated calls to all ElevenLabs tool webhooks (/identify-customer, /create-appointment, /book-appointment, etc.) by including `_agentId` in the body without supplying a secret header.

- **Affected:** backend/app/api/deps.py:154-177, backend/app/api/deps.py:180-206
- **Evidence:** _lookup_org_id: if secret resolves — uses it. If not, falls back to `organizations.elevenlabs_agent_id` lookup from `body.get('_agentId')`. This means possession of a publicly-observable agent_id grants full tool-webhook access.
- **Confidence:** 80 · **Verified:** CODE-ONLY

### `SEC-015` — Billing checkout (plan subscribe) accessible to plain employees — privilege escalation  ·  MEDIUM / PrivEsc

POST /api/billing/checkout-session is guarded by `require_org` (any authenticated org member), not `require_org_admin`. This allows a plain employee to initiate a Stripe Checkout session to upgrade, downgrade, or change the org's billing plan. While the checkout URL itself is not automatically completed (the user must follow the link and confirm payment), generating a checkout session still exposes the org's Stripe customer_id and creates a pending session that could cause billing confusion. Analogous write endpoints in billing (/api/billing/sync which calls _handle_subscription) are also employee-accessible.

- **Affected:** backend/app/api/routes/billing.py:288-292, backend/app/api/routes/billing.py:338-340
- **Evidence:** billing.py:289-290 — `@router.post('/checkout-session') async def billing_checkout(body: CheckoutRequest, user: CurrentUser = Depends(require_org))` — require_org, not require_org_admin. billing.py:339 — same pattern for /sync.
- **Confidence:** 85 · **Verified:** CODE-ONLY

### `SEC-016` — Authentication failures produce no audit log entries  ·  MEDIUM / AuditLogging

Failed authentication events (invalid/expired JWT in get_current_user, invalid webhook secrets in verify_post_call_secret/verify_master_secret, unresolvable ElevenLabs org in resolve_tool_org) produce no persistent audit log entries. Only Stripe webhook signature failures are logged (billing_security_events table). An ongoing credential-stuffing or brute-force attempt against any webhook endpoint or JWT validation would be invisible in the DB. Application logs (stderr) would contain the FastAPI 422/401 entries, but these are ephemeral in Railway.

- **Affected:** backend/app/api/deps.py:22-43, backend/app/api/deps.py:123-145, backend/app/api/deps.py:199-206
- **Evidence:** No `logger.warning` or DB insert calls in the 401 branches of get_current_user, verify_post_call_secret, verify_master_secret, or resolve_tool_org. Contrast with stripe_webhook.py:46-62 which does log signature failures to billing_security_events.
- **Confidence:** 95 · **Verified:** CODE-ONLY

### `SEC-024` — require_org calls get_service_client() directly (not in threadpool) for disabled-org check  ·  MEDIUM / Concurrency

require_org (deps.py:75-88) is a synchronous FastAPI Depends called from async route handlers. It directly calls `get_service_client().table(...).execute()` — a synchronous network call — from the dependency resolver without run_in_threadpool. This blocks the async event loop for every authenticated request while the org-status DB check completes. Under load, this can stall all concurrent requests. Note: get_current_user correctly wraps its DB call via run_in_threadpool (line 56), but require_org's secondary check does not.

- **Affected:** backend/app/api/deps.py:66-90
- **Evidence:** deps.py:75-85 — `client = get_service_client(); org_rows = client.table('organizations').select('disabled_at').eq('id', user.org_id)...execute()` — executed synchronously inside a non-async function that is called as a Depends from async routes.
- **Confidence:** 88 · **Verified:** CODE-ONLY

### `SEC-007` — JWKS fetched synchronously with blocking httpx.get in JWT verification hot path  ·  LOW / Concurrency

decode_supabase_jwt calls _get_jwks() which uses a blocking httpx.get() call. This function is invoked inside get_current_user which runs in the event loop via run_in_threadpool. However, _get_jwks is also called directly from decode_supabase_jwt which is called from the threadpool. During a JWKS refresh (cache miss), the blocking HTTP call will block a threadpool worker thread. Under sustained load with concurrent JWKS expiry, multiple workers could block simultaneously on the JWKS endpoint, exhausting the thread pool.

- **Affected:** backend/app/core/security.py:19-30, backend/app/core/security.py:33-61
- **Evidence:** `httpx.get(_jwks_url(), timeout=5)` at line 25 is a synchronous blocking HTTP call with a 5-second timeout. Multiple concurrent requests can all hit this path simultaneously when the 300-second TTL expires.
- **Confidence:** 70 · **Verified:** RUNTIME-NEEDED

### `SEC-011` — In-process rate limiter lost on restart and bypassed by horizontal scale  ·  LOW / RateLimit

The rate limiter in ratelimit.py uses in-process Python dict+deque state. On process restart (Railway redeploy), all rate limit windows are reset, allowing a burst of LLM-spend immediately post-deploy. The comment in ratelimit.py acknowledges that horizontal scaling would bypass it. As noted, Railway currently runs one process, but rate limit state is permanently lost on any restart/crash. Additionally, the rate limit only covers copilot_chat (20/60s), rule_generate (6/60s), and cases_propose (6/60s) — other AI-spend endpoints (e.g., /api/kiki-zentrale/context/update, knowledge resource indexing) are unrestricted.

- **Affected:** backend/app/services/ratelimit.py:1-50, backend/app/api/routes/copilot.py:160, backend/app/api/routes/kiki_zentrale.py:961-962, backend/app/api/routes/cases.py:146-147
- **Evidence:** ratelimit.py:6 — `_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)` is a module-level variable that resets on process restart. Comment at line 8-10 explicitly notes horizontal scale limitation.
- **Confidence:** 90 · **Verified:** CODE-ONLY

### `SEC-012` — FastAPI /docs and /openapi.json publicly accessible with no authentication  ·  LOW / ExposedAPI

FastAPI is initialized without `docs_url=None` or `openapi_url=None`, meaning the interactive Swagger UI at /docs and the machine-readable schema at /openapi.json are publicly accessible without authentication. These pages expose the full API surface including all route signatures, request/response schemas, and enum values. While not directly exploitable, they materially aid reconnaissance.

- **Affected:** backend/app/main.py:84
- **Evidence:** `app = FastAPI(title='HeyKiki Portal API', version='0.1.0')` — no `docs_url=None` or `openapi_url=None` parameter. CORS config does not restrict /docs or /openapi.json.
- **Confidence:** 98 · **Verified:** CODE-ONLY

### `SEC-013` — delete_organization uses require_org (not require_org_admin) as outer Depends with inline role check  ·  LOW / AuthZ

DELETE /api/settings/organization uses `Depends(require_org)` in its signature, then checks `user.role != 'org_admin'` inline. This is logically correct but inconsistent with the pattern: the outer dependency has already loaded and returned the user, so any employee can reach the function body. The inline check catches it, but this double-layer approach diverges from the established pattern of using `require_org_admin` at the Depends level (which is what every other admin endpoint does). A future code refactor risk exists if the inline check is accidentally removed.

- **Affected:** backend/app/api/routes/settings.py:373-378
- **Evidence:** `user: CurrentUser = Depends(require_org)` on line 374, then `if user.role != 'org_admin': raise HTTPException(403)` on line 378. Compare with nearby routes like `get_settings` which correctly use `Depends(require_org_admin)` (line 154).
- **Confidence:** 85 · **Verified:** CODE-ONLY

### `SEC-014` — _require_admin in kiki_zentrale rejects super_admin — inconsistent role model  ·  LOW / AuthZ

The local `_require_admin` helper in kiki_zentrale.py checks `user.role != 'org_admin'` strictly, which means a super_admin user (role='super_admin') is blocked from mutating agent config on behalf of an org even though `require_org_admin` (in deps.py:115) explicitly allows super_admin. This creates an inconsistency: require_org_admin allows super_admin but _require_admin does not. A super_admin operating inside a specific org context would get a 403 on save_leitfaden, create/update/delete required fields, update context, etc.

- **Affected:** backend/app/api/routes/kiki_zentrale.py:55-59, backend/app/api/deps.py:115
- **Evidence:** kiki_zentrale.py:56 — `if user.role != 'org_admin'` — strictly requires org_admin, blocks super_admin. deps.py:115 — `if user.role not in ('org_admin', 'super_admin')` — explicitly permits super_admin.
- **Confidence:** 90 · **Verified:** CODE-ONLY

### `SEC-017` — CORS policy uses env-configured origin list but allows credentials — misconfiguration risk  ·  LOW / CORS

The app uses `allow_credentials=True` with `allow_origins=settings.cors_origin_list` (configurable list from CORS_ORIGINS env var). The default in non-production is `http://localhost:5173`. If CORS_ORIGINS is misconfigured in production (e.g., set to `*` or left as localhost), it could allow any origin to make credentialed requests. Using `allow_credentials=True` with `allow_methods=['*']` and `allow_headers=['*']` is maximally permissive for methods and headers. There is no runtime validation that CORS_ORIGINS is set correctly in production.

- **Affected:** backend/app/main.py:112-118, backend/app/core/config.py:31
- **Evidence:** main.py:114 — `allow_origins=settings.cors_origin_list`. config.py:31 — default `cors_origins: str = 'http://localhost:5173'`. No validation that cors_origins is non-localhost in production in validate_runtime_config (config.py:178-215).
- **Confidence:** 60 · **Verified:** RUNTIME-NEEDED

### `SEC-018` — JWKS cache is a module-level global with no thread lock — potential race on first population  ·  LOW / RaceCondition

The JWKS cache in security.py is a plain dict `_jwks_cache = {"keys": None, "ts": 0.0}`. When the cache expires and multiple concurrent requests all check `_jwks_cache['keys'] is None`, each will independently call httpx.get() to fetch the JWKS. This is a thundering herd on cache miss, not a data-race corruption risk (Python's GIL protects simple dict assignments). However, under load at startup or at TTL boundary, N threads can simultaneously make HTTP calls to the Supabase JWKS endpoint, potentially rate-limiting the auth service.

- **Affected:** backend/app/core/security.py:12-30
- **Evidence:** `_jwks_cache: dict = {'keys': None, 'ts': 0.0}` at line 12. `_get_jwks` at lines 19-30 has no mutex/lock before the stale-check + HTTP-fetch sequence.
- **Confidence:** 75 · **Verified:** RUNTIME-NEEDED

### `SEC-020` — No input length validation on free-text fields in customer search and job report submission  ·  LOW / MissingValidation

The customer list/export endpoints accept a `q` search parameter with no length limit. In submit_job (technician_jobs.py:332), the `description` field is truncated at 2000 chars and needs list items are capped at 10 items, but `extra_demands` and `site_visit_notes` have no length bounds. In the customer search, an unbounded `q` can create a very long PostgREST filter string. For the public job endpoints, excessively long strings can cause performance issues in DB pattern matching.

- **Affected:** backend/app/api/routes/customers.py:300-308, backend/app/services/technician_jobs.py:326-333
- **Evidence:** customers.py list_customers function — `q: str \| None = None` with no Query(max_length=...) constraint. technician_jobs.py:327 — `extra_demands: (report.get('extra_demands') or '').strip() or None` — no length limit applied before storage.
- **Confidence:** 72 · **Verified:** CODE-ONLY

### `SEC-022` — Crypto decrypt failure is silent None — callers may proceed without credentials  ·  LOW / SecretHandling

crypto.decrypt() returns None on both 'no token stored' and 'wrong key / tampered ciphertext' (InvalidToken). A caller cannot distinguish between 'credentials not configured' and 'credentials corrupted or key rotated'. Code paths that use decrypted SMTP password or PDS API key will silently proceed to the next fallback (e.g., Brevo) or raise a service-level error, but the root cause (key mismatch) is only surfaced as a logger.warning, not as a startup-time failure or an alert. If the SETTINGS_ENC_KEY is rotated without re-encrypting stored credentials, all org-specific OAuth tokens and SMTP passwords become silently inaccessible.

- **Affected:** backend/app/core/crypto.py:45-66
- **Evidence:** crypto.py:59-66 — `except InvalidToken: logger.warning(...); return None`. Same None is returned for missing token (line 56-57). Callers receive None in both cases and cannot distinguish them without out-of-band key validation.
- **Confidence:** 85 · **Verified:** CODE-ONLY

### `SEC-025` — Photo upload path stored in Supabase storage is not validated to remain within org scope  ·  LOW / DataIntegrity

In add_photo (technician_jobs.py:268-269), the storage path is constructed as `{link['org_id']}/jobs/{link['id']}/{uuid}_{safe_name}`. The safe_name is only slash-stripped, not otherwise sanitized (e.g., against `..`). Since the org_id prefix is hard-coded from the DB (not user-supplied), the path cannot escape org scope in Supabase storage. However, the filename component (safe_name) is truncated to 80 chars from the end (`[-80:]`), which could include special characters other than `/`. This is low risk given the org_id prefix is trusted.

- **Affected:** backend/app/services/technician_jobs.py:267-270
- **Evidence:** technician_jobs.py:268 — `safe_name = (filename or 'foto.jpg').replace('/', '_')[-80:]` — replaces only forward slash. Other path-separator characters (backslash on Windows Supabase SDK) or URL-encoded sequences are not stripped.
- **Confidence:** 40 · **Verified:** RUNTIME-NEEDED

### `SEC-019` — Sensitive field `smtp_password` visible in API request body schema via /openapi.json  ·  INFO / DataExposure

The EmailConfigUpdate Pydantic model exposes `smtp_password` as a plaintext string field in PATCH /api/settings/email-config. While the API correctly encrypts this before storage, the password travels over the wire in plaintext JSON (protected by TLS in production, but logged by any proxy/WAF in between). More importantly, the openapi.json schema (publicly accessible at /openapi.json) documents the `smtp_password` field name, making it immediately apparent to any observer that SMTP credentials flow through this endpoint.

- **Affected:** backend/app/api/routes/settings.py:75, backend/app/api/routes/settings.py:259-273
- **Evidence:** settings.py:75 — `smtp_password: str \| None = None  # plaintext in → encrypted at rest`. The field is included in the Pydantic model and therefore appears in /openapi.json as a string input field.
- **Confidence:** 80 · **Verified:** CODE-ONLY

### `SEC-021` — Service-role Supabase key is a singleton cached globally — key rotation requires restart  ·  INFO / SecretHandling

get_service_client() in supabase_client.py uses @lru_cache making the client (and therefore the service-role key) a process-level singleton. A key rotation in Railway env vars requires a backend process restart to take effect. There is no mechanism to detect or invalidate the cached key. In a key-compromise scenario, the compromised key remains active until the next restart.

- **Affected:** backend/app/db/supabase_client.py:9-54
- **Evidence:** supabase_client.py:9 — `@lru_cache` decorator on `get_service_client()`. Comment at line 30: 'credential/URL env changes are only picked up on restart.'
- **Confidence:** 90 · **Verified:** CODE-ONLY

### `SEC-023` — No per-user (user_id) scoping in rate limiter — org-level only  ·  INFO / RateLimit

The enforce_rate_limit function buckets calls by (name, org_id). An org with many employees could collectively exhaust another legitimate user's quota within the same org, or a single employee could use the entire org's allotment. There is no per-user sub-limit. This is an internal fairness concern but could cause denial-of-service against specific employees within a shared org.

- **Affected:** backend/app/services/ratelimit.py:24-44
- **Evidence:** ratelimit.py:33 — `key = (name, org_id or '_global')` — no user_id component in the key.
- **Confidence:** 75 · **Verified:** CODE-ONLY

---

## Live Supabase Advisor Findings (runtime-verified)

- **RLS enabled but NO policy (20 tables, INFO):** `action_tasks`, `billing_checkout_sessions`, `billing_events`, `billing_migration_log`, `billing_notifications`, `billing_security_events`, `billing_usage_reports`, `billing_webhook_events`, `case_links`, `employee_absences`, `maintenance_plans`, `missed_calls`, `oauth_connections`, `oauth_purpose_links`, `org_secrets`, `outbound_calls`, `technician_job_links`, `text_modules`, `tools`, `vehicles`.
  - *Interpretation:* RLS ON + no policy = deny-all to PostgREST anon/authenticated roles (secure-by-default). Backend uses service_role (bypasses RLS), so tenant isolation for these tables relies on APP-LAYER org_id filters, not DB policy. No policy backstop if a query is ever under-scoped or the anon key is exposed.
- **WARN:** auth_org_id() SECURITY DEFINER executable by authenticated via /rest/v1/rpc/auth_org_id
- **WARN:** rls_auto_enable() SECURITY DEFINER executable by anon+authenticated
- **WARN:** kz_begin_agent_sync has mutable search_path
- **WARN:** Supabase Auth leaked-password protection DISABLED

