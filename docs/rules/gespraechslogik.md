# Business Rules — Gesprächslogik (conversation logic)

Rules governing how Kiki conducts the call: the org-configurable Leitfaden (agent_required_fields), the Wenn/Dann "Schritt 1a" block, and the hard conversational guardrails baked into the static prompt template. Verified against `backend/app/services/agent_config.py`, `backend/app/api/routes/kiki_zentrale.py`, `backend/app/schemas/conversation_logic.py`, `backend/app/services/agent_prompt_template.txt`, and `frontend/src/components/kiki/`.

## GSP-01 — Kiki stellt immer nur eine Frage auf einmal.
- **Enforced by:** PROMPT-ONLY (`agent_prompt_template.txt` line 64: „Stelle IMMER nur eine Frage auf einmal.")
- **Surfaced in UI:** — (not org-configurable)
- **Covered by test:** NONE (behavioral; eval harness in docs/AGENT_EVAL_BASELINE.md does not assert this explicitly)
- **Prompt block:** intro/behavior section (before „## Schritt 1")
- **Status:** prompt-only

## GSP-02 — Kiki macht keine Gesprächszusammenfassungen und wiederholt keine bereits gesammelten Daten.
- **Enforced by:** PROMPT-ONLY (`agent_prompt_template.txt` lines 583–585, with FALSCH/RICHTIG example)
- **Surfaced in UI:** —
- **Covered by test:** NONE
- **Prompt block:** NIEMALS guardrail list (between „## Abschluss" and „## Autonomie-Hinweis" area, lines 570–600)
- **Status:** prompt-only

## GSP-03 — Die Pflichtfelder/Leitfaden-Punkte werden in der vom Betrieb konfigurierten Reihenfolge (sort_order) abgearbeitet; bereits bekannte/automatisch erkannte Felder werden nicht erneut erfragt, nur kurz bestätigt.
- **Enforced by:** `agent_config.py:render_required_fields_block` (lines 530–582; ordered fetch in `_fetch_required_fields` line 321, `order("sort_order")`); reorder persisted by `kiki_zentrale.py:save_leitfaden` (PATCH /leitfaden, index = sort_order) and `reorder_required_fields`
- **Surfaced in UI:** Kiki-Zentrale → Leitfaden tab (`frontend/src/components/kiki/ConfigSections.tsx` PflichtfelderSection, drag list; `KikiZentralePage.tsx` slug `leitfaden`)
- **Covered by test:** `backend/tests/test_dynamic_prompt.py::test_required_fields_lists_label_description_and_optional` (order/lead text), `::test_required_fields_empty_has_sensible_fallback`
- **Prompt block:** `## Pflichtfelder` (token `{{KZ_REQUIRED_FIELDS}}`)
- **Status:** enforced (rendering); the agent following the order is prompt-driven

## GSP-04 — Felder mit is_duty=false werden im Leitfaden als „(optional)" markiert; ohne jede Konfiguration gilt der Default-Satz Name, Telefonnummer, Adresse, Anliegen (Pflicht) + Kundennummer (optional).
- **Enforced by:** `agent_config.py:render_required_fields_block` (line 556 `opt = "" if f.get("is_duty", True) else " (optional)"`; fallback lines 538–542)
- **Surfaced in UI:** Leitfaden tab — Pflicht/Optional toggle per field (PflichtfelderSection)
- **Covered by test:** `test_dynamic_prompt.py::test_required_fields_lists_label_description_and_optional`, `::test_required_fields_empty_has_sensible_fallback`
- **Prompt block:** `## Pflichtfelder`
- **Status:** enforced

## GSP-05 — Das gesperrte Feld „problem_description" (is_locked, seeded per Migration 0052) kann nicht gelöscht werden; sein Hinweistext rendert INNERHALB des Pflichtfelder-Blocks an seiner Position.
- **Enforced by:** `kiki_zentrale.py:delete_required_field` (lines 742–761 → 400 „Pflichtfeld ist gesperrt…"); rendering switch in `agent_config.py` lines 1013–1024 (`KZ_PROBLEM_HINTS` emptied when the field row exists) + `render_problem_description_block` (lines 617–628)
- **Surfaced in UI:** Leitfaden tab — lock icon, delete disabled (`ConfigSections.tsx` lines ~244, 268, 320; special edit path for `field_key === 'problem_description'` line ~106)
- **Covered by test:** `test_dynamic_prompt.py::test_problem_description_empty_is_blank`, `::test_problem_description_includes_text` (rendering); delete-block itself: NONE
- **Prompt block:** `## Pflichtfelder` / `{{KZ_PROBLEM_HINTS}}`
- **Status:** enforced

## GSP-06 — Die firmenspezifische Wenn/Dann-Gesprächslogik wird als verbindlicher Block „Schritt 1a" kompiliert; trifft ein Zweig zu, ersetzt er die generischen Rückfragen aus Schritt 1, Schritte 0/2/3 bleiben unverändert.
- **Enforced by:** `agent_config.py:render_conversation_logic_block` (lines 585–614) + `app/schemas/conversation_logic.py:compile_conversation_logic`; token `{{KZ_CONVERSATION_LOGIC}}` (line 1024)
- **Surfaced in UI:** Kiki-Zentrale → Gesprächslogik tab (`frontend/src/components/kiki/GespraechslogikSection.tsx`, builder + live preview via POST /conversation-logic/preview)
- **Covered by test:** `backend/tests/test_conversation_logic.py::test_render_block_wraps_with_schritt_1a_header`, `::test_compiler_produces_numbered_german_block`, `::test_or_conditions_join_with_oder`
- **Prompt block:** `## Schritt 1a — Firmenspezifische Gesprächslogik (VERBINDLICH)`
- **Status:** enforced (compilation/injection); branch-following at runtime is prompt-driven

## GSP-07 — Gesprächslogik-Bäume werden vor dem Speichern hart validiert: max. 10 Regeln, 5 Zweige, 8 Aktionen, 4 Bedingungen, 200 Zeichen pro Text, 80 Knoten, 4000 kompilierte Zeichen, Verschachtelung nur 1 Ebene tief, „Sonst" nie zuerst.
- **Enforced by:** `kiki_zentrale.py:_validate_logic_or_422` (lines 793–817, 422 on violation) calling `conversation_logic.py:validate_conversation_logic` (MAX_* constants lines 21–27)
- **Surfaced in UI:** Gesprächslogik tab — save/preview errors shown from the 422 detail (German messages)
- **Covered by test:** `test_conversation_logic.py::test_validation_rejects_sonst_first_and_deep_nesting`
- **Prompt block:** — (pre-save guard)
- **Status:** enforced

## GSP-08 — Deaktivierte oder leere Gesprächslogik (conversation_logic_enabled=false bzw. keine blocks) erzeugt KEINEN Prompt-Block; ein korrupter gespeicherter Baum darf das Prompt-Rendering nie zum Absturz bringen.
- **Enforced by:** `agent_config.py:render_conversation_logic_block` (lines 589–605: returns "" on disabled/empty; try/except with warning on compile failure)
- **Surfaced in UI:** Gesprächslogik tab — enable/disable toggle (GET/PATCH /conversation-logic, `kiki_zentrale.py` lines 820–852)
- **Covered by test:** `test_conversation_logic.py::test_render_block_disabled_or_empty_is_empty`
- **Prompt block:** `{{KZ_CONVERSATION_LOGIC}}` (vanishes)
- **Status:** enforced

## GSP-09 — Kiki fragt NIEMALS proaktiv nach der E-Mail-Adresse (tool-übergreifend); E-Mail wird nur reaktiv oder situativ erhoben — AUSNAHME: steht „E-Mail-Adresse" explizit im Leitfaden, wird sie dort regulär erfragt.
- **Enforced by:** PROMPT-ONLY (`agent_prompt_template.txt` lines 609–631); backend supports it: `email` optional in bookAppointment/leaveMessage tool specs (lines 672, 713, 677: booking never blocked on missing email)
- **Surfaced in UI:** Leitfaden tab (only by adding an E-Mail field, which triggers the AUSNAHME)
- **Covered by test:** NONE (prompt behavior; the optional-email backend path not specifically tested for this rule)
- **Prompt block:** `## E-Mail-Erhebung (tool-übergreifend)`
- **Status:** prompt-only

## GSP-10 — Datumsklarheit: Wochentage nie selbst nennen, nie Datum + Wochentag kombinieren; `wunschDatum` wörtlich übergeben (nicht verkürzen), konkretes Datum schlägt Wochentagsangabe.
- **Enforced by:** PROMPT-ONLY for the speaking rules (`agent_prompt_template.txt` lines 456–470, 576–578, 653); the literal-phrase parsing itself is backend code (`backend/app/services/scheduling.py` date parsing — partially enforces the intent)
- **Surfaced in UI:** —
- **Covered by test:** NONE for the prompt rules (scheduling parser has its own tests; the „nie Wochentag dazu"-output rule is untested)
- **Prompt block:** `## Schritt 3 — Termin` + `## hk_getAvailableAppointments` parameter docs
- **Status:** partially-enforced

## GSP-11 — Vor end_call MUSS die Abschluss-Frage „Kann ich sonst noch etwas für Sie tun?" gestellt und die Antwort abgewartet werden; ein „Danke" mitten im Gespräch ist kein Auflege-Signal; Verabschiedung mit wörtlichem Schlusssatz.
- **Enforced by:** PROMPT-ONLY (`agent_prompt_template.txt` lines 586–600)
- **Surfaced in UI:** —
- **Covered by test:** NONE
- **Prompt block:** guardrail list around `## Abschluss` / `## end_call`
- **Status:** prompt-only

## GSP-12 — Aktivieren des Leitfaden-Punkts „Preisauskunft" ist nur möglich, wenn mindestens ein aktiver Artikel mit Preis > 0 hinterlegt ist (Toggle-Schreibweg synchronisiert mit agent_configs).
- **Enforced by:** `kiki_zentrale.py:save_leitfaden` (lines 663–671 priced-items guard → 422; linked_setting write-through lines 649–673) and `_field_effective_active` in `agent_config.py` (lines 519–527) for rendering
- **Surfaced in UI:** Leitfaden tab — linked rows (Termin/KVA/Preisauskunft) toggle; error toast on 422
- **Covered by test:** NONE found for the no-prices guard (searched test_round2_features.py, test_dynamic_prompt.py for `price_info`/`leitfaden`)
- **Prompt block:** `## Pflichtfelder` (offer line at configured position via `_LINKED_OFFER_LINES`)
- **Status:** enforced — guard test coverage missing
