# Stress test + multi-tenant isolation plan (60–70 orgs)

Status: **PLAN — ready to run once a staging stack + Step-0 preconditions are confirmed.** Goal: prove the CRM handles ~64 organizations concurrently with no lag **and no cross-org data leakage**.

## Ground rules (safety — read first)
- **Run against a SEPARATE seeded set of UAT test orgs (or a Supabase branch / staging Railway), NEVER real customer orgs.**
- Outbound is LIVE in prod (`OUTBOUND_TEST_SCOPE_ONLY=0`). **Do not hit `send_email` or outbound-call routes** — those reach real people. Read-heavy scenarios only on prod; do WRITE + saturation runs on staging.
- Stripe is gated off — leave it off.

## Step 0 — Preconditions (check live before running)
```sql
-- org/user scale
select count(*) from organizations;
select count(*) from organizations where name like 'LOADTEST-%';   -- need >= 64, else seed
-- DB pool ceiling
select setting from pg_settings where name = 'max_connections';
select count(*) from pg_stat_activity;                              -- current usage
```
- **Token strategy:** is `SUPABASE_JWT_SECRET` set on the backend?
  - **Yes →** mint HS256 JWTs offline (cheap, no Auth users needed; matches `core/security.py`).
  - **No (ES256/JWKS only) →** create a real Supabase Auth user per test org and `POST /auth/v1/token?grant_type=password` for each.
- Note whether the Supabase **pooler (pgBouncer, :6543)** fronts PostgREST. The backend uses PostgREST (:443), so the practical ceiling is the PostgREST/DB pool — record both.
- Pick SLO bars (suggested below).

## Step 1 — Provision N isolated test orgs (additive, pre-authorized; ideally on a branch)
Prefer **Supabase `create_branch`** for an isolated throwaway Postgres copy (zero prod risk). Otherwise seed a numbered, trivially-deletable block in a staging DB.

Per org `i` in 1..64 (all additive):
1. `insert organizations (heykiki_org_id='loadtest-<i>', name='LOADTEST-<i>', slug='loadtest-<i>')` → capture `org_id`.
2. Create a Supabase Auth user `loadtest+<i>@example.invalid` → capture `auth uid`.
3. `insert public.users (id=<auth uid>, org_id=<org_id>, role='org_admin', email=...)`.
4. **Seed DISTINCTIVE per-org data so leakage is instantly visible:** customers with `full_name='LEAKCANARY-<i>-<n>'` and `notes='ORGTOKEN-<org_id>'`, plus matching `calls`/`inquiries`/`cost_estimates`/`invoices` carrying the same `org_id`. The canary MUST encode the org index.
5. Build `tokens.json`: `{ org_index: { token, org_id, canary } }` for k6.

## Step 2 — Scenarios
- **Read mix (the load):** concurrent `GET /api/dashboard/overview`, `/api/customers`, `/api/calls`, `/api/cost-estimates`, `/api/invoices` across all N orgs.
- **Isolation assertion (the point):** every response for org `i` must contain ONLY `i`'s canary and NEVER another org's `ORGTOKEN`. Fail loudly on any foreign token.
- **Write isolation (staging only):** create a customer per org, confirm it appears only in that org.

## Step 3 — Metrics / SLOs (suggested)
| Metric | Target |
|---|---|
| p95 latency (read endpoints) | < 800 ms under 64-org concurrency |
| p99 latency | < 2 s |
| error rate | < 0.5% |
| cross-org leak | **0 — any leak is an automatic fail** |
| DB connections | stay under `max_connections` (watch `pg_stat_activity`) |

## k6 script (skeleton)
`tokens.json` from Step 1 sits next to this script. Run: `k6 run --vus 64 --duration 5m stress.js`.
```javascript
import http from 'k6/http'
import { check, fail } from 'k6'
import { SharedArray } from 'k6/data'
import { Counter } from 'k6/metrics'

const BASE = __ENV.BASE_URL // e.g. https://staging-backend.up.railway.app
const orgs = new SharedArray('orgs', () => JSON.parse(open('./tokens.json')))
const leaks = new Counter('cross_org_leaks')

const READ_PATHS = [
  '/api/dashboard/overview',
  '/api/customers?limit=50',
  '/api/calls?limit=50',
  '/api/cost-estimates',
  '/api/invoices',
]

export const options = {
  scenarios: { soak: { executor: 'ramping-vus', startVUs: 0,
    stages: [{ duration: '1m', target: 64 }, { duration: '4m', target: 64 }, { duration: '30s', target: 0 }] } },
  thresholds: {
    http_req_duration: ['p(95)<800', 'p(99)<2000'],
    http_req_failed: ['rate<0.005'],
    cross_org_leaks: ['count==0'],   // hard fail on ANY leak
  },
}

export default function () {
  const me = orgs[Math.floor(Math.random() * orgs.length)]
  const headers = { Authorization: `Bearer ${me.token}` }
  const path = READ_PATHS[Math.floor(Math.random() * READ_PATHS.length)]
  const res = http.get(`${BASE}${path}`, { headers })

  check(res, { 'status 200': (r) => r.status === 200 })

  // ISOLATION ASSERTION: this org's body must not contain ANY other org's token.
  const body = res.body || ''
  for (const other of orgs) {
    if (other.org_id !== me.org_id && body.includes(`ORGTOKEN-${other.org_id}`)) {
      leaks.add(1)
      fail(`LEAK: org ${me.org_id} saw ${other.org_id} via ${path}`)
    }
  }
}
```

## Teardown
- If seeded in a shared DB: `delete from <child tables> where org_id in (loadtest ids); delete from users where email like 'loadtest+%'; delete from organizations where name like 'LOADTEST-%';` + delete the Auth users.
- If a Supabase branch: just drop the branch.

## Notes from the isolation audit (item 6 — already verified solid)
App-level `org_id` filtering + `validate_fk_in_org` IDOR guards hold on every route; service-role bypasses RLS, so the **app filter is the boundary** — this test exercises exactly that boundary. Add a **negative probe** for the one residual surface: the `deps.py` `agent_id`-only webhook fallback (an attacker who learns an org's `elevenlabs_agent_id` can write within THAT org if no `X-HeyKiki-Secret` is sent — bounded to one org, not cross-org reads). Recommend hardening it to require the per-org secret given outbound is live.
