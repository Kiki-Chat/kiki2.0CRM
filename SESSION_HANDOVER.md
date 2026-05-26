# KikiJarvis CRM — Session Handover (for the Kiki-Zentrale build)

> Paste this as starting context. Read `HANDOVER.md` for full detail. Scannable summary below.

## Recent changes
_Append one dated bullet per shipped, UI-visible change. Newest first._

- **2026-05-26:** **KVA `sent_at` stamp fix (follow-up to P0.5 side-finding).** `backend/app/api/routes/cost_estimates.py::set_status` was building its stamp map inline as `{"accepted": "accepted_at", "rejected": "rejected_at"}.get(payload.status)` — missing `"sent": "sent_at"`. So any PATCH to `/api/cost-estimates/{id}/status` with `status="sent"` would update only `status` and leave `sent_at` NULL, which silently kills the AI Insights `kva_followup` suggestion (the `_ai_insights` defensive `if sent` guard skips NULL-`sent_at` rows). `CostEstimateStatus` schema docstring explicitly lists `sent` as a valid status, so the bug was reachable even though no current frontend caller hits it (frontend only sends `'accepted'`; the `POST /send` route still correctly stamps `sent_at`). Fix lifts the stamp map to module scope as `_STAMP = {"sent": "sent_at", "accepted": "accepted_at", "rejected": "rejected_at"}`, mirroring `invoices._STAMP`. 4 new tests in `backend/tests/test_cost_estimate_status_stamp.py` (sent stamps sent_at · accepted stamps accepted_at + no cross-stamp · rejected stamps rejected_at · draft/invoiced stamp nothing). Full backend suite: `35 passed in 59s`. **Existing row KVA-2026-00001** (`id=6a6e394a-939a-41d5-8e0b-606ae96c5405`, test org) is almost certainly seeded/manual-SQL data (no reachable frontend path produces this state); backfill `update cost_estimates set sent_at = updated_at where id = '6a6e394a-939a-41d5-8e0b-606ae96c5405' and sent_at is null` is **queued for Amber** to authorise + run via Supabase MCP. Commit `42fa6fa`.

- **2026-05-26:** **P0.5 — AI Insights tab empty-state polish + diagnosis.** Probed `_ai_insights('c4dbf596…')` directly via `/tmp/probe_ai_insights.py`: returns a clean, well-shaped response (`enabled=true`, `kpis` all 0, `suggestions=[]`). The 'broken' symptom in the sprint was actually the **correct rendering** — current test-org data has zero actionable items (1 sent-but-undated KVA caught by the `if sent` defensive guard, 1 not-yet-overdue invoice with due_date 6 days in the future, 7 customers all <3 days old). **No code bug.** Polish: `KiInsightsTab.tsx` empty state now has a larger CheckCircle2 in a tinted disc + "Sie sind auf dem Laufenden!" heading + explanatory sub-line listing WHAT this tab surfaces (KVA-Nachfassen, überfällige Rechnungen, inaktive Kunden), so the empty state reads as "nothing to do" rather than "broken". Typecheck clean. **Side finding spawned as background task (chip up for Amber):** KVA-2026-00001 has `status='sent'` but `sent_at=NULL` — separate investigation into the KVA-send-flow status-transition path. Commit `82adfdf`.
- **2026-05-26:** **P0.4 — Gmail-style read/unread state for calls.** Migration `0017_call_read_state` adds `calls.read_at timestamptz null` (NULL = unread, the default) + partial index `idx_calls_unread on (org_id) where read_at is null` for fast badge counts. Backend `POST /api/calls/{id}/mark-read` (idempotent — only sets `read_at = now()` when currently NULL, so the first-opened timestamp is preserved on reopens). Dashboard `/overview` adds `kpis.unread_calls`. **Frontend visual:** CallLogsPage list items use `font-semibold text-text` (caller name) + `text-body` (summary) when unread, `font-medium text-muted` / `text-muted` when read. Mark-read mutation fires on `selectedId` change when the call is unread; invalidates `['calls']` + `['dashboard', 'overview']` so the sidebar Anrufe badge decrements live. **AppLayout.tsx now sources the badge from a real `/api/dashboard/overview` query** — replaces the hardcoded `{ calls: 3 }` that was always 3 regardless of state. Sidebar badge auto-hides at 0 (existing falsy check). Typecheck clean; backend `31 passed in 65s`. Browser-visual loop verification deferred to next deploy (no local backend per "your own terminals"). Commits `227117e` (migration) + `35798a2` (code).
- **2026-05-26:** **P0.3 — `started_at` fallback cascade.** `backend/app/services/post_call.py` `_process_one` was setting `started_at=NULL` whenever `metadata.start_time_unix_secs` was missing (e.g. Petra Linktest row `conv_LINKTEST_1` rendering as "Eingehend · — · 1:00"). Now cascades through `metadata.start_time_unix_secs` → `metadata.start_time` → `phone_call.start_time_unix_secs` → `datetime.now(utc)` as last resort, with `float()` parsing guarded so malformed values fall through instead of raising. **`started_at` is now guaranteed non-NULL on every persisted call row.** Backfilled the Petra row directly (`started_at = created_at`, the webhook-receipt proxy) — confirmed 0 NULL `started_at` rows remain in the test org. 5 new tests in `backend/tests/test_post_call_started_at.py` (each cascade path + malformed-value guard); 9 post_call tests pass in 0.30s. Commit `717947c`.
- **2026-05-26:** **P0.2 — SELECT-first dedup on post-call retries.** `backend/app/services/post_call.py` `_process_one` now short-circuits with `status="skipped", skip_reason="already_processed"` when an N8N/ElevenLabs retry arrives with a `conversation_id` whose call row is already fully processed (`status=completed` AND `summary` or `transcript` present). Partial rows (first webhook crashed mid-processing) are still allowed to complete on retry. Layered on top of the existing global `elevenlabs_conversation_id text unique` (0001:82) — the DB already blocked the duplicate INSERT; this kills the redundant `get_or_create_customer` / `broadcast_new_call` / `ensure_call_inquiry` work and gives the acceptance-criterion skip response. Skipped from sprint scope as redundant: (a) `(org_id, conv_id)` scoped unique (global already exists), (b) atomic tx (existing upsert-first + idempotent ensure_call_inquiry on `call_id` already guarantees it). 4 new tests in `backend/tests/test_post_call_dedup.py` (happy dedup · in-flight retry · false-positive guard on different conv_ids with same caller/start/duration · missing-conv_id regression). Full suite: `26 passed in 64.55s`. Also cleaned up the 2 Postman test rows (`b2e82cf9…`/`df9f97f2…` with `conv_TEST_pc_001`/`conv_PROD_pc_001`, 12min apart — not actual prod duplicates) + their inquiries (`ANF-2026-0008`/`ANF-2026-0012`); 0 duplicate groups remain in the test org. Commit `e54641a`.
- **2026-05-26:** **P0.1 — Hide tool-call ⚙ chips from customer-facing transcript.** `frontend/src/pages/CallLogsPage.tsx` Transcript render now gated on `me.data?.role === 'super_admin'`, prop-drilled `CallLogsPage → CallDetail → Transcript`. Chip data stays on the call object; only the visual is hidden. Default state for `org_admin` (kikitest01) = chips hidden. Typecheck clean (`npm run build`). Browser-visual verification of the `super_admin` path deferred until P0.6 creates one. Commit `80b72a6`.
- **2026-05-26:** **Emergency prompt fix on SAFE test agent** `agent_5001…`: stripped the `Step 3 — Appointment` **CATEGORY CHECK (MANDATORY)** block that limited bookings to maintenance only — repairs / defects / consultations / new-customer enquiries now flow through the booking path. Replaced 4 lingering `Husmann & Dreier` / `Husmann und Dreier` company-name references with `Murdock Law` (line-320 "Managing directors: Mr Husmann and Mr Dreier" intentionally untouched per Amber). Routed through `patch_agent_safely` (endpoint_label `prompt-editor`, same path as Kiki-Zentrale Prompt-Editor UI). **snapshot_id** `033ea496-5d19-4e1e-8b1c-357400f4b560`, **audit row** `3fe47535-1980-42d5-9b36-59a3f71d9338`, EL HTTP 200, no rollback. Prompt 52,877 → 51,734 chars; `first_message` / `client_events` / `tools` / `voice` / `language` unchanged. Rollback: Kiki-Zentrale → Verlauf & Rückgängig, or `rollback_to_snapshot(snapshot_id="033ea496-5d19-4e1e-8b1c-357400f4b560", actor_id=None)`. Patch script: `/tmp/patch_agent_category_check_fix.py` (not committed — one-off).
- **2026-05-26:** Deployed the full app on Railway (project `kikijarvis-backend`): new **frontend** service (Dockerfile → `serve` static SPA) at https://frontend-production-4bdf.up.railway.app, **backend** redeployed with the dashboard endpoints, `CORS_ORIGINS` updated to allow the frontend origin. See **Deployment (Railway)** below. ⚠ frontend build root must be `/frontend` (`railway up frontend --path-as-root`, or set Root Directory in the dashboard).
- **2026-05-26:** Dashboard tabs built — **Anrufe**, **Finanzen**, **KI-Nutzung**, **KI-Insights** (real aggregation endpoints in `dashboard.py`, recharts charts/sparklines). KI-Nutzung shows AI-minute-quota transparency (not timesheets). KI-Insights snooze/erledigt tracking via `ai_suggestion_actions` (migration 0016). **EN/DE language toggle removed everywhere** (`i18n.tsx`/`useLang`/`LangProvider` deleted; `language_preference` no longer read by the frontend, column kept in DB); the **frontend is now German-only**. Commits `ade6d3d`, `952eeba`.

## Deployment (Railway)
Both services live in the `kikijarvis-backend` project (env `production`):
- **Frontend** — service `frontend` → **https://frontend-production-4bdf.up.railway.app** (multi-stage `frontend/Dockerfile` → `serve -s dist` on `$PORT`). `VITE_API_URL` is baked at **build time** (Dockerfile ARG default) to the backend URL. Build root must be `/frontend`: deploy with `railway up frontend --path-as-root --service frontend`, or set the service's Root Directory to `/frontend` in the dashboard so plain `railway up` works.
- **Backend** — service `backend` → **https://backend-production-3f88a.up.railway.app** (`backend/Dockerfile`, gunicorn+uvicorn, Root Directory `/backend`). `CORS_ORIGINS` env must include the frontend origin.

**⚠ If the BACKEND URL changes, update every place that hardcodes it:**
1. ElevenLabs `hk_*` tool webhook URLs — re-run `scripts/create_hk_tools_safe.py <NEW_BASE_URL>`.
2. n8n → backend **post-call webhook** target.
3. ElevenLabs **Conversation Initiation Data Webhook Override** URL.
4. Frontend `VITE_API_URL` (Dockerfile ARG default) — rebuild + redeploy the frontend.
5. Backend `CORS_ORIGINS` (only if the frontend domain also changed).

**Changing the FRONTEND URL is easy** — nothing external points at it; just update the backend's `CORS_ORIGINS` to the new origin. To give it a friendlier name: either a custom Railway subdomain (e.g. `heykiki-crm.up.railway.app` — free, via the dashboard if the name is available) or a real custom domain like `app.heykiki.de` (own the domain + add the DNS CNAME Railway provides).

## 1. Current state
- **HEAD (main):** Kiki-Zentrale complete (this commit) — `feat: Kiki-Zentrale — full agent control with safety layer, snapshots, rollback, and audit`. Prior: `eb972ae` (docs: session handover).
- **Working tree:** clean, pushed to `origin/main`.
- **Modules complete:**
  - Shell + Auth (Supabase email/pw + magic link, protected routes)
  - Dashboard (Overview tab live; Calls/Finance/Time/AI tabs still placeholder)
  - Anrufe / Call Logs (3-pane, Realtime, audio-on-demand)
  - Kunden (list + detail, documents, inquiries)
  - Kalender (FullCalendar + Geschäftszeiten + Projekt-Timeline toggle)
  - Mitarbeiter (employees, absences, invites)
  - Planungstafel (drag-drop assets, Gantt)
  - Kostenvoranschläge / KVA (fpdf2 PDF, live preview)
  - Katalog & Vorlagen
  - **Rechnungen / Invoices** (migration 0012) — list/form/PDF, KVA→invoice
  - **Projekte** (migration 0013) — list/form/workspace (9 tabs) + Calendar timeline
  - **Einstellungen / Settings** (migration 0014) — `/settings/:section` + personal modal
  - **Kiki-Zentrale** (migration 0015) — `/kiki-zentrale/:section`, 13 sections (Verhalten, Prompt-Editor, Pflichtfelder, Branche & Kontext, Terminregeln, Terminkategorien, KVA-Automatisierung, Preisauskunft, Leistungsangebot, Notdienst, Telefon, Ausgehende Anrufe, Verlauf & Rückgängig). Safety layer `services/elevenlabs_agent.py`: cross-org guard → pre-write snapshot → additive array merge → **audio assertion** → surgical PATCH → post-write verify → **auto-rollback** → per-field audit. 35 endpoints; 8 unit + 6 live tests green; E2E 15/15.
- **Remaining: none — all CRM modules complete.**

## 2. Tech stack
- **Frontend:** React + TS + Vite, Tailwind (CSS-var design tokens), TanStack Query, React Router, Radix UI, FullCalendar, @dnd-kit. **Local-only** (`localhost:5173`, not on Vercel yet).
- **Backend:** FastAPI on **Python 3.13** (venv `backend/.venv`), deployed to **Railway** (`railway up`, NOT the MCP plugin). Runs locally **without `--reload`**.
- **DB:** Supabase Postgres, project `ifbluvdcbcesuhvkxsfn`. Migrations 0001–0014, applied via Supabase **MCP `apply_migration`** (no CLI). RLS scoped by `org_id`; backend uses service role (bypasses RLS).
- **Voice:** ElevenLabs agents (Kiki) via webhooks/N8N. **PDFs:** fpdf2 + bundled DejaVu fonts.

## 3. Test org credentials
- **heykikiOrgId:** `kiki-test-007`
- **organisationId (DB uuid):** `c4dbf596-86fd-4484-88d9-095b2c082afb`
- **Login:** `kikitest01@gmail.com` · password **held by Amber** (not stored in repo — ask before browser verification; don't type it yourself)
- **SAFE agent ID (use this):** `agent_5001ksahz3w7fhx90j71xr800py4`
- **DANGEROUS agent ID — NEVER use (live production):** `agent_7201kpabftdxftzaz735r6vezxpy`
  - ⚠️ This doc is the **only** intentional mention (as a warning). Any other occurrence in code/env = STOP.

## 4. Hard UX constraints (applied throughout — keep applying)
1. **Left sub-nav swaps content** — one section visible at a time, no endless scroll.
2. **One primary green save button** visible at a time per section.
3. **German UI labels** throughout (code/comments English).
4. **Lucide icons only.**
5. **TanStack Query `staleTime: 5 * 60 * 1000`** on all data fetches.
6. **Accent color as a CSS variable** (`lib/accent.ts applyAccent()` overrides `--green-*`) — never hardcode `#4a9b3f`.
7. **Deep-linkable sub-routes** (`/settings/{section}` pattern; `useParams`).
8. **Accordions start collapsed.**
9. **Action before diagnostic** (e.g. push: "Aktivieren" first, technical status collapsed below).
10. **No duplicated UI** between similar contexts (one shared component, e.g. placeholder chips for both invoice + KVA templates).

## 5. Kiki-Zentrale safety constraints (FRONT AND CENTER)
- **Additive provisioning only — never overwrite.** Do NOT replace `system_prompt` / `prompt`, `first_message`, or `client_events`. Merge/append; preserve existing values.
- **`client_events` must always include `"audio"`** — write the FULL required set, never a subset that drops audio (breaks call audio capture).
- **Duplicate-check on every write** — read current config first; only add what's missing (mirror `scripts/create_hk_tools_safe.py` idempotent pattern).
- **Read agent config via direct ElevenLabs API curl** — the Supabase/other MCP does NOT expose agent `tools`/`client_events`. Use:
  `curl -H "xi-api-key: $ELEVENLABS_API_KEY" https://api.elevenlabs.io/v1/convai/agents/<SAFE_AGENT_ID>` (`ELEVENLABS_API_KEY` is in `backend/.env`).
- **Never reference the production agent** `agent_7201…` in code, env, scripts, or API calls. Operate only on the safe agent / the test org's stored agent id.

## 6. Operational state
- **`SETTINGS_ENC_KEY`** = `sJFS7VeCfO-7XI5-fYUF0J-SfJOR5MhNm81hZGASlwI=`
  - Local `backend/.env`: **set** ✓ · `.env.example`: placeholder only ✓
  - Railway prod: **PENDING** — must be pasted into Railway env vars (same value) or the prod backend **refuses to boot** (Fernet key validated at import). Backend also won't decrypt stored SMTP/PDS creds without the matching key.
- **Backend prod health:** `https://backend-production-3f88a.up.railway.app/health`
- **Local run:** backend `cd backend && ./.venv/bin/uvicorn app.main:app --port 8000` (restart after edits — no `--reload`); frontend `cd frontend && npm run dev`.
- **Uncommitted work:** none (clean; this doc is the only pending file → committed in `docs: session handover for Kiki-Zentrale`).

## 7. Step 0 safety checks (run BEFORE any Kiki-Zentrale code)
1. **DB — stored agent is the safe one:**
   `SELECT elevenlabs_agent_id FROM organizations WHERE heykiki_org_id = 'kiki-test-007';`
   → must return `agent_5001ksahz3w7fhx90j71xr800py4`.
2. **Repo grep — dangerous ID absent from code:**
   `rg 'agent_7201kpabftdxftzaz735r6vezxpy' -g '!SESSION_HANDOVER.md'`
   → must return **zero matches** (exclusion skips this doc; a hit anywhere else = STOP).
3. **Railway env scan** — check no env var hardcodes any agent id (esp. `agent_7201…`); only `ELEVENLABS_API_KEY` should exist.
4. **ElevenLabs GET on the SAFE agent** — confirm `tools`, `client_events`, `prompt`/`system_prompt`, `first_message`, `language`, `voice_id` are all visible before mutating anything.

## 8. Known pitfalls (do not repeat)
- **Preview screenshots are stale/downscaled** → trust `preview_eval` DOM reads as authoritative.
- **Radix menus/dialogs don't open via synthetic `.click()`** → dispatch `pointerdown`+`pointerup`+`click`; set React-controlled inputs via the native value setter + `input` event.
- **Backend has no `--reload`** → restart uvicorn after backend edits or routes go stale (405).
- **Supabase MCP `execute_sql` returns only the LAST statement's result** for multi-statement queries — query one thing at a time.
- **`public.users` vs `auth.users` name collision** — schema-qualify (`public.users`) in migrations.
- **Route module name vs config object:** `app/api/routes/settings.py` collides with the `settings` config object → import aliased (`settings as settings_routes`) in `main.py`. Same trap likely for a `kiki`/`agent` module — check.
- **Encrypted-field pattern** (`email_configs`/`pds_configs`): store `*_encrypted`, **never return ciphertext** (return `has_password`/`has_api_key` booleans), and **only re-encrypt when a new secret is supplied** (empty input = keep existing). Reuse `app/core/crypto.py` (`encrypt`/`decrypt`).
- **Address JSONB:** PATCH replaces the column **wholesale** to drop legacy `{raw}` — don't merge old + new keys.
- **Migrations:** write the `supabase/migrations/00XX_*.sql` file AND apply via MCP `apply_migration` (both).
- **Reference-product UX we deliberately diverged from:** no infinite settings scroll (sub-nav), no nested horizontal tabs (radio-cards), no duplicated placeholder UI, action-before-diagnostic, 2×2 grids for 4 peer items.
