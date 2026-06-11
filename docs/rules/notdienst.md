# Business Rules — Notdienst (Emergency Service)

Rules governing the emergency-service path: the Notdienst toggle and windows, the native `transfer_to_number` system tool, no-booking-on-emergency, and the `emergency_flag` on call logs. All references verified in code on branch `improvements-kiki-zentral` (2026-06-11).

## ND-01 — Ist der Notdienst deaktiviert (`emergency_enabled=false`), darf Kiki niemals weiterleiten, sondern nimmt außerhalb der Geschäftszeiten nur das Anliegen auf.
- **Enforced by:** `backend/app/services/agent_config.py:render_emergency_block` (disabled branch) + `backend/app/services/agent_config.py:build_transfer_tool` (returns no emergency transfer when `emergency_enabled` is falsy → tool entry absent on the agent, so a transfer is technically impossible)
- **Surfaced in UI:** `frontend/src/components/kiki/ConfigSections.tsx:NotdienstSection` (toggle)
- **Covered by test:** `backend/tests/test_dynamic_prompt.py::test_emergency_disabled_says_no_notdienst`
- **Prompt block:** `{{KZ_EMERGENCY}}` ("# Notdienst & Notfälle")
- **Status:** enforced

## ND-02 — Ein Notfall liegt nur bei einem der konfigurierten Notfall-Stichwörter vor; ohne Konfiguration gilt die Standard-Stichwortliste, und bei Unsicherheit wird genau EINMAL nachgefragt.
- **Enforced by:** `backend/app/services/agent_config.py:render_emergency_block` + `_DEFAULT_EMERGENCY_KEYWORDS` (fallback only when org configured none) — conversational behavior itself is PROMPT-ONLY
- **Surfaced in UI:** `NotdienstSection` keyword editor incl. trade templates (frontend-only, deduped append)
- **Covered by test:** `backend/tests/test_dynamic_prompt.py::test_emergency_enabled_lists_configured_keywords`
- **Prompt block:** `{{KZ_EMERGENCY}}` keyword list ("Ein NOTFALL liegt nur bei einem dieser Fälle vor")
- **Status:** prompt-only

## ND-03 — Der Notdienst greift entweder NUR außerhalb der Geschäftszeiten (`emergency_only_outside_business_hours`) oder JEDERZEIT, jeweils ergänzt um zusätzliche Notdienst-Zeitfenster (`emergency_extra_windows`).
- **Enforced by:** `backend/app/services/agent_config.py:render_emergency_block` + `_emergency_windows_str` — PROMPT-ONLY at call time (the transfer-tool condition also references the window: "Notdienst-Zeitfenster aktiv")
- **Surfaced in UI:** `NotdienstSection` (only-outside toggle + extra-windows editor)
- **Covered by test:** NONE (window rendering itself untested; looked in test_dynamic_prompt.py)
- **Prompt block:** `{{KZ_EMERGENCY}}` active-window clause
- **Status:** prompt-only

## ND-04 — Ist der Zuschlags-Hinweis aktiviert, weist Kiki VOR der Weiterleitung auf den Notdienst-Zuschlag hin (konfigurierter Text oder Standardformulierung).
- **Enforced by:** `backend/app/services/agent_config.py:render_emergency_block` (surcharge branch) — PROMPT-ONLY
- **Surfaced in UI:** `NotdienstSection` (`emergency_surcharge_notice_enabled` / `emergency_surcharge_text`)
- **Covered by test:** NONE
- **Prompt block:** `{{KZ_EMERGENCY}}` surcharge line
- **Status:** prompt-only

## ND-05 — Bei einem bestätigten Notfall wird KEIN Termin gebucht — `hk_getAvailableAppointments` und `hk_bookAppointment` sind tabu; Notfall und Terminvergabe schließen sich aus.
- **Enforced by:** PROMPT-ONLY (`render_emergency_block`, explicit no-booking line); the booking pre-gate section of the template states the Notdienst path is unaffected by booking-category gating
- **Surfaced in UI:** —
- **Covered by test:** agent-eval scenario `emergency_transfer_no_booking` in `backend/tests/agent_evals/scenarios.json` (behavioral eval, passed in 2026-06-10 baseline run)
- **Prompt block:** `{{KZ_EMERGENCY}}` + "Vorgehen bei bestätigtem Notfall"
- **Status:** prompt-only

## ND-06 — Die Notdienst-Weiterleitung läuft über das native System-Werkzeug `transfer_to_number` (Conference-Bridge) an `emergency_number` (Fallback `forwarding_number`); Nummern werden zwingend auf E.164 normalisiert.
- **Enforced by:** `backend/app/services/agent_config.py:build_transfer_tool` (transfer object + condition string) + `_dial_clean` (E.164: `0…`→`+49…`, `00…`→`+…`; Twilio rejects non-E.164). The legacy `hk_transferCall` webhook (`backend/app/api/routes/tools/transfer_call.py`, `services/transfer.py`) stays attached only as diagnostic fallback; the prompt no longer references it.
- **Surfaced in UI:** `NotdienstSection` (`emergency_number`)
- **Covered by test:** eval scenario `emergency_transfer_no_booking` calls `transfer_to_number`; no unit test for `build_transfer_tool`/`_dial_clean` (looked in test_agent_config.py — NONE)
- **Prompt block:** "Vorgehen bei bestätigtem Notfall" (Gasgeruch → sofortiger Transfer ohne Rückfrage; sonst erst Bestätigungsfrage)
- **Status:** enforced (tool config) / prompt-only (when to fire)

## ND-07 — Bei Gasgeruch erfolgt die Weiterleitung SOFORT ohne weitere Frage; bei allen anderen Notfall-Stichwörtern fragt Kiki erst „Soll ich Sie sofort zum Notdienst weiterverbinden?" und verbindet nur bei „Ja".
- **Enforced by:** PROMPT-ONLY (`agent_prompt_template.txt` lines ~119–129)
- **Surfaced in UI:** —
- **Covered by test:** NONE (eval corpus covers confirmed-emergency transfer, not the gas-smell fast path specifically)
- **Prompt block:** "## Vorgehen bei bestätigtem Notfall"
- **Status:** prompt-only

## ND-08 — Ist KEINE Notdienst-Nummer hinterlegt (oder schlägt der Transfer fehl), wird NICHT weitergeleitet, sondern sofort eine dringende Rückrufnotiz erstellt (`hk_createInquiry`, `dringend=true`, `rueckrufGewuenscht=true`).
- **Enforced by:** `render_emergency_block` (no-number branch) — PROMPT-ONLY conversationally, but structurally backed: `build_transfer_tool` returns `None`/no emergency entry without a number, so the transfer tool genuinely cannot fire
- **Surfaced in UI:** —
- **Covered by test:** NONE
- **Prompt block:** `{{KZ_EMERGENCY}}` final lines
- **Status:** partially-enforced

## ND-09 — Jede Speicherung der Notdienst- oder Telefonie-Einstellungen stößt automatisch den Prompt-Repush UND die Neusynchronisation der System-Tools (`transfer_to_number`, `voicemail_detection`, `transfer_to_agent`) an den ElevenLabs-Agenten an.
- **Enforced by:** `backend/app/api/routes/kiki_zentrale.py:_schedule_repush` (labels `kz_emergency`/`kz_phone`/`kz_retry` → system-tool resync, see lines ~90–92; `PATCH /emergency` at line ~1221) + `backend/app/services/agent_config.py:sync_system_tools_for_org` (best-effort, never raises)
- **Surfaced in UI:** `NotdienstSection` save (KikiZentralePage)
- **Covered by test:** NONE found for the repush trigger (looked in test_agent_config.py and route tests)
- **Prompt block:** —
- **Status:** enforced

## ND-10 — Ein Call-Log wird nur dann als Notdienst markiert (`emergency_flag=true`), wenn der Anruf außerhalb der Geschäftszeiten einging UND der Anruf inhaltlich als dringend erkannt wurde (explizites data_collection-Feld ODER zweisprachiger DE/EN-Inhalts-Fallback).
- **Enforced by:** `backend/app/services/inquiries.py` (`emergency = outside_hours and agent_urgent`, lines ~115–138) + `_content_signals_emergency` (bilingual `_EMERGENCY_TERMS` fallback, fix 2026-06-09) + `backend/app/services/scheduling.py:is_emergency_by_hours` (requires `emergency_enabled` AND outside business hours)
- **Surfaced in UI:** `frontend/src/pages/calls/atoms.tsx:NotdienstBadge` shown in Inbox, Transcript, Workspace (reads `emergency_flag`)
- **Covered by test:** `backend/tests/test_inquiry_emergency.py` (German/English positive + negative cases) and `backend/tests/test_business_hours.py`
- **Prompt block:** —
- **Status:** enforced

## ND-11 — Eine Mitarbeiter-Weiterleitung (Live-Transfer an `incoming_forwarding_number`) wird nur innerhalb der Geschäftszeiten und NICHT im Notfall angeboten; ohne hinterlegte Nummer gibt es nur eine Rückrufnotiz.
- **Enforced by:** `backend/app/services/agent_config.py:build_transfer_tool` (staff transfer entry only when number set and ≠ emergency number; condition: "innerhalb der Geschäftszeiten (KEIN Notfall)") + `render_staff_transfer_block` (`{{KZ_STAFF_TRANSFER}}`); the within-hours/non-emergency check itself is condition-text, i.e. LLM-judged
- **Surfaced in UI:** Telefonie settings (`incoming_forwarding_number`) in KikiZentralePage
- **Covered by test:** NONE
- **Prompt block:** `{{KZ_STAFF_TRANSFER}}`
- **Status:** partially-enforced

## ND-12 — `transfer_to_agent` darf in eingehenden Anrufen NIEMALS verwendet werden — im Notfall zählt ausschließlich `transfer_to_number`.
- **Enforced by:** PROMPT-ONLY (`agent_prompt_template.txt` lines ~599–600) + `build_transfer_to_agent_tool` description restricting use to outbound off-topic handoffs
- **Surfaced in UI:** —
- **Covered by test:** `backend/tests/agent_evals/test_fixtures_valid.py` lists the tool; no behavioral unit test
- **Prompt block:** transfer_to_agent prohibition section
- **Status:** prompt-only
