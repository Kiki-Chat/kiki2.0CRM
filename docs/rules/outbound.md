# Business Rules — Outbound (ausgehende Anrufe & Anlass-E-Mails)

Registry-driven outbound engine (Path A): one sweep (`run_due_outbound`) serves every occasion via `OCCASIONS` specs; manual/UAT single dispatch via `send_single_outbound`. All rule statements in German; metadata in English. Verified against code on 2026-06-11.

## OUT-01 — Ausgehende Anrufe werden nur ausgelöst, wenn der Org-Hauptschalter `outbound_enabled` UND der jeweilige Anlass-Schalter in `outbound_occasions` aktiviert sind (fehlender Schlüssel = deaktiviert).
- **Enforced by:** `backend/app/services/outbound_dispatch.py:_passes_gate`
- **Surfaced in UI:** `frontend/src/components/kiki/ConfigSections.tsx` (master Toggle + per-occasion checkboxes, ~lines 890–898)
- **Covered by test:** `backend/tests/test_outbound_reminders.py::test_run_due_outbound_gating_skips`, `::test_uniform_gate_branches`
- **Prompt block:** —
- **Status:** enforced

## OUT-02 — Ausgehende Anrufe erfolgen nur im konfigurierten Zeitfenster (`outbound_time_from`/`outbound_time_to`, inkl. Über-Nacht-Fenster) und an den konfigurierten Wochentagen, beides in Europe/Berlin-Zeit.
- **Enforced by:** `backend/app/services/outbound_dispatch.py:_passes_gate` + `_within_window` (Berlin tz via `_BERLIN = ZoneInfo("Europe/Berlin")`)
- **Surfaced in UI:** `frontend/src/components/kiki/ConfigSections.tsx` (Von/Bis time inputs + weekday buttons, ~lines 939–947)
- **Covered by test:** `backend/tests/test_outbound_reminders.py::test_uniform_gate_branches`, `::test_run_due_outbound_gating_skips`
- **Prompt block:** —
- **Status:** enforced

## OUT-03 — Jeder Dispatch ist über das `outbound_calls`-Ledger zyklus-idempotent: Einmal-Anlässe feuern höchstens einmal pro Datensatz; wiederkehrende Anlässe rücken erst nach Ablauf des Cooldowns einen Zyklus vor, gedeckelt durch `max_cycles`.
- **Enforced by:** `backend/app/services/outbound_dispatch.py:_cycle_decision` + `_claim` (atomic guard = partial unique index `(org_id, occasion, referenz_id, cycle_no) WHERE status<>'failed'`)
- **Surfaced in UI:** —
- **Covered by test:** `backend/tests/test_outbound_reminders.py::test_run_due_outbound_dedup_excludes_already_dispatched`, `::test_payment_cooldown_skips_within_window`, `::test_payment_fires_next_cycle_after_cooldown`, `::test_payment_max_cycles_caps`
- **Prompt block:** —
- **Status:** enforced

## OUT-04 — Zahlungserinnerungen sind ausdrücklich KEINE Mahnung: freundlicher Ton, keine Mahngebühren/Fristen/rechtlichen Schritte; wiederkehrend mit Cooldown (`payment_reminder_days`, Default 14 Tage) und maximal 3 Zyklen, nur für überfällige, unbezahlte Rechnungen (status sent/overdue, due_date < heute, paid_at NULL).
- **Enforced by:** `backend/app/services/outbound_occasions.py:_render_payment_reminder` (tone is rendered server-side into the per-call prompt) + `_select_payment_reminder`; cycle caps in spec `OCCASIONS["payment_reminder"]` (recurring=True, cooldown_days=14, max_cycles=3)
- **Surfaced in UI:** per-occasion checkbox in `ConfigSections.tsx`
- **Covered by test:** `backend/tests/test_outbound_reminders.py::test_render_payment_reminder_soft_tone`, `::test_payment_max_cycles_caps`
- **Prompt block:** rendered per call (`## PRIMÄRE AUFGABE – Zahlungserinnerung (freundlich, KEINE Mahnung)` in the conversation_config_override); tone itself is prompt-only at call time
- **Status:** partially-enforced (selection/cycles enforced; soft tone is prompt-only)

## OUT-05 — Arbeits-Anlässe (case_gate `must_be_open`) feuern nicht, wenn der verknüpfte Vorgang (inquiry) `completed` oder `deleted` ist; Zufriedenheits- und Bewertungsanrufe feuern umgekehrt nur auf abgeschlossene Vorgänge (letzte 30 Tage).
- **Enforced by:** `backend/app/services/outbound_dispatch.py:run_due_outbound` (close-case gate, `_CLOSED_STATUSES`) + `backend/app/services/outbound_occasions.py:_select_completed_inquiries`
- **Surfaced in UI:** —
- **Covered by test:** `backend/tests/test_outbound_reminders.py::test_close_case_gate_skips_completed_inquiry`, `::test_satisfaction_fires_on_completed_inquiry`
- **Prompt block:** —
- **Status:** enforced

## OUT-06 — Bewertungsanrufe (`review_request`) erfordern zusätzlich das Org-Flag `google_reviews_enabled`; ohne Flag wird der Anlass übersprungen.
- **Enforced by:** `backend/app/services/outbound_dispatch.py:run_due_outbound` (spec.org_flag check) + spec `OCCASIONS["review_request"].org_flag`
- **Surfaced in UI:** — (occasion checkbox exists; org flag not found in the outbound config section)
- **Covered by test:** `backend/tests/test_outbound_reminders.py::test_review_skipped_when_reviews_disabled`, `::test_review_fires_when_enabled`
- **Prompt block:** —
- **Status:** enforced

## OUT-07 — Bei kurzem Auflegen (Dauer < `outbound_short_hangup_seconds`, Default 20 s) wird ein Rückwahl-Versuch geplant, sofern `outbound_recall_on_short_hangup` aktiv ist; Wiederholung nach `outbound_retry_interval_minutes` (Default 5), begrenzt durch `outbound_retry_max_attempts`; die nächste Sweep-Runde wählt erneut.
- **Enforced by:** `backend/app/services/outbound_dispatch.py:schedule_short_hangup_retry` (called from `backend/app/services/post_call.py:~406`) + `run_due_retries` (clears `next_retry_at` before re-dial to prevent double-fire)
- **Surfaced in UI:** `frontend/src/components/kiki/ConfigSections.tsx` (recall toggle + settings, ~lines 927–937)
- **Covered by test:** NONE found (searched backend/tests for `schedule_short_hangup_retry`, `run_due_retries` — only an incidental comment in test_outbound_reminders.py:718)
- **Prompt block:** —
- **Status:** enforced — but [VERIFY WITH AMBER]: no dedicated test coverage for the retry path

## OUT-08 — Jeder Anruf erhält eine serverseitig gerenderte deutsche Voicemail-Nachricht (`voicemailMessage` in den dynamic_variables); der Agent darf die Mailbox-Funktion nur bei zweifelsfreier Anrufbeantworter-Ansage auslösen — im Zweifel gilt: Mensch.
- **Enforced by:** `backend/app/services/outbound_occasions.py:build_call_content` (every occasion's `render` returns a voicemail string); the human/machine decision is PROMPT-ONLY (`_BASE_OUTBOUND`, block "## Mailbox / Anrufbeantworter")
- **Surfaced in UI:** —
- **Covered by test:** `backend/tests/test_outbound_reminders.py::test_render_appointment_reminder_vars_and_text` (asserts voicemailMessage present)
- **Prompt block:** `## Mailbox / Anrufbeantworter` in `_BASE_OUTBOUND` (outbound_occasions.py, not the inbound agent_prompt_template.txt)
- **Status:** partially-enforced (message delivery enforced; trigger discipline prompt-only)

## OUT-09 — Solange `OUTBOUND_TEST_SCOPE_ONLY` aktiv ist, werden alle ausgehenden Anrufe und E-Mails auf die Test-Ziele erzwungen und Sends für Orgs außerhalb der Test-Allowlist verweigert; seit GO-LIVE 2026-06-07 steht das Flag auf 0 — Anrufe/E-Mails erreichen ECHTE Kunden.
- **Enforced by:** `backend/app/services/outbound_scope.py:enforce_call_scope` / `enforce_email_scope` (call scope applied in `appointment_notify.py:121`; email scope in `outbound_dispatch.py:_maybe_send_occasion_email`)
- **Surfaced in UI:** —
- **Covered by test:** `backend/tests/test_outbound_scope.py` (all 10 tests, e.g. `::test_call_out_of_scope_org_is_refused`, `::test_guard_off_passes_real_number_through`)
- **Prompt block:** —
- **Status:** enforced — NOTE: `enforce_call_scope` guards only the click-triggered appointment path (appointment_notify); the sweep's `_dispatch_one` dials `customer.phone` directly. [VERIFY WITH AMBER] whether sweep calls should also pass through the call-scope guard (moot while LIVE, relevant if the flag is ever flipped back to 1)

## OUT-10 — Die drei Termin-Anlässe (Bestätigung/Absage/Verschiebung) werden NIE automatisch vom Sweep gewählt — sie feuern nur per Menschen-Klick im Call-Log; ihre Anlass-E-Mail sendet immer (`email_always=True`), die der übrigen 7 Anlässe nur bei gesetztem `OUTBOUND_OCCASION_EMAILS_ENABLED`.
- **Enforced by:** `backend/app/services/outbound_occasions.py:_select_none` (select returns []) + `backend/app/services/outbound_dispatch.py:_maybe_send_occasion_email` (email_always / settings flag gate); click path = `backend/app/services/appointment_notify.py:notify_appointment_outcome`
- **Surfaced in UI:** call-log action tab (Confirm/Cancel/Reschedule buttons; `frontend/src/pages/calls/Workspace.tsx` area)
- **Covered by test:** `backend/tests/test_appointment_notify.py`, `backend/tests/test_appointment_occasions.py`
- **Prompt block:** —
- **Status:** enforced

## OUT-11 — Der Reschedule-Expiry-Sweep löst abgelaufene Kunden-Terminvorschläge nur bei Autonomie-Level 3 automatisch auf (Vorschlag verwerfen; bei `replace_intent` Termin stornieren + benachrichtigen); bei L1/L2 bleibt der Vorgang offen und wird nur in der UI als überfällig markiert — nie automatisches Stornieren echter Buchungen.
- **Enforced by:** `backend/app/services/outbound_dispatch.py:run_due_reschedule_expiry` (gated via `appointments._get_kiki_level`; runs for ALL orgs, also non-outbound-enabled, inside `run_due_outbound`)
- **Surfaced in UI:** overdue badge from `reschedule_expires_at` (appointments UI)
- **Covered by test:** NONE found in backend/tests (searched `reschedule_expir` — no hits)
- **Prompt block:** —
- **Status:** enforced — but [VERIFY WITH AMBER]: no test coverage for the expiry sweep found

## OUT-12 — Der Sweep-Endpunkt `POST /api/outbound/run-due-reminders` ist secret-geschützt (X-HeyKiki-Secret); der manuelle Einzel-Dispatch `POST /api/outbound/send` ist org-gebunden, umgeht Zeitfenster/Wochentag/Anlass- und Close-Case-Gates und überspringt mit `to_number`-Override (Testnummer) zusätzlich das Ledger (wiederholbar).
- **Enforced by:** `backend/app/api/routes/outbound.py:run_due_reminders` (Depends(verify_post_call_secret)) / `:send_outbound` (Depends(require_org)) + `outbound_dispatch.py:send_single_outbound`
- **Surfaced in UI:** —
- **Covered by test:** `backend/tests/test_outbound_reminders.py::test_cron_endpoint_requires_secret`, `::test_send_single_override_dials_test_number_and_skips_ledger`, `::test_send_route_maps_lookup_to_404`
- **Prompt block:** —
- **Status:** enforced

## OUT-13 — Der per Anruf mitgeschickte Outbound-System-Prompt ist firmen-agnostisch, ausschließlich deutsch, und enthält Leitplanken: nie „Termin ist gebucht“ sagen (nur reservieren), nie buchen/ändern ohne vorherige Verfügbarkeitsprüfung und ausdrückliche Kundenbestätigung, `end_call` nie direkt nach der Eröffnung.
- **Enforced by:** PROMPT-ONLY — `backend/app/services/outbound_occasions.py:_BASE_OUTBOUND` + `assemble_system_prompt` (rendered server-side, shipped via conversation_config_override)
- **Surfaced in UI:** —
- **Covered by test:** `backend/tests/test_outbound_reminders.py::test_override_prompt_is_company_agnostic_and_tool_filtered`
- **Prompt block:** `## Leitplanken`, `## Gesprächsende` in `_BASE_OUTBOUND` (outbound override prompt; the inbound `agent_prompt_template.txt` only routes via its "Outbound-Anlass-Header" note at line ~430)
- **Status:** prompt-only
