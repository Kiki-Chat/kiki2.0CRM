# Handover — Call-Log Redesign (Posteingang · Fokus·Agenda)

_Last updated 2026-06-15. Branch `feature/call-log-redesign` (pushed to origin)._
_Commits: `9da7962` (Posteingang wired to live data) → `31271d0` (case bundling + remove Kiki-empfiehlt/Notiz)._
_UAT only. Nothing deployed. PR: https://github.com/imamber20/kikijarvis-crm/pull/new/feature/call-log-redesign_

---

## 1. Resume the running environment (do this first)

Worktree: `/Users/iamber/Code Jamming/KikiJarvis/.claude/worktrees/flamboyant-gauss-86cf29` (branch `feature/call-log-redesign`).

The branch runs its **own** backend on `:8001` so main's `:8000` is untouched, and `:8001` is **test-scoped (safe outbound — no real customer dials)**.

Gitignored local setup (recreate if missing):
- `frontend/node_modules` → symlink to main's: `ln -s "/Users/iamber/Code Jamming/KikiJarvis/frontend/node_modules" "<wt>/frontend/node_modules"`
- `backend/.venv` → symlink to main's: `ln -s "/Users/iamber/Code Jamming/KikiJarvis/backend/.venv" "<wt>/backend/.venv"`
- `frontend/.env` (copy of main's) with **`VITE_API_URL=http://localhost:8001`**
- `backend/.env` (copy of main's) with **`OUTBOUND_TEST_SCOPE_ONLY=1`** (forced — keeps confirm-appointment from dialing a real number)

`.claude/launch.json` (LOCAL ONLY, intentionally uncommitted) has two configs to start via the preview MCP:
- `preview` — vite on `:5173`, absolute `cwd` = `<wt>/frontend`
- `backend-8001` — `uvicorn app.main:app --port 8001 --reload`, absolute `cwd` = `<wt>/backend`

Start order: `preview_start "backend-8001"`, then `preview_start "preview"`. Verify booted via `preview_logs`.

**Login (dashboard, kiki-test-007):** `kikitest01@gmail.com` / `KikiTest2026!` (org_admin; org_id `c4dbf596-86fd-4484-88d9-095b2c082afb`). View at `http://localhost:5173/posteingang` (set `document.documentElement.dataset.theme='dark'`).

Supabase project = `ifbluvdcbcesuhvkxsfn` (kikiJarvis). Use the Supabase MCP for SQL/migrations.

---

## 2. What's DONE and verified

- Pixel-accurate **Fokus·Agenda** Posteingang (from the design handoff `~/Desktop/design_handoff_posteingang_anrufe`). Sidebar item **Posteingang** added; **Anrufe** cockpit (`/calls`) untouched.
- **Wired to live kiki-test-007 data** via `frontend/src/pages/posteingang/api.ts` (queries + mappers + mutations). Mock module retired.
- **Decisions** from `/api/actions/pending`; resolve through real endpoints — verified `POST /api/appointments/{id}/confirm`; also reject / propose-alternative / approve-/decline-proposal, KVA `POST /api/cost-estimates/{id}/send` + `PATCH /status`.
- **Assign dropdown** everywhere (`PATCH /api/inquiries/{id}/assign`). Bottom bar **Termin · KVA · Rechnung**.
- **Triage** (verified): reversible **spam** `POST /api/calls/{id}/spam` and move-call `POST /api/calls/{id}/assign-inquiry` — **two NEW endpoints** in `backend/app/api/routes/calls.py`; additive migration `supabase/migrations/0071_calls_is_spam.sql` (applied).
- **CASE BUNDLING (the big one):** the inbox "Alle Fälle" now bundles calls **by ticket = `inquiry.project_id`** (the AI-grouping container; relabeled **"Fall"**, never "Projekt"). One row per case; expand → the call journey (in/out/in) built from `callEntries` (no per-row fetch); multi-call tickets sorted first. Verified with a seeded German multi-call case **Familie Hoffmann** (3 calls, project `PRJ-2026-90001`) in kiki-test-007.
- Removed **"Kiki empfiehlt"**; removed drawer **"Notiz"** button.

---

## 3. What REMAINS (resume tasks, in order)

From the latest 11-point change list (ran out of context mid-list):

1. **(point 4) Move triage out of the inbox into the Anrufe cockpit.** Currently the "Nicht zugeordnet" section is in `PosteingangPage.tsx` and the triage block is in `posteingang/CallDrawer.tsx`. Move "Vorgang zuordnen / Neuer Vorgang / Als Spam" to the existing call-log cockpit's right-pane action area (`pages/calls/Workspace.tsx` / `CallDetail`). Endpoints already exist (`/spam`, `/assign-inquiry`, `POST /api/calls/{id}/inquiry` for new). Then remove the section from the inbox.
2. **(points 1, 2, 6) Strict assign ≠ confirm + name the case + the specific action on each decision card.** Removing the reco already fixed the assign-also-confirms behavior; still TODO: make assignment visibly its own step, and label each decision card with its **case name + specific action** (map `action.inquiry_id` → the call's `project_title`/`inquiry_subject`). NB: backend requires an assignee before `POST /appointments/{id}/confirm` succeeds.
3. **(point 10) Make the audio button actually play.** `GET /api/calls/{id}/audio` returns `audio/mpeg` but needs the bearer token → fetch as blob with the auth header → object URL → `<audio>`. In `posteingang/CallDrawer.tsx` (`AudioPlayer` + the "Aufnahme abspielen" button).
4. **Per-call case LABEL in the call log** that deep-links to that case in the inbox (edit the `/calls` row to show the Fall + link to `/posteingang`).

From the original scope (separate follow-up, not in this PR):

5. **Employee scoping** — the "Meine" filter + role-scoped list/detail endpoints + notify-on-assign. Backend list endpoints currently return ALL org data to every role.
6. **Relabel** — UI already says "Fall"; the DB-layer relabel is deferred.

---

## 4. Key files

| Area | Path |
|---|---|
| Inbox screen | `frontend/src/pages/PosteingangPage.tsx` |
| Data + mutations | `frontend/src/pages/posteingang/api.ts` |
| Atoms (Btn, AssigneeDot, Timeline, …) | `frontend/src/pages/posteingang/parts.tsx` |
| Call drawer | `frontend/src/pages/posteingang/CallDrawer.tsx` |
| Tokens added | `frontend/src/index.css` |
| Nav item | `frontend/src/components/layout/nav.ts` |
| Route | `frontend/src/App.tsx` (`/posteingang`) |
| New backend endpoints | `backend/app/api/routes/calls.py` (`/spam`, `/assign-inquiry`) |
| Migration | `supabase/migrations/0071_calls_is_spam.sql` |
| AI grouper (bundling) | `backend/app/services/cases/grouper.py` → trigger `POST /api/customers/{id}/cases/propose` then `POST /api/cases/apply` (writes a `projects` row + `inquiries.project_id`; `cases` table is legacy/empty). `projects.status` enum = `planning|active|completed|archived` |

Type-check: `<wt>/frontend/node_modules/.bin/tsc -b <wt>/frontend` (currently green).

---

## 5. Gotchas

- Explore agents report **MAIN** absolute paths — always write to the **worktree**.
- The preview viewport **resets to a huge size on navigation** → `preview_resize` to ~1280×1000 and `scrollIntoView` before screenshots, or content renders tiny.
- zsh: `$PIPESTATUS` is empty after a pipe (bash-only) — use `$pipestatus[1]` or avoid the pipe.
- Backend on `:8001` is test-scoped: confirm-appointment **won't dial**, and the confirmation email "fails" only because the test env has no Brevo key — both are expected/safe.
- Amber's numbers (safe to dial if you flip `OUTBOUND_TEST_SCOPE_ONLY=0` for a single test): `+1 278 799 7839`, `+91 8920100973`.

## 6. Standing constraints
UAT only — **no Railway deploy** without explicit approval. Additive migrations pre-authorized; non-additive needs explicit OK. Test data: kiki-test-007 (+ a one-time OK was given to seed in the TobiasDachdecker org). Talk to Amber in **English**; the **UI is German**.
