# Paid-Onboarding Orchestration — Implementation Spec

_Last updated: 2026-06-20. Companion to `STRIPE_PHASE2_HANDOVER.md` and `STRIPE_BILLING_UAT.md`._

## 0. Goal

Customers onboard through an **external funnel and pay BEFORE they get CRM access**. Payment is
the trigger for everything else: account creation, AI agent, phone number, and the welcome emails.

```
Fill personal & company info
        │
        ▼
Choose plan + pay (Stripe Checkout)            ← payment happens FIRST
        │
        ▼  checkout.session.completed (Stripe webhook)
Our backend  ──────────────►  n8n onboarding webhook
        │                          │
        │                          ├─ create ElevenLabs agent (from template)
        │                          ├─ allocate Twilio number + bind to agent
        │                          └─ POST /api/heykiki/provision  (create CRM account)
        │                          
        ▼
Customer receives e-mails:
   • Stripe payment receipt + invoice         (Stripe-owned)
   • "Onboarding gestartet"                    (n8n / our backend)
   • "Rufnummer zugewiesen"                    (n8n / our backend)
   • "Ihr CRM-Konto wurde erstellt"            (n8n / our backend)
        │
        ▼
Inside the CRM the plan is live: included minutes, usage, receipts,
UPGRADE, and EXTRA-USAGE (overage) — see §6 (already built).
```

## 1. What already exists (verified 2026-06-20)

| Capability | Location | Notes |
|---|---|---|
| Stripe catalog (Solo/Team/Premium, base + metered overage) | `backend/app/services/stripe_catalog.py` | idempotent `ensure_catalog()` |
| Hosted Checkout (subscribe) | `stripe_provisioning.create_checkout_session` | returns a `billing.stripe.com` URL |
| Stripe webhook ingest (verify→dedup→handlers) | `backend/app/services/stripe_webhook.py` | `checkout.session.completed` → `_handle_checkout_completed` |
| State-sync onto `organizations.billing_*` | `stripe_webhook._handle_subscription` | derives plan + minutes from base-item metadata |
| Provisioning (org + admin user + agent_config) | `backend/app/services/provisioning.py` `provision_org()` | rollback-safe; **requires a pre-existing `elevenlabsAgentId`** |
| Provisioning HTTP route | `POST /api/heykiki/provision` | gated by `verify_master_secret` (header `MASTER_WEBHOOK_SECRET`) |
| n8n workflow `HeyKiki CRM Provision (test)` | `n8n_heykiki_provision.json` | `Webhook → Process Lead → Check Agent (EL) → Agent has phone? → Wait 15s → Provision CRM` |
| Billing notifications + email dispatch | `backend/app/services/billing_notifications.py` | `send_email()` fallback chain (Brevo) |
| Phone metadata fetch | `agent_config.fetch_phone_meta_for_agent` | **fetches** an already-bound EL phone; does NOT allocate |

## 2. Confirmed gaps (what this spec covers)

1. **No payment→n8n coupling.** `_handle_checkout_completed` only syncs DB + sends our welcome email; it makes **no outbound call to n8n**.
2. **No ElevenLabs agent creation** anywhere in the Stripe/provision path — `provision_org` assumes the agent id already exists.
3. **No Twilio number allocation** — only a fetch of an already-bound number.
4. **No public pre-payment funnel** — the frontend has only internal CRM pages; `/provision` is master-secret-gated.
5. **Only 1 of the 3 onboarding emails exists** (`notify_subscription_activated`). No `onboarding_started` / `twilio_number_assigned` / `crm_account_created`.

> The two big external pieces (the **public funnel UI** and the **Twilio number purchase**) live outside this repo. This spec defines the backend contract they integrate against so they can be built independently.

---

## 3. Target architecture

### 3.1 Trigger — extend the Stripe webhook to fan out to n8n

`_handle_checkout_completed` already runs on `checkout.session.completed`. Add a **best-effort outbound POST** to an n8n webhook after the DB sync, behind a config flag so it ships inert.

- **New config** (`app/core/config.py`): `n8n_onboarding_webhook_url: str = ""` (`N8N_ONBOARDING_WEBHOOK_URL`), `n8n_onboarding_enabled: bool = False` (`N8N_ONBOARDING_ENABLED`), and a shared secret `n8n_shared_secret` (`N8N_SHARED_SECRET`) sent as a header so n8n can authenticate us.
- **New module** `app/services/onboarding_dispatch.py` → `dispatch_onboarding(session, sub)`:
  - Builds the payload (see §4) from the Checkout session + subscription + the customer object (company/contact captured at Checkout, §3.4).
  - POSTs to `N8N_ONBOARDING_WEBHOOK_URL` with header `X-HeyKiki-Secret: <N8N_SHARED_SECRET>`.
  - **Idempotent**: include `checkout_session_id`; n8n must dedupe on it. Record the attempt in a new `onboarding_events` row (§5) so a failed dispatch can be retried by a sweep.
  - **Best-effort**: a failure NEVER breaks the webhook (matches the existing email try/except pattern).
- Call it from `_handle_checkout_completed` after `_handle_subscription`, gated by `settings.n8n_onboarding_enabled and settings.n8n_onboarding_webhook_url`.

### 3.2 Orchestration — n8n owns the chain

Extend `n8n_heykiki_provision.json` so the webhook node accepts our §4 payload and runs:

1. **Create ElevenLabs agent** (§3.3) — POST EL `/v1/convai/agents/create` cloning a template agent, with the org name; capture `agent_id`. _(Optional: do this in our backend instead — see §3.3 alt.)_
2. **Allocate Twilio number** (§3.3) — purchase a DE number via Twilio, then bind it to the EL agent via EL `/v1/convai/phone-numbers`. Capture `phone_number`.
3. **Email: "Rufnummer zugewiesen"** — once the number is bound.
4. **Provision CRM** — `POST /api/heykiki/provision` (header `X-Master-Secret`) with the §4.2 body (now including `elevenlabsAgentId`). `provision_org` creates the org + admin + agent_config + backfills history.
5. **Email: "Ihr CRM-Konto wurde erstellt"** — with the login link.

n8n should send "Onboarding gestartet" at the very start (step 0). Stripe sends the receipt/invoice independently.

### 3.3 ElevenLabs agent + Twilio number

**Where:** the cleanest split is _n8n does the external API calls_ (EL create, Twilio purchase, EL bind) because it already holds those credentials and the existing flow lives there.

**Backend alternative (recommended if you want it auditable + testable):** add `app/services/onboarding_provision.py`:
- `create_agent_from_template(org_name) -> agent_id` — uses the EL API (mirror `agent_config.configure_agent`; clone the template agent id from config `EL_TEMPLATE_AGENT_ID`).
- `allocate_twilio_number(country="DE") -> phone_sid, e164` — Twilio `IncomingPhoneNumbers.create` (creds already in `.env`: `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN`).
- `bind_number_to_agent(agent_id, e164)` — EL `/v1/convai/phone-numbers` (the read side already exists in `agent_config.fetch_phone_meta_for_agent`).
Then a single backend endpoint `POST /api/heykiki/onboard` (master-secret) does agent→number→`provision_org` in order and returns the org id. n8n calls just this one endpoint. **This keeps allocation idempotent + audited and unit-testable**, and is the preferred path.

> Either way, allocation MUST be idempotent: key on `heykiki_org_id`/`checkout_session_id` so a retry doesn't buy a second Twilio number.

### 3.4 Capturing personal & company info at Checkout

`create_checkout_session` already sets `billing_address_collection="required"` + `tax_id_collection`. To carry the funnel's personal/company fields through to provisioning:
- Pass them as `subscription_data.metadata` / `customer` fields when the **funnel** creates the Checkout (company name → customer name, contact email, phone). They then arrive on the `customer`/`subscription` objects the webhook reads.
- For the login email use the **payer email** (`customer.email`) so "same email + phone used for account creation" holds by construction; the phone goes onto `organizations.phone_number`.

### 3.5 Public pre-payment funnel (out of repo)

A standalone landing/funnel (not the CRM SPA): collect personal + company info → create a Stripe Checkout (subscribe mode) pre-filled with that info as metadata → redirect to Stripe. On success, Stripe fires the webhook (§3.1). No CRM login exists yet at this point — the CRM account is created by step §3.2.4. This is the only piece with **no backend dependency** beyond the metadata convention in §3.4.

---

## 4. Payload contracts

### 4.1 Backend → n8n (`N8N_ONBOARDING_WEBHOOK_URL`)
```jsonc
{
  "checkout_session_id": "cs_test_...",   // idempotency key
  "stripe_customer_id": "cus_...",
  "stripe_subscription_id": "sub_...",
  "plan_title": "Kiki Team",
  "email": "owner@firma.de",              // payer == login email
  "phone": "+49...",                       // → organizations.phone_number
  "company_name": "Mustermann GmbH",
  "admin_name": "Max Mustermann",
  "heykiki_org_id": "kiki-xxxx"            // optional; n8n may mint it
}
```

### 4.2 n8n → `POST /api/heykiki/provision` (existing `ProvisionRequest`)
```jsonc
{
  "heykikiOrgId": "kiki-xxxx",
  "orgName": "Mustermann GmbH",
  "loginEmail": "owner@firma.de",
  "loginPassword": "<generated; user resets via 'set password' email>",
  "elevenlabsAgentId": "agent_...",        // created in §3.3
  "adminName": "Max Mustermann",
  "contactEmail": "owner@firma.de"
}
```
> Note: `provision_org` does not currently link `stripe_customer_id` onto the new org. Add `stripeCustomerId` to `ProvisionRequest` (additive) and write it on the org insert, OR have the webhook's later `customer.subscription.*` events link by customer — but linking at provision time is cleaner so the very first `summary` call is already `configured`.

## 5. Data model (additive only — pre-authorized)

- **`onboarding_events`** (new table): `id`, `checkout_session_id` UNIQUE, `org_id` nullable, `stage` (`dispatched|agent_created|number_assigned|provisioned|failed`), `payload jsonb`, `error text`, `created_at`, `updated_at`. Mirrors `billing_webhook_events` so dispatch + each n8n step is idempotent and retryable.
- `organizations`: reuse existing `heykiki_org_id`, `phone_number`, `stripe_customer_id`, `elevenlabs_agent_id`. Add `onboarding_status` (`pending|active|failed`) if a CRM-visible status is wanted.

## 6. The three onboarding emails

Add to `billing_notifications.py` (same `record_notification` + `_maybe_dispatch_email` chain, German copy, deduped on `checkout_session_id`):
- `notify_onboarding_started(org_id|email)` — "Wir richten Ihren Account ein."
- `notify_twilio_number_assigned(org_id, phone)` — "Ihre Rufnummer <phone> ist aktiv."
- `notify_crm_account_created(org_id, login_url)` — "Ihr CRM-Konto ist bereit. Jetzt anmelden."

These can be sent by n8n (HTTP nodes) or by the backend at each step. Backend is preferred (one templating path, testable). **Stripe still owns the payment receipt + invoice email** — do not duplicate it.

## 7. Security / correctness checklist

- `STRIPE_WEBHOOK_SECRET` must be set in prod (live-key boot guard already enforces this — `config.validate_runtime_config`). Locally the `POST /api/billing/sync` fallback covers the missing webhook.
- n8n↔backend authenticated **both ways**: `MASTER_WEBHOOK_SECRET` (n8n→/provision) and `N8N_SHARED_SECRET` (backend→n8n).
- Idempotency keyed on `checkout_session_id` end-to-end (dispatch, agent create, number purchase, provision) so Stripe retries / n8n re-runs never double-provision or double-buy a number.
- Email/phone identity: payer email = login email = org contact; phone stored on the org (§3.4).
- Outbound scope guard: appointment-epic `OUTBOUND_TEST_SCOPE_ONLY` does NOT gate `send_email()`; onboarding emails will actually send. Confirm sender/Reply-To with Amber (email-send is Amber's track).

## 8. Effort & sequencing

| # | Item | Where | Effort | Depends on |
|---|---|---|---|---|
| 1 | `onboarding_events` table | migration (additive) | S | — |
| 2 | `onboarding_dispatch` + webhook fan-out (flagged inert) | `stripe_webhook.py`, new svc, `config.py` | M | 1 |
| 3 | 3 onboarding email helpers | `billing_notifications.py` | S | — |
| 4 | `create_agent_from_template` + `allocate_twilio_number` + `bind` | new `onboarding_provision.py` | L | — |
| 5 | `POST /api/heykiki/onboard` (agent→number→provision, idempotent) | new route | M | 4 |
| 6 | `stripeCustomerId` on `ProvisionRequest` + org insert | `schemas/provision.py`, `provisioning.py` | S | — |
| 7 | n8n workflow rewire to call `/onboard` + send emails | `n8n_heykiki_provision.json` | M | 2,5 |
| 8 | Public pre-payment funnel (Checkout w/ metadata) | external repo | L | §3.4 |

Recommended order: **3 → 1 → 2 → 6 → 4 → 5 → 7 → 8**. Ships inert until `N8N_ONBOARDING_ENABLED=1` + the funnel is live, so it can land behind the current flow safely (local = UAT; no prod deploy without Amber's approval).

---

## 9. Already shipped on this branch (CRM-side, the "inside the CRM" part of the goal)

Built + verified 2026-06-20 (local UAT only):
- **In-CRM Upgrade flow** — `POST /api/billing/change-plan` (`billing.py`) → `stripe_provisioning.change_subscription_plan` swaps base+metered items in place (proration on, upgrade-only guard via `stripe_catalog.plan_rank`), then `/sync`. Frontend "Tarif upgraden" picker on the Abrechnung card (only shows higher tiers). Verified live: Team→Premium swapped both items, reverted clean.
- **Explicit extra-usage UI** — `BillingSummary` gains `overage_cents_per_min` / `minutes_over` / `projected_overage_cents`; Abrechnung renders a "Mehrverbrauch (Extra-Nutzung)" panel (included / used / over / tariff / projected charge). Verified: 313/250 → +63 Min × 0,75 € = 47,25 €.
- **2nd pre-overage warning** — `billing_notifications.check_and_notify_over_quota` now fires at **80 % (first)** and **95 % (final)** before the over-quota alert, each deduped per period; matching front-end banners. Unit-tested.
