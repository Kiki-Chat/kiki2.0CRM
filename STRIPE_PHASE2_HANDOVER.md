# Stripe Billing — Phase 2 Handover (+ Phase 1 context)

> **New session: start here.** This is the full state of the Stripe billing module so you can
> continue without the prior chat. Read this, then `SESSION_HANDOVER.md` (the 2026-06-08
> billing bullets) and `STRIPE_INTEGRATION_HANDOVER.md` (the original discovery). The code is
> merged to `main`. Everything is **gated OFF by default** and runs against **Stripe TEST mode**.

---

## 0. TL;DR — current state

- **Phase 1 (read-first reflection) + Phase 2 (provisioning/checkout/trial/notifications/admin-writes) are BUILT, TESTED, and merged to `main`.** Commits: `2395f9d` (P1), `947e66f`+`f8c2db4`+`49f02b7` (P2).
- **Migrations applied** to Supabase `ifbluvdcbcesuhvkxsfn`: `0048_billing.sql` (P1, 5 tables) + `0049_billing_phase2.sql` (P2, 2 tables).
- **Two feature gates, both default `False`** (`backend/app/core/config.py`): `STRIPE_BILLING_ENABLED` (mounts routers) and `STRIPE_USAGE_REPORTING_ENABLED` (arms the usage-record WRITE path).
- **~55 hermetic tests pass; 0 regressions.** Checkout + a trial→`past_due` test-clock cycle were proven against real Stripe test mode.
- `stripe==11.6.0` pinned **`<12` on purpose** (the live subs use the LEGACY usage-records API removed in v12).

### THE PLAN RIGHT NOW: **test key only** (look-and-feel)
We are NOT going live yet. During the Railway "transition" week (real + test customers poking the CRM):
- Use the **TEST key** (`sk_test_…`) **everywhere**, including Railway prod.
- A test key sees ONLY test data → **real customers' real billing is invisible and untouched.** That's intended: it's still development; showing/charging real billing would not help.
- Real customers get **look-and-feel only**: they can open Settings → Abrechnung, see the plan picker, click "Jetzt abonnieren" → a **test-mode** Stripe Checkout (pay with `4242 4242 4242 4242`) → **nothing real happens.** Tell them: *"billing is preview-only; no real charges."*
- **Swap to the live key only at true go-live** (after the §7 checklist). Until then, never put `rk_live_`/`sk_live_` anywhere.

---

## 1. Phase 1 foundation (the base Phase 2 builds on)

**Doctrine** (from `STRIPE_INTEGRATION_HANDOVER.md`): the Stripe account is LIVE with ~80 real customers. READ their state into the CRM first; WRITE only on objects we own (subs with `application == null`); standardize new tenants onto a clean catalog. Legacy ChatDash subs (`application != null`) are read-only.

**Safety layer — `backend/app/services/stripe_billing.py`** (mirrors `patch_agent_safely`):
- `stripe_call_safely(...)` — every mutation: audit row in `billing_events` (pending→succeeded/failed) FIRST, **Connect-attribution write block** (refuse if `subscription.application != null`), **cross-org guard**, **idempotency key**, **additive metadata merge** (never clobber). NO auto-rollback (Stripe writes aren't reversible — detect-and-alert).
- `stripe_read(...)` — pure reads; audited only on error (keeps the ledger a write record).
- `get_stripe()` / `is_configured()` — key gate; raises `StripeConfigError` if no key.

**Migration `0048`** — 5 backend-only tables (RLS on, NO client policy, like `org_secrets`): `billing_events` (audit), `billing_webhook_events` (`stripe_event_id` UNIQUE dedup), `billing_usage_reports` (`call_id` UNIQUE = one-call-one-report), `billing_migration_log` (matcher proposals), `billing_security_events`. Plus nullable `billing_*` columns on `organizations` + `calls.billing_usage_report_id`.

**Read endpoints** (`backend/app/api/routes/billing.py`, `require_org`): `/summary` `/invoices` `/upcoming-invoice` `/payment-methods` `/portal-session`. **Webhook** (`stripe_webhook.py` route + service): raw-body signature verify → dedup → background process → always 200. **Usage reporting** (`billing_usage.py`) fires from the post-call **ROUTE** (`routes/post_call.py`), so historical backfill (`history_import` → `_process_one`) is structurally excluded. **Super-admin reads** (`billing_admin.py`) + **dry-run matcher** (`stripe_matcher.py`, email/`difflib`, zero write-back). Read-only UI: `SettingsPage.tsx` Abrechnung + standalone `admin/AdminBillingPage.tsx`.

**Key facts:** real table is `organizations` (American). Soft-stop over-quota = report ALL minutes (no cap), bill overage. `minutes_from_seconds` uses `round()` (confirm round-vs-ceil before live).

---

## 2. Phase 2 implementation (everything new)

**Migration `0049`** — 2 backend-only tables: `billing_notifications` (in-app feed; `dedup_key` UNIQUE = one alert per period) + `billing_checkout_sessions`.

| Area | File(s) | What |
|---|---|---|
| **Catalog** | `services/stripe_catalog.py` | `ensure_catalog()` idempotently creates Solo/Team/Premium in Stripe (flat **base** + **graduated metered** so soft-stop bills overage automatically). `find_plan_prices(title, interval)` resolves prices by stable `lookup_key` (`kiki_solo_base_month`, …). **PLACEHOLDER prices** (`PLANS` dict). Metadata matches the handover §4a. |
| **Provisioning / Checkout** | `services/stripe_provisioning.py` | `ensure_stripe_customer(org)` (idempotent) + `create_checkout_session(org, plan, interval, trial_days=14)` → hosted Stripe Checkout, pre-filled, base+metered line items, `automatic_tax`. |
| **Webhook handlers** | `services/stripe_webhook.py` | `checkout.session.completed` → link sub to org; `trial_will_end` → sync + notify; `payment_failed` → `past_due` + notify. |
| **Notifications** | `services/billing_notifications.py` | `record_notification` (deduped) + `notify_over_quota/_trial_will_end/_payment_failed` + `check_and_notify_over_quota`. **Email is deferred to Amber's Brevo track** (in-app only for now). |
| **Super-admin writes** | `services/stripe_admin_actions.py` | `approve_match` (writes `heykiki_org_id` to Stripe metadata + links org), `reject_match`, `retry_payment`, `cancel_subscription` (Connect-blocked → 409). |
| **Endpoints** | `routes/billing.py`, `routes/billing_admin.py` | `GET /api/billing/plans`, `POST /api/billing/checkout-session`, `POST /api/billing/sync` (webhook fallback — lists the org's sub, syncs the live one via `_handle_subscription`, returns `BillingSummary`; never writes to Stripe); super-admin `POST .../matches/{id}/approve|reject`, `.../orgs/{id}/retry-payment|cancel-subscription`. |
| **Frontend** | `pages/SettingsPage.tsx`, `admin/AdminBillingPage.tsx`, `lib/dashApi.ts` | Abrechnung plan-picker + "Jetzt abonnieren" + trial/payment-required banners; super-admin approve/reject on the match queue. |
| **Tests** | `backend/tests/test_billing_phase2.py`, `test_billing_admin_actions.py` (+ P1: `test_stripe_safety/usage/webhook/matcher.py`, shared `billing_fakes.py`) | hermetic FakeDB + fake-Stripe. |

**Full route set** (when `STRIPE_BILLING_ENABLED=1`): 9 customer (`/api/billing/*`, incl. `POST /sync`) + 10 super-admin (`/api/super-admin/billing/*`) + the webhook.

---

## 3. Config & env — **TEST-KEY-ONLY**

`backend/app/core/config.py` settings (all read from env):
| var | local now | Railway look-and-feel week | go-live (later) |
|---|---|---|---|
| `STRIPE_SECRET_KEY` | `sk_test_…` | **`sk_test_…`** (same test key) | `rk_live_…` (live, restricted) |
| `STRIPE_BILLING_ENABLED` | `1` | `1` (shows the UI) | `1` |
| `STRIPE_USAGE_REPORTING_ENABLED` | `0` | **`0`** (never bill) | `1` only after rounding/Connect decided |
| `STRIPE_WEBHOOK_SECRET` | test `whsec_` (optional) | test `whsec_` if a test webhook is set up | live `whsec_` |
| `BILLING_PORTAL_RETURN_URL` | — | frontend `/settings/abrechnung` | same |

**Why test key on prod is safe:** test universe ≠ live universe. Real customers' subs/invoices/money are in LIVE mode and a test key cannot read or write them. So real customers see "not configured" → the subscribe **look-and-feel**; any checkout they start is a **test** checkout (`4242` card), charging nothing real. Usage reporting stays OFF so no metered writes happen at all.

**Do NOT** put a live key anywhere until go-live. **Do NOT** flip `STRIPE_USAGE_REPORTING_ENABLED` with a live key (it would bill real subscriptions).
**Railway deploy + env vars are a deploy action** → needs Amber's explicit approval (see `[[feedback_local_uat_railway_prod]]`). Don't `railway up` autonomously.

---

## 4. Test fixtures & how to verify

**Test org:** `kiki-test-007` = org id `c4dbf596-86fd-4484-88d9-095b2c082afb` (also `OUTBOUND_TEST_ORG_IDS`). Pre-authorized for reversible test-data writes ONLY.
**Test catalog:** lives in the Stripe test sandbox (acct `acct_1RDkSzDF5qbrNGDc`, test mode). Re-create/refresh anytime: `python -c "from app.services.stripe_catalog import ensure_catalog; print(ensure_catalog())"`. Lookup keys: `kiki_{solo|team|premium}_{base|metered}_{month|year}`.
**Test card:** `4242 4242 4242 4242`, any future expiry/CVC.

**Verify (run from `backend/`, venv active):**
1. **Routes:** restart uvicorn with the gate on → `curl -s localhost:8000/openapi.json | grep -o '/api/billing/[a-z-]*' | sort -u` (expect `/plans`, `/checkout-session`, …).
2. **Tests:** `.venv/bin/python -m pytest tests/test_stripe_*.py tests/test_billing_*.py -q` → ~55 green.
3. **Checkout (test mode):**
   ```python
   from app.services.stripe_provisioning import create_checkout_session
   print(create_checkout_session("c4dbf596-86fd-4484-88d9-095b2c082afb","Kiki Solo","month",trial_days=14))
   # -> {"url": "https://checkout.stripe.com/c/pay/cs_test_…", "session_id": "cs_test_…"}  (open the URL, pay 4242)
   ```
4. **Trial lifecycle (test clock):** create a sub with `trial_period_days=14` on a `stripe.test_helpers.TestClock`, advance 15 days, retrieve → status `past_due`; feed it to `stripe_webhook._handle_subscription(db, sub)` → org `billing_status` syncs. (Full script is in the 2026-06-08 chat / reproduce from §2.)
5. **UI:** Settings → Abrechnung (picker/banners) + super-admin `/admin` → Abrechnung tab.
> ⚠️ Restart the backend after merging — no hot-reload (`[[project_backend_no_reload]]`). The running preview may still be Phase-1 until restarted.

---

## 5. Remaining work / go-live checklist

1. ~~**Confirm real plan prices** in `stripe_catalog.PLANS`~~ ✅ **CONFIRMED by Amber 2026-06-08** — Solo €99 (99 min, €1.19/min over) / Team €249 (250 min, €1.00/min) / Premium €599 (750 min, €0.70/min); annual = 10× monthly. Values are final; they still live only in the TEST sandbox (see #2 for the LIVE catalog).
2. **Create the canonical catalog in LIVE mode** (run `ensure_catalog()` with the live key) — until then, checkout fails closed on live (lookup_keys don't exist there).
3. **Decide minutes rounding** (`minutes_from_seconds`: round vs ceil) and **legacy-Connect usage** reconciliation.
4. **Live webhook endpoint** in the Stripe dashboard → `https://<railway-backend>/api/billing/stripe-webhook` → set the live `STRIPE_WEBHOOK_SECRET`. (Local live round-trip needs the Stripe CLI — not installed.)
5. **Link real orgs:** run the matcher live → super-admin approves matches (write-back `heykiki_org_id`).
6. **Flip gates** on Railway (`STRIPE_BILLING_ENABLED=1`; `STRIPE_USAGE_REPORTING_ENABLED=1` ONLY after #3) with the **live** key, and **deploy (Amber-approved)**.
7. Optional: wire email notifications (Amber's track); super-admin retry-payment/cancel **buttons** (endpoints exist, UI not yet).

---

## 6. Gotchas & safety

- **One key = one universe** (test OR live; can't reflect both at once).
- Gates default OFF; with no key + gates off the app behaves exactly as before.
- `stripe` pinned `<12` (legacy usage-records API). Don't bump without porting to Meters API.
- Backend has **no hot-reload** — restart uvicorn after edits.
- Additive migrations are pre-authorized; apply via Supabase MCP `apply_migration` (was flaky this session — if it errors `net::ERR_FAILED`, paste the `.sql` into the dashboard SQL editor).
- Built in a git **worktree** on branch `stripe` (`.claude/worktrees/stripe`) then merged to `main`; the worktree can be removed (`git worktree remove`).
- Memory notes: `[[project_stripe_billing_phase1]]` (state), `[[feedback_local_uat_railway_prod]]` (deploy approval), `[[feedback_test_data_kiki_test_007]]` (test-data scope), `[[feedback_email_send_amber_owned]]` (email track).
