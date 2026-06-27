# Stripe Onboarding + Legacy Migration — Implementation Spec

Status: **spec only — NOT built.** Captures every decision/clarification from the
2026-06-26…28 sessions so this can be implemented in one go later. The surrounding
billing + entitlements system (referenced below) **is** built and deployed.

---

## 0. Where we already are (built + deployed)

- **Live Stripe catalog** (Basis/Legacy/Pro/Enterprise) — created via `POST /api/super-admin/billing/ensure-catalog` (master-secret guarded; run once per Stripe mode).
- **Subscribe flow** — `POST /api/billing/checkout-session`: subscribe-first UI, `automatic_tax`, `phone_number_collection`, `client_reference_id=org_id`, `payment_method_collection="if_required"` (no card when a 100%-off promo makes it €0), returns to the caller's `window.location.origin`.
- **Plan switch** — `POST /api/billing/change-plan` (up + down) with a prorated **preview** (`/change-plan/preview`).
- **Entitlements** (`backend/app/services/entitlements.py`): plan → feature keys + seat limits; `/api/me` returns `{plan_title, features, dev_plan_switcher}`. Frontend gates the nav (lock + soft preview) + routes (`FeatureRoute`). **Hard enforcement**: `require_entitlement()` → 402 on gated routers + copilot guardrail (`FEATURE_BY_TOOL`). Gated by env flag **`ENTITLEMENTS_ENFORCED`** (OFF in prod until cutover; fails open for no-plan orgs; super_admin bypass).
- **Seats**: Basis 1 · Legacy 5 · Pro 5 · Enterprise 10 — shown in plan cards, enforced on employee create/import/copilot.
- **Soft preview**: locked menu shows pitch + **blurred real-data teaser** ("Kiki hat aus deinen Anrufen X Angebote vorbereitet") from `GET /api/entitlements/teaser`.
- **Always-process** (Amber's decision): enforcement sits ONLY on customer routes + copilot — NOT the automation pipelines. A locked tier still accrues Vorgänge/Angebote server-side; upgrade unlocks the full history instantly.

## 1. Confirmed pricing + packaging (Amber 2026-06-26/27)

| Tier | Base €/mo | Incl. min | Overage €/min | Seats | Self-serve? | Features (cumulative) |
|---|---|---|---|---|---|---|
| **Kiki Basis** | 99 | 100 | 1.00 | 1 | ✅ | Kiki (Anrufe qualifizieren), Kontakte, Geschäftszeiten, Begrüßungen |
| **Kiki Legacy** | 179 | 200 | 0.75 | 5 | ❌ grandfather | Basis + Vorgänge + Aufträge + Basic Notizen (manuell) |
| **Kiki Pro** | 249 | 200 | 0.75 | 5 | ✅ | Basis + Vorgänge, Planungstafel, Kalender/Termine, Automatische Notizen (KI) |
| **Kiki Enterprise** | 599 | 750 | 0.50 | 10 | ✅ | Pro + Projekte, Finanzen (Angebote/Rechnungen), Artikel/Katalog, ERP, API |

- Prices NET; **19 % MwSt** added at checkout via Stripe Tax (`tax_behavior=exclusive`).
- Annual = 10× monthly (2 months free).
- **Usage = inbound + outbound minutes combined** (already the case — no direction filter anywhere).
- Gated MENUS (today): `cases`, `calendar`, `planning`, `projects`, `finance`. Sub-features (Aufträge, KI-/Basic-Notizen) deferred to a later sub-feature gating pass.

## 2. Payment-first ONBOARDING (new public signup) — to build

**Core principle (Amber's correction): the CRM org is created ONLY after Stripe confirms payment.** No org before money — otherwise orphan accounts. So the binding key BEFORE payment is an **onboarding token**, not `org_id` (which doesn't exist yet).

### Flow
1. **Public onboarding form** (new page, no auth) collects: company name, contact name, **email**, **phone**, billing address, trade, and the **chosen plan** (Basis/Pro/Enterprise — Legacy is never offered to new signups).
2. Backend creates an **onboarding lead** row + a Stripe **Checkout session WITHOUT an org**:
   - `client_reference_id = <onboarding_token>` (the lead id), NOT org_id.
   - `metadata` = the form fields (or just the lead id; read the lead on webhook).
   - Stripe customer prefilled with name/email/phone/address.
   - The form's plan step IS the "choose plan" screen — gives time to bind the lead before redirecting to Stripe.
3. User pays on the prefilled Stripe page (`automatic_tax`, `phone_number_collection`, `payment_method_collection` per the existing checkout).
4. **Webhook `checkout.session.completed` is the trigger** → read the lead via `client_reference_id`/metadata → **create the org**, link `stripe_customer_id` + subscription, set `billing_plan_title`, provision (EL agent / Twilio / etc. per `ONBOARDING_ORCHESTRATION_SPEC.md`), send credentials email, mark the lead `converted`.
5. Subsequent `customer.subscription.*` / `invoice.*` events sync as today.

### What to build
- `onboarding_leads` table (token/id, form fields, stripe_session_id, status: created|converted|abandoned, created_at). Additive migration.
- Public endpoint `POST /api/onboarding/start` → creates lead + checkout, returns checkout URL. (No auth; rate-limit.)
- Extend `stripe_webhook._handle` for `checkout.session.completed` **when there's no org yet**: branch on a lead reference → org-creation/provision path. (Today's handler links to an existing org via `heykiki_org_id`; add the lead branch.)
- Public onboarding page (frontend) — form + plan picker → calls `/api/onboarding/start` → `window.location = checkoutUrl`.
- Welcome email with login/set-password link (uses `FRONTEND_PUBLIC_URL`).

### Open inputs needed from Amber
- Exact form fields + which are required.
- Whether a trial is offered on the public funnel (today checkout has no trial).
- Provisioning depth at signup (EL agent + Twilio number now, or later) — see `ONBOARDING_ORCHESTRATION_SPEC.md` (n8n fan-out is the planned mechanism).

## 3. Legacy MIGRATION (existing ~80 customers) — to build

**Decisions:** the ~80 legacy customers are in the **SAME Stripe account we control** → in-place handling possible. **Link, don't re-bill** — their money stays where it is; the CRM reflects it. They land on the **Kiki Legacy** grandfather tier (hidden from new signups), keep their existing subscription, and can **upgrade in place** or **downgrade to Basis**.

### Flow
1. **Export** the ~80 from live Stripe (id, email, phone, current price, MRR, status). Amber provides this.
2. **Match → link**: reuse `backend/app/services/stripe_matcher.py` (`propose_matches`) → super-admin approve (`/api/super-admin/billing/matches/{id}/approve`) writes `stripe_customer_id` + `heykiki_org_id`.
3. **Assign tier**: stamp `billing_plan_title = 'Kiki Legacy'` (+ their included minutes) on the linked org. Optionally an `entitlement_overrides` grant for any custom grandfathered features (column not built yet — add if needed).
4. Customer logs in → sees Legacy features (Basis + Vorgänge + Aufträge) + the rest locked with the soft preview/teaser.
5. **Upgrade** = the existing in-place `change-plan` swap (same account). **Downgrade to Basis** = allowed (change-plan already permits down between self-serve tiers; Legacy→Basis works since Basis is self-serve).

### ⚠️ Reconcile before in-place writes
- The Stripe safety layer (`stripe_billing.py`) **refuses writes to Connect-attributed subs** (`subscription.application != null`). VERIFY the legacy subs' attribution; if Connect-attributed, either whitelist them for the migration action or create a fresh native subscription on upgrade.
- A free-tier (or Once-coupon) customer with **no card on file** who upgrades to a paid plan needs a card-collection step (Stripe portal "add payment method" or a setup checkout) before the prorated charge can collect.

### What to build
- A super-admin "assign Legacy" action (or extend approve) to set `billing_plan_title='Kiki Legacy'` on link.
- (Optional) `organizations.entitlement_overrides jsonb` for per-org grandfather grants/comps/add-ons (the resolver already supports `{grant:[],revoke:[]}` — just needs the column + to read it in `_org_plan_and_features`/`_org_entitlements`).
- Connect-attribution reconciliation for the upgrade path.

## 4. Stripe coupons / discounts (gotcha)

- A coupon's **duration** controls carry-over: **"Forever/Permanent" applies to EVERY invoice including after an upgrade** (why a demo upgrade was also €0). For real promos and demos where the upgrade should be charged, use **"Once"** (or limited-duration).
- `allow_promotion_codes` is on at checkout; `payment_method_collection="if_required"` means a 100%-off promo → €0 → no card prompt.

## 5. Stripe Dashboard config (ops, Amber's side)

- **Branding** (Settings → Branding): logo + icon, Brand color `#4A9B3F`, Accent `#2D6B3D` — brands Checkout + Portal + invoices + emails.
- **Customer portal** (Settings → Billing): **turn OFF "Customers can change plans"** (otherwise it shows Stripe's raw proration lines; plan changes happen in-app). Keep Invoices + Update payment method ON; Cancellations per policy (support-only → OFF).
- **Stripe Tax**: must be ACTIVE in live or checkout 402s on `automatic_tax`.
- **Live webhook**: register `…/api/billing/stripe-webhook` for `checkout.session.completed`, `customer.subscription.*`, `invoice.paid|payment_succeeded|payment_failed`; set its signing secret as `STRIPE_WEBHOOK_SECRET`.
- **`FRONTEND_PUBLIC_URL`** on the **prod backend** → `https://crm.kikichat.de` (drives emailed links + portal return). Currently mis-set to the raw `forntend-…` railway domain.

## 6. Config flags

| Flag | Purpose | Prod | UAT |
|---|---|---|---|
| `ENTITLEMENTS_ENFORCED` | hard 402 + copilot guardrail + seat limits | **0** until cutover | 1 (for testing) |
| `DEV_PLAN_SWITCHER` | 🧪 in-CRM plan toggle (no Stripe) for QA | **0** (never) | 1 |
| `STRIPE_BILLING_ENABLED` | mount billing routes | 1 | 1 |
| `STRIPE_USAGE_REPORTING_ENABLED` | report per-call minutes to Stripe metered item | 0 | 0 |

## 7. Key files / endpoints

- Catalog/prices: `backend/app/services/stripe_catalog.py` (PLANS) · ensure: `/api/super-admin/billing/ensure-catalog`.
- Checkout/upgrade/preview/dev-set-plan: `backend/app/api/routes/billing.py` + `stripe_provisioning.py`.
- Entitlements (features, seats, enforcement): `backend/app/services/entitlements.py`.
- `/api/me` (features, plan, dev flag) + teaser: `backend/app/api/routes/me.py`.
- Frontend gating: `frontend/src/components/FeatureGate.tsx`, `lib/entitlements.ts`, `lib/useMe.ts`, `components/layout/{nav.ts,Sidebar.tsx}`, `App.tsx`.
- Matcher/admin: `backend/app/services/stripe_matcher.py`, `app/api/routes/billing_admin.py`.
- Related: `ONBOARDING_ORCHESTRATION_SPEC.md` (provisioning fan-out), `STRIPE_PHASE2_HANDOVER.md`.

## 8. TODO checklist (for the implementer)

- [ ] `onboarding_leads` table + `POST /api/onboarding/start`.
- [ ] Webhook `checkout.session.completed` lead → org-creation branch + provisioning + welcome email.
- [ ] Public onboarding page (form + plan picker).
- [ ] `entitlement_overrides` column + read it in the resolver (for grandfather grants/add-ons).
- [ ] Super-admin "assign Legacy on link" action.
- [ ] Connect-attribution reconciliation for legacy upgrades; card-collection-on-upgrade for no-card customers.
- [ ] (Optional later) sub-feature gating (Aufträge, KI-/Basic-Notizen); rich soft preview (video).
- [ ] Prod cutover: flip `ENTITLEMENTS_ENFORCED=1` after all orgs have plans; set `FRONTEND_PUBLIC_URL`; Dashboard branding/portal/Tax/webhook.
