# German Language Audit Changelog

Branch: `fix/de-language-audit-luca`  
Date: 2026-06-26  
Authority: Amber PO override — **Angebot** (not Kostenvoranschlag) for all display text; internal keys `doc_type=kva`, `referenz_typ=KVA` unchanged.

## Summary

Second-pass audit fixing grammar errors, incomplete Angebot migration, Sie→Du (including outbound call scripts), Luca meeting notes, and remaining CSV gaps. Frontend build (`npm run build`) passes.

## Critical fixes (Luca's top complaints)

| Area | Before | After | File |
|------|--------|-------|------|
| Posteingang AI card | `KVA`, `Kostenvoranschlag für …`, `KVA erstellen` | `Angebot`, `Angebot für …`, `Angebot erstellen` | `frontend/src/pages/posteingang/api.ts:154` |
| Posteingang pending | `KVA-Antwort` | `Angebot-Antwort` | `frontend/src/pages/posteingang/api.ts:162` |
| Angebot gender | `Neuer Angebot`, `Der Angebot`, `Unverbindlicher Angebot` | `Neues Angebot`, `Das Angebot`, `Unverbindliches Angebot` | `CostEstimateFormPage.tsx`, `CostEstimatesPage.tsx`, `projectTabs.tsx` |
| Angebot gender | `Ihr Angebot`, `ein gesendeter Angebot` | `Dein Angebot`, `ein gesendetes Angebot` | `CostEstimatesPage.tsx`, `SettingsPage.tsx` |
| API error | `Der Angebot ist abgelaufen` | `Das Angebot ist abgelaufen` | `backend/app/api/routes/cost_estimates.py:505` |
| Outbound KVA ref | `Ihren Angebot`, `den Angebot` | `dein Angebot`, `das Angebot` | `backend/app/services/outbound_occasions.py` |

## Luca meeting notes (2026-06-26)

| Item | Before | After | File |
|------|--------|-------|------|
| Status filter | `Alle Status` | `Status: alle` | `CaseList.tsx`, `CostEstimatesPage.tsx`, `InvoicesPage.tsx`, `CatalogPage.tsx`, `projectTabs.tsx` |
| Call log column | `Vorgang / Anfrage` | `Vorgang` | `frontend/src/pages/calls/log/LogTable.tsx:248` |
| Worklist tab | `Aktionen` | `Aufgaben` | `Workspace.tsx`, `LogDrawer.tsx` |
| Kiki-Zentrale nav | `Umbenennen` | `Versionsverlauf` | `KikiZentralePage.tsx:47` |

## Rule-based fixes

### Sie → Du
- **Frontend:** `Ihres Minutenkontingents` → `deines Minutenkontingents`; email templates `Sehr geehrte` → `Hallo`; full `LoginPage.tsx` Germanization.
- **Backend voice:** All outbound occasion first messages + voicemails in `outbound_occasions.py`; tool responses in `appointments.py`, `identify.py`, `inquiries.py`, `transfer.py`, `conversation_init.py`, `pds.py`, `knowledge.py`.
- **Emails:** `occasion_emails.py`, `appointment_emails.py`, `cost_estimates.py`, route defaults in `cost_estimates.py` / `invoices.py`; invite subject `Ihr Zugang` → `dein Zugang`.

### Fall → Vorgang / FL- → VG-
- `LogDrawer.tsx` fallback `Fall` → `Vorgang`
- `ProjectFormPage.tsx` placeholder `FL-…` → `VG-…`
- `projects.py` HTTP errors: all `Fall`/`Fälle` → `Vorgang`/`Vorgänge`
- `validate_fk_in_org(..., label="Fall")` → `label="Vorgang"` (invoices, inquiries, cost_estimates, appointments)

### Agent / ElevenLabs → Kiki
- `Kiki OK`, `Kiki-Problem`, `Kiki-Status`, `Kiki erreichbar` in `KikiZentralePage.tsx`
- Admin orgs: `Kiki`, `Kiki-Status`, `kein Kiki` in `AdminOrgsPage.tsx`
- Rollback modals: `Kiki wird …` in `VerlaufSection.tsx`, `PromptEditorSection.tsx`
- API errors: `Sprach-ID` instead of `ElevenLabs Agent ID` in `super_admin.py`, `calls.py`

### Denglisch
- `Login` → `Zugang` in `employees.py` user messages
- `Kalender-Sync` → `Kalender-Abgleich` in `calendar_settings.py`
- `Matcher ausführen` → `Probelauf starten` in `AdminBillingPage.tsx`
- `Lädt…` → `Wird geladen…` (multiple pages)
- `ggü. Vorperiode` → `gegenüber Vormonat` in `dashboard/shared.tsx`
- `Aktionsempfehlungen` → `Empfehlungen` in `KiInsightsTab.tsx`

## Tests updated
- `backend/tests/test_kva_send_and_routes.py`: assertions match `Angebot wurde erstellt` / `Das Angebot wurde per E-Mail versendet`

## Final pass (2026-06-26, session 2)

### PDF Angebot footer
- Removed §632 Abs. 3 BGB / §650c Kostenvoranschlag legal text for unbinding Angebote
- Replaced with neutral unverbindliches-Angebot wording + Toleranz ±{tol}% in `backend/app/services/cost_estimates.py`

### Inbound Du (phone persona)
- Full Sie→Du pass on `backend/app/services/agent_prompt_template.txt` (~65 patterns)
- Price-script Du in `backend/app/services/agent_config.py`
- Trade diagnostic/self-help examples Du in `backend/app/services/trade_profiles.py`
- Added explicit Duzen + German/Kiki summary rules in prompt `# Ton` section

### Call summary language
- `post_call.py`: sanitize EL summary/title (`agent`→`Kiki`, `Kostenvoranschlag`→`Angebot`)
- `call_enrichment.py`: after enrichment, persist German bullet summary to `calls.summary`

## PO decisions — resolved

1. ~~§632 PDF footer~~ — fixed (Angebot-only neutral text)
2. ~~EL summary English/agent~~ — prompt rules + ingest sanitization + enrichment override
3. ~~Inbound Sie in prompt files~~ — full Du pass applied
4. **Table column `Aktionen`** on CRUD tables — kept as standard edit/delete column label (intentional)

## Verification (final)

- `npm run build` — pass
- Post-fix grep: no user-visible `Kostenvoranschlag`, `KVA` label, `Neuer/Der Angebot`, `Agent OK`, `ElevenLabs` in UI strings
- Inbound prompt: 0 formal Sie/Ihnen/Ihr (except Du rule meta-text)
