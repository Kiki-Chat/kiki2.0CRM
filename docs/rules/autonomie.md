# Business Rules — Autonomie (Kiki autonomy levels)

Per-capability autonomy for the voice agent: each capability (Termine, KVA, Projekte, Rechnungen) has an enable toggle + a level 1/2/3 on `agent_configs`, with the legacy single `kiki_level` as fallback. Levels gate both what the prompt tells Kiki AND what the backend actually executes.

## AUT-01 — Jede Fähigkeit (Termine, KVA, Projekte, Rechnungen) hat einen eigenen Schalter + Autonomie-Stufe 1/2/3; fehlt die Stufe, gilt das Legacy-Feld `kiki_level` (Default 2).
- **Enforced by:** `backend/app/services/agent_config.py:render_autonomy_block` (prompt side) + per-service readers (`appointments.py:_get_kiki_level`, `cost_estimates.py:draft_cost_estimate`, `projects.py:maybe_create_project_for_appointment`, `invoices.py:maybe_create_invoice_for_project`)
- **Surfaced in UI:** `frontend/src/components/kiki/AutonomieSection.tsx` (toggle = on/off; off = level 1 "record-only"; level picker per capability)
- **Covered by test:** `backend/tests/test_round2_features.py::test_render_autonomy_block_per_capability_overrides_legacy`, `::test_render_autonomy_block_unknown_level_defaults_to_l2`
- **Prompt block:** `## Autonomie-Hinweis` (`{{KZ_AUTONOMY}}` token)
- **Status:** enforced

## AUT-02 — Bei deaktivierten Terminen oder Stufe 1 nimmt Kiki nur eine Anfrage auf (`hk_createInquiry`); es wird KEINE Termin-Zeile angelegt (`appointmentId=None`).
- **Enforced by:** `backend/app/services/appointments.py:book_appointment` (level==1 branch) + `_get_kiki_level` (disabled ⇒ level 1); prompt side also in `agent_config.py:render_scheduling_rules_block` (appointments_enabled=False ⇒ "Buche KEINE festen Termine")
- **Surfaced in UI:** AutonomieSection.tsx ("Nur Anfrage aufnehmen — keine Buchung")
- **Covered by test:** `backend/tests/test_round2_features.py::test_get_kiki_level_reads_value`, `::test_get_kiki_level_defaults_to_2_when_missing`; `backend/tests/test_dynamic_prompt.py::test_autonomy_appointments_off_says_no_booking`
- **Prompt block:** `## Autonomie-Hinweis` + scheduling-rules block (`{{KZ_SCHEDULING_RULES}}`)
- **Status:** enforced

## AUT-03 — Bei Stufe 2 bucht Kiki den Termin als Reservierung (`status='pending'`); das Team bestätigt anschließend, und Kiki sagt dem Anrufer, dass die Bestätigung folgt.
- **Enforced by:** `backend/app/services/appointments.py:book_appointment` (levels 2&3 create status='pending')
- **Surfaced in UI:** AutonomieSection.tsx ("Vorläufig buchen — das Team bestätigt"); pending appointments on the calendar
- **Covered by test:** agent-eval scenario `booking_l2_reservation` (`backend/tests/agent_evals/`)
- **Prompt block:** `## Autonomie-Hinweis` (L2 Termine line)
- **Status:** enforced

## AUT-04 — Bei Stufe 3 wird der Termin ebenfalls als 'pending' gebucht und erst NACH dem Anruf automatisch auf 'confirmed' gesetzt (Post-Call), damit die Bestätigung nicht mit dem laufenden Gespräch kollidiert.
- **Enforced by:** `backend/app/services/post_call.py:_fire_level3_confirmations` (no-op unless level==3); booking comment in `appointments.py:book_appointment`
- **Surfaced in UI:** confirmed appointments on the calendar (no dedicated indicator)
- **Covered by test:** `backend/tests/test_round2_features.py::test_book_appointment_l3_creates_pending_for_postcall_confirm`, `::test_fire_level3_noop_when_not_level3`, `::test_fire_level3_confirms_and_notifies`
- **Prompt block:** `## Autonomie-Hinweis` (L3 Termine line: "buchst verbindlich … bestätigst direkt im Gespräch")
- **Status:** enforced

## AUT-05 — Ist KVA deaktiviert (oder Stufe 1), wird beim Tool-Aufruf KEIN Kostenvoranschlags-Entwurf angelegt; Kiki nimmt den Wunsch nur als Anliegen auf.
- **Enforced by:** `backend/app/services/cost_estimates.py:draft_cost_estimate` (gate on `kva_enabled` / legacy `kva_automation_enabled`)
- **Surfaced in UI:** AutonomieSection.tsx ("Nur Anfrage aufnehmen — kein KVA")
- **Covered by test:** `backend/tests/test_kva_send_and_routes.py::test_draft_cost_estimate_gated_off_no_insert`; `backend/tests/test_round2_features.py::test_draft_cost_estimate_noop_when_kva_disabled`
- **Prompt block:** `## Autonomie-Hinweis` (KVA L1 line)
- **Status:** enforced
- **Note:** the prompt-side gate covers level 1; the service-side gate only checks the enabled flag, not `kva_level==1` — at L1-with-enabled-true a tool call would still draft. [VERIFY WITH AMBER] whether L1+enabled should also hard-block drafting server-side.

## AUT-06 — Bei KVA-Stufe 2 erstellt Kiki nur einen ENTWURF (status='draft'); das TEAM prüft und versendet ihn — Kiki behauptet nie, der KVA sei schon verschickt.
- **Enforced by:** `backend/app/services/cost_estimates.py:draft_cost_estimate` (level != 3 ⇒ draft stays draft, no send)
- **Surfaced in UI:** Cost-estimates page (draft status); AutonomieSection.tsx ("Entwurf erstellen — das Team versendet")
- **Covered by test:** `backend/tests/test_kva_send_and_routes.py::test_draft_cost_estimate_l2_drafts_without_send`
- **Prompt block:** `hk_draftCostEstimate` tool description ("Bei Autonomie-Stufe 2 prüft und versendet das TEAM…") + `## Autonomie-Hinweis`
- **Status:** enforced

## AUT-07 — Bei KVA-Stufe 3 wird der frische Entwurf best-effort direkt per E-Mail an den Kunden versendet; 'sent' wird NUR nach erfolgreichem Versand gestempelt, bei jedem Fehler (keine E-Mail, Render-/Sendefehler) bleibt er Entwurf.
- **Enforced by:** `backend/app/services/cost_estimates.py:_send_draft_kva` (called from `draft_cost_estimate` when level==3)
- **Surfaced in UI:** Cost-estimates page (sent vs. draft status); AutonomieSection.tsx ("Entwurf erstellen & direkt an den Kunden senden")
- **Covered by test:** `backend/tests/test_kva_send_and_routes.py::test_draft_cost_estimate_l3_invokes_send`, `::test_send_draft_kva_no_email_skips_deliberately`, `::test_send_draft_kva_send_raises_is_caught_stays_draft`, `::test_send_draft_kva_success_stamps_sent`
- **Prompt block:** `hk_draftCostEstimate` tool description (say "versendet" only when tool result confirms `versendet`)
- **Status:** enforced

## AUT-08 — Der Reschedule-Sicherheitstimer ist Stufen-gesteuert: bei Stufe 1/2 passiert NICHTS automatisch (UI zeigt nur "überfällig", ein Mensch entscheidet); nur bei Stufe 3 wird der abgelaufene Vorschlag automatisch verworfen und der alte Slot nur bei `replace_intent` storniert (reversibel) + Kunde benachrichtigt.
- **Enforced by:** `backend/app/services/outbound_dispatch.py:run_due_reschedule_expiry` (gates on `appointments._get_kiki_level < 3`); proposal stamping + `reschedule_expires_at` in `appointments.py` (reschedule flow, `_reschedule_timeout_hours`, default 24h)
- **Surfaced in UI:** call-detail action card ("Kunde schlägt {time} vor") + overdue badge from `reschedule_expires_at`
- **Covered by test:** NONE found for `run_due_reschedule_expiry` (searched backend/tests for the function name)
- **Prompt block:** —
- **Status:** partially-enforced (enforced in code; no unit test found)

## AUT-09 — Ein Termin-Reschedule ist immer nur ein VORSCHLAG auf dem bestehenden Termin: es wird kein neuer Termin erstellt und nichts an den Kunden gesendet, bis ein Admin den Vorschlag bestätigt (approve-proposal) oder der Timer (AUT-08) ihn auflöst.
- **Enforced by:** `backend/app/services/appointments.py` (reschedule flow: appointment_change inquiry + `customer_proposed_*` stamp, no send); `POST /appointments/{id}/approve-proposal` commits it
- **Surfaced in UI:** call-detail action card with one-click approve
- **Covered by test:** [VERIFY WITH AMBER] — looked for reschedule-proposal tests in backend/tests; found none by name
- **Prompt block:** — (tool returns "Sie werden zur Bestätigung kontaktiert")
- **Status:** enforced

## AUT-10 — Projekte werden als Back-Office-Automation Stufen-gesteuert angelegt: aus/Stufe 1 = kein Projekt, Stufe 2 = Projekt als Entwurf ('planning') bei Terminbestätigung, Stufe 3 = automatisch 'active'; die Stufe erscheint NICHT im Agenten-Prompt.
- **Enforced by:** `backend/app/services/projects.py:maybe_create_project_for_appointment`
- **Surfaced in UI:** AutonomieSection.tsx (Projekte capability, "back-office" rows); Projects page
- **Covered by test:** NONE found (searched for the function name in backend/tests)
- **Prompt block:** — (explicitly excluded by `render_autonomy_block`: "Projekte + Rechnungen … contribute nothing to the prompt")
- **Status:** partially-enforced (enforced in code; no test found)

## AUT-11 — Rechnungen werden Stufen-gesteuert nur als ENTWURF angelegt (aus/Stufe 1 = nichts; Stufe 2 und 3 = ein 'draft' pro Projekt bei Projektabschluss); ein automatischer Versand existiert auf keiner Stufe.
- **Enforced by:** `backend/app/services/invoices.py:maybe_create_invoice_for_project`
- **Surfaced in UI:** AutonomieSection.tsx ("Rechnung automatisch erstellen (Versand folgt manuell)"); Invoices page
- **Covered by test:** NONE found (searched for the function name in backend/tests)
- **Prompt block:** —
- **Status:** partially-enforced (enforced in code; no test found)

## AUT-12 — Im AI-Copilot werden alle schreibenden Tools (kind write/sensitive/dangerous) nie direkt ausgeführt, sondern nur vorgeschlagen und erst nach expliziter Nutzer-Bestätigung (/confirm) ausgeführt.
- **Enforced by:** `backend/app/services/copilot/tools.py:Tool.needs_confirm` (kind in write/sensitive/dangerous ⇒ confirm) + the copilot orchestrator's propose/confirm loop
- **Surfaced in UI:** Copilot chat confirm dialog
- **Covered by test:** `backend/tests/test_copilot.py::test_write_tool_is_proposed_not_executed`, `::test_phase2_4_tools_registered_and_gated`
- **Prompt block:** — (copilot has its own system prompt, not agent_prompt_template.txt)
- **Status:** enforced
