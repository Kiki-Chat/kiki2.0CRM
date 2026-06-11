# Business Rules — Domain: Termine (Appointments)

Registry of appointment booking/scheduling rules as actually implemented or prompted in KikiJarvis. Sources verified: `backend/app/services/appointments.py`, `backend/app/services/scheduling.py`, `backend/app/api/routes/appointments.py`, `backend/app/services/outbound_dispatch.py`, `backend/app/services/agent_config.py`, `backend/app/services/agent_prompt_template.txt`, frontend `KikiZentralePage` (Terminregeln/Terminkategorien sections), `CalendarPage.tsx`, `pages/calls/AppointmentCard.tsx`, and backend tests.

## TRM-01 — Termine sind frühestens nach der konfigurierten Vorlaufzeit (in Stunden, optional nur Werktagsstunden zählend, Hard-Cap 90 Tage) buchbar; am frühestmöglichen Tag zusätzlich nicht vor der „Frühester Termin"-Uhrzeit.
- **Enforced by:** `appointments.py:_add_lead_hours`, `appointments.py:get_available_slots` (earliest_dt / earliest_clock checks), rules read in `appointments.py:_scheduling_rules` (flat columns win over legacy jsonb)
- **Surfaced in UI:** Kiki-Zentrale → Terminregeln (`TerminregelnSection` in `frontend/src/components/kiki/ConfigSections`)
- **Covered by test:** `tests/test_dynamic_prompt.py::test_scheduling_enabled_renders_lead_time_and_clock`, `::test_scheduling_lead_time_hours_wins_over_days` (prompt rendering; slot-engine lead-time math itself has no direct unit test)
- **Prompt block:** `{{KZ_SCHEDULING_RULES}}` → "**Vorlauf:** Termine sind frühestens X Stunden…" (`agent_config.py:render_scheduling_rules_block`)
- **Status:** enforced

## TRM-02 — Slots werden nur innerhalb der Geschäftszeiten (inkl. Mittagspause und geschlossener Tage) angeboten.
- **Enforced by:** `appointments.py:get_available_slots` (open/close/break-hour loop), `scheduling.py:normalize_business_hours` / `default_business_hours`
- **Surfaced in UI:** Kiki-Zentrale → Terminregeln (business hours editor via `scheduling.py:save_business_hours`)
- **Covered by test:** NONE found for the slot-loop business-hours filtering
- **Prompt block:** Tageszeit-Modus section ("# Tageszeit-Modus … verbindlich, geht VOR den Leitfaden") governs in/out-of-hours behavior conversationally
- **Status:** enforced

## TRM-03 — Slot-Kapazität: pro Zeitfenster maximal `parallel_slots` gleichzeitige Termine, wobei jeder bestehende Termin beidseitig um `buffer_minutes` Pufferzeit gepolstert wird; bei der Buchung wird live re-validiert (SLOT_TAKEN).
- **Enforced by:** `appointments.py:_slot_conflicts` (used in `get_available_slots` AND re-checked in `book_appointment` → error `SLOT_TAKEN`)
- **Surfaced in UI:** Kiki-Zentrale → Terminregeln (Pufferzeit, parallele Slots)
- **Covered by test:** NONE found for `_slot_conflicts` / SLOT_TAKEN path
- **Prompt block:** `{{KZ_SCHEDULING_RULES}}` ("Es können bis zu N Termine parallel stattfinden.")
- **Status:** enforced

## TRM-04 — Pro Tag werden höchstens `max_appointments_per_day` Termine vergeben; volle Tage liefern keine Slots und Buchungsversuche scheitern mit DAY_FULL.
- **Enforced by:** `appointments.py:get_available_slots` (per_day Counter, "day already at capacity"), `appointments.py:book_appointment` (DAY_FULL re-check)
- **Surfaced in UI:** Kiki-Zentrale → Terminregeln (Max. Termine pro Tag)
- **Covered by test:** NONE found
- **Prompt block:** `{{KZ_SCHEDULING_RULES}}` ("Pro Tag sind höchstens N Termine möglich.")
- **Status:** enforced

## TRM-05 — Eine erkannte Termin-Kategorie (case-insensitive Name-Match) bestimmt die Termindauer (min. 15 Min, Default 60) und den Standard-Mitarbeiter; ohne Match gilt 60 Min / erster aktiver Mitarbeiter.
- **Enforced by:** `appointments.py:_resolve_category`, `appointments.py:book_appointment` (duration + `_employee_by_id` → `_first_employee` fallback)
- **Surfaced in UI:** Kiki-Zentrale → Terminkategorien (`TerminkategorienSection`); category name stored on the appointment for the Offene-Aktion card
- **Covered by test:** `tests/test_round2_features.py::test_fetch_categories_resolves_employee_display_name`
- **Prompt block:** `{{KZ_APPOINTMENT_CATEGORIES}}` ("## Termin-Kategorien" — defines which Anliegen are bookable)
- **Status:** enforced

## TRM-06 — Autonomiestufen (appointments_level, Default 2; deaktivierte Termine = Stufe 1): L1 = nur Anliegen aufnehmen, KEINE Termin-Zeile; L2 = Buchung als Reservierung (status='pending'), Team bestätigt; L3 = ebenfalls 'pending' im Call, Auto-Confirm erst NACH dem Anruf.
- **Enforced by:** `appointments.py:_get_kiki_level` + `appointments.py:book_appointment` (L1 early-return with `appointmentId=None`; L2/L3 insert as 'pending'); L3 flip in `post_call._fire_level3_confirmations`
- **Surfaced in UI:** Kiki-Zentrale → Autonomie (per-capability toggle + level)
- **Covered by test:** `tests/test_round2_features.py::test_book_appointment_l1_inquiry_only_no_appointment`, `::test_book_appointment_l2_creates_pending`, `::test_book_appointment_l3_creates_pending_for_postcall_confirm`, `::test_get_kiki_level_reads_value`, `::test_fire_level3_confirms_and_notifies`
- **Prompt block:** `{{KZ_AUTONOMY}}` (`agent_config.py:render_autonomy_block`, tested by `test_render_autonomy_block_per_level`)
- **Status:** enforced

## TRM-07 — Reservierungs- vs. Bestätigungs-Wortlaut: Auf L2 sagt Kiki genau einmal „Ich reserviere den Termin für Sie. Die finale Bestätigung kommt von unserem Team." — niemals „Ich buche den Termin"; nur auf L3 darf verbindlich bestätigt werden.
- **Enforced by:** PROMPT-ONLY (wording); the underlying status='pending' is enforced by `appointments.py:book_appointment`
- **Surfaced in UI:** — (heard on the call; pending state visible in calls Workspace `AppointmentCard.tsx`)
- **Covered by test:** `tests/test_round2_features.py::test_render_autonomy_block_per_level` (block text only)
- **Prompt block:** "## Schritt 3 — Termin" rule 5 (Reservierungs-Satz GENAU EINMAL) + `{{KZ_AUTONOMY}}` Termine sub-block
- **Status:** prompt-only

## TRM-08 — Bestätigen erfordert einen zugewiesenen Mitarbeiter: ein 'pending'-Termin ohne assigned_employee_id kann nicht bestätigt werden (API antwortet 409, nicht nur UI-Sperre); Bestätigen ist außerdem nur aus dem Status 'pending' erlaubt (sonst 409).
- **Enforced by:** `routes/appointments.py:_confirm` (409 NO_EMPLOYEE_ASSIGNED + 409 state-machine check)
- **Surfaced in UI:** calls Workspace „Offene Aktionen" card (`pages/calls/AppointmentCard.tsx`) — confirm moves it to the Kalender and fires confirmation call+email
- **Covered by test:** `tests/test_appointments_actions.py::test_confirm_409_when_no_employee_assigned`, `::test_confirm_409_when_not_pending`, `::test_confirm_happy_path_sets_confirmed_at_and_status`
- **Prompt block:** —
- **Status:** enforced

## TRM-09 — Umbuchung (changeAppointment) ist IMMER ein In-Place-Vorschlag auf der bestehenden Termin-Zeile (customer_proposed_* + appointment_change-Inquiry) — es wird NIE eine zweite Termin-Zeile angelegt und im Call NICHTS an den Kunden gesendet; der Admin committet per approve-proposal.
- **Enforced by:** `appointments.py:change_appointment` (proposal stamp, best-effort), `routes/appointments.py:_approve_proposal` (in-place move → confirmed + confirmation call/email)
- **Surfaced in UI:** call-detail action card „Kunde schlägt {time} vor" → POST `/appointments/{id}/approve-proposal` / decline
- **Covered by test:** `tests/test_appointment_reschedule_writeback.py::test_change_appointment_stamps_customer_proposal_additively`, `tests/test_appointments_actions.py::test_approve_proposal_applies_slot_and_confirms`, `::test_approve_proposal_409_when_no_proposal`, `::test_decline_proposal_clears_fields`, `::test_decline_proposal_replace_intent_cancels_original`
- **Prompt block:** outbound Alternativtermin section ("Alternativtermin-Vorschlag" callback handling)
- **Status:** enforced

## TRM-10 — Reschedule-Sicherheitstimer: jeder Vorschlag bekommt reschedule_expires_at = now + reschedule_request_timeout_hours (Default 24, per Org); nach Ablauf passiert auf L1/L2 NICHTS Automatisches (nur Overdue-Flag für den Menschen), auf L3 wird der stale Vorschlag verworfen und der Alt-Termin nur bei replace_intent storniert (reversibel) + Kunde benachrichtigt.
- **Enforced by:** `appointments.py:_reschedule_timeout_hours` + `change_appointment` (stamp), `outbound_dispatch.py:run_due_reschedule_expiry` (L-gated sweep, idempotent)
- **Surfaced in UI:** overdue badge on the proposal card (driven by reschedule_expires_at)
- **Covered by test:** NONE found for `run_due_reschedule_expiry` itself (searched backend/tests for the function name; only the writeback stamp and decline/replace paths are tested)
- **Prompt block:** —
- **Status:** partially-enforced (sweep code in place, no test; UI overdue badge not re-verified in this pass)

## TRM-11 — Stornieren/Verschieben ohne starke Identität (Telefonnummern-Match) erfordert Datums-Bestätigung; bei mehreren Treffern wird NIE geraten (DATE_CONFIRMATION_REQUIRED / MULTIPLE_MATCHES).
- **Enforced by:** `appointments.py:cancel_appointment` (name-fallback branch), `appointments.py:change_appointment` (multi-appointment branch)
- **Surfaced in UI:** — (agent-tool behavior)
- **Covered by test:** NONE found for the disambiguation branches
- **Prompt block:** "## Schritt 3 — Termin" / Rückruf-zu-bestehendem-Termin guidance ("Wenn ich einen Termin … nicht finde …")
- **Status:** enforced

## TRM-12 — Termine, die mehr als 14 Tage in der Zukunft gewünscht werden, bucht Kiki nicht selbst (Slot-Suche ist auf max. 14 Tage Fenster begrenzt); der Wunsch wird laut Leitfaden nur als Anliegen aufgenommen.
- **Enforced by:** `appointments.py:get_available_slots` (`days = min(int(payload.days or 7), 14)`) — backend caps the window; the "nimm es als Anliegen auf" behavior itself is prompt-driven
- **Surfaced in UI:** —
- **Covered by test:** NONE
- **Prompt block:** "## Schritt 3 — Termin" rule 6 ("Wünscht der Anrufer einen Termin in mehr als 14 Tagen Voraus …")
- **Status:** partially-enforced

## TRM-13 — Notfall und Terminbuchung schließen sich aus: bei bestätigtem Notfall ruft Kiki keine Termin-Tools auf (nur Notfall-Weg), und im Wartungstermine-only-Modus wird nie aktiv ein Termin angeboten.
- **Enforced by:** PROMPT-ONLY — no backend guard found in `appointments.py`/routes blocking booking during an emergency call (searched for emergency checks in the booking path)
- **Surfaced in UI:** —
- **Covered by test:** NONE
- **Prompt block:** "## Notfall-Definition (verbindlich)" rule 0 ("NOTFALL = KEINE TERMINBUCHUNG") and `<!-- WARTUNGSTERMINE_ONLY_V2 -->` block in `agent_prompt_template.txt`
- **Status:** prompt-only
