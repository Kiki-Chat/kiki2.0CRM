# MIGRATION PLAN — Personal → Company EU Production

*Move KikiJarvis from the current setup (your personal Railway + Supabase **ap-northeast-1 / Tokyo**) to the company's **EU** production (GDPR-correct for German customers), and switch on the pay-upfront strategy with **live** Stripe keys. This is a runbook + the decisions you must make first. Nothing here is automatic — treat it as a checklist.*

## 0. Current topology (what we're moving)
- **Backend + Frontend + Redis:** Railway project `kikijarvis-backend` (backend svc `f6ec2789`, frontend `76b5084b`, env `production`), domains `backend-production-3f88a` / `frontend-production-4bdf`.
- **Database + Auth + Storage:** Supabase `ifbluvdcbcesuhvkxsfn` (region **ap-northeast-1** ⚠️ not EU), 76 migrations (`supabase/migrations/0001…0076`), `customer-files` storage bucket, Supabase Auth users.
- **External:** ElevenLabs (voice agents), Stripe (TEST keys today), Brevo (email), Google OAuth (calendar), n8n (provisioning).

## 1. Decisions to lock BEFORE migrating (these shape the code/infra)
| # | Decision | Recommendation |
|---|---|---|
| D1 | Who creates the org+login — n8n (after payment) or the Stripe webhook? | **n8n** calls `POST /api/heykiki/provision` (bind-only) after payment; the webhook only **ties payment by email+mobile** + activates. Keeps one provisioning path. |
| D2 | How does the buyer log in (they came from a form, no password)? | Supabase **magic-link / set-password invite** at provision time (don't require a typed password in the form). Needs a small change to `provision_org` (today it requires a password). |
| D3 | Match precedence | **email AND mobile** → auto-link (already built); email-only → super-admin review queue (already built). |
| D4 | Billing gate on CRM login? | Recommend **yes** eventually (block login until `billing_status` active) — but ship as a follow-up; today `disabled_at` is the only gate. |
| D5 | EU host: stay on Railway (EU region) or move to company cloud? | **Railway EU region** is the lowest-effort GDPR-correct move; a company AWS/Hetzner EU host is more work. Decide based on company policy. |
| D6 | Supabase EU project: migrate data or start fresh? | New customers are pay-upfront, so a **fresh EU Supabase project** (schema only, minimal seed) is cleanest if you don't need to carry the ~17 legacy orgs; otherwise do a full data export/import (§3). |
| D7 | Keep the in-CRM self-serve "Tarif wählen" subscribe card? | **Remove** it (new model = pay on the marketing site). Small frontend deletion (`SettingsPage` subscribe card) — deferred until you confirm. |

## 2. Provision the new EU infrastructure (company account)
1. **Supabase (EU):** new project in **eu-central-1 (Frankfurt)** under the company org. Note its URL + anon key + service-role key + JWT settings.
2. **Apply schema:** run all `supabase/migrations/0001…0076` against the new project (Supabase CLI `db push`, or apply in order). Then run `get_advisors(security)` → should match the current 6-intentional-items baseline.
3. **Storage:** create the `customer-files` bucket (private) with the same path convention (`{org}/...`).
4. **Railway (or chosen host), company account, EU region:** create backend + frontend + Redis services; set backend root dir = `backend`, frontend root dir = `frontend` (or deploy backend with `--path-as-root backend`).
5. **Domain:** company domain (e.g. `app.heykiki.de` + `api.heykiki.de`). Point DNS; get TLS.

## 3. Data migration (only if D6 = carry legacy data)
- **DB:** `pg_dump` the public schema data from the old project → `pg_restore`/`psql` into the new EU project (schema already applied). Watch RLS — restore as the service role/owner.
- **Auth users:** Supabase `auth.users` don't move with a plain `pg_dump` of `public`. Use Supabase's auth migration (export users + re-import, or the dashboard's project-migration tooling). Password hashes carry; magic-link users re-invite.
- **Storage:** copy the `customer-files` objects (Supabase Storage migration / `rclone` between buckets).
- **`org_secrets`:** these are **Fernet-encrypted with `SETTINGS_ENC_KEY`**. To carry them, **reuse the same `SETTINGS_ENC_KEY`** on the new backend; otherwise decrypt-on-old + re-encrypt-on-new. Do **not** lose this key.

## 4. Secrets / env vars on the new backend (set ALL before first boot)
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (new EU project) · `SETTINGS_ENC_KEY` (same as old if carrying `org_secrets`) · `BACKEND_PUBLIC_URL` (= new api domain — **critical**, drives EL webhook + OAuth redirects).
- `ELEVENLABS_API_KEY` (company EL workspace) · `CORS_ORIGINS` (= new frontend origin).
- **Stripe LIVE:** `STRIPE_SECRET_KEY` (live), `STRIPE_WEBHOOK_SECRET` (live endpoint signing secret), price/product config.
- `BREVO_API_KEY` + `BREVO_SMTP_*` · `GOOGLE_CLIENT_ID/SECRET` · `OUTBOUND_TEST_SCOPE_ONLY` (set `1` until you're ready for real outbound, then `0`).
- `COPILOT_MONTHLY_COST_CAP_USD` (default 25) · `COPILOT_ENABLED`.
- **Frontend build args** (baked at build time — see `frontend/Dockerfile`): `VITE_API_URL` (= new api domain), `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_COPILOT_ENABLED`.

## 5. Stripe go-live (live keys = yours, for production)
1. With the **live** key, run `ensure_catalog()` (stripe_catalog) once → creates/links the live Solo/Team/Premium base+metered prices (VAT **exclusive**). Verify `find_plan_prices()` resolves all three.
2. Register **Stripe Tax** for DE.
3. Create the **live webhook endpoint** → `https://<api domain>/api/billing/stripe-webhook`; subscribe to `checkout.session.completed`, `customer.subscription.*`, `invoice.*`; copy its **signing secret** into `STRIPE_WEBHOOK_SECRET`.
4. Confirm **no trial** (we removed `DEFAULT_TRIAL_DAYS`) and **no self-serve plan change** (portal config already blocks it).

## 6. ElevenLabs + n8n (the external agent seam)
- **n8n** must, per org: create the EL agent + 11 `hk_` tools + German prompt, buy/assign a phone number, set the agent's **conversation-init webhook** to `https://<api domain>/api/elevenlabs/conversation-init` with the `X-HeyKiki-Secret` header, then call `POST /api/heykiki/provision` (master secret) with `agent_externally_managed=true`, `elevenlabs_agent_id`, `phone_number`, `elevenlabs_phone_number_id`, plus the customer email+mobile+plan.
- The CRM **binds + verifies** (does NOT re-render the agent). Run the bind, then `verify_agent_health` should be green.
- Update the **master secret** + the n8n target URL to the new backend.

## 7. Cutover sequence
1. Freeze writes on the old system (maintenance note).
2. Final data sync (§3) if carrying data.
3. Point DNS to the new EU services; verify TLS.
4. Smoke test (§8) on the new prod.
5. Flip `OUTBOUND_TEST_SCOPE_ONLY=0` only when ready for real customer calls/emails.
6. Decommission the personal-account services after a grace period.

## 8. Go-live smoke test (new prod)
- `GET /api/health` = ok · `GET /api/openapi.json` ≈ 230 paths · frontend `/` = 200.
- Supabase advisors = 6 intentional items.
- One real onboarding: marketing form → live Stripe pay → webhook ties by email+mobile → n8n provisions+binds → buyer logs in (magic link) → agent answers a call → records an inquiry. (Use a controlled number.)
- Enable leaked-password protection in the new Supabase Auth (audit item **3.4**).

## 9. Rollback
- DNS back to the old services (kept warm during the grace period).
- Stripe: keep the old webhook endpoint disabled-not-deleted until the new one is proven.
- Because the new EU DB is separate, a rollback loses only data created during the cutover window — keep that window short.

---
### Code status feeding this plan
- **Done + LIVE (current prod):** Batches 1–9.
- **Done, committed, HELD for your test→merge:** trial removal, n8n bind-only seam, email+mobile webhook tie.
- **Deferred (need your decision, see §1):** login mechanism (D2), billing gate (D4), removing the in-CRM subscribe card (D7), the public marketing-site checkout endpoint (depends on whether checkout starts pre-CRM).
- **Your manual items:** live Stripe keys (§5), Supabase leaked-password toggle (3.4), the n8n workflow + marketing form.
