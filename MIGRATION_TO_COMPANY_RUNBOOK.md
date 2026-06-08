# Migration runbook — personal stack → company stack (GitHub + Supabase + Railway), white-labeled

Status: **PLAN ONLY — not started.** Needs the company accounts + a maintenance window. Do this AFTER the open CRM bugs are closed and a DB verification pass is possible.

## The fork question (important — your premise is half-right)
**A plain GitHub fork does NOT auto-sync.** Pushing to your personal repo does **not** propagate to a fork; a fork only shares history at creation time. To get "changes I make in my repo reflect into the company repo", you need an explicit **one-way push-mirror**, not a fork's natural behaviour.

**Recommended:** keep your personal repo `imamber20/kikijarvis-crm` as the source of truth and add an **automated push-mirror** to the company repo:
- **Best:** a scheduled + on-push **GitHub Action in the personal repo** that pushes `main` + tags to the company repo using a company-org deploy token. (`git push --mirror` style, but scoped to `main`/tags so you don't clobber company-only branches.)
- **Simplest:** `git remote set-url --add --push origin <company-url>` locally so one `git push` writes both remotes (works only from your machine; the Action is more robust for cron/CI).
- Make the company repo a **fork only for the visible "forked-from" link** — the mirror is the real sync.
- **Avoid:** repo *transfer* (you lose ownership/control) and two hand-edited repos (they diverge).
- **Company Railway then auto-deploys from the company `main`.** (Your personal Railway stays manual `railway up`, as today.)

Net topology: you edit personal → Action mirrors to company `main` → company Railway auto-deploys prod. Your personal Railway/Supabase become the **UAT mirror** (keep `OUTBOUND_TEST_SCOPE_ONLY=1` there permanently so UAT never calls real customers).

## Runbook

### P0 — Prep (no changes yet)
- Decide the **app + api DNS** names and the **brand strings** (name, logo, email from-name) — is this a rebrand or only a domain/ownership change?
- Confirm the **company Supabase** plan handles the data volume + PITR, and the **company Railway** is the paid plan.
- **Snapshot personal counts** at run time: `auth.users`, every public table, storage buckets/objects, applied migrations.
- **Inventory ALL personal Railway env vars** — many are NOT in the repo `.env`. Critical: `SETTINGS_ENC_KEY` (app-level at-rest encryption — if it changes, every stored secret/credential becomes undecryptable), Brevo SMTP keys, ElevenLabs/OpenAI/Twilio/Stripe keys, `MASTER_WEBHOOK_SECRET`.
- Set `OUTBOUND_TEST_SCOPE_ONLY=1` on personal during cutover so nothing fires at real customers mid-migration.

### P1 — GitHub
1. Create the company repo as a **fork** of the personal repo (for the link).
2. Add `.github/workflows/mirror.yml` in the **personal** repo: on-push to `main` + a `~15m` cron (GitHub cron can lag up to ~1h and only runs on the default branch), pushing `main`+tags to the company repo via a company-org token secret.
3. Branch-protect the company `main`.
4. Verify a test commit propagates personal → company within the window.

### P2 — Supabase (fresh company project; pg_dump/restore — NOT project-transfer)
> Project-transfer keeps the same project ref and gives you no independent second stack, so it can't serve as prod-distinct-from-UAT. Use a fresh project.
1. Create the company project; record its **ref / URL / anon key / service-role key**.
2. Apply migrations **0001 → 0051 in order** (0050 = phone2 index, 0051 = address_text — both from the current branch).
3. **Create the `org-assets` storage bucket** (it has no migration today — ideally add one; per-tenant logo/accent depend on it).
4. **Migrate AUTH users FIRST, preserving their UUIDs** — `public.users.id` FKs to `auth.users.id`, so restoring public data before auth breaks the FK.
5. `pg_dump` **public data-only** and restore *after* auth exists.
6. **Re-upload all storage objects** so paths match (`org_id/customer_id/...`).
7. **Copy `SETTINGS_ENC_KEY` unchanged** (it's an app secret, not a Supabase key).
8. Parity-check row counts vs the P0 snapshot.

### P3 — Railway (company project: frontend + backend + Redis)
1. Create the 3 services from the existing Dockerfiles.
2. Set backend env, swapping: `SUPABASE_URL` + service-role, `CORS_ORIGINS`, `BACKEND_PUBLIC_URL`, `FRONTEND_PUBLIC_URL`, `REDIS_URL`, `APP_ENV=production`; **carry `SETTINGS_ENC_KEY`**, webhook secrets, ElevenLabs/OpenAI/Twilio/Brevo/Stripe keys. Keep `OUTBOUND_TEST_SCOPE_ONLY=1` until smoke-tested.
3. Repoint: OAuth redirect URIs, the **Supabase Auth redirect allow-list**, the **ElevenLabs + n8n webhooks**, and the **Stripe webhook URL + signing secret**.
4. Deploy backend from company `main`.

### P4 — White-label + DNS
1. Set the **frontend Railway BUILD ARGS** (runtime env does NOT work — Vite inlines `VITE_*` at build time; see `frontend/Dockerfile`): `VITE_API_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_COPILOT_ENABLED` → company values. **Any new `VITE_*` flag must be added to `frontend/Dockerfile`** or it bakes as undefined.
2. Add Railway **custom domains** + registrar CNAMEs; wait for TLS.
3. Swap brand strings / email from-name if rebranding (per-tenant logo/accent already work via org settings once `org-assets` exists).
4. Rebuild frontend; confirm it points at the **company** URLs.

### P5 — Cutover + verify
- Smoke-test: login, customer list, a test call ingest, dashboard, Kiki-Zentrale, billing summary.
- Flip `OUTBOUND_TEST_SCOPE_ONLY=0` on company only when confident.
- Point production DNS at the company frontend; keep personal as UAT.

## HIGH-risk failure modes (read before starting)
- **`SETTINGS_ENC_KEY` mismatch** → every at-rest credential (org secrets, OAuth tokens) becomes undecryptable. Copy it exactly.
- **Auth users restored after public data** → `users` FK breaks. Auth first, UUIDs preserved.
- **`org-assets` bucket missing** → per-tenant logos 404.
- **Frontend env set at runtime instead of build args** → app talks to the old (personal) backend. Must be build ARGs.

## Decisions needed from you
1. Rebrand (name/logo/from-address) or only domain + ownership change?
2. Confirm: personal = UAT (scope-only=1 permanently), company = prod auto-deployed from company `main`, synced via the mirror Action — yes?
3. Can the company Supabase plan carry the data volume + PITR? Can auth password hashes be carried, or must users reset?
4. UAT data-refresh cadence + PII policy (how often to pull prod data down to the personal UAT stack, and whether to anonymize).
