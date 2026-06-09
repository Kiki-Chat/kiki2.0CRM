# Vorgang (Case) Threading — Local UAT

Branch: `feature/vorgang-case-threading` (off `main`). **NOT committed, NOT pushed, NOT deployed.**

Goal: tie every activity about one matter (inbound intake call + outbound follow-ups +
appointment(s) + KVA(s) + emails + docs) into ONE customer case ("Vorgang"), with a
staff-facing case number and a customer-facing topic name. Build LOCAL-only first; review
the look & feel; promote to prod only after Amber's explicit OK.

Spec: `THREADS_BUILD_PROMPT.md`

## Decisions (locked 2026-06-09)
- **DB**: additive changes applied to the SHARED Supabase (reversible). Prod code is
  unaffected — the feature code is not deployed, new columns are nullable, and nothing in
  prod reads them.
- **Case number**: REUSE the existing `inquiries.number` (`ANF-YYYY-NNNN`) as the
  staff-facing case number; relabel it "Vorgang" in the UI. No new `VG-` number is minted.
- **Status**: keep the existing enum (`open|in_progress|completed|deleted`) for now; map the
  spec's `resolved`/`closed` onto `completed`. No disruptive enum migration in Phase 1.
- **Vorgang = inquiry** (1:1). The existing `projects` layer (a bundle *above* inquiries) is
  left untouched.

## Isolation / rollback
- Code: lives only on this branch — delete the branch to undo.
- Schema (migration `0055`): additive. Rollback =
  `alter table calls drop column inquiry_id;`
  `alter table inquiries drop column subject;`
  `drop table case_links;` (+ remove the `0055` migration record).

## Phases — all built & preview-verified on the TobiasDachdecker org
- [x] **P1 Foundation** — migration 0055 applied (shared DB): `calls.inquiry_id`,
      `inquiries.subject`, `case_links` live. Backfill linked **all 174 calls** (148 inbound,
      25 outbound). Going-forward linking: inbound stamps `calls.inquiry_id` in
      `ensure_call_inquiry`; outbound stamps it post-call from the `outbound_calls` ledger
      (`link_outbound_call_to_case`, German referenz derivation). `/api/calls` enrichment
      resolves via `calls.inquiry_id` (+ legacy fallback) and surfaces `inquiry_number` +
      `inquiry_subject`. **Vorgang chip** on the call detail (both directions).
- [x] **P2 Case thread UI** — Customer page → **Vorgänge cards** (status · topic · ANF-number ·
      call count · last activity · open badge). New route `/vorgang/:id` → **thread view**
      (`VorgangThreadPage`): header + status switcher + stats + in/out calls + one unified
      `Verlauf` timeline. Backend `GET /api/inquiries/{id}/thread` (`build_case_thread`).
- [x] **P3 Outbound-vs-inbound action sets** — outbound call screen shows a **Gesprächsergebnis**
      panel (Bestätigt/Verschoben/Abgelehnt/Abgebrochen/Nicht erreicht) and **hides** the
      Termin/KVA intake; inbound keeps full intake. Cut-off detection: a <20s outbound call
      shows a **"nachfassen"** warning. *(Visual flag only — does not yet auto-raise an Aktion;
      see "Deliberately not done".)*
- [x] **P4 Link/Merge** — `POST /api/inquiries/{id}/link` + `/merge` and the
      **Verknüpfen / Zusammenführen** modal + "Thema benennen" (subject) editor. Smart inbound
      topic matching + ElevenLabs agent prompt = **not done** (see below).

## Deliberately NOT done (need explicit go-ahead)
- **ElevenLabs agent prompt** (topic-based greeting, no case numbers read out): touches the
  LIVE agent / real calls — left untouched on purpose.
- **Cut-off → auto-raise Aktion**: the <20s "nachfassen" flag is shown on the call, but does
  not yet create an entry in the Aktionen to-do list (would need post-call action generation).
- **Status enum** still `open|in_progress|completed|deleted` (spec's waiting/resolved/closed
  mapped onto these).
- Subjects are still empty in the data → cards/threads fall back to the title; the
  "Thema benennen" editor is how staff/agent set them going forward.

## Current local state / how to run
- Backend is running locally on :8000 (started by this session). To restart after edits
  (no hot-reload): `pkill -f app.main:app` then
  `backend/.venv/bin/uvicorn --app-dir backend app.main:app --port 8000`.
- Frontend dev server on :5173 (HMR picks up edits). All changes are uncommitted on the branch.
- [ ] **P2 Case thread UI** — customer → Vorgänge cards; Vorgang → one chronological thread.
- [ ] **P3 Outbound-vs-inbound action sets** + cut-off ("nachfassen") detection.
- [ ] **P4 Link/Merge** + smart inbound topic matching + ElevenLabs agent prompt.

## Progress log
- 2026-06-09 — branch created; codebase mapped end-to-end; decisions locked; migration 0055 drafted.
