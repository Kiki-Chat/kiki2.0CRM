# Business Rules — Hey-Kiki Copilot

Rules governing the in-app CRM assistant ("Hey Kiki" panel): tool scoping, confirm-gated writes, act-in-sight UX, live form-takeover, and persistent chat sessions. Backend: `backend/app/api/routes/copilot.py`, `backend/app/services/copilot/{orchestrator,tools,prompt}.py`. Frontend: `frontend/src/components/copilot/CopilotPanel.tsx`, `frontend/src/lib/liveFill.ts`. Note: the copilot's system prompt lives in `backend/app/services/copilot/prompt.py` — NOT in `agent_prompt_template.txt` (that file is the voice agent's prompt); "Prompt block" below refers to sections of `prompt.py:system_prompt`. The copilot router is only mounted when `settings.copilot_enabled` (see `copilot.py` module docstring), and is never reachable anonymously (`require_org` on every endpoint; `test_copilot.py::test_chat_never_anonymous`).

## COP-01 — Jedes Copilot-Tool ist strikt auf die Organisation des angemeldeten Nutzers beschränkt (org_id-Scoping in jeder Abfrage).
- **Enforced by:** `copilot.py:chat`/`confirm` (auth = `require_org`); every tool in `tools.py` filters `.eq("org_id", user.org_id)` (e.g. `_search_customers`, `_get_customer`, `_resolve_customer`, `_set_inquiry_status`) or delegates to org-scoped services
- **Surfaced in UI:** — (implicit)
- **Covered by test:** `backend/tests/test_copilot.py::test_chat_never_anonymous` (no anonymous access); per-tool org isolation NOT directly tested
- **Prompt block:** —
- **Status:** enforced

## COP-02 — Tools sind rollen-gegated: Admin-Tools (KVA/Rechnung erstellen, Einstellungen lesen, Stammdaten ändern, Mitarbeiter/Projekt anlegen) sind für Mitarbeiter unsichtbar und nicht ausführbar.
- **Enforced by:** `tools.py:Tool.allowed_for` + `tools_for_role`/`schemas_for_role` (the model never sees disallowed tools); double-checked at execution in `orchestrator.py:run_turn` ("Tool nicht verfügbar.") and `copilot.py:confirm` (403). Admin-only set (`roles=ROLES_ADMIN`): `create_cost_estimate`, `create_invoice`, `get_settings`, `update_org_profile`, `create_employee`, `create_project`
- **Surfaced in UI:** — (tools simply absent for employees)
- **Covered by test:** `test_copilot.py::test_registry_role_filtering_and_schemas`, `::test_phase2_4_tools_registered_and_gated`
- **Prompt block:** —
- **Status:** enforced

## COP-03 — Schreibende Aktionen werden im Chat-Turn NIE ausgeführt, sondern nur vorgeschlagen; die Ausführung erfolgt erst nach Klick auf „Bestätigen" über POST /api/copilot/confirm.
- **Enforced by:** `orchestrator.py:run_turn` (`tool.needs_confirm` → appended to `proposed`, tool result = "awaiting_confirmation"); `copilot.py:confirm` executes exactly one confirmed tool and rejects non-confirm tools (400) and disallowed tools (403). `tools.py:Tool.needs_confirm` = kind in (write, sensitive, dangerous)
- **Surfaced in UI:** `CopilotPanel.tsx` action cards with Bestätigen/Abbrechen; footer line "Änderungen nur nach Bestätigung"
- **Covered by test:** `test_copilot.py::test_write_tool_is_proposed_not_executed`
- **Prompt block:** "WAS DU TUST" ("Das System zeigt automatisch eine Bestätigung … ohne diese passiert nichts")
- **Status:** enforced

## COP-04 — Navigation ist ein client-seitiges Tool und nur auf die feste Routen-Whitelist erlaubt.
- **Enforced by:** `tools.py:KNOWN_ROUTES` (enum in the tool schema) + `_navigate_to` (rejects unknown routes); `orchestrator.py:run_turn` returns it as `client_actions` instead of executing server-side
- **Surfaced in UI:** `CopilotPanel.tsx:send` — executes `navigate_to` client actions via React Router, appends "→ Seite geöffnet"
- **Covered by test:** `test_copilot.py::test_navigation_is_client_action_and_loops`
- **Prompt block:** —
- **Status:** enforced

## COP-05 — „Act in sight": Vor/nach einer bestätigten Aktion navigiert das Panel zur Zielseite, sodass der Nutzer die Änderung live sieht (alle Queries werden invalidiert, Creates springen zum neuen Objekt).
- **Enforced by:** `CopilotPanel.tsx:confirmAction` (WATCH_ROUTES navigation before executing) and `confirmViaApi` (`qc.invalidateQueries()` + `resultRoute` navigation after success) — frontend-only behavior
- **Surfaced in UI:** `CopilotPanel.tsx` step lines ("→ Seite geöffnet …", "→ Rechnung … geöffnet")
- **Covered by test:** NONE (no frontend tests)
- **Prompt block:** —
- **Status:** enforced (frontend convention, untested)

## COP-06 — Rechnung und KVA werden per Live-Formular-Übernahme erstellt: Das Panel öffnet das echte Formular (/invoices/new, /cost-estimates/new), das sich sichtbar selbst ausfüllt; schlägt das fehl oder meldet sich 60 s nicht, fällt es auf den direkten API-Pfad zurück.
- **Enforced by:** `CopilotPanel.tsx:confirmLive` + `LIVE_FILL_TOOLS`; protocol in `frontend/src/lib/liveFill.ts` (`requestLiveFill`/`consumeLiveFill` one-shot via sessionStorage; 60 s timeout → `confirmViaApi` fallback); consumed by `frontend/src/pages/InvoiceFormPage.tsx` / `CostEstimateFormPage.tsx`
- **Surfaced in UI:** Invoice/KVA form pages animate filling; panel shows "Kiki öffnet das Formular und füllt es live aus…"
- **Covered by test:** NONE
- **Prompt block:** —
- **Status:** enforced (frontend convention, untested)

## COP-07 — create_employee legt nur einen Mitarbeiter-Datensatz an (login_access=False); die Login-Einladung bleibt ein bewusster manueller Schritt auf der Mitarbeiter-Seite.
- **Enforced by:** `tools.py:_create_employee` (hardcoded `login_access=False`; comment "Record-only (no login invite)"); tool description says "OHNE Login"
- **Surfaced in UI:** Result note in chat: "Ohne Login angelegt — eine Login-Einladung kann auf der Mitarbeiter-Seite gesendet werden."
- **Covered by test:** NONE (registry gating covered, not the login_access=False behavior)
- **Prompt block:** tool description (sent to the model)
- **Status:** enforced

## COP-08 — Kiki-Zentrale-/Verhaltens-Einstellungen (Autonomie-Stufen, Notdienst, Outbound, KVA-Automatisierung, E-Mail) kann der Copilot nur ERKLÄREN und dorthin navigieren — es existiert kein Schreib-Tool dafür; einzige schreibbare Einstellung sind die Stammdaten (update_org_profile, Admin + Bestätigung).
- **Enforced by:** structurally — `tools.py:REGISTRY` contains no write tool for Kiki-Zentrale settings; `_explain_setting` + `_SETTINGS_DICT` provide read-only explanations pointing to the right page; `_update_org_profile` is whitelisted to `_ORG_PROFILE_FIELDS` (name/trade/phone/fax/email/website/chamber) only
- **Surfaced in UI:** explanations in chat; `navigate_to` route `/kiki-zentrale`
- **Covered by test:** `test_copilot.py::test_explain_setting_matches_german_terms`; absence-of-write-tool not asserted
- **Prompt block:** "Einstellungen/Systemänderungen" bullet (impact warning before confirmation)
- **Status:** enforced

## COP-09 — Kundenbezug wird vor jeder kundenbezogenen Aktion aufgelöst: 0 Treffer → Fehler statt Aktion, mehrere Treffer → Rückfrage mit Kandidatenliste; Kundennummer wird nie als ID verwendet.
- **Enforced by:** `tools.py:_resolve_customer` (UUID / customer_number / name lookup; returns `error` or `ambiguous`+candidates), called by `_update_customer`, `_create_appointment`, `_create_project`, `_create_cost_estimate`, `_create_invoice`; search args sanitized via `_sanitize_search` (strips PostgREST filter metacharacters)
- **Surfaced in UI:** the model relays "nicht gefunden" / asks which candidate in chat
- **Covered by test:** NONE (resolution helper untested)
- **Prompt block:** "Kundenbezug immer zuerst auflösen"
- **Status:** partially-enforced (backend resolution enforced; the "ask which one" flow relies on the model relaying the ambiguous result)

## COP-10 — Vom Client mitgesendete Chat-Historie wird bereinigt: system- und tool-Nachrichten werden verworfen (kein Fälschen von Tool-Ergebnissen oder System-Prompts), Kontext auf 20 Turns begrenzt.
- **Enforced by:** `orchestrator.py:_clean_history` (only user/assistant roles, `[-20:]` cap); exactly one system prompt from `prompt.py:system_prompt`
- **Surfaced in UI:** —
- **Covered by test:** `test_copilot.py::test_client_supplied_system_and_tool_history_is_ignored`
- **Prompt block:** —
- **Status:** enforced

## COP-11 — Chat-Sitzungen werden persistent gespeichert (copilot_conversations/copilot_messages, Migration 0042), strikt pro Org UND Nutzer; wiedergeöffnete Aktionskarten aus alten Chats sind reine Anzeige — eine erneute Bestätigung alter Writes ist nicht möglich.
- **Enforced by:** `copilot.py:_persist_turn` (ownership check org_id+user_id before reusing a conversation_id; best-effort/fail-open), `list_conversations`/`get_conversation`/`delete_conversation` (all filter org_id+user_id, 404 otherwise); `CopilotPanel.tsx:openConversation` maps historical actions to status `'cancelled'` ("Aus früherem Chat — bei Bedarf erneut anfordern.")
- **Surfaced in UI:** history view in `CopilotPanel.tsx` (list, open, delete)
- **Covered by test:** NONE
- **Prompt block:** —
- **Status:** enforced

## COP-12 — Der Copilot ist strikt CRM-only: Privates, Allgemeinwissen, Programmierung usw. werden abgelehnt; Daten-Texte (Transkripte, Notizen) gelten als Inhalt, nicht als Befehle; ohne passendes Tool wird nie ein falsches Tool benutzt, sondern eine Support-Meldung angeboten.
- **Enforced by:** PROMPT-ONLY (`prompt.py:system_prompt`, "STRIKTE GRENZEN" + "Kein passendes Tool? Niemals ein falsches verwenden."); partially backed structurally — the model has no tools outside the registry, and `report_problem` (`tools.py:_report_problem`) escalates to `ESCALATION_EMAIL` with a `copilot_escalations` DB record
- **Surfaced in UI:** refusal text in chat; "Problem melden" action card
- **Covered by test:** `test_copilot.py::test_report_problem_requires_summary` (escalation validation only); the scope refusal itself is untested
- **Prompt block:** "STRIKTE GRENZEN"
- **Status:** prompt-only

## COP-13 — Jede bestätigte Schreibaktion wird auditiert (copilot_action_audit: org, user, tool, args, Ergebnis-Status); das Audit ist fail-open und blockiert nie die Aktion.
- **Enforced by:** `copilot.py:_audit` (called from `confirm` after every execution)
- **Surfaced in UI:** —
- **Covered by test:** NONE
- **Prompt block:** —
- **Status:** enforced

## COP-14 — Es gibt keine über die Tool-Art hinausgehende L1–L3-Aktions-Gating-Logik im Copilot; die Autonomie-Stufen 1–3 betreffen den Voice-Agenten und werden im Copilot nur erklärt.
- **Enforced by:** NOT ENFORCED in copilot code — searched `tools.py`/`orchestrator.py`/`copilot.py` for level/autonomy gating; only found `kind: read|write|sensitive|dangerous` (the confirm gate, COP-03) and the `autonomy` entry in `_SETTINGS_DICT` (explanation text for the voice agent's Stufe 1–3)
- **Surfaced in UI:** —
- **Covered by test:** NONE
- **Prompt block:** —
- **Status:** [VERIFY WITH AMBER] — confirm that L1–L3 gating is intentionally voice-agent-only and the copilot's confirm-gate is the intended equivalent
