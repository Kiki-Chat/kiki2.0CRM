# Stripe Billing — Phase 1 Manual UAT Checklist

**Scope:** LOCAL/UAT only. Code is committed to origin/main but **NOT deployed to Railway**.
The module is gated OFF by default; nothing here can touch real customers or money.

**Key placement:** put the Stripe **TEST** key (`sk_test_…`) in **local `backend/.env`** — NOT Railway.

---

## Part A — Testable NOW (no Stripe key needed)

1. **Billing UI shows** — log in (test org) → *Einstellungen → Abrechnung*.
   - ✅ "Aktueller Tarif: Kiki Solo", Status "Aktiv", **"Zahlungsdetails verwalten"** button, "KI-Minuten X / 99" bar.

2. **Over-quota banner (soft-stop notification)** — lower the org's `billing_quota_minutes` below used → reload.
   - ✅ Amber banner: *"Kontingent aufgebraucht – Mehrverbrauch wird berechnet"* + red bar. (Ask me to flip it on.)

3. **Unconfigured fallback** — an org with no Stripe link → Abrechnung shows only usage KPIs + support note (no plan card/button). This is what you saw before I seeded the test org.

4. **Super-admin dashboard** — log in at `/admin` (super-admin) → **Abrechnung** tab.
   - ✅ Overview cards (orgs / delinquent / unlinked / MRR / YTD), Stripe-health panel, customer-match review queue, per-org billing table.

5. **Inert when off** — unset `STRIPE_BILLING_ENABLED` → app behaves exactly as before (no billing routes).

---

## Part B — Testable AFTER you drop a TEST key into `backend/.env`

6. **Manage payment (portal)** — click "Zahlungsdetails verwalten" → redirects to the Stripe-hosted billing portal (change card / view invoices).
7. **Invoices + next amount** — real invoice list + next-invoice amount render.
8. **Webhook sync** — trigger `invoice.payment_failed` (I set this up) → org status flips to "Zahlung überfällig".
9. **Usage reporting** — enable `STRIPE_USAGE_REPORTING_ENABLED` → complete a test call → exactly one usage record posted (a retry posts nothing).
10. **Trial / payment-fail / retry** — via Stripe test clocks (I run these).

---

## NOT built yet — these are **Phase 2** (the flows you described)

- **New-customer Checkout** (subscribe with pre-filled details). Phase 1 only *manages existing* customers via the portal; it does not *create/subscribe* new ones.
- **Trial → trial-end lockout** ("deadlock" when the trial ends without payment).
- **Email/push notifications** on over-quota (Phase 1 = the in-app banner only).
- **Live customer↔org link** write-back (approve in the super-admin review queue).
