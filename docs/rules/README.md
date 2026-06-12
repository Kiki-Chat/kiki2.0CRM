# Business Rules — Index

Registry of all documented business rules, grouped by domain. One line per rule; full detail (Enforced by / UI / Tests / Prompt block) lives in the per-domain files. Statuses: `enforced` (backend code), `prompt-only` (LLM instruction only), `partially-enforced` (code + prompt/test gaps), `mixed` (split per aspect), `VERIFY` (status itself unconfirmed). Generated 2026-06-11.

## Termine ([termine.md](termine.md))

| Rule | German statement (short) | Status |
|------|--------------------------|--------|
| TRM-01 | Termine frühestens nach Vorlaufzeit (Std., optional Werktags, Cap 90 Tage) + „Frühester Termin"-Uhrzeit | enforced |
| TRM-02 | Slots nur innerhalb der Geschäftszeiten (inkl. Mittagspause, geschlossene Tage) | enforced |
| TRM-03 | Max. `parallel_slots` pro Fenster, Puffer beidseitig, Live-Re-Validierung (SLOT_TAKEN) | enforced |
| TRM-04 | Höchstens `max_appointments_per_day` Termine pro Tag (DAY_FULL) | enforced |
| TRM-05 | Termin-Kategorie bestimmt Dauer (min. 15, Default 60) + Standard-Mitarbeiter | enforced |
| TRM-06 | Autonomiestufen: L1 nur Anliegen, L2 'pending' + Team bestätigt, L3 Auto-Confirm nach dem Anruf | enforced |
| TRM-07 | L2-Wortlaut „Ich reserviere…" genau einmal — nie „Ich buche"; verbindlich nur auf L3 | prompt-only |
| TRM-08 | Bestätigen erfordert zugewiesenen Mitarbeiter + Status 'pending' (sonst 409) | enforced |
| TRM-09 | Umbuchung immer In-Place-Vorschlag, nie zweite Termin-Zeile, Admin committet | enforced |
| TRM-10 | Reschedule-Sicherheitstimer (Default 24 h): L1/L2 nur Overdue-Flag, L3 verwirft stale Vorschlag | partially-enforced |
| TRM-11 | Stornieren/Verschieben ohne starke Identität: Datums-Bestätigung, nie raten bei Mehrfachtreffern | enforced |
| TRM-12 | Termine >14 Tage voraus bucht Kiki nicht selbst (Slot-Fenster gecappt), nur Anliegen | partially-enforced |
| TRM-13 | Notfall und Terminbuchung schließen sich aus; Wartungstermine-only bietet nie aktiv an | prompt-only |

## Notdienst ([notdienst.md](notdienst.md))

| Rule | German statement (short) | Status |
|------|--------------------------|--------|
| ND-01 | Notdienst deaktiviert ⇒ nie weiterleiten, außerhalb Geschäftszeiten nur Anliegen aufnehmen | enforced |
| ND-02 | Notfall nur bei konfigurierten Stichwörtern (sonst Standardliste); bei Unsicherheit EINMAL nachfragen | prompt-only |
| ND-03 | Notdienst greift nur außerhalb Geschäftszeiten ODER jederzeit, plus Extra-Zeitfenster | prompt-only |
| ND-04 | Zuschlags-Hinweis (falls aktiviert) VOR der Weiterleitung | prompt-only |
| ND-05 | Bei bestätigtem Notfall KEIN Termin — Termin-Tools tabu | prompt-only |
| ND-06 | Weiterleitung via natives `transfer_to_number` an `emergency_number`, E.164-normalisiert | mixed (tool enforced / Auslösung prompt-only) |
| ND-07 | Gasgeruch ⇒ sofort weiterleiten; sonst erst Bestätigungsfrage, verbinden nur bei „Ja" | prompt-only |
| ND-08 | Ohne Notdienst-Nummer keine Weiterleitung, sondern dringende Rückrufnotiz | partially-enforced |
| ND-09 | Speichern der Notdienst-/Telefonie-Settings triggert Prompt-Repush + System-Tool-Resync | enforced |
| ND-10 | `emergency_flag` nur bei außerhalb Geschäftszeiten UND inhaltlich dringend (inkl. DE/EN-Fallback) | enforced |
| ND-11 | Mitarbeiter-Weiterleitung nur innerhalb Geschäftszeiten und NICHT im Notfall | partially-enforced |
| ND-12 | `transfer_to_agent` nie in eingehenden Anrufen — Notfall nur via `transfer_to_number` | prompt-only |

## Preise ([preise.md](preise.md))

| Rule | German statement (short) | Status |
|------|--------------------------|--------|
| PRE-01 | Preisauskunft Default AUS: keine Preise am Telefon, stattdessen KVA anbieten | prompt-only |
| PRE-02 | Bei Preisauskunft AN: nur Preise aus dem KB-Dokument „Preisliste", nie erfunden | prompt-only |
| PRE-03 | Preisauskunft nicht aktivierbar ohne aktive Artikel mit Preis > 0 (422) | enforced |
| PRE-04 | Preisliste-KB wird automatisch aus dem Katalog erzeugt und bei jeder Änderung neu generiert | enforced |
| PRE-05 | Bei deaktivierter Preisauskunft/leerer Liste wird das KB-Dokument entfernt und gelöscht | enforced |
| PRE-06 | Toggle-Wechsel pusht sofort in den Live-Agenten (Prompt-Repush) | enforced |
| PRE-07 | Leitfaden-Zeile „Preisauskunft" ist zwei-Wege-synchron mit `price_info_enabled` | enforced |
| PRE-08 | hk_queryKnowledgeBase ist Stub („keine Informationen") — keine Preisquelle | enforced |
| PRE-09 | KVA-Entwürfe übernehmen nur im Gespräch genannte Positionen/Preise — nie erfunden | prompt-only |
| PRE-10 | hk_draftCostEstimate nur bei aktivierter KVA-Automatisierung, sonst Anfrage | enforced |

## Leitfaden ([leitfaden.md](leitfaden.md))

| Rule | German statement (short) | Status |
|------|--------------------------|--------|
| LEIT-01 | Leitfaden wird nur als komplette geordnete Liste gespeichert, EIN Repush pro Speichern | enforced |
| LEIT-02 | Veralteter Leitfaden (ID-Mismatch) wird mit 409 abgelehnt | enforced |
| LEIT-03 | Verknüpfte Angebots-Zeilen spiegeln immer die agent_configs-Einstellung (Zwei-Wege-Sync) | partially-enforced |
| LEIT-04 | Preisauskunft im Leitfaden nicht aktivierbar ohne bepreisten Artikel (422) | enforced |
| LEIT-05 | Gesperrte Felder (is_locked) können nicht gelöscht werden | enforced |
| LEIT-06 | Jede neue Org wird idempotent mit dem Standard-Leitfaden geseedet | enforced |
| LEIT-07 | Leitfaden erreicht den Agenten als geordnete Liste; bekannte Felder nicht erneut erfragen | partially-enforced |
| LEIT-08 | Leerer/inaktiver Leitfaden fällt auf Standard-Set zurück | enforced |
| LEIT-09 | Aktive Angebots-Zeilen rendern Angebots-Anweisung an ihrer Position; inaktive rendern nichts | partially-enforced |
| LEIT-10 | E-Mail nur bei Versandwunsch erfragen — außer sie steht explizit im Leitfaden | prompt-only |
| LEIT-11 | Bestandsbezug ohne System-Treffer: Lücke nie gegenüber dem Anrufer transparent machen | prompt-only |
| LEIT-12 | Proaktive Rückruf-Eröffnung nur bei kundenbezogenen HÄNGENDEN AKTIONEN; nie Termine halluzinieren | prompt-only |

## Autonomie ([autonomie.md](autonomie.md))

| Rule | German statement (short) | Status |
|------|--------------------------|--------|
| AUT-01 | Jede Fähigkeit hat Schalter + Stufe 1/2/3; Fallback Legacy `kiki_level` (Default 2) | enforced |
| AUT-02 | Termine aus / L1 ⇒ nur Anfrage, keine Termin-Zeile | enforced |
| AUT-03 | L2 ⇒ Reservierung 'pending', Team bestätigt | enforced |
| AUT-04 | L3 ⇒ 'pending' im Call, Auto-Confirm erst nach dem Anruf | enforced |
| AUT-05 | KVA aus (oder L1) ⇒ kein Entwurf, nur Anliegen — Anm.: Server-Gate prüft nur enabled, nicht Level 1 | enforced (mit VERIFY-Note) |
| AUT-06 | KVA L2 ⇒ nur ENTWURF, Team versendet; Kiki behauptet nie Versand | enforced |
| AUT-07 | KVA L3 ⇒ Direktversand best-effort; 'sent' nur nach Erfolg | enforced |
| AUT-08 | Reschedule-Timer Stufen-gesteuert: L1/L2 nichts Automatisches, nur L3 löst auf | partially-enforced |
| AUT-09 | Reschedule immer nur VORSCHLAG auf bestehendem Termin bis Admin-Approve | enforced (Testlage VERIFY) |
| AUT-10 | Projekte Stufen-gesteuert (aus/L1 keins, L2 'planning', L3 'active'); nicht im Prompt | partially-enforced |
| AUT-11 | Rechnungen nur als ENTWURF (L2/L3); kein Auto-Versand auf irgendeiner Stufe | partially-enforced |
| AUT-12 | Copilot: schreibende Tools nie direkt, nur Vorschlag + explizite Bestätigung | enforced |

## Gesprächslogik ([gespraechslogik.md](gespraechslogik.md))

| Rule | German statement (short) | Status |
|------|--------------------------|--------|
| GSP-01 | Immer nur eine Frage auf einmal | prompt-only |
| GSP-02 | Keine Gesprächszusammenfassungen, keine Wiederholung gesammelter Daten | prompt-only |
| GSP-03 | Pflichtfelder in konfigurierter Reihenfolge; bekannte Felder nicht erneut erfragen | enforced |
| GSP-04 | is_duty=false ⇒ „(optional)"; Default-Satz ohne Konfiguration | enforced |
| GSP-05 | Gesperrtes Feld problem_description nicht löschbar; Hinweistext rendert an seiner Position | enforced |
| GSP-06 | Wenn/Dann-Logik kompiliert als verbindlicher Block „Schritt 1a" | enforced |
| GSP-07 | Logik-Bäume vor Speichern hart validiert (Max-Limits, „Sonst" nie zuerst) | enforced |
| GSP-08 | Deaktivierte/leere/korrupte Logik erzeugt keinen Block und crasht nie das Rendering | enforced |
| GSP-09 | Nie proaktiv nach E-Mail fragen — außer „E-Mail-Adresse" steht im Leitfaden | prompt-only |
| GSP-10 | Datumsklarheit: nie Wochentage selbst nennen; `wunschDatum` wörtlich übergeben | partially-enforced |
| GSP-11 | Vor end_call Abschluss-Frage stellen und Antwort abwarten | prompt-only |
| GSP-12 | Leitfaden-Punkt „Preisauskunft" nur mit bepreistem Artikel aktivierbar | enforced |

## Outbound ([outbound.md](outbound.md))

| Rule | German statement (short) | Status |
|------|--------------------------|--------|
| OUT-01 | Anrufe nur bei `outbound_enabled` UND aktivem Anlass-Schalter | enforced |
| OUT-02 | Nur im konfigurierten Zeitfenster + Wochentagen (Europe/Berlin) | enforced |
| OUT-03 | Dispatch zyklus-idempotent via Ledger; Cooldown + `max_cycles` | enforced |
| OUT-04 | Zahlungserinnerung ist KEINE Mahnung (freundlich, max. 3 Zyklen, nur überfällig/unbezahlt) | partially-enforced |
| OUT-05 | Arbeits-Anlässe nicht auf geschlossene Vorgänge; Zufriedenheit/Bewertung nur auf abgeschlossene | enforced |
| OUT-06 | Bewertungsanrufe erfordern zusätzlich `google_reviews_enabled` | enforced |
| OUT-07 | Kurzes Auflegen ⇒ Rückwahl-Versuch (Intervall + Max-Versuche) | enforced (Testlage VERIFY) |
| OUT-08 | Serverseitig gerenderte Voicemail; Mailbox nur bei zweifelsfreier Ansage, im Zweifel Mensch | partially-enforced |
| OUT-09 | `OUTBOUND_TEST_SCOPE_ONLY` erzwingt Test-Ziele; seit GO-LIVE auf 0 (echte Kunden) | enforced (Lücke VERIFY) |
| OUT-10 | Termin-Anlässe nur per Menschen-Klick, nie vom Sweep; deren E-Mail sendet immer | enforced |
| OUT-11 | Reschedule-Expiry-Sweep nur bei L3 automatisch; L1/L2 nur Overdue-Markierung | enforced (Testlage VERIFY) |
| OUT-12 | Sweep-Endpunkt secret-geschützt; manueller Einzel-Dispatch org-gebunden, umgeht Gates | enforced |
| OUT-13 | Outbound-Prompt firmen-agnostisch, deutsch, mit Leitplanken (nie „gebucht", erst prüfen+bestätigen) | prompt-only |

## Copilot ([copilot.md](copilot.md))

| Rule | German statement (short) | Status |
|------|--------------------------|--------|
| COP-01 | Jedes Tool strikt org-gescoped | enforced |
| COP-02 | Rollen-Gating: Admin-Tools für Mitarbeiter unsichtbar und nicht ausführbar | enforced |
| COP-03 | Schreibende Aktionen nie im Chat-Turn, nur Vorschlag + /confirm | enforced |
| COP-04 | Navigation nur auf feste Routen-Whitelist | enforced |
| COP-05 | „Act in sight": Navigation zur Zielseite vor/nach bestätigter Aktion | enforced |
| COP-06 | Rechnung/KVA via Live-Formular-Übernahme mit API-Fallback (60 s) | enforced |
| COP-07 | create_employee legt nur Datensatz ohne Login an; Einladung bleibt manuell | enforced |
| COP-08 | Kiki-Zentrale-Settings nur erklären/navigieren; einzig Stammdaten schreibbar | enforced |
| COP-09 | Kundenbezug vor jeder Aktion auflösen: 0 Treffer ⇒ Fehler, mehrere ⇒ Rückfrage | partially-enforced |
| COP-10 | Client-Historie bereinigt (kein system/tool-Fälschen), 20-Turn-Cap | enforced |
| COP-11 | Sitzungen persistent pro Org+Nutzer; alte Aktionskarten nur Anzeige | enforced |
| COP-12 | Strikt CRM-only; Daten-Texte sind Inhalt, nie Befehle; nie falsches Tool | prompt-only |
| COP-13 | Jede bestätigte Schreibaktion auditiert (fail-open) | enforced |
| COP-14 | Keine L1–L3-Gating-Logik im Copilot — Stufen betreffen nur den Voice-Agenten | VERIFY |

## Totals

98 rules — enforced: 64 · prompt-only: 19 · partially-enforced: 14 · mixed: 1 (ND-06)

## VERIFY WITH AMBER — resolutions (2026-06-12)

Amber's standing ruling: **L1 = aus, L2 = halbautomatisch, L3 = vollautomatisch — für JEDE Autonomie-Stufe, serverseitig.**

1. **AUT-05 — RESOLVED/FIXED**: `draft_cost_estimate` blockt jetzt auch bei `kva_level <= 1` serverseitig (Projekte/Rechnungen/Termine taten das bereits).
2. **AUT-09 — RESOLVED**: Reschedule-Vorschlags-Flow seit 2026-06-11 getestet (`test_appointments_actions.py` approve/decline/Status-Gates + `test_reschedule_expiry.py`).
3. **OUT-07 — offen (niedrig)**: Short-Hangup-Retry weiter ohne dedizierten Test; Pre-Dial-Liveness-Guard (2026-06-11) testet den gefährlichsten Teil des Re-Dials mit.
4. **OUT-09 — offen (moot solange LIVE)**: Scope-Guard für Sweep-Calls erst relevant, falls `OUTBOUND_TEST_SCOPE_ONLY` je wieder auf 1 geht.
5. **OUT-11 — RESOLVED**: Expiry-Sweep seit 2026-06-11 getestet (`test_reschedule_expiry.py`: Race/Window/Flag-Pfade).
6. **COP-14 — RESOLVED (by design)**: Copilot übergeht die L1–L3-Stufen bewusst — jede Schreibaktion wird vom Menschen im Panel bestätigt; das Confirm-Gate IST der Autonomie-Mechanismus des Copilots.
