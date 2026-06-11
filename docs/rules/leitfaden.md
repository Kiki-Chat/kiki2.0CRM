# Business Rules — Leitfaden (Gesprächsleitfaden / Pflichtfelder)

Rules governing the ordered Gesprächsleitfaden in Kiki-Zentrale (formerly "Pflichtfelder"): the field list, the linked offer-steps (Termin/KVA/Preisauskunft), how the list reaches the agent prompt via `{{KZ_REQUIRED_FIELDS}}`, and the static prompt blocks for Bestandsbezug and callbacks on open cases. All references verified in code on 2026-06-11.

## LEIT-01 — Der Leitfaden wird nur als KOMPLETTE geordnete Liste gespeichert (Index = sort_order, pro Zeile ein Aktiv-Schalter), mit genau EINEM Agent-Repush pro Speichern.
- **Enforced by:** `backend/app/api/routes/kiki_zentrale.py:save_leitfaden` (PATCH `/kiki-zentrale/leitfaden`; admin-gated via `_require_admin`; single `_schedule_repush(..., "kz_leitfaden")`)
- **Surfaced in UI:** `frontend/src/components/kiki/ConfigSections.tsx:LeitfadenSection` (route `/kiki-zentrale/leitfaden`; old `/pflichtfelder` redirects in `KikiZentralePage.tsx`)
- **Covered by test:** NONE (endpoint itself untested; repush plumbing covered by `backend/tests/test_round2_features.py::test_repush_bg_delegates`)
- **Prompt block:** —
- **Status:** enforced

## LEIT-02 — Ein veralteter Leitfaden darf nicht gespeichert werden: Stimmen die gesendeten Zeilen-IDs nicht exakt mit dem DB-Stand überein, wird mit 409 abgelehnt.
- **Enforced by:** `backend/app/api/routes/kiki_zentrale.py:save_leitfaden` (`current_ids != sent_ids` → 409 "Die Liste ist veraltet…")
- **Surfaced in UI:** error toast in `ConfigSections.tsx:LeitfadenSection`
- **Covered by test:** NONE
- **Prompt block:** —
- **Status:** enforced

## LEIT-03 — Verknüpfte Angebots-Zeilen (Termin/KVA/Preisauskunft) spiegeln IMMER die echte agent_configs-Einstellung; ihr eigenes is_active ist nur Positions-Platzhalter (Zwei-Wege-Sync).
- **Enforced by:** `backend/app/api/routes/kiki_zentrale.py:list_required_fields` (read-through from `agent_configs`) and `save_leitfaden` (write-through to `appointments_enabled`/`kva_enabled`/`price_info_enabled` via `_LINKED_SETTINGS`); render side: `backend/app/services/agent_config.py:_field_effective_active`
- **Surfaced in UI:** `ConfigSections.tsx:LeitfadenSection` (toggles on the linked rows = Autonomie/Preisauskunft settings)
- **Covered by test:** `backend/tests/test_round2_features.py::test_seed_required_fields_inserts_name_phone_address` (asserts `linked_setting == "appointments_enabled"` on the seeded row) — render/sync paths NOT directly tested
- **Prompt block:** —
- **Status:** partially-enforced

## LEIT-04 — Preisauskunft kann im Leitfaden nicht aktiviert werden, solange kein aktiver Artikel mit Preis > 0 existiert (422).
- **Enforced by:** `backend/app/api/routes/kiki_zentrale.py:save_leitfaden` (`no_prices` guard on `catalog_items`; comment says same guard as PATCH `/price-info`)
- **Surfaced in UI:** error toast "Preisauskunft kann nicht aktiviert werden…" in LeitfadenSection
- **Covered by test:** NONE (for the leitfaden path)
- **Prompt block:** `# Preise` (referenced by the rendered offer line)
- **Status:** enforced

## LEIT-05 — Gesperrte Felder (is_locked, z. B. Name/Telefon/Adresse/Anliegen und die Angebots-Zeilen) können nicht gelöscht werden — nur umsortiert/bearbeitet.
- **Enforced by:** `backend/app/api/routes/kiki_zentrale.py:delete_required_field` (locked → 400 "Pflichtfeld ist gesperrt…"; missing → 404; repush only on real delete)
- **Surfaced in UI:** LeitfadenSection (locked rows have no delete control)
- **Covered by test:** NONE
- **Prompt block:** —
- **Status:** enforced

## LEIT-06 — Jede neue Org wird idempotent mit dem Standard-Leitfaden geseedet: Name, Telefon (caller_id), Adresse, Anliegen (alle gesperrt), optionale E-Mail (standardmäßig inaktiv) plus die drei verknüpften Angebots-Zeilen.
- **Enforced by:** `backend/app/services/provisioning.py:_seed_required_fields` (`_DEFAULT_REQUIRED_FIELDS`, migration 0060; no-op when rows exist)
- **Surfaced in UI:** initial LeitfadenSection contents for a fresh org
- **Covered by test:** `backend/tests/test_round2_features.py::test_seed_required_fields_inserts_name_phone_address`, `::test_seed_required_fields_idempotent_when_rows_exist`
- **Prompt block:** —
- **Status:** enforced

## LEIT-07 — Der Leitfaden erreicht den Agenten als geordnete Liste im Prompt-Token {{KZ_REQUIRED_FIELDS}} unter „## Pflichtfelder“; der Agent muss die Punkte in GENAU dieser Reihenfolge abarbeiten und bereits bekannte/automatisch erkannte Felder NICHT erneut erfragen.
- **Enforced by:** `backend/app/services/agent_config.py:render_required_fields_block` (lead paragraph + ordered bullets; wired at `agent_config.py:1013`) — the ordering obligation itself is an instruction to the LLM
- **Surfaced in UI:** drag-and-drop order in LeitfadenSection; prompt preview in `PromptEditorSection.tsx`
- **Covered by test:** `backend/tests/test_dynamic_prompt.py::test_required_fields_lists_label_description_and_optional`
- **Prompt block:** `## Pflichtfelder` → `{{KZ_REQUIRED_FIELDS}}` (agent_prompt_template.txt ~line 633)
- **Status:** partially-enforced (rendering enforced; conversational ordering is prompt-only)

## LEIT-08 — Ein leerer oder komplett inaktiver Leitfaden fällt auf ein sinnvolles Standard-Set zurück (Name, Telefonnummer, Adresse, Anliegen; optional Kundennummer) — der Agent verliert nie seine Datenerfassungs-Anweisung.
- **Enforced by:** `backend/app/services/agent_config.py:render_required_fields_block` (both `if not fields` and `if not lines` fallbacks)
- **Surfaced in UI:** —
- **Covered by test:** `backend/tests/test_dynamic_prompt.py::test_required_fields_empty_has_sensible_fallback`
- **Prompt block:** `## Pflichtfelder`
- **Status:** enforced

## LEIT-09 — Aktive Angebots-Zeilen rendern an ihrer gezogenen Position eine ANGEBOTS-Anweisung (Termin anbieten / KVA anbieten / Preisauskunft) statt einer Frage; eine inaktive verknüpfte Zeile rendert NICHTS — der Negativfall wird von KZ_AUTONOMY / KZ_PRICE_INFO getragen.
- **Enforced by:** `backend/app/services/agent_config.py:_LINKED_OFFER_LINES` + `render_required_fields_block` (offer line at the row's position; skip when `_field_effective_active` is false)
- **Surfaced in UI:** LeitfadenSection (offer rows draggable between fields)
- **Covered by test:** NONE (no test renders a linked offer row)
- **Prompt block:** `## Pflichtfelder`; negative case in `{{KZ_AUTONOMY}}` / `{{KZ_PRICE_INFO}}`
- **Status:** partially-enforced

## LEIT-10 — Die E-Mail-Adresse wird nur bei ausdrücklichem Versandwunsch (KVA/Bestätigung per Mail) erfragt — AUSSER „E-Mail-Adresse“ steht im Leitfaden: dann hat die Liste Vorrang und die E-Mail wird regulär an ihrer Position erfragt.
- **Enforced by:** PROMPT-ONLY — static rule in `backend/app/services/agent_prompt_template.txt` (~lines 620–631, "AUSNAHME: Steht „E-Mail-Adresse“ in der Leitfaden-Liste …"); the email field itself is seeded inactive by `provisioning.py:_DEFAULT_REQUIRED_FIELDS`
- **Surfaced in UI:** email row toggle in LeitfadenSection
- **Covered by test:** NONE
- **Prompt block:** the E-Mail-Erfassung section preceding `## Pflichtfelder`
- **Status:** prompt-only

## LEIT-11 — Bestandsbezug ohne System-Treffer: Findet Kiki einen referenzierten Termin/Auftrag/Kunden nicht, behandelt sie das als Lücke der zweiten Datenquelle und macht diese Lücke gegenüber dem Anrufer NICHT transparent (kein „Sie sind nicht im System“).
- **Enforced by:** PROMPT-ONLY — static block `# Bestandsbezug ohne System-Treffer` in `agent_prompt_template.txt` (~line 137); not configurable in Kiki-Zentrale (no KZ token, verified by grep)
- **Surfaced in UI:** — (read-only via prompt preview in PromptEditorSection)
- **Covered by test:** NONE
- **Prompt block:** `# Bestandsbezug ohne System-Treffer`
- **Status:** prompt-only

## LEIT-12 — Rückruf auf offenen Vorgang: Die proaktive Eröffnung („Schön, dass Sie zurückrufen — geht es um den Alternativtermin am [Datum]?“) ist NUR beim kundenbezogenen Block „HÄNGENDE AKTIONEN“ erlaubt; beim org-weiten Hint im NEUKUNDE-/WEITERGELEITET-Pfad gilt der normale Neukunden-Leitfaden, das Wort „Termin“ allein ist KEIN Rückruf, und Termine ohne konkretes Tool-Datum dürfen nie halluziniert werden.
- **Enforced by:** PROMPT-ONLY — static block `# Rückruf auf offenen Vorgang` in `agent_prompt_template.txt` (~lines 505–590); data side (HÄNGENDE AKTIONEN section) is produced by the `hk_identifyCustomer` tool, prompt behavior is uncoded
- **Surfaced in UI:** —
- **Covered by test:** NONE in backend pytest (case-threading lives on `feature/vorgang-case-threading`; agent-side behavior checked via the eval harness replay corpus, `docs/AGENT_EVAL_BASELINE.md`)
- **Prompt block:** `# Rückruf auf offenen Vorgang`
- **Status:** prompt-only
