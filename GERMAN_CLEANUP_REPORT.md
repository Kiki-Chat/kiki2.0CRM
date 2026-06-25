# German UI Cleanup — Change Report

**Branch:** `feat/de-translation-pass` (off `claude/peaceful-johnson-fb4e72` HEAD `fa7a2b3`)
**Sources:** `Kiki-CRM-Texte-korrigiert.xlsx` (156 string corrections) + `HeyKiki-UI-Texte-Amber.docx` (8 global rules, 21 screens, bugs, features)
**Tooling note:** the extraction/import scripts in `scripts/i18n_cleanup/` are **git-excluded** — never committed. Only product changes are committed.

**Status: committed · frontend `tsc -b` clean · backend suite 967 passed** (the single failure is a network-only env artifact — a test makes a real HTTP call to the dummy `SUPABASE_URL`).

## ⚠️ Verification correction (honesty note)
An earlier version of this report claimed "Sie→Du done" after the *first* pass. That was wrong — the first pass used a **narrow grep filter** and missed instances. Two later rounds caught them:
- **Live preview review** (rendered the app on :5199) found ~18 missed Sie strings (admin gates, error messages, Rufumleitung guide, form subtitles, invoice/email templates) + the `KVA-2026` placeholder → fixed (`edb4c0a`).
- **Comprehensive *unfiltered* scan** then found **14 more** (DashboardPage, CostEstimatesPage email, projectTabs, RufumleitungGuidePage ×3, SetPasswordPage, CalendarPage, Modals, CustomerFormModal, AgentSyncBanner, `KVA-Platzhalter`/`KVA-E-Mail`) → fixed (`7810123`).

**Round 3 — rendered admin/employee/technician audit (preview on :5173).** The admin "gate" turned out to be a **CORS/port issue** (backend allows `localhost:5173`; preview was on `:5199`) — the `govindyadav0703` account IS `org_admin` (`/api/me` → 200, role `org_admin`). On :5173 the admin content rendered, and per-screen `preview_eval` text audits caught **~30 more misses** the earlier filtered greps left: admin `Kalender-Sync`→`Kalender-Abgleich`; employee `Login`-badge→`Zugang`, "Kein Login nötig"→"Keine Anmeldung nötig", **"Quota überschritten"→"Kontingent überschritten"** (Luca's #1 flagged error), `Module`→`Bereiche`, `CSV Import`→`CSV-Import`; and **~20 backend written-Sie** (employee_invite email, cost-estimate/invoice/billing/cases/settings/appointments route emails+errors, kiki_zentrale validation, common.py auth, ratelimit). All fixed.

**FINAL verified tally (unfiltered, frontend + backend): formal Sie/Ihr = 0 · KVA/Kostenvoranschlag word = 0 · Fall/Fälle UI = 0 · Denglisch (Login/Sync/Quota/Module/Monteur) = 0.** Rendered-verified: admin Settings (du subtitle, Kalender-Abgleich, du email templates), employee Mitarbeiter (ZUGANG column, Techniker roles), technician JobLinkPage (source: Abgeschlossen/Vorgang/0 Sie). Phone-persona Sie (what Kiki *says* on calls — pds/identify/transfer/inquiries/conversation_init + prompts) deliberately left for the brand decision.

**Lesson learned: a narrow/filtered grep is NOT verification. Unfiltered scan + rendered audit is.**

---

## ⚠️ Needs you / flagged (not silently done)

1. **`Angebot` legal text.** KVA→Angebot is applied everywhere per your call. The PDF still prints *"Dieses Angebot ist gemäß § 632 Abs. 3 BGB unverbindlich"* — but **§ 632 BGB is Kostenvoranschlag-specific, and an Angebot can be legally binding.** Have someone confirm this clause is still correct for an "Angebot", or it may need rewording/removal. (`backend/app/services/cost_estimates.py:205`)
2. **Two DB migrations to run manually** (you said you'll execute SQL in Supabase):
   - `supabase/migrations/0077_case_number_vg_prefix.sql` — `FL-… → VG-…`
   - `supabase/migrations/0078_cost_estimate_kva_to_ag_prefix.sql` — `KVA-… → AG-…`
   Until run, existing records keep old prefixes while new ones mint the new prefix. (I did **not** touch any DB — the MCP env changed and only "KikiDashboard"/"prod" are reachable.)
3. **Agent phone persona (du vs Sie on calls).** I applied du to all *written* customer docs (emails/PDFs/billing), but **deliberately did NOT** change the agent's spoken scripts (`outbound_occasions.py`, `agent_prompt_template.txt`) — Kiki saying "du" to customers on the phone is a brand decision. Confirm and I'll extend it.
4. **The English call summary** (your screenshot: *"The user… the agent confirmed…"*). It's **ElevenLabs server-side generated** — not a static string. Forcing German + "Kiki" needs an EL transcript-summary prompt added to the agent config + a verification call. Flagged, not done.

---

## ✅ Done & committed (per phase)

| Commit | Phase | Verified |
|---|---|---|
| `74ce298` | **156 Excel corrections** auto-imported (204 occ, 60 files); 23 "entfernen" rows skipped | tsc ✓ |
| `349f159` | **Fall→Vorgang** frontend (Regel in call-logic; `'fall'` enum + identifiers preserved) | tsc ✓ |
| `8276577` | **FL-→VG- prefix** (`gen_case_number`) + migration 0077 + backend "Fall" text (idioms/Notfall safe) | 48 tests ✓ |
| `ab801e7` | **Bugs:** `&amp;`→`&`, Fertig→Abgeschlossen (+ technician button), plural "1 Projekt/Anfrage", Top→Häufigste Anrufer | tsc ✓ |
| `ce6a989` | **KVA/Kostenvoranschlag→Angebot** product-wide (labels/PDFs/emails/prompts; masc→neuter gender fixes); `kva` prefix KVA→AG + migration 0078; doc_type key + `referenz_typ` discriminator kept | 967 tests ✓ |
| `7937f40` | **Denglisch** (KI-Insights→KI-Auswertung, Timeline→Zeitachse, Sync→Synchronisieren, einloggen→anmelden, Plan-Limit→Kontingent) + **Aktion→Aufgabe** (todo) | tsc ✓ |
| `888fcbf` | **Sie→Du** frontend UI + customer-facing written docs (emails/PDFs/billing), correct verb conjugation | 967 tests ✓ |
| `5465bfa` | **Agent→Kiki** + dev-jargon (Agenten-Begrüßung→Kikis Begrüßung, Kontext-Initialisierung→Gesprächseinstieg) | tsc ✓ |

### Luca's 8 global rules
| Rule | Status |
|---|---|
| 1 · Sie→Du | **Done** for CRM UI + written customer docs. (Phone scripts flagged above.) |
| 2 · Fall→Vorgang + FL→VG | **Done** (text + prefix + migration 0077). |
| 3 · KVA→Angebot | **Done** product-wide (your override of Luca's Kostenvoranschlag; legal text flagged). |
| 4 · Aktion→Aufgabe | **Done** (Excel + hardcoded todo strings). |
| 5 · Monteur→Techniker | **Done** (UI via Excel; 2 leftovers were in prompt files). |
| 6 · Denglisch | **Done** (display only; identifiers/routes/CSS untouched). |
| 7 · Dev jargon | **Done** for located strings. |
| 8 · ElevenLabs out of UI | **Done** (display gone via Excel; only code comments mention it). |

### Bugs (docx §23) & your B-list
Entities ✓ · plural ✓ (Projekt/Anfrage; a shared `plural()` helper for *all* count displays is a nice-to-have follow-up) · Fertig→Abgeschlossen ✓ · Häufigste Anrufer ✓ · Zuständing → ignore (not in code) · code-fragments → skipped on import · "Kiki hat alles im Griff" → done via Excel · one word "Aufgaben" → applied where found.

---

## ⏳ Remaining / follow-ups
- The 4 flagged items above (legal text, 2 migrations, phone persona, EL summary).
- **Field-tags `caller_id`/`address` hide:** I couldn't find them rendered visibly in the current code (only the German label + semantic badges show) — may already be hidden, or needs the exact screen from Luca.
- **Per-screen docx polish:** most table rows were "(bleibt)" (no change) or already covered by the sweeps/Excel; any remaining one-off rewordings can be a quick cleanup pass.
- **Features (separate PR, as agreed):** KVA type-dropdown cleanup · date-range filters (Angebot + Rechnungen) · split Wissensbasis nav · move KI-Vorschläge to Kiki-Zentrale · remove KI-confidence badge.

## How to verify locally
- Frontend: `cd frontend && npx tsc -b` (clean).
- Backend: needs `SETTINGS_ENC_KEY` (any Fernet key) + `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` env to collect; then `pytest -q` → 967 pass (1 network-only).
- Browser preview of the changed screens not yet done (needs a running dev server + login).
