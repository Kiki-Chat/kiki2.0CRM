# German Cleanup — Every Change (before → after)

Branch `feat/de-translation-pass` vs its start point. **583 changed lines across 101 files.**


## `backend/app/api/routes/actions.py`  (4)

- `-` """Draft KVAs older than 24h — assumed to have stalled and need sending."""
  `+` """Draft Angebote older than 24h — assumed to have stalled and need sending."""
- `-` num = r.get("number") or "KVA"
  `+` num = r.get("number") or "Angebot"
- `-` """Sent KVAs from the last 7 days with no accept/reject yet."""
  `+` """Sent Angebote from the last 7 days with no accept/reject yet."""
- `-` num = r.get("number") or "KVA"
  `+` num = r.get("number") or "Angebot"

## `backend/app/api/routes/calls.py`  (3)

- `-` num = kva.get("number") or "KVA"
  `+` num = kva.get("number") or "Angebot"
- `-` KVA and status change tied to this inquiry, plus the raw record lists the thread
  `+` Angebot and status change tied to this inquiry, plus the raw record lists the thread
- `-` # "Offene Punkte" = pending appointments + KVAs awaiting send/answer.
  `+` # "Offene Punkte" = pending appointments + Angebote awaiting send/answer.

## `backend/app/api/routes/cases.py`  (13)

- `-` A Fall is a ticket: customer + the call(s) and the five linked things
  `+` A Vorgang is a ticket: customer + the call(s) and the five linked things
- `-` (Anfragen/Anrufe · Termine · KVA · Rechnungen · Mitarbeiter). Batched (no N+1)."""
  `+` (Anfragen/Anrufe · Termine · Angebot · Rechnungen · Mitarbeiter). Batched (no N+1)."""
- `-` "die automatische Fall-Gruppierung ist bis zum Monatswechsel pausiert.",
  `+` "die automatische Vorgangs-Gruppierung ist bis zum Monatswechsel pausiert.",
- `-` "title": (g.label or "Fall")[:120], "created_by": _uid(user),
  `+` "title": (g.label or "Vorgang")[:120], "created_by": _uid(user),
- `-` raise HTTPException(status_code=422, detail="Fall nicht gefunden.")
  `+` raise HTTPException(status_code=422, detail="Vorgang nicht gefunden.")
- `-` detail="Dieser Fall gehört zu einem anderen Kunden — eine "
  `+` detail="Dieser Vorgang gehört zu einem anderen Kunden — eine "
- `-` "Anfrage kann nur einem Fall desselben Kunden zugeordnet werden.",
  `+` "Anfrage kann nur einem Vorgang desselben Kunden zugeordnet werden.",
- `-` raise HTTPException(status_code=404, detail="Fall not found")
  `+` raise HTTPException(status_code=404, detail="Vorgang nicht gefunden")
- `-` validate_fk_in_org(client, table="cases", fk_id=case_id, org_id=org_id, label="Fall")
  `+` validate_fk_in_org(client, table="cases", fk_id=case_id, org_id=org_id, label="Vorgang")
- `-` "title": (payload.label or "Neuer Fall")[:120], "created_by": _uid(user),
  `+` "title": (payload.label or "Neuer Vorgang")[:120], "created_by": _uid(user),
- `-` raise HTTPException(status_code=404, detail="Fall nicht gefunden.")
  `+` raise HTTPException(status_code=404, detail="Vorgang nicht gefunden.")
- `-` validate_fk_in_org(client, table="cases", fk_id=case_id, org_id=org_id, label="Fall")
  `+` validate_fk_in_org(client, table="cases", fk_id=case_id, org_id=org_id, label="Vorgang")
- `-` validate_fk_in_org(client, table="cases", fk_id=case_id, org_id=org_id, label="Fall")
  `+` validate_fk_in_org(client, table="cases", fk_id=case_id, org_id=org_id, label="Vorgang")

## `backend/app/api/routes/catalog.py`  (1)

- `-` # Legacy alias still used by the KVA quick-select until it is repointed.
  `+` # Legacy alias still used by the Angebot quick-select until it is repointed.

## `backend/app/api/routes/cost_estimates.py`  (7)

- `-` # never fires for that KVA because it gates on a non-NULL sent_at.
  `+` # never fires for that Angebot because it gates on a non-NULL sent_at.
- `-` # Case grouping: a KVA for an inquiry belongs to that inquiry's
  `+` # Case grouping: a Angebot for an inquiry belongs to that inquiry's
- `-` return build_pdf(org, customer, _ce_for_pdf(row), totals), (row.get("number") or "KVA")
  `+` return build_pdf(org, customer, _ce_for_pdf(row), totals), (row.get("number") or "Angebot"…
- `-` """Render subject + HTML body for the KVA / Angebot / AB email.
  `+` """Render subject + HTML body for the Angebot / Angebot / AB email.
- `-` "kva": "Kostenvoranschlag",
  `+` "kva": "Angebot",
- `-` }.get(doc_type, "Kostenvoranschlag")
  `+` }.get(doc_type, "Angebot")
- `-` detail="Der Kostenvoranschlag ist abgelaufen. Bitte zuerst die Gültigkeit verlängern.",
  `+` detail="Der Angebot ist abgelaufen. Bitte zuerst die Gültigkeit verlängern.",

## `backend/app/api/routes/customers.py`  (2)

- `-` # open points (pending appointments + KVAs awaiting send/answer). Computed in
  `+` # open points (pending appointments + Angebote awaiting send/answer). Computed in
- `-` KVAs) — same event shape as the per-call Verlauf, scoped to this customer."""
  `+` Angebote) — same event shape as the per-call Verlauf, scoped to this customer."""

## `backend/app/api/routes/dashboard.py`  (1)

- `-` "title": f"{e.get('number') or 'KVA'} wurde vor {(now - sent).days} Tagen versendet, noch …
  `+` "title": f"{e.get('number') or 'Angebot'} wurde vor {(now - sent).days} Tagen versendet, n…

## `backend/app/api/routes/inquiries.py`  (2)

- `-` call (in/out), appointment, KVA and status change on this case, the raw record
  `+` call (in/out), appointment, Angebot and status change on this case, the raw record
- `-` """Merge this Vorgang INTO another: moves its calls/appointments/KVAs onto the
  `+` """Merge this Vorgang INTO another: moves its calls/appointments/Angebote onto the

## `backend/app/api/routes/invoices.py`  (12)

- `-` # unless we check it. Reject pointers to another org's customer / KVA / case
  `+` # unless we check it. Reject pointers to another org's customer / Angebot / case
- `-` validate_fk_in_org(client, table="cost_estimates", fk_id=payload.kva_id, org_id=org_id, la…
  `+` validate_fk_in_org(client, table="cost_estimates", fk_id=payload.kva_id, org_id=org_id, la…
- `-` # INV-009: a KVA may be converted into a Rechnung exactly once. If the source
  `+` # INV-009: a Angebot may be converted into a Rechnung exactly once. If the source
- `-` detail="Dieser Kostenvoranschlag wurde bereits in eine Rechnung umgewandelt.",
  `+` detail="Dieses Angebot wurde bereits in eine Rechnung umgewandelt.",
- `-` # Case grouping: an invoice built from a KVA belongs to that KVA's
  `+` # Case grouping: an invoice built from a Angebot belongs to that Angebot's
- `-` # Fall (case, directly or via the KVA's inquiry) — inherit when not set.
  `+` # Fall (case, directly or via the Angebot's inquiry) — inherit when not set.
- `-` # (invoices have no inquiry_id; the case is resolved through the KVA.)
  `+` # (invoices have no inquiry_id; the case is resolved through the Angebot.)
- `-` # Converting a KVA: mark the source estimate invoiced and link it both ways.
  `+` # Converting a Angebot: mark the source estimate invoiced and link it both ways.
- `-` # deleting the just-created invoice so we never leave an invoice whose KVA
  `+` # deleting the just-created invoice so we never leave an invoice whose Angebot
- `-` "invoice create: KVA back-link failed AND invoice rollback failed "
  `+` "invoice create: Angebot back-link failed AND invoice rollback failed "
- `-` validate_fk_in_org(client, table="cost_estimates", fk_id=payload.kva_id, org_id=org_id, la…
  `+` validate_fk_in_org(client, table="cost_estimates", fk_id=payload.kva_id, org_id=org_id, la…
- `-` Same precedence as KVA: customer template → request payload → German
  `+` Same precedence as Angebot: customer template → request payload → German

## `backend/app/api/routes/kiki_zentrale.py`  (1)

- `-` # ─── KVA-Automatisierung / Preisauskunft ─────────────────────────────────────
  `+` # ─── Angebot-Automatisierung / Preisauskunft ─────────────────────────────────────

## `backend/app/api/routes/projects.py`  (4)

- `-` # Invoices: case_id ∈ cases OR via the KVA chain (no inquiry_id on invoices).
  `+` # Invoices: case_id ∈ cases OR via the Angebot chain (no inquiry_id on invoices).
- `-` # Invoices: case_id ∈ cases OR via the KVA chain (no project/inquiry on invoices).
  `+` # Invoices: case_id ∈ cases OR via the Angebot chain (no project/inquiry on invoices).
- `-` items.append({"type": "cost_estimate", "date": k.get("created_at"), "amount": k.get("total…
  `+` items.append({"type": "cost_estimate", "date": k.get("created_at"), "amount": k.get("total…
- `-` # KVA chain: invoice → cost_estimate → (case_id ∈ cases OR inquiry_id ∈ members).
  `+` # Angebot chain: invoice → cost_estimate → (case_id ∈ cases OR inquiry_id ∈ members).

## `backend/app/services/agent_config.py`  (15)

- `-` OFF (default) → Kiki gives NO prices and offers a Kostenvoranschlag instead.
  `+` OFF (default) → Kiki gives NO prices and offers a Angebot instead.
- `-` "  nennen kannst, und biete an, dass das Team einen unverbindlichen\n"
  `+` "  nennen kannst, und biete an, dass das Team ein unverbindliches\n"
- `-` "  Kostenvoranschlag erstellt — keine Preise raten."
  `+` "  Angebot erstellt — keine Preise raten."
- `-` "  Team einen unverbindlichen Kostenvoranschlag erstellt:\n"
  `+` "  Team ein unverbindliches Angebot erstellt:\n"
- `-` "  das Team meldet sich mit einem unverbindlichen Kostenvoranschlag.“"
  `+` "  das Team meldet sich mit einem unverbindlichen Angebot.“"
- `-` "- **Kostenvoranschlag anbieten** — biete an dieser Stelle aktiv einen "
  `+` "- **Angebot anbieten** — biete an dieser Stelle aktiv einen "
- `-` "unverbindlichen Kostenvoranschlag an."
  `+` "unverbindlichen Angebot an."
- `-` offer-steps (Termin/KVA/Preisauskunft) at their configured position.
  `+` offer-steps (Termin/Angebot/Preisauskunft) at their configured position.
- `-` "höchste Priorität, zuerst): Felder erfragen bzw. Angebote (Termin/KVA/"
  `+` "höchste Priorität, zuerst): Felder erfragen bzw. Angebote (Termin/Angebot/"
- `-` Emits a Termine sub-block and a KVA sub-block, each gated by its own enable
  `+` Emits a Termine sub-block and a Angebot sub-block, each gated by its own enable
- `-` # ── Kostenvoranschläge (KVA) ──
  `+` # ── Angebote ──
- `-` "  Kostenvoranschläge: Du erstellst KEINE Kostenvoranschläge und schlägst "
  `+` "  Angebote: Du erstellst KEINE Angebote und schlägst "
- `-` "  Kostenvoranschläge: Erstelle aus den besprochenen Positionen einen "
  `+` "  Angebote: Erstelle aus den besprochenen Positionen einen "
- `-` "  Kostenvoranschläge: Erstelle aus den besprochenen Positionen einen "
  `+` "  Angebote: Erstelle aus den besprochenen Positionen einen "
- `-` else "'audio' fehlt in client_events — der Agent bliebe im Anruf stumm.",
  `+` else "'audio' fehlt in client_events — Kiki bliebe im Anruf stumm.",

## `backend/app/services/agent_prompt_template.txt`  (8)

- `-` Projekte und Kostenvoranschläge.
  `+` Projekte und Angebote.
- `-` KVA oder eine Bestätigung per E-Mail (z. B. „schicken Sie mir das
  `+` Angebot oder eine Bestätigung per E-Mail (z. B. „schicken Sie mir das
- `-` **Wann aufrufen:** Wenn Anrufer auf eine frühere Anfrage/Auftrag Bezug nimmt („meine Anfra…
  `+` **Wann aufrufen:** Wenn Anrufer auf eine frühere Anfrage/Auftrag Bezug nimmt („meine Anfra…
- `-` **Wann aufrufen:** Wenn der Anrufer ausdrücklich einen Kostenvoranschlag wünscht oder ihr …
  `+` **Wann aufrufen:** Wenn der Anrufer ausdrücklich ein Angebot wünscht oder ihr im Gespräch …
- `-` **Zweck:** Erstellt aus den besprochenen Positionen einen Kostenvoranschlag-ENTWURF. Bei A…
  `+` **Zweck:** Erstellt aus den besprochenen Positionen einen Angebot-ENTWURF. Bei Autonomie-S…
- `-` - `customerId` (optional): Kunden-ID aus hk_identifyCustomer / hk_bookAppointment, damit d…
  `+` - `customerId` (optional): Kunden-ID aus hk_identifyCustomer / hk_bookAppointment, damit d…
- `-` **Hinweis:** Das Tool erstellt immer einen ENTWURF. Sage dem Anrufer NIE „Ich habe Ihnen d…
  `+` **Hinweis:** Das Tool erstellt immer einen ENTWURF. Sage dem Anrufer NIE „Ich habe Ihnen d…
- `-` **Fehlerbehandlung:** „Ich konnte den Kostenvoranschlag gerade nicht erstellen. Ich notier…
  `+` **Fehlerbehandlung:** „Ich konnte das Angebot gerade nicht erstellen. Ich notiere Ihren Wu…

## `backend/app/services/appointment_emails.py`  (10)

- `-` company = org.get("name") or "Ihr Dienstleister"
  `+` company = org.get("name") or "Dein Dienstleister"
- `-` f"hiermit bestätigen wir Ihren Termin am {datum} um {uhr} Uhr{titel_clause}.\n\n"
  `+` f"hiermit bestätigen wir deinen Termin am {datum} um {uhr} Uhr{titel_clause}.\n\n"
- `-` "Sollten Sie den Termin verschieben oder absagen müssen, melden Sie sich bitte "
  `+` "Solltest du den Termin verschieben oder absagen müssen, melde dich bitte "
- `-` f"leider müssen wir Ihren Termin am {datum} um {uhr} Uhr{titel_clause} absagen. "
  `+` f"leider müssen wir deinen Termin am {datum} um {uhr} Uhr{titel_clause} absagen. "
- `-` "Wir bitten um Ihr Verständnis.\n\n"
  `+` "Wir bitten um dein Verständnis.\n\n"
- `-` "Gerne vereinbaren wir einen neuen Termin – melden Sie sich einfach bei uns.\n\n"
  `+` "Gerne vereinbaren wir einen neuen Termin – melde dich einfach bei uns.\n\n"
- `-` f"wir müssen Ihren Termin am {datum} um {uhr} Uhr{titel_clause} leider verschieben "
  `+` f"wir müssen deinen Termin am {datum} um {uhr} Uhr{titel_clause} leider verschieben "
- `-` f"und schlagen Ihnen einen neuen Termin vor: {neu}.\n\n"
  `+` f"und schlagen dir einen neuen Termin vor: {neu}.\n\n"
- `-` "Bitte geben Sie uns kurz Bescheid, ob Ihnen der neue Termin passt – alternativ "
  `+` "Bitte gib uns kurz Bescheid, ob dir der neue Termin passt – alternativ "
- `-` f"wir müssen Ihren Termin am {datum} um {uhr} Uhr{titel_clause} leider verschieben. "
  `+` f"wir müssen deinen Termin am {datum} um {uhr} Uhr{titel_clause} leider verschieben. "

## `backend/app/services/billing_notifications.py`  (13)

- `-` # HeyKiki→customer, unlike white-labeled org→customer invoice/KVA mails).
  `+` # HeyKiki→customer, unlike white-labeled org→customer invoice/Angebot mails).
- `-` # Same branded shell as the Invoice/KVA emails (green-gradient header +
  `+` # Same branded shell as the Invoice/Angebot emails (green-gradient header +
- `-` body="Ihre kostenlose Testphase endet in Kürze. Bitte hinterlegen Sie eine "
  `+` body="deine kostenlose Testphase endet in Kürze. Bitte hinterlege eine "
- `-` "Zahlungsmethode, damit Ihre KI ohne Unterbrechung weiterläuft.",
  `+` "Zahlungsmethode, damit deine KI ohne Unterbrechung weiterläuft.",
- `-` plan = plan_title or "Ihr Tarif"
  `+` plan = plan_title or "Dein Tarif"
- `-` body=f"Ihr Abonnement „{plan}“ ist aktiv. Vielen Dank! Ihre KI-Sekretärin läuft "
  `+` body=f"Dein Abonnement „{plan}“ ist aktiv. Vielen Dank! deine KI-Sekretärin läuft "
- `-` "ohne Unterbrechung weiter. Rechnungen und Zahlungsbeleg finden Sie in Ihrem "
  `+` "ohne Unterbrechung weiter. Rechnungen und Zahlungsbeleg findest du in deinem "
- `-` body="Ihre letzte Zahlung ist fehlgeschlagen. Bitte aktualisieren Sie Ihre "
  `+` body="deine letzte Zahlung ist fehlgeschlagen. Bitte aktualisiere deine "
- `-` body=f"Sie haben Ihr Kontingent ({quota} Min.) überschritten ({used} Min. genutzt). "
  `+` body=f"Du hast dein Kontingent ({quota} Min.) überschritten ({used} Min. genutzt). "
- `-` body=f"Sie haben {used} von {quota} inkludierten Minuten genutzt. Ab {quota} Min. "
  `+` body=f"Du hast {used} von {quota} inkludierten Minuten genutzt. Ab {quota} Min. "
- `-` "wird jede weitere Minute nach Ihrem Tarif berechnet.",
  `+` "wird jede weitere Minute nach deinem Tarif berechnet.",
- `-` body=f"Sie haben {used} von {quota} inkludierten Minuten genutzt – Ihr Kontingent "
  `+` body=f"Du hast {used} von {quota} inkludierten Minuten genutzt – dein Kontingent "
- `-` "ist fast aufgebraucht. Ab dem Erreichen wird jede weitere Minute nach Ihrem "
  `+` "ist fast aufgebraucht. Ab dem Erreichen wird jede weitere Minute nach deinem "

## `backend/app/services/cases/apply_run.py`  (1)

- `-` "title": (c["label"] or "Fall")[:120],
  `+` "title": (c["label"] or "Vorgang")[:120],

## `backend/app/services/common.py`  (5)

- `-` """Next case (Fall) number: ``FL-{TOKEN}-{NNNN}`` (e.g. FL-KC007-0001). The
  `+` """Next Vorgang (case) number: ``VG-{TOKEN}-{NNNN}`` (e.g. VG-KC007-0001). The
- `-` case is the bundled grouping ticket; numbers run over the ``cases`` table,
  `+` Vorgang is the bundled grouping ticket; numbers run over the ``cases`` table,
- `-` ``services.projects.gen_project_number`` — so the two never collide.)"""
  `+` ``services.projects.gen_project_number`` — so the two never collide.)
- `-` prefix = f"FL-{get_org_token(client, org_id)}-"
  `+` Prefix changed FL-→VG- (migration 0077) to match the 'Vorgang' UI wording."""
- `-` 
  `+` prefix = f"VG-{get_org_token(client, org_id)}-"

## `backend/app/services/copilot/prompt.py`  (4)

- `-` - **Kein passendes Tool? Niemals ein falsches verwenden.** Gibt es für eine Anfrage kein p…
  `+` - **Kein passendes Tool? Niemals ein falsches verwenden.** Gibt es für eine Anfrage kein p…
- `-` - **Sorgfalt vor dem Anlegen/Ändern:** Sammle zuerst die WICHTIGEN Angaben und stelle dafü…
  `+` - **Sorgfalt vor dem Anlegen/Ändern:** Sammle zuerst die WICHTIGEN Angaben und stelle dafü…
- `-` - **Kundenbezug immer zuerst auflösen:** Bevor du eine kundenbezogene Aktion (Kunde ändern…
  `+` - **Kundenbezug immer zuerst auflösen:** Bevor du eine kundenbezogene Aktion (Kunde ändern…
- `-` - **Einstellungen/Systemänderungen:** weise vor der Bestätigung kurz auf die Auswirkung hi…
  `+` - **Einstellungen/Systemänderungen:** weise vor der Bestätigung kurz auf die Auswirkung hi…

## `backend/app/services/copilot/tools.py`  (9)

- `-` "Die Autonomie wird pro Bereich (Termine, KVA, Projekte, Rechnungen) als Stufe 1–3 eingest…
  `+` "Die Autonomie wird pro Bereich (Termine, Angebot, Projekte, Rechnungen) als Stufe 1–3 ein…
- `-` "KI-Vorschläge erinnern dich automatisch (KVA nachfassen, offene Rechnungen, Wartung). Die…
  `+` "KI-Vorschläge erinnern dich automatisch (Angebot nachfassen, offene Rechnungen, Wartung).…
- `-` "Ausgehende Anrufe/E-Mails (Terminerinnerung, KVA-Nachfassen) sendet Kiki automatisch zu b…
  `+` "Ausgehende Anrufe/E-Mails (Terminerinnerung, Angebot nachfassen) sendet Kiki automatisch …
- `-` "Bei aktiver KVA-Automatisierung erstellt Kiki nach passenden Anrufen automatisch einen KV…
  `+` "Bei aktiver Angebot-Automatisierung erstellt Kiki nach passenden Anrufen automatisch eine…
- `-` "Die E-Mail-Konfiguration legt fest, über welches Konto Rechnungen/KVAs versendet werden (…
  `+` "Die E-Mail-Konfiguration legt fest, über welches Konto Rechnungen/Angebote versendet werd…
- `-` "Die Stammdaten (Name, Anschrift, Telefon, Bank, Steuer) erscheinen auf Rechnungen/KVAs un…
  `+` "Die Stammdaten (Name, Anschrift, Telefon, Bank, Steuer) erscheinen auf Rechnungen/Angebot…
- `-` return {"error": f"KVA nicht angelegt: {getattr(exc, 'detail', str(exc))}"}
  `+` return {"error": f"Angebot nicht angelegt: {getattr(exc, 'detail', str(exc))}"}
- `-` description="Finanz-Überblick: Umsatz, bezahlte/offene Rechnungen, ausstehende KVAs.",
  `+` description="Finanz-Überblick: Umsatz, bezahlte/offene Rechnungen, ausstehende Angebote.",
- `-` description="Erstelle einen Kostenvoranschlag (KVA/Angebot) als ENTWURF. Frage vorher Kund…
  `+` description="Erstelle ein Angebot als ENTWURF. Frage vorher Kunde + Positionen (Beschreibu…

## `backend/app/services/cost_estimates.py`  (31)

- `-` """Cost estimate (Kostenvoranschlag) helpers: numbering, totals, PDF."""
  `+` """Cost estimate (Angebot) helpers: numbering, totals, PDF."""
- `-` "kva": "KOSTENVORANSCHLAG",
  `+` "kva": "ANGEBOT",  # KVA→Angebot product-wide (Amber's call); doc_type key stays "kva"
- `-` # INV-002: scope the per-year sequence by doc-type so KVA/ANG/AB/RG numbers
  `+` # INV-002: scope the per-year sequence by doc-type so the numbers
- `-` # are contiguous *per type* (KVA-2026-00001, KVA-2026-00002, …) instead of
  `+` # are contiguous *per type* (AG-2026-00001, AG-2026-00002, …) instead of
- `-` 
  `+` # Angebot→AG: the former "kva" type is now branded "Angebot" → AG- Aktenzeichen.
- `-` prefix = {"kva": "KVA", "offer": "ANG", "order_confirmation": "AB", "invoice": "RE"}.get(
  `+` prefix = {"kva": "AG", "offer": "ANG", "order_confirmation": "AB", "invoice": "RE"}.get(
- `-` doc_type, "KVA"
  `+` doc_type, "AG"
- `-` """Top-left org-logo render for KVA / Invoice / Angebot / AB PDFs (P1.3).
  `+` """Top-left org-logo render for Angebot / Invoice / Angebot / AB PDFs (P1.3).
- `-` title = DOC_TITLES.get(doc_type, "KOSTENVORANSCHLAG")
  `+` title = DOC_TITLES.get(doc_type, "ANGEBOT")
- `-` f"Dieser Kostenvoranschlag ist gemäß § 632 Abs. 3 BGB unverbindlich. "
  `+` f"Dieses Angebot ist gemäß § 632 Abs. 3 BGB unverbindlich. "
- `-` "wir Sie unverzüglich informieren (§ 650c BGB)."
  `+` "wir dich unverzüglich informieren (§ 650c BGB)."
- `-` else "Vielen Dank für Ihr Vertrauen."
  `+` else "Vielen Dank für dein Vertrauen."
- `-` nr_label = {"kva": "KVA-Nr.:", "offer": "Angebot-Nr.:"}.get(doc_type, "KVA-Nr.:")
  `+` nr_label = {"kva": "Angebot-Nr.:", "offer": "Angebot-Nr.:"}.get(doc_type, "Angebot-Nr.:")
- `-` pdf.cell(0, 6, f"Zu Ihrer Anfrage: {subject[:70]}", new_x="LMARGIN", new_y="NEXT")
  `+` pdf.cell(0, 6, f"Zu deiner Anfrage: {subject[:70]}", new_x="LMARGIN", new_y="NEXT")
- `-` default_intro = "Vielen Dank für Ihren Auftrag. Wir berechnen Ihnen wie folgt:"
  `+` default_intro = "Vielen Dank für deinen Auftrag. Wir berechnen dir wie folgt:"
- `-` default_intro = f'Für Ihre Anfrage erstellen wir Ihnen folgenden {title.title()}:'
  `+` default_intro = f'Für deine Anfrage erstellen wir dir folgenden {title.title()}:'
- `-` # and the resulting reduced figure. Guarded so KVA/Angebot/AB and invoices
  `+` # and the resulting reduced figure. Guarded so Angebot/Angebot/AB and invoices
- `-` """Best-effort email send of a freshly-drafted KVA (used by L3). Self-contained
  `+` """Best-effort email send of a freshly-drafted Angebot (used by L3). Self-contained
- `-` subject = f"Kostenvoranschlag {number} von {org_name}"
  `+` subject = f"Angebot {number} von {org_name}"
- `-` f"anbei senden wir Ihnen den Kostenvoranschlag {number}.\n\n"
  `+` f"anbei senden wir dir das Angebot {number}.\n\n"
- `-` f"Bei Rückfragen stehen wir Ihnen gerne zur Verfügung.\n\n"
  `+` f"Bei Rückfragen stehen wir dir gerne zur Verfügung.\n\n"
- `-` filename = f"KVA-{number}.pdf"
  `+` filename = f"{number}.pdf"  # number already carries its type prefix (AG-/ANG-/RE-)
- `-` """hk_draftCostEstimate handler: create a DRAFT Kostenvoranschlag from the
  `+` """hk_draftCostEstimate handler: create a DRAFT Angebot from the
- `-` agent's collected positions/subject, gated on the org's KVA-Automatisierung
  `+` agent's collected positions/subject, gated on the org's Angebot-Automatisierung
- `-` - KVA-Automatisierung off → no-op, returns success=False with a German note.
  `+` - Angebot-Automatisierung off → no-op, returns success=False with a German note.
- `-` it fails, the KVA stays a draft (no raise). At L1/L2 it stays a draft for
  `+` it fails, the Angebot stays a draft (no raise). At L1/L2 it stays a draft for
- `-` return {"success": False, "message": "KVA-Erstellung ist nicht aktiviert."}
  `+` return {"success": False, "message": "Angebot-Erstellung ist nicht aktiviert."}
- `-` # at level 1 — KVA was the only one relying on the prompt alone, so a tool
  `+` # at level 1 — Angebot was the only one relying on the prompt alone, so a tool
- `-` return {"success": False, "message": "KVA-Erstellung ist nicht aktiviert."}
  `+` return {"success": False, "message": "Angebot-Erstellung ist nicht aktiviert."}
- `-` # KVA level 3: try to send immediately; otherwise leave as a draft.
  `+` # Angebot level 3: try to send immediately; otherwise leave as a draft.
- `-` message = "Kostenvoranschlag wurde erstellt."
  `+` message = "Angebot wurde erstellt."

## `backend/app/services/email_send.py`  (3)

- `-` because the dominant use case here is KVA / Rechnung PDF attachments).
  `+` because the dominant use case here is Angebot / Rechnung PDF attachments).
- `-` # already guard (KVA/invoice → 400), but this protects every current + future
  `+` # already guard (Angebot/invoice → 400), but this protects every current + future
- `-` # calls/emails, KVA, invoice, employee invite, test mail). Falls back to the
  `+` # calls/emails, Angebot, invoice, employee invite, test mail). Falls back to the

## `backend/app/services/email_templates.py`  (4)

- `-` """Shared branded email shell for all CRM-sent emails (Invoice, KVA, Test, …).
  `+` """Shared branded email shell for all CRM-sent emails (Invoice, Angebot, Test, …).
- `-` parts.append(f'<p class="footer-disclaimer" style="margin: 12px 0 0 0; color: #555555; fon…
  `+` parts.append(f'<p class="footer-disclaimer" style="margin: 12px 0 0 0; color: #555555; fon…
- `-` company = _html.escape(company_name) if company_name and str(company_name).strip() else "I…
  `+` company = _html.escape(company_name) if company_name and str(company_name).strip() else "D…
- `-` """Shell + a client-authored plain-text message (Invoice / KVA / Test)."""
  `+` """Shell + a client-authored plain-text message (Invoice / Angebot / Test)."""

## `backend/app/services/inquiries.py`  (2)

- `-` Termin→appointment.inquiry_id, KVA→cost_estimate.inquiry_id, Vorgang→the inquiry
  `+` Termin→appointment.inquiry_id, Angebot→cost_estimate.inquiry_id, Vorgang→the inquiry
- `-` itself, Rechnung→the invoice's KVA. Wartung/Rückruf have no case → None."""
  `+` itself, Rechnung→the invoice's Angebot. Wartung/Rückruf have no case → None."""

## `backend/app/services/invoices.py`  (5)

- `-` 'completed', auto-draft an invoice from the case's ACCEPTED KVA, gated by
  `+` 'completed', auto-draft an invoice from the case's ACCEPTED Angebot, gated by
- `-` Case↔Project split (migration 0073): KVAs and invoices anchor on
  `+` Case↔Project split (migration 0073): Angebote and invoices anchor on
- `-` # Source = the case's ACCEPTED KVA (only invoice an agreed quote).
  `+` # Source = the case's ACCEPTED Angebot (only invoice an agreed quote).
- `-` "subject": f"Rechnung zu Fall {case.get('number') or ''}".strip(),
  `+` "subject": f"Rechnung zu Vorgang {case.get('number') or ''}".strip(),
- `-` # Mirror the manual KVA→invoice link.
  `+` # Mirror the manual Angebot→invoice link.

## `backend/app/services/occasion_emails.py`  (23)

- `-` company = org.get("name") or "Ihr Dienstleister"
  `+` company = org.get("name") or "Dein Dienstleister"
- `-` company = org.get("name") or "Ihr Dienstleister"
  `+` company = org.get("name") or "Dein Dienstleister"
- `-` f"{greet}\n\nwir möchten Sie an Ihren Termin am {datum} um {uhr} Uhr{tc} erinnern.\n\n"
  `+` f"{greet}\n\nwir möchten dich an deinen Termin am {datum} um {uhr} Uhr{tc} erinnern.\n\n"
- `-` "Falls Sie den Termin verschieben oder absagen möchten, melden Sie sich bitte kurz "
  `+` "Falls du den Termin verschieben oder absagen möchtest, melde dich bitte kurz "
- `-` ref = f"Kostenvoranschlag {nr}" if nr else "Kostenvoranschlag"
  `+` ref = f"Angebot {nr}" if nr else "Angebot"
- `-` subject = f"Nachfrage zu Ihrem {ref}"
  `+` subject = f"Nachfrage zu deinem {ref}"
- `-` f"{greet}\n\nwir möchten kurz zu Ihrem {ref}{bc}{summe} nachfragen, ob dazu noch "
  `+` f"{greet}\n\nwir möchten kurz zu deinem {ref}{bc}{summe} nachfragen, ob dazu noch "
- `-` "Fragen offen sind oder wie Sie verfahren möchten.\n\nFür Rückfragen stehen wir "
  `+` "Fragen offen sind oder wie du verfahren möchtest.\n\nFür Rückfragen stehen wir "
- `-` f"Ihnen gerne zur Verfügung.\n\n{sign}"
  `+` f"dir gerne zur Verfügung.\n\n{sign}"
- `-` f"{greet}\n\ndürfen wir Sie freundlich an unsere offene {ref}{summe}{faellig} "
  `+` f"{greet}\n\ndürfen wir dich freundlich an unsere offene {ref}{summe}{faellig} "
- `-` "erinnern? Falls Ihre Zahlung bereits unterwegs ist, betrachten Sie diese "
  `+` "erinnern? Falls deine Zahlung bereits unterwegs ist, betrachte diese "
- `-` subject = "War alles zu Ihrer Zufriedenheit?"
  `+` subject = "War alles zu deiner Zufriedenheit?"
- `-` f"{greet}\n\nwir haben kürzlich Ihren Auftrag{bc} abgeschlossen und möchten gerne "
  `+` f"{greet}\n\nwir haben kürzlich deinen Auftrag{bc} abgeschlossen und möchten gerne "
- `-` "wissen: War alles zu Ihrer Zufriedenheit? Über eine kurze Rückmeldung freuen wir "
  `+` "wissen: War alles zu deiner Zufriedenheit? Über eine kurze Rückmeldung freuen wir "
- `-` subject = "Ihre Bewertung würde uns sehr freuen"
  `+` subject = "deine Bewertung würde uns sehr freuen"
- `-` f"{greet}\n\nvielen Dank, dass wir Ihren Auftrag{bc} für Sie erledigen durften. "
  `+` f"{greet}\n\nvielen Dank, dass wir deinen Auftrag{bc} für dich erledigen durften. "
- `-` "Wenn Sie zufrieden waren, würden wir uns sehr über eine kurze Online-Bewertung "
  `+` "Wenn du zufrieden warst, würden wir uns sehr über eine kurze Online-Bewertung "
- `-` subject = "Ihre nächste Wartung steht an"
  `+` subject = "deine nächste Wartung steht an"
- `-` f"{greet}\n\nbei Ihnen steht die nächste regelmäßige Wartung an. Gerne vereinbaren "
  `+` f"{greet}\n\nbei dir steht die nächste regelmäßige Wartung an. Gerne vereinbaren "
- `-` f"wir dafür einen Termin – melden Sie sich einfach bei uns.\n\n{sign}"
  `+` f"wir dafür einen Termin – melde dich einfach bei uns.\n\n{sign}"
- `-` subject = "Wir haben Ihren Anruf verpasst"
  `+` subject = "Wir haben deinen Anruf verpasst"
- `-` f"{greet}\n\nwir haben Ihren Anruf leider verpasst und möchten uns gerne bei Ihnen "
  `+` f"{greet}\n\nwir haben deinen Anruf leider verpasst und möchten uns gerne bei dir "
- `-` "zurückmelden. Rufen Sie uns gerne wieder an oder antworten Sie kurz auf diese "
  `+` "zurückmelden. Ruf uns gerne wieder an oder antworte kurz auf diese "

## `backend/app/services/outbound_occasions.py`  (9)

- `-` # Follow up KVAs that were SENT (awaiting response) at least N days ago.
  `+` # Follow up Angebote that were SENT (awaiting response) at least N days ago.
- `-` kva_ref = f"Kostenvoranschlag {nr}" if nr else "Kostenvoranschlag"
  `+` kva_ref = f"Angebot {nr}" if nr else "Angebot"
- `-` f"Ihren {kva_ref}{betreff_clause}{summe_clause}{datum_clause}. Ich wollte "
  `+` f"Ihr {kva_ref}{betreff_clause}{summe_clause}{datum_clause}. Ich wollte "
- `-` "## PRIMÄRE AUFGABE – KVA-Nachfassen\n"
  `+` "## PRIMÄRE AUFGABE – Angebot nachfassen\n"
- `-` "„KVA angenommen – Auftrag gewünscht“).\n"
  `+` "„Angebot angenommen – Auftrag gewünscht“).\n"
- `-` "- Möchte der Kunde den Kostenvoranschlag erneut zugeschickt bekommen: "
  `+` "- Möchte der Kunde das Angebot erneut zugeschickt bekommen: "
- `-` """Default: the record carries inquiry_id directly (appointments, KVAs)."""
  `+` """Default: the record carries inquiry_id directly (appointments, Angebote)."""
- `-` """Invoices have no inquiry_id — derive it via the linked KVA (cost_estimate)."""
  `+` """Invoices have no inquiry_id — derive it via the linked Angebot (cost_estimate)."""
- `-` referenz_typ="KVA",
  `+` referenz_typ="KVA",  # internal ledger discriminator (NOT display) — stays KVA

## `backend/app/services/price_knowledge.py`  (1)

- `-` the toggle — the prompt instructs the agent to fall back to the KVA offer when
  `+` the toggle — the prompt instructs the agent to fall back to the Angebot offer when

## `backend/app/services/projects_auto.py`  (1)

- `-` "case_reason": "automatisch: neuer Fall",
  `+` "case_reason": "automatisch: neuer Vorgang",

## `backend/app/services/provisioning.py`  (2)

- `-` ("email", "E-Mail-Adresse", "E-Mail des Kunden (für Bestätigungen und Kostenvoranschläge)"…
  `+` ("email", "E-Mail-Adresse", "E-Mail des Kunden (für Bestätigungen und Angebote)", False, F…
- `-` ("offer_kva", "Kostenvoranschlag anbieten", "Kiki bietet an dieser Stelle aktiv einen unve…
  `+` ("offer_kva", "Angebot anbieten", "Kiki bietet an dieser Stelle aktiv ein unverbindliches …

## `backend/tests/test_batch6_billing.py`  (1)

- `-` for doc_type, prefix in [("kva", "KVA"), ("offer", "ANG"),
  `+` for doc_type, prefix in [("kva", "AG"), ("offer", "ANG"),

## `backend/tests/test_batch_cd_fixes.py`  (5)

- `-` # Cases are numbered FL-{token}-NNNN over the cases table. 5 existed, #3
  `+` # Cases (Vorgänge) are numbered VG-{token}-NNNN over the cases table. 5 existed,
- `-` # deleted → 4 rows remain, highest suffix 0005.
  `+` # #3 deleted → 4 rows remain, highest suffix 0005.
- `-` "cases": [[{"number": "FL-KC007-0005"}, {"number": "FL-KC007-0004"}]],
  `+` "cases": [[{"number": "VG-KC007-0005"}, {"number": "VG-KC007-0004"}]],
- `-` assert common.gen_case_number(db, "o1") == "FL-KC007-0006"  # COUNT+1 would re-issue 0005
  `+` assert common.gen_case_number(db, "o1") == "VG-KC007-0006"  # COUNT+1 would re-issue 0005
- `-` assert common.gen_case_number(db, "o1") == "FL-KC007-0001"
  `+` assert common.gen_case_number(db, "o1") == "VG-KC007-0001"

## `backend/tests/test_email_templates.py`  (1)

- `-` assert "Ihr Dienstleister" in out
  `+` assert "Dein Dienstleister" in out  # du-form product-wide

## `backend/tests/test_outbound_reminders.py`  (1)

- `-` assert "Kostenvoranschlag" in fmk
  `+` assert "Angebot" in fmk  # KVA→Angebot product-wide

## `frontend/src/App.tsx`  (2)

- `-` <Suspense fallback={<div className="flex h-screen items-center justify-center text-muted">…
  `+` <Suspense fallback={<div className="flex h-screen items-center justify-center text-muted">…
- `-` {/* Cases are now the split view at /cases; deep-links to a single Fall
  `+` {/* Cases are now the split view at /cases; deep-links to a single Vorgang

## `frontend/src/admin/AdminBillingPage.tsx`  (6)

- `-` <Stat label="Säumig" value={ov.delinquent_count} tone={ov.delinquent_count ? 'warn' : unde…
  `+` <Stat label="Im Verzug" value={ov.delinquent_count} tone={ov.delinquent_count ? 'warn' : u…
- `-` <Stat label="MRR (geschätzt)" value={fmtCents(ov.mrr_estimate_cents, cur)} />
  `+` <Stat label="Wiederkehrender Umsatz (geschätzt)" value={fmtCents(ov.mrr_estimate_cents, cu…
- `-` <Stat label="Umsatz YTD" value={fmtCents(ov.revenue_ytd_cents, cur)} />
  `+` <Stat label="Umsatz lfd. Jahr" value={fmtCents(ov.revenue_ytd_cents, cur)} />
- `-` <th className="px-4 py-2 text-right">Aktion</th>
  `+` <th className="px-4 py-2 text-right">Aufgabe</th>
- `-` <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-500">Keine Vorschläge — „M…
  `+` <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-500">Keine Vorschläge — „P…
- `-` {o.is_legacy && <span className="rounded-full bg-amber-500/15 px-1.5 py-0.5 text-[10px] fo…
  `+` {o.is_legacy && <span className="rounded-full bg-amber-500/15 px-1.5 py-0.5 text-[10px] fo…

## `frontend/src/admin/AdminLoginPage.tsx`  (1)

- `-` 'Dieser Login hat keinen Super-Admin-Zugang. Bitte verwenden Sie das Kunden-Portal.',
  `+` 'Diese Anmeldung hat keinen Super-Admin-Zugang. Bitte verwende das Kunden-Portal.',

## `frontend/src/admin/AdminOrgFormPage.tsx`  (4)

- `-` label="ElevenLabs Agent ID *"
  `+` label="Sprach-ID (technisch)"
- `-` <Field label="Admin Login-E-Mail *" value={loginEmail} onChange={setLoginEmail} required t…
  `+` <Field label="Admin-Anmelde-E-Mail *" value={loginEmail} onChange={setLoginEmail} required…
- `-` <Field label="Admin Login-Passwort *" value={loginPassword} onChange={setLoginPassword} re…
  `+` <Field label="Admin-Anmelde-Passwort *" value={loginPassword} onChange={setLoginPassword} …
- `-` <Field label="ElevenLabs Agent ID *" value={editAgentId} onChange={setEditAgentId} require…
  `+` <Field label="Sprach-ID (technisch)" value={editAgentId} onChange={setEditAgentId} require…

## `frontend/src/admin/AdminOrgsPage.tsx`  (2)

- `-` <div><span className="text-slate-500">KVAs:</span> <span className="font-mono">{s.kvas_sen…
  `+` <div><span className="text-slate-500">Angebote:</span> <span className="font-mono">{s.kvas…
- `-` Alle Kunden, Anrufe, Anfragen, Termine, KVAs, Rechnungen und Benutzer dieser
  `+` Alle Kunden, Anrufe, Anfragen, Termine, Angebote, Rechnungen und Benutzer dieser

## `frontend/src/admin/AdminProtectedRoute.tsx`  (2)

- `-` return <div className="flex h-screen items-center justify-center bg-slate-950 text-slate-4…
  `+` return <div className="flex h-screen items-center justify-center bg-slate-950 text-slate-4…
- `-` return <div className="flex h-screen items-center justify-center bg-slate-950 text-slate-4…
  `+` return <div className="flex h-screen items-center justify-center bg-slate-950 text-slate-4…

## `frontend/src/admin/AgentHealthModal.tsx`  (1)

- `-` <div className="py-8 text-center text-sm text-slate-400">Lädt…</div>
  `+` <div className="py-8 text-center text-sm text-slate-400">Wird geladen…</div>

## `frontend/src/auth/ProtectedRoute.tsx`  (1)

- `-` <div className="flex h-full items-center justify-center text-muted">Loading…</div>
  `+` <div className="flex h-full items-center justify-center text-muted">Wird geladen…</div>

## `frontend/src/components/CsvImportModal.tsx`  (1)

- `-` phone_salvaged_from_email: 'Telefonnummer aus E-Mail-Feld gerettet',
  `+` phone_salvaged_from_email: 'Telefonnummer aus E-Mail-Feld übernommen',

## `frontend/src/components/PersonalSettingsModal.tsx`  (1)

- `-` <button onClick={submitPw} disabled={changePw.isPending} className="rounded-md bg-green-pr…
  `+` <button onClick={submitPw} disabled={changePw.isPending} className="rounded-md bg-green-pr…

## `frontend/src/components/cases/grouping.tsx`  (10)

- `-` title="In anderen Fall verschieben"
  `+` title="In anderen Vorgang verschieben"
- `-` Aus Fall lösen
  `+` Aus Vorgang lösen
- `-` <div className="px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-faint">In F…
  `+` <div className="px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-faint">In V…
- `-` → {c.label || 'Fall'}
  `+` → {c.label || 'Vorgang'}
- `-` <div className="px-2.5 py-1.5 text-xs text-muted">Keine weiteren Fälle dieses Kunden.</div…
  `+` <div className="px-2.5 py-1.5 text-xs text-muted">Keine weiteren Vorgänge dieses Kunden.</…
- `-` const l = window.prompt('Neuer Fall — Thema:')
  `+` const l = window.prompt('Neuer Vorgang — Thema:')
- `-` ＋ Neuer Fall…
  `+` ＋ Neuer Vorgang…
- `-` t === 'auto' ? <Tag variant="success">sicher</Tag> : t === 'review' ? <Tag variant="warnin…
  `+` t === 'auto' ? <Tag variant="success">sicher</Tag> : t === 'review' ? <Tag variant="warnin…
- `-` {picked.size} Fälle übernehmen
  `+` {picked.size} Vorgänge übernehmen
- `-` {proposal.n_inquiries} Anfragen analysiert ({proposal.model}). Haken = als einen Fall bünd…
  `+` {proposal.n_inquiries} Anfragen analysiert ({proposal.model}). Haken = als einen Vorgang b…

## `frontend/src/components/copilot/CopilotPanel.tsx`  (3)

- `-` *    (new invoice/KVA/customer/appointment) so the user watches it appear,
  `+` *    (new invoice/Angebot/customer/appointment) so the user watches it appear,
- `-` return `Kostenvoranschlag erstellen${a.args.subject ? ': ' + s('subject') : ''}`
  `+` return `Angebot erstellen${a.args.subject ? ': ' + s('subject') : ''}`
- `-` if (tool === 'create_cost_estimate' && ce?.id) return { route: `/cost-estimates/${ce.id}`,…
  `+` if (tool === 'create_cost_estimate' && ce?.id) return { route: `/cost-estimates/${ce.id}`,…

## `frontend/src/components/dashboard/FinanzenTab.tsx`  (1)

- `-` <DashKpi label="KVAs ausstehend" value={k.kvas_pending_count} sub={fmtEur(k.kvas_pending_s…
  `+` <DashKpi label="Ausstehende Angebote" value={k.kvas_pending_count} sub={fmtEur(k.kvas_pend…

## `frontend/src/components/dashboard/KiInsightsTab.tsx`  (4)

- `-` <DashKpi label="KVAs zum Nachfassen" value={k.kva_followup_count} icon={FileText} />
  `+` <DashKpi label="Angebote zum Nachfassen" value={k.kva_followup_count} icon={FileText} />
- `-` <p className="text-base font-semibold text-text">Sie sind auf dem Laufenden!</p>
  `+` <p className="text-base font-semibold text-text">Du bist auf dem Laufenden!</p>
- `-` Keine offenen Vorschläge. Kiki prüft regelmäßig auf KVAs, die ein Nachfassen brauchen, übe…
  `+` Keine offenen Vorschläge. Kiki prüft regelmäßig auf Angebote, die ein Nachfassen brauchen,…
- `-` <button onClick={() => act.mutate({ suggestion_key: s.id, action: 'snooze', snooze_days: 3…
  `+` <button onClick={() => act.mutate({ suggestion_key: s.id, action: 'snooze', snooze_days: 3…

## `frontend/src/components/dashboard/KiNutzungTab.tsx`  (2)

- `-` <Panel title={`Top Anrufer (${pl})`} className="lg:col-span-4">
  `+` <Panel title={`Häufigste Anrufer (${pl})`} className="lg:col-span-4">
- `-` <span>Für Änderungen am Kontingent oder Tarif wenden Sie sich bitte an <a href="mailto:sup…
  `+` <span>Für Änderungen am Kontingent oder Tarif wende dich bitte an <a href="mailto:support@…

## `frontend/src/components/dashboard/shared.tsx`  (1)

- `-` return <div className="rounded-xl border border-border bg-surface p-12 text-center text-sm…
  `+` return <div className="rounded-xl border border-border bg-surface p-12 text-center text-sm…

## `frontend/src/components/kiki/AgentSyncBanner.tsx`  (1)

- `-` message="Die manuelle Bearbeitung des Prompts wird verworfen und durch den aus Ihren Einst…
  `+` message="Die manuelle Bearbeitung des Prompts wird verworfen und durch den aus deinen Eins…

## `frontend/src/components/kiki/AutonomieSection.tsx`  (12)

- `-` // Per-capability autonomy (topics 19/21/22). Termine + KVA act in the call;
  `+` // Per-capability autonomy (topics 19/21/22). Termine + Angebot act in the call;
- `-` { key: 'kva', label: 'Kostenvoranschläge (KVA)', hint: 'Die Telefon-KI erstellt Kostenvora…
  `+` { key: 'kva', label: 'Angebote', hint: 'Die Telefon-KI erstellt Angebote.',
- `-` levels: ['Nur Anfrage aufnehmen — kein KVA', 'Entwurf erstellen — das Team versendet', 'En…
  `+` levels: ['Nur Anfrage aufnehmen — kein Angebot', 'Entwurf erstellen — das Team versendet',…
- `-` { key: 'projects', label: 'Fälle & Plantafel', hint: 'Im Hintergrund bei Terminbestätigung…
  `+` { key: 'projects', label: 'Vorgänge & Plantafel', hint: 'Im Hintergrund bei Terminbestätig…
- `-` levels: ['Keinen Fall anlegen', 'Fall als Entwurf bei Terminbestätigung', 'Fall automatisc…
  `+` levels: ['Keinen Vorgang anlegen', 'Vorgang als Entwurf bei Terminbestätigung', 'Vorgang a…
- `-` { key: 'invoices', label: 'Rechnungen', hint: 'Im Hintergrund bei Fallabschluss.', backOff…
  `+` { key: 'invoices', label: 'Rechnungen', hint: 'Im Hintergrund bei Vorgangsabschluss.', bac…
- `-` levels: ['Keine Rechnung anlegen', 'Rechnungsentwurf bei Fallabschluss', 'Rechnung automat…
  `+` levels: ['Keine Rechnung anlegen', 'Rechnungsentwurf bei Vorgangsabschluss', 'Rechnung aut…
- `-` Schalter aus, nimmt Kiki die Anfrage nur auf. Termine &amp; KVA wirken im Telefongespräch;…
  `+` Schalter aus, nimmt Kiki die Anfrage nur auf. Termine & Angebot wirken im Telefongespräch;…
- `-` &amp; Rechnungen laufen im Hintergrund.
  `+` & Rechnungen laufen im Hintergrund.
- `-` <td className="px-3 py-2.5 text-body">Der Schalter ist aus — Kiki nimmt die Anfrage nur au…
  `+` <td className="px-3 py-2.5 text-body">Der Schalter ist aus — Kiki nimmt die Anfrage nur au…
- `-` <td className="px-3 py-2.5 text-body">Kiki erledigt die Aufgabe (z. B. Entwurf oder Vorsch…
  `+` <td className="px-3 py-2.5 text-body">Kiki erledigt die Aufgabe (z. B. Entwurf oder Vorsch…
- `-` <td className="px-3 py-2.5 text-body">Kiki übernimmt alles automatisch — ohne weitere Best…
  `+` <td className="px-3 py-2.5 text-body">Kiki übernimmt alles automatisch — ohne weitere Best…

## `frontend/src/components/kiki/ConfigSections.tsx`  (16)

- `-` ['kva_followup', 'KVA-Nachfassen'], ['appointment_reminder', 'Terminerinnerung'],
  `+` ['kva_followup', 'Angebot nachfassen'], ['appointment_reminder', 'Terminerinnerung'],
- `-` placeholder="Beschreibung für den KI-Agenten (optional)"
  `+` placeholder="Beschreibung für Kiki (optional)"
- `-` // Speichern (one agent push — no more push-per-drag). Linked rows (Termin/KVA/
  `+` // Speichern (one agent push — no more push-per-drag). Linked rows (Termin/Angebot/
- `-` kva_enabled: 'Autonomie (Bereich „Kostenvoranschläge“)',
  `+` kva_enabled: 'Autonomie (Bereich „Angebote“)',
- `-` Angebots-Punkte (Termin, KVA, Preisauskunft) an ihrer Position aktiv angeboten. Der Schalt…
  `+` Angebots-Punkte (Termin, Angebot, Preisauskunft) an ihrer Position aktiv angeboten. Der Sc…
- `-` <Field label="Beschreibung (optional)"><input value={newDesc} onChange={(e) => setNewDesc(…
  `+` <Field label="Beschreibung (optional)"><input value={newDesc} onChange={(e) => setNewDesc(…
- `-` <p className="mb-2 text-sm text-muted">Kurze Anweisungen, die dem System-Prompt zur Laufze…
  `+` <p className="mb-2 text-sm text-muted">Kurze Anweisungen, die Kiki zu Beginn jedes Gespräc…
- `-` <GroupLabel>Wissens-Quellen (ElevenLabs Wissensdatenbank)</GroupLabel>
  `+` <GroupLabel>Wissens-Quellen</GroupLabel>
- `-` <button onClick={() => reindex.mutate(r.id)} title="Neu indizieren" className="text-muted …
  `+` <button onClick={() => reindex.mutate(r.id)} title="Neu einlesen" className="text-muted ho…
- `-` <span>Geschäftszeiten werden in der Kiki-Zentrale unter <a href="/kiki-zentrale/geschaefts…
  `+` <span>Geschäftszeiten legst du in der Kiki-Zentrale fest unter <a href="/kiki-zentrale/ges…
- `-` <p className="mt-2 text-sm text-muted">Noch keine Kategorien. Lege Termintypen wie „Beratu…
  `+` <p className="mt-2 text-sm text-muted">Noch keine Kategorien. Leg Termintypen wie „Beratun…
- `-` {edit?.id && <button disabled={delCat.isPending || saveCat.isPending} onClick={() => kc.co…
  `+` {edit?.id && <button disabled={delCat.isPending || saveCat.isPending} onClick={() => kc.co…
- `-` : 'Kiki gibt keine Preise heraus und verweist auf einen Kostenvoranschlag.'}
  `+` : 'Kiki gibt keine Preise heraus und verweist auf ein Angebot.'}
- `-` <p className="mb-4 text-sm text-muted">Klicke einen bestehenden Eintrag an, um ihn zwische…
  `+` <p className="mb-4 text-sm text-muted">Klick einen bestehenden Eintrag an, um ihn zwischen…
- `-` <Field label="Schwelle „früh aufgelegt&quot; (Sek.)"><input type="number" min={5} max={120…
  `+` <Field label="Schwelle „früh aufgelegt“ (Sek.)"><input type="number" min={5} max={120} val…
- `-` <p className="mt-2 text-[11px] text-muted">Hinweis: Wiederholungen werden vom geplanten Au…
  `+` <p className="mt-2 text-[11px] text-muted">Hinweis: Wiederholungen werden vom geplanten Au…

## `frontend/src/components/kiki/GespraechslogikSection.tsx`  (11)

- `-` subrule: 'Verschachtelter Fall (Wenn/Sonst)',
  `+` subrule: 'Verschachtelte Regel (Wenn/Sonst)',
- `-` help: 'Der Fall, den Kiki zuerst prüft.',
  `+` help: 'Die Regel, die Kiki zuerst prüft.',
- `-` help: 'Wird nur geprüft, wenn der Fall darüber NICHT zutrifft.',
  `+` help: 'Wird nur geprüft, wenn die Regel darüber NICHT zutrifft.',
- `-` help: 'Greift, wenn keiner der Fälle darüber zutrifft.',
  `+` help: 'Greift, wenn keine der Regeln darüber zutrifft.',
- `-` // Offer-point rows (Termin/KVA/Preisauskunft) ARE selectable in rules — they
  `+` // Offer-point rows (Termin/Angebot/Preisauskunft) ARE selectable in rules — they
- `-` // were filtered out before, which is why "Termine" and "KVA" were missing from
  `+` // were filtered out before, which is why "Termine" and "Angebot" were missing from
- `-` // offer points (Termine/KVA/Preisauskunft) and also INACTIVE fields — a field
  `+` // offer points (Termine/Angebot/Preisauskunft) and also INACTIVE fields — a field
- `-` <p className="text-sm text-faint">Die Vorschau lädt…</p>
  `+` <p className="text-sm text-faint">Vorschau wird geladen…</p>
- `-` + Weiterer Fall (andernfalls, wenn …)
  `+` + Weitere Regel (andernfalls, wenn …)
- `-` + Auffang-Fall (alle anderen)
  `+` + Auffang-Regel (alle anderen)
- `-` <button onClick={onRemove} title="Fall löschen" className="ml-auto text-muted hover:text-e…
  `+` <button onClick={onRemove} title="Regel löschen" className="ml-auto text-muted hover:text-…

## `frontend/src/components/kiki/PromptEditorSection.tsx`  (2)

- `-` <div className="p-12 text-center text-muted">Lädt…</div>
  `+` <div className="p-12 text-center text-muted">Wird geladen…</div>
- `-` <div className="p-8 text-center text-muted">Diff wird berechnet…</div>
  `+` <div className="p-8 text-center text-muted">Änderungen werden berechnet…</div>

## `frontend/src/components/kiki/VerhaltenSection.tsx`  (6)

- `-` <GroupLabel>Persona & Stimme</GroupLabel>
  `+` <GroupLabel>Stimme & Auftreten</GroupLabel>
- `-` <Field label="Persona-Name">
  `+` <Field label="Name der Stimme">
- `-` <Field label="Begrüßungs-Nachricht" hint={`${firstMessage.length}/500 Zeichen`}>
  `+` <Field label="Begrüßung" hint={`${firstMessage.length}/500 Zeichen`}>
- `-` <GroupLabel>Begrüßungstext (HeyKiki-seitig)</GroupLabel>
  `+` <GroupLabel>Begrüßungstext (von HeyKiki vorgegeben)</GroupLabel>
- `-` Dieser Text wird zusätzlich zur Agenten-Begrüßung verwendet, um die Kontext-Initialisierun…
  `+` Dieser Text wird zusätzlich zu Kikis Begrüßung verwendet, um den Gesprächseinstieg zu steu…
- `-` Variante (sonst gilt die Standard-Begrüßung des Agenten oben).
  `+` Variante (sonst gilt die Standard-Begrüßung von Kiki oben).

## `frontend/src/components/kiki/VerlaufSection.tsx`  (5)

- `-` <th className="px-3 py-2 font-semibold">Aktion</th>
  `+` <th className="px-3 py-2 font-semibold">Aufgabe</th>
- `-` <td className="px-3 py-2">{e.rolled_back ? <Tag variant="warning">Rückgängig</Tag> : ok ? …
  `+` <td className="px-3 py-2">{e.rolled_back ? <Tag variant="warning">Rückgängig</Tag> : ok ? …
- `-` <button onClick={() => setDetail(e)} className="text-xs font-medium text-green-deep hover:…
  `+` <button onClick={() => setDetail(e)} className="text-xs font-medium text-green-deep hover:…
- `-` <th className="px-3 py-2 font-semibold">Aktion</th>
  `+` <th className="px-3 py-2 font-semibold">Aufgabe</th>
- `-` {isLoading && <tr><td colSpan={5} className="px-3 py-8 text-center text-muted">Lädt…</td><…
  `+` {isLoading && <tr><td colSpan={5} className="px-3 py-8 text-center text-muted">Wird gelade…

## `frontend/src/components/layout/Sidebar.tsx`  (1)

- `-` const email = session?.user.email ?? 'Setup pending'
  `+` const email = session?.user.email ?? 'Einrichtung offen'

## `frontend/src/components/layout/Topbar.tsx`  (3)

- `-` aria-label="Seitenleiste umschalten"
  `+` aria-label="Seitenleiste ein/aus"
- `-` aria-label="Hey Kiki Assistent umschalten"
  `+` aria-label="Kiki-Assistent ein/aus"
- `-` aria-label="Design umschalten"
  `+` aria-label="Darstellung wechseln"

## `frontend/src/components/layout/nav.ts`  (3)

- `-` { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  `+` { to: '/', icon: LayoutDashboard, label: 'Übersicht' },
- `-` { to: '/cases', icon: Layers, label: 'Fälle' },
  `+` { to: '/cases', icon: Layers, label: 'Vorgänge' },
- `-` { to: '/cost-estimates', label: 'Kostenvoranschläge' },
  `+` { to: '/cost-estimates', label: 'Angebote' },

## `frontend/src/lib/kikiApi.ts`  (1)

- `-` /** Set on the three offer-step rows (Termin/KVA/Preisauskunft). */
  `+` /** Set on the three offer-step rows (Termin/Angebot/Preisauskunft). */

## `frontend/src/pages/CalendarPage.tsx`  (6)

- `-` // (same takeover pattern as the invoice/KVA forms). Consumed on mount AND on
  `+` // (same takeover pattern as the invoice/Angebot forms). Consumed on mount AND on
- `-` <button onClick={() => setMode('projects')} className={cn('rounded px-3 py-1 text-sm', mod…
  `+` <button onClick={() => setMode('projects')} className={cn('rounded px-3 py-1 text-sm', mod…
- `-` {syncCal.isPending ? 'Synchronisiert…' : 'Sync'}
  `+` {syncCal.isPending ? 'Synchronisiert…' : 'Synchronisieren'}
- `-` {del.isPending ? 'Löscht…' : 'Löschen'}
  `+` {del.isPending ? 'Wird gelöscht…' : 'Löschen'}
- `-` note: 'Termin live ausgefüllt & gespeichert',
  `+` note: 'Termin direkt ausgefüllt & gespeichert',
- `-` note: e instanceof Error ? e.message : 'Formular-Ausfüllen fehlgeschlagen',
  `+` note: e instanceof Error ? e.message : 'Formular konnte nicht ausgefüllt werden',

## `frontend/src/pages/CallLogsPage.tsx`  (1)

- `-` <p className="mt-1 text-[13px] text-muted">Passen Sie die Filter an oder setzen Sie sie zu…
  `+` <p className="mt-1 text-[13px] text-muted">Passe die Filter an oder setze sie zurück.</p>

## `frontend/src/pages/CatalogPage.tsx`  (5)

- `-` <h1 className="text-2xl font-bold text-text">Artikel & Vorlagen</h1>
  `+` <h1 className="text-2xl font-bold text-text">Artikel & Betriebsmittel</h1>
- `-` <p className="mt-0.5 text-sm text-muted">Positionen und Textbausteine verwalten</p>
  `+` <p className="mt-0.5 text-sm text-muted">Positionen, Textbausteine und Betriebsmittel verw…
- `-` <button onClick={exportCsv} className="inline-flex items-center gap-2 rounded-md border bo…
  `+` <button onClick={exportCsv} className="inline-flex items-center gap-2 rounded-md border bo…
- `-` <button onClick={() => fileRef.current?.click()} className="inline-flex items-center gap-2…
  `+` <button onClick={() => fileRef.current?.click()} className="inline-flex items-center gap-2…
- `-` <p className="mt-1 text-sm text-muted">Erstellen Sie Ihren ersten Textbaustein.</p>
  `+` <p className="mt-1 text-sm text-muted">Erstelle deinen ersten Textbaustein.</p>

## `frontend/src/pages/CostEstimateFormPage.tsx`  (13)

- `-` { v: 'kva', l: 'Kostenvoranschlag' },
  `+` { v: 'kva', l: 'Angebot' },
- `-` // live PDF preview — saving '' here silently shipped a KVA missing
  `+` // live PDF preview — saving '' here silently shipped a Angebot missing
- `-` note: `KVA${ce.number ? ' ' + ce.number : ''} live ausgefüllt & gespeichert`,
  `+` note: `Angebot${ce.number ? ' ' + ce.number : ''} live ausgefüllt & gespeichert`,
- `-` note: e instanceof Error ? e.message : 'Formular-Ausfüllen fehlgeschlagen',
  `+` note: e instanceof Error ? e.message : 'Formular konnte nicht ausgefüllt werden',
- `-` <h1 className="text-2xl font-bold text-text">{isEdit ? `${loadedNumber ?? 'KVA'} bearbeite…
  `+` <h1 className="text-2xl font-bold text-text">{isEdit ? `${loadedNumber ?? 'Angebot'} bearb…
- `-` <p className="mt-0.5 text-sm text-muted">{isEdit ? 'Kostenvoranschlag bearbeiten' : 'Erste…
  `+` <p className="mt-0.5 text-sm text-muted">{isEdit ? 'Angebot bearbeiten' : 'Erstellen Sie e…
- `-` Kiki füllt den Kostenvoranschlag aus … bitte kurz zusehen, gespeichert wird automatisch.
  `+` Kiki füllt das Angebot aus … bitte kurz zusehen, gespeichert wird automatisch.
- `-` {/* Number first (the "header"), then topic — one KVA per inquiry;
  `+` {/* Number first (the "header"), then topic — one Angebot per inquiry;
- `-` the KVA inherits the inquiry's PROJEKT automatically. */}
  `+` the Angebot inherits the inquiry's PROJEKT automatically. */}
- `-` <p className="mt-1 text-xs text-muted">Der KVA wird automatisch dem Fall dieser Anfrage zu…
  `+` <p className="mt-1 text-xs text-muted">Der Angebot wird automatisch dem Vorgang dieser Anf…
- `-` <div><div className={labelCls}>Ihre Referenz / Auftragsnummer</div>
  `+` <div><div className={labelCls}>Deine Referenz / Auftragsnummer</div>
- `-` <p className="mt-1 text-xs text-muted">{isBinding ? 'Verbindliches Angebot.' : `Unverbindl…
  `+` <p className="mt-1 text-xs text-muted">{isBinding ? 'Verbindliches Angebot.' : `Unverbindl…
- `-` {/* Saving KVAs is admin-only; employees can still view (PDF preview). */}
  `+` {/* Saving Angebote is admin-only; employees can still view (PDF preview). */}

## `frontend/src/pages/CostEstimatesPage.tsx`  (12)

- `-` const TYPE_LABEL: Record<string, string> = { kva: 'KVA', offer: 'Angebot', order_confirmat…
  `+` const TYPE_LABEL: Record<string, string> = { kva: 'Angebot', offer: 'Angebot', order_confi…
- `-` <h1 className="text-2xl font-bold text-text">Kostenvoranschläge</h1>
  `+` <h1 className="text-2xl font-bold text-text">Angebote</h1>
- `-` <p className="mt-0.5 text-sm text-muted">{estimates.length} Kostenvoranschläge</p>
  `+` <p className="mt-0.5 text-sm text-muted">{estimates.length} Angebote</p>
- `-` + Neuer KVA
  `+` + Neuer Angebot
- `-` <div className="mb-1 text-xs font-medium text-muted">KVA-Nummer</div>
  `+` <div className="mb-1 text-xs font-medium text-muted">Angebotsnummer</div>
- `-` <option value="kva">KVA</option>
  `+` <option value="kva">Angebot</option>
- `-` <tr><td colSpan={9} className="px-4 py-12 text-center text-muted">Keine Kostenvoranschläge…
  `+` <tr><td colSpan={9} className="px-4 py-12 text-center text-muted">Keine Angebote.</td></tr…
- `-` const [subject, setSubject] = useState(`Ihr Kostenvoranschlag ${estimate.number ?? ''}`)
  `+` const [subject, setSubject] = useState(`Ihr Angebot ${estimate.number ?? ''}`)
- `-` `Sehr geehrte Damen und Herren,\n\nanbei erhalten Sie unseren Kostenvoranschlag ${estimate…
  `+` `Sehr geehrte Damen und Herren,\n\nanbei erhalten Sie unser Angebot ${estimate.number ?? '…
- `-` title="KVA senden"
  `+` title="Angebot senden"
- `-` <div><div className="mb-1 text-xs font-semibold text-body">An</div><input value={to} onCha…
  `+` <div><div className="mb-1 text-xs font-semibold text-body">An</div><input value={to} onCha…
- `-` <p className="rounded-md bg-info-bg px-3 py-2 text-xs text-info">Hinweis: E-Mail-Versand (…
  `+` <p className="rounded-md bg-info-bg px-3 py-2 text-xs text-info">Hinweis: E-Mail-Versand (…

## `frontend/src/pages/CustomerDetailPage.tsx`  (19)

- `-` return <div className="flex h-full items-center justify-center text-muted">Lädt…</div>
  `+` return <div className="flex h-full items-center justify-center text-muted">Wird geladen…</…
- `-` <FileText size={15} /> Kostenvoranschlag erstellen
  `+` <FileText size={15} /> Angebot erstellen
- `-` appointments, KVAs) from the backend. The old frontend-reconstructed
  `+` appointments, Angebote) from the backend. The old frontend-reconstructed
- `-` const l = window.prompt('Neuer Fall — Thema:')
  `+` const l = window.prompt('Neuer Vorgang — Thema:')
- `-` <Plus size={14} /> Neuer Fall
  `+` <Plus size={14} /> Neuer Vorgang
- `-` {cases.length > 0 && <Tag variant="ai">{cases.length} Fälle</Tag>}
  `+` {cases.length > 0 && <Tag variant="ai">{cases.length} Vorgänge</Tag>}
- `-` title="Fall öffnen (alle Anfragen)"
  `+` title="Vorgang öffnen (alle Anfragen)"
- `-` <span className="truncate text-sm font-bold text-text">{c.label || 'Fall'}</span>
  `+` <span className="truncate text-sm font-bold text-text">{c.label || 'Vorgang'}</span>
- `-` <span className="text-xs text-muted">{items.length} Anfragen</span>
  `+` <span className="text-xs text-muted">{items.length} {items.length === 1 ? 'Anfrage' : 'Anf…
- `-` title="In anderen Fall verschieben"
  `+` title="In anderen Vorgang verschieben"
- `-` Aus Fall lösen
  `+` Aus Vorgang lösen
- `-` {others.length > 0 && <div className="px-2.5 py-1 text-[10px] font-bold uppercase tracking…
  `+` {others.length > 0 && <div className="px-2.5 py-1 text-[10px] font-bold uppercase tracking…
- `-` → {c.label || 'Fall'}
  `+` → {c.label || 'Vorgang'}
- `-` const l = window.prompt('Neuer Fall — Thema:')
  `+` const l = window.prompt('Neuer Vorgang — Thema:')
- `-` ＋ Neuer Fall…
  `+` ＋ Neuer Vorgang…
- `-` t === 'auto' ? <Tag variant="success">sicher</Tag> : t === 'review' ? <Tag variant="warnin…
  `+` t === 'auto' ? <Tag variant="success">sicher</Tag> : t === 'review' ? <Tag variant="warnin…
- `-` {picked.size} Fälle übernehmen
  `+` {picked.size} Vorgänge übernehmen
- `-` {proposal.n_inquiries} Anfragen analysiert ({proposal.model}). Haken = als einen Fall bünd…
  `+` {proposal.n_inquiries} Anfragen analysiert ({proposal.model}). Haken = als einen Vorgang b…
- `-` // status change, appointment booked/rescheduled/confirmed and KVA for this
  `+` // status change, appointment booked/rescheduled/confirmed and Angebot for this

## `frontend/src/pages/CustomersPage.tsx`  (3)

- `-` label={exporting ? 'Export…' : 'CSV Export'}
  `+` label={exporting ? 'Export…' : 'CSV-Export'}
- `-` <HeaderBtn icon={Upload} label="CSV Import" onClick={() => setCsvOpen(true)} />
  `+` <HeaderBtn icon={Upload} label="CSV-Import" onClick={() => setCsvOpen(true)} />
- `-` <Trash2 size={15} /> {del.isPending ? 'Löscht…' : `Löschen (${selected.size})`}
  `+` <Trash2 size={15} /> {del.isPending ? 'Wird gelöscht…' : `Löschen (${selected.size})`}

## `frontend/src/pages/DashboardPage.tsx`  (3)

- `-` { id: 'ki-insights', label: 'KI-Insights', icon: Sparkles },
  `+` { id: 'ki-insights', label: 'KI-Auswertung', icon: Sparkles },
- `-` {callsCount} Anrufe · {casesCount} Fälle · {total} offen
  `+` {callsCount} Anrufe · {casesCount} Vorgänge · {total} offen
- `-` <div className="flex h-full items-center justify-center text-sm text-muted">Lädt Entscheid…
  `+` <div className="flex h-full items-center justify-center text-sm text-muted">Entscheidungen…

## `frontend/src/pages/EmployeesPage.tsx`  (12)

- `-` <span className="text-muted">Kein Login</span>
  `+` <span className="text-muted">Kein Zugang</span>
- `-` {isLoading ? 'Lädt…' : error ? `Fehler: ${(error as Error).message}` : 'Keine Mitarbeiter.…
  `+` {isLoading ? 'Wird geladen…' : error ? `Fehler: ${(error as Error).message}` : 'Keine Mita…
- `-` Ein Techniker arbeitet vor Ort und braucht <span className="font-medium">keinen Login</spa…
  `+` Ein Techniker arbeitet vor Ort und braucht <span className="font-medium">keinen Zugang</sp…
- `-` <input type="email" name="tech_email" autoComplete="off" value={email} onChange={(e) => se…
  `+` <input type="email" name="tech_email" autoComplete="off" value={email} onChange={(e) => se…
- `-` label="Login-Zugang zu HeyKiki"
  `+` label="Zugang zu HeyKiki"
- `-` sub="Der Mitarbeiter erhält eine E-Mail-Einladung und kann sich einloggen. Zählt zum Plan-…
  `+` sub="Der Mitarbeiter erhält eine E-Mail-Einladung und kann sich anmelden. Zählt zum gebuch…
- `-` <input type="email" name="employee_email" autoComplete="off" value={email} onChange={(e) =…
  `+` <input type="email" name="employee_email" autoComplete="off" value={email} onChange={(e) =…
- `-` <p className="mt-1 text-xs text-muted">Admins haben automatisch vollen Zugriff auf alle Mo…
  `+` <p className="mt-1 text-xs text-muted">Admins haben automatisch vollen Zugriff auf alle Be…
- `-` <Check checked={active} onChange={setActive} label="Konto aktiv" sub="Inaktive Konten könn…
  `+` <Check checked={active} onChange={setActive} label="Konto aktiv" sub="Inaktive Konten könn…
- `-` label="Techniker / Monteur"
  `+` label="Techniker"
- `-` <Check checked={active} onChange={setActive} label="Konto aktiv" sub="Inaktive Konten könn…
  `+` <Check checked={active} onChange={setActive} label="Konto aktiv" sub="Inaktive Konten könn…
- `-` label="Techniker / Monteur"
  `+` label="Techniker"

## `frontend/src/pages/InvoiceFormPage.tsx`  (12)

- `-` const INVOICE_INTRO = 'Vielen Dank für Ihren Auftrag. Wir berechnen Ihnen wie folgt:'
  `+` const INVOICE_INTRO = 'Vielen Dank für deinen Auftrag. Wir berechnen dir wie folgt:'
- `-` const INVOICE_CLOSING = 'Bitte überweisen Sie den Betrag innerhalb der Zahlungsfrist auf u…
  `+` const INVOICE_CLOSING = 'Bitte überweise den Betrag innerhalb der Zahlungsfrist auf unser …
- `-` // KVAs you can turn into an invoice: any of this customer's that aren't rejected
  `+` // Angebote you can turn into an invoice: any of this customer's that aren't rejected
- `-` // Import positions/subject/customer from a cost estimate (KVA → Rechnung).
  `+` // Import positions/subject/customer from a cost estimate (Angebot → Rechnung).
- `-` setError('KVA konnte nicht übernommen werden.')
  `+` setError('Angebot konnte nicht übernommen werden.')
- `-` // On mount: if arriving from a KVA ("In Rechnung umwandeln"), import it.
  `+` // On mount: if arriving from a Angebot ("In Rechnung umwandeln"), import it.
- `-` note: e instanceof Error ? e.message : 'Formular-Ausfüllen fehlgeschlagen',
  `+` note: e instanceof Error ? e.message : 'Formular konnte nicht ausgefüllt werden',
- `-` <div className="mt-3"><div className={labelCls}>Aus KVA übernehmen (optional)</div>
  `+` <div className="mt-3"><div className={labelCls}>Aus Angebot übernehmen (optional)</div>
- `-` <option value="">KVA übernehmen…</option>
  `+` <option value="">Angebot übernehmen…</option>
- `-` {selectableKvas.map((k) => <option key={k.id} value={k.id}>{k.number} — {k.subject || 'KVA…
  `+` {selectableKvas.map((k) => <option key={k.id} value={k.id}>{k.number} — {k.subject || 'Ang…
- `-` {kvaId && <p className="mt-1 text-xs text-green-deep">Positionen aus {estimates.find((e) =…
  `+` {kvaId && <p className="mt-1 text-xs text-green-deep">Positionen aus {estimates.find((e) =…
- `-` <div className="col-span-2"><div className={labelCls}>Ihre Referenz / Auftragsnummer</div>
  `+` <div className="col-span-2"><div className={labelCls}>Deine Referenz / Auftragsnummer</div…

## `frontend/src/pages/InvoicesPage.tsx`  (1)

- `-` <div><div className="mb-1 text-xs font-semibold text-body">An</div><input value={to} onCha…
  `+` <div><div className="mb-1 text-xs font-semibold text-body">An</div><input value={to} onCha…

## `frontend/src/pages/JobLinkPage.tsx`  (3)

- `-` <FieldBlock label="War die Erfahrung gut?">
  `+` <FieldBlock label="Lief alles gut?">
- `-` <FieldBlock label="Wie war der Vor-Ort-Termin?">
  `+` <FieldBlock label="Wie war der Termin vor Ort?">
- `-` {[['Ja, fertig', true], ['Noch offen', false]].map(([label, val]) => (
  `+` {[['Abgeschlossen', true], ['Noch offen', false]].map(([label, val]) => (

## `frontend/src/pages/KikiZentralePage.tsx`  (4)

- `-` { slug: 'branche-kontext', label: 'Branche & Kontext', icon: BookOpen },
  `+` { slug: 'branche-kontext', label: 'Gewerk & Wissensbasis', icon: BookOpen },
- `-` <p className="mt-0.5 text-sm text-muted">Vollständige Kontrolle über Ihren KI-Agenten — Ve…
  `+` <p className="mt-0.5 text-sm text-muted">Volle Kontrolle über deine KI — Verhalten, Sprach…
- `-` <div className="rounded-xl border border-border bg-surface p-12 text-center text-muted">Lä…
  `+` <div className="rounded-xl border border-border bg-surface p-12 text-center text-muted">Wi…
- `-` <h2 className="mb-1 text-lg font-bold text-text">Ausnahmen &amp; Sonderfälle</h2>
  `+` <h2 className="mb-1 text-lg font-bold text-text">Ausnahmen & Sonderfälle</h2>

## `frontend/src/pages/LoginPage.tsx`  (6)

- `-` setError(err instanceof Error ? err.message : 'Sign-in failed')
  `+` setError(err instanceof Error ? err.message : 'Anmeldung fehlgeschlagen.')
- `-` setError(err instanceof Error ? err.message : 'Could not send link')
  `+` setError(err instanceof Error ? err.message : 'Link konnte nicht gesendet werden.')
- `-` setError(err instanceof Error ? err.message : 'Could not send reset link')
  `+` setError(err instanceof Error ? err.message : 'Zurücksetz-Link konnte nicht gesendet werde…
- `-` <h1 className="text-xl font-bold text-text">HeyKiki Portal</h1>
  `+` <h1 className="text-xl font-bold text-text">HeyKiki-Portal</h1>
- `-` <p className="text-sm text-muted">Sign in to your account</p>
  `+` <p className="text-sm text-muted">Bei deinem Konto anmelden</p>
- `-` <label className="mb-1.5 block text-sm font-medium text-body">Email</label>
  `+` <label className="mb-1.5 block text-sm font-medium text-body">E-Mail</label>

## `frontend/src/pages/Placeholder.tsx`  (1)

- `-` <p className="text-sm">This module ships in a later phase.</p>
  `+` <p className="text-sm">Dieser Bereich folgt in einer späteren Version.</p>

## `frontend/src/pages/PlanningBoardPage.tsx`  (2)

- `-` <p className="mt-0.5 text-sm text-muted">Termine Fahrzeugen und Werkzeug zuweisen</p>
  `+` <p className="mt-0.5 text-sm text-muted">Fahrzeuge und Werkzeug für Termine einplanen</p>
- `-` {v === 'day' ? 'Tag' : 'Timeline'}
  `+` {v === 'day' ? 'Tag' : 'Zeitachse'}

## `frontend/src/pages/PosteingangPage.tsx`  (6)

- `-` // and resolve through the real appointment/KVA endpoints.
  `+` // and resolve through the real appointment/Angebot endpoints.
- `-` {/* Which case (Fall) this decision belongs to — point 2/6. */}
  `+` {/* Which case (Vorgang) this decision belongs to — point 2/6. */}
- `-` ? 'Kiki hat Ihre Anrufe bearbeitet und in Fälle sortiert. Hier treffen Sie die offenen Ent…
  `+` ? 'Kiki hat deine Anrufe bearbeitet und in Vorgänge sortiert. Hier triffst du die offenen …
- `-` : 'Das sind Ihre offenen Aufgaben — was Kiki für Sie vorbereitet hat und worauf Sie reagie…
  `+` : 'Das sind deine offenen Aufgaben — was Kiki für dich vorbereitet hat und worauf du reagi…
- `-` {loading ? 'Lädt…' : allDone ? 'Alles erledigt — gut gemacht.' : `${liveDecisions.length} …
  `+` {loading ? 'Wird geladen…' : allDone ? 'Alles erledigt — gut gemacht.' : `${liveDecisions.…
- `-` { n: vorgaenge.length, l: 'Fälle', c: 'var(--text)' },
  `+` { n: vorgaenge.length, l: 'Vorgänge', c: 'var(--text)' },

## `frontend/src/pages/ProjectFormPage.tsx`  (3)

- `-` Der Fall <span className="font-bold">{attachCaseNumber || 'FL-…'}</span> wird diesem Proje…
  `+` Der Vorgang <span className="font-bold">{attachCaseNumber || 'FL-…'}</span> wird diesem Pr…
- `-` {attachCaseId && <p className="mt-1 text-xs text-muted">Aus dem Fall übernommen — nicht än…
  `+` {attachCaseId && <p className="mt-1 text-xs text-muted">Aus dem Vorgang übernommen — nicht…
- `-` <p className="mb-3 text-sm text-muted">Legen Sie ein geplantes Budget für das Projekt fest…
  `+` <p className="mb-3 text-sm text-muted">Lege ein geplantes Budget für das Projekt fest. Das…

## `frontend/src/pages/ProjectWorkspacePage.tsx`  (12)

- `-` { key: 'cases', label: 'Fälle', icon: Layers },
  `+` { key: 'cases', label: 'Vorgänge', icon: Layers },
- `-` { key: 'cost_estimates', label: 'Kostenvoranschläge', icon: FileText },
  `+` { key: 'cost_estimates', label: 'Angebote', icon: FileText },
- `-` // Termine / KVA / Rechnungen / Team into the project's other tabs (the backend
  `+` // Termine / Angebot / Rechnungen / Team into the project's other tabs (the backend
- `-` ['KVA', s.cost_estimates], ['Rechnungen', s.invoices], ['Mitarbeiter', s.employees],
  `+` ['Angebot', s.cost_estimates], ['Rechnungen', s.invoices], ['Mitarbeiter', s.employees],
- `-` completed: { label: 'Fertig', cls: 'bg-success-bg text-success' },
  `+` completed: { label: 'Abgeschlossen', cls: 'bg-success-bg text-success' },
- `-` <h3 className="text-sm font-bold text-text">Fälle in diesem Projekt <span className="text-…
  `+` <h3 className="text-sm font-bold text-text">Vorgänge in diesem Projekt <span className="te…
- `-` <Plus size={15} /> Fall hinzufügen
  `+` <Plus size={15} /> Vorgang hinzufügen
- `-` <div className="px-2 py-1.5 text-[11px] font-bold uppercase tracking-wide text-faint">Fall…
  `+` <div className="px-2 py-1.5 text-[11px] font-bold uppercase tracking-wide text-faint">Vorg…
- `-` <div className="truncate text-sm font-semibold text-text">{c.title || 'Fall'}</div>
  `+` <div className="truncate text-sm font-semibold text-text">{c.title || 'Vorgang'}</div>
- `-` )) : <p className="px-2.5 py-3 text-xs text-muted">Keine freien Fälle für diesen Kunden.</…
  `+` )) : <p className="px-2.5 py-3 text-xs text-muted">Keine freien Vorgänge für diesen Kunden…
- `-` <span className="truncate text-base font-bold text-text">{c.title || 'Fall'}</span>
  `+` <span className="truncate text-base font-bold text-text">{c.title || 'Vorgang'}</span>
- `-` Noch keine Fälle zugeordnet. Über „Fall hinzufügen" einen Fall des Kunden anhängen — seine…
  `+` Noch keine Vorgänge zugeordnet. Über „Vorgang hinzufügen" einen Vorgang des Kunden anhänge…

## `frontend/src/pages/ProjectsPage.tsx`  (5)

- `-` <p className="mt-0.5 text-sm text-muted">{projects.length} Projekte · {activeProjects.leng…
  `+` <p className="mt-0.5 text-sm text-muted">{projects.length} {projects.length === 1 ? 'Proje…
- `-` {/* Cards — a lean Fall is a ticket: customer + the call(s) and the five things
  `+` {/* Cards — a lean Vorgang is a ticket: customer + the call(s) and the five things
- `-` (Anfragen/Anrufe · Termine · KVA · Rechnungen · Mitarbeiter). No budget/dates. */}
  `+` (Anfragen/Anrufe · Termine · Angebot · Rechnungen · Mitarbeiter). No budget/dates. */}
- `-` <Stat icon={<Layers size={14} />} n={p.stats.cases ?? 0} title="Fälle" />
  `+` <Stat icon={<Layers size={14} />} n={p.stats.cases ?? 0} title="Vorgänge" />
- `-` <Stat icon={<FileText size={14} />} n={p.stats.cost_estimates} title="KVA" />
  `+` <Stat icon={<FileText size={14} />} n={p.stats.cost_estimates} title="Angebot" />

## `frontend/src/pages/RufumleitungGuidePage.tsx`  (11)

- `-` („Immer weiterleiten"). Klappt das bei Ihrem Gerät nicht, nutzen Sie die Codes weiter unte…
  `+` („Immer weiterleiten"). Klappt das bei deinem Gerät nicht, nutze die Codes weiter unten.
- `-` <Step n={1}>Öffnen Sie die <span className="font-semibold text-text">Einstellungen</span>.…
  `+` <Step n={1}>Öffne die <span className="font-semibold text-text">Einstellungen</span>.</Ste…
- `-` <Step n={2}>Tippen Sie auf <span className="font-semibold text-text">Telefon</span> (bei m…
  `+` <Step n={2}>Tippe auf <span className="font-semibold text-text">Telefon</span> (bei manche…
- `-` <Step n={3}>Wählen Sie <span className="font-semibold text-text">Rufweiterleitung</span> u…
  `+` <Step n={3}>Wähle <span className="font-semibold text-text">Rufweiterleitung</span> und ak…
- `-` <Step n={4}>Tippen Sie auf <span className="font-semibold text-text">Weiterleiten an</span…
  `+` <Step n={4}>Tippe auf <span className="font-semibold text-text">Weiterleiten an</span> und…
- `-` <Step n={1}>Öffnen Sie die <span className="font-semibold text-text">Telefon-App</span>.</…
  `+` <Step n={1}>Öffne die <span className="font-semibold text-text">Telefon-App</span>.</Step>
- `-` <Step n={2}>Tippen Sie oben rechts auf das <span className="font-semibold text-text">Menü …
  `+` <Step n={2}>Tippe oben rechts auf das <span className="font-semibold text-text">Menü (⋮)</…
- `-` <Step n={3}>Wählen Sie <span className="font-semibold text-text">Anrufe</span> bzw. <span …
  `+` <Step n={3}>Wähle <span className="font-semibold text-text">Anrufe</span> bzw. <span class…
- `-` <Step n={4}>Wählen Sie <span className="font-semibold text-text">Immer weiterleiten</span>…
  `+` <Step n={4}>Wähle <span className="font-semibold text-text">Immer weiterleiten</span> und …
- `-` ? 'Die Codes sind bereits mit Ihrer HeyKiki-Nummer ausgefüllt.'
  `+` ? 'Die Codes sind bereits mit deiner HeyKiki-Nummer ausgefüllt.'
- `-` : 'Sobald Ihnen eine HeyKiki-Nummer zugewiesen ist, erscheint sie hier automatisch.'}
  `+` : 'Sobald dir eine HeyKiki-Nummer zugewiesen ist, erscheint sie hier automatisch.'}

## `frontend/src/pages/SetPasswordPage.tsx`  (1)

- `-` <h1 className="text-xl font-bold text-text">HeyKiki Portal</h1>
  `+` <h1 className="text-xl font-bold text-text">HeyKiki-Portal</h1>

## `frontend/src/pages/SettingsPage.tsx`  (34)

- `-` { slug: 'google-reviews', label: 'Google Reviews', icon: Star },
  `+` { slug: 'google-reviews', label: 'Google-Bewertungen', icon: Star },
- `-` <p className="mt-0.5 text-sm text-muted">Verwalten Sie Ihr Unternehmen, Ihre Integrationen…
  `+` <p className="mt-0.5 text-sm text-muted">Verwalte dein Unternehmen, deine Integrationen un…
- `-` <div className="rounded-xl border border-border bg-surface p-12 text-center text-muted">Lä…
  `+` <div className="rounded-xl border border-border bg-surface p-12 text-center text-muted">Wi…
- `-` <p className="mt-2 text-xs text-muted">PNG, JPG oder SVG, max. 2 MB. Erscheint in Seitenle…
  `+` <p className="mt-2 text-xs text-muted">PNG, JPG oder SVG, max. 2 MB. Erscheint in Seitenle…
- `-` <button className="rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white"…
  `+` <button className="rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white"…
- `-` <button className="rounded-md border border-green-primary px-4 py-2 text-sm font-semibold …
  `+` <button className="rounded-md border border-green-primary px-4 py-2 text-sm font-semibold …
- `-` <div className="text-2xl font-bold text-text">Dashboard</div>
  `+` <div className="text-2xl font-bold text-text">Übersicht</div>
- `-` <div className="text-base font-semibold text-body">Rechnungen & Kostenvoranschläge</div>
  `+` <div className="text-base font-semibold text-body">Rechnungen & Angebote</div>
- `-` <span><strong>Zahlung erforderlich.</strong> Ihre letzte Zahlung ist fehlgeschlagen. Bitte…
  `+` <span><strong>Zahlung erforderlich.</strong> Deine letzte Zahlung ist fehlgeschlagen. Bitt…
- `-` <span><strong>Testphase aktiv</strong>{s?.period_end ? ` – endet am ${new Date(s.period_en…
  `+` <span><strong>Testphase aktiv</strong>{s?.period_end ? ` – endet am ${new Date(s.period_en…
- `-` <div className="mt-2 text-xs text-muted">Der Wechsel gilt sofort; die Differenz wird antei…
  `+` <div className="mt-2 text-xs text-muted">Der Wechsel gilt sofort; die Differenz wird antei…
- `-` <span><strong>Letzte Warnung: {Math.round(pct)} % verbraucht.</strong> Ihr Kontingent ist …
  `+` <span><strong>Letzte Warnung: {Math.round(pct)} % verbraucht.</strong> Dein Kontingent ist…
- `-` <span>Ihr Minutenkontingent ist aufgebraucht. Ihre KI bleibt erreichbar — der <strong>Mehr…
  `+` <span>Dein Minutenkontingent ist aufgebraucht. Deine KI bleibt erreichbar — der <strong>Me…
- `-` <div className="text-xs font-bold uppercase tracking-wide text-muted">Darüber</div>
  `+` <div className="text-xs font-bold uppercase tracking-wide text-muted">Mehr als das</div>
- `-` <div className="mt-2 text-xs text-muted">Der Mehrverbrauch wird zusätzlich zur Grundgebühr…
  `+` <div className="mt-2 text-xs text-muted">Der Mehrverbrauch wird zusätzlich zur Grundgebühr…
- `-` <div className="text-xs text-muted">Starten Sie Ihr Abonnement — inkl. Testphase. Alle Pre…
  `+` <div className="text-xs text-muted">Starte dein Abonnement — inkl. Testphase. Alle Preise …
- `-` <span>Für Fragen zu Ihrem Abonnement wenden Sie sich an <a href="mailto:support@heykiki.de…
  `+` <span>Für Fragen zu deinem Abonnement wende dich an <a href="mailto:support@heykiki.de" cl…
- `-` { icon: FileText, title: 'KVA-Nachfassen', sub: 'Vorschlag wenn ein gesendeter KVA nicht b…
  `+` { icon: FileText, title: 'Angebot nachfassen', sub: 'Vorschlag, wenn ein gesendeter Angebo…
- `-` { icon: Receipt, title: 'Zahlungserinnerung', sub: 'Vorschlag für Zahlungserinnerung bei ü…
  `+` { icon: Receipt, title: 'Zahlungserinnerung', sub: 'Vorschlag für eine Zahlungserinnerung …
- `-` { icon: Wrench, title: 'Wartungserinnerung', sub: 'Erscheint wenn Wartung laut Wartungsver…
  `+` { icon: Wrench, title: 'Wartungserinnerung', sub: 'Erscheint, wenn die Wartung laut Wartun…
- `-` <p className="text-sm text-muted">Automatische Aktionsempfehlungen im Dashboard</p>
  `+` <p className="text-sm text-muted">Automatische Empfehlungen in der Übersicht</p>
- `-` {enabled && <p className="mt-2 text-sm text-muted">Die KI analysiert Ihre Daten täglich um…
  `+` {enabled && <p className="mt-2 text-sm text-muted">Kiki wertet deine Daten täglich um 06:0…
- `-` <p className="mt-1 text-sm text-muted">Erhalten Sie auf diesem Gerät sofort eine Benachric…
  `+` <p className="mt-1 text-sm text-muted">Erhalte auf diesem Gerät sofort eine Benachrichtigu…
- `-` <Banner>Standardversand über info@kiki-zusammenfassung.de bis eigener SMTP eingetragen.</B…
  `+` <Banner>Standardversand über info@kiki-zusammenfassung.de, bis eine eigene SMTP-Adresse ei…
- `-` <p className="mb-2 text-sm text-body">Verfügbare Platzhalter — klicken Sie auf einen Platz…
  `+` <p className="mb-2 text-sm text-body">Verfügbare Platzhalter — klicke auf einen Platzhalte…
- `-` <textarea data-field="kvaBody" onFocus={(e) => (lastFocused.current = e.currentTarget)} va…
  `+` <textarea data-field="kvaBody" onFocus={(e) => (lastFocused.current = e.currentTarget)} va…
- `-` { provider: 'calendly', name: 'Calendly', summary: 'Eingehende Calendly-Buchungen erschein…
  `+` { provider: 'calendly', name: 'Calendly', summary: 'Eingehende Calendly-Buchungen erschein…
- `-` <h2 className="text-lg font-bold text-text">Google Reviews</h2>
  `+` <h2 className="text-lg font-bold text-text">Google-Bewertungen</h2>
- `-` <p className="mb-4 text-sm text-muted">Ändern Sie das Passwort für Ihren Firmen-Login.</p>
  `+` <p className="mb-4 text-sm text-muted">Ändere das Passwort für deinen Firmen-Zugang.</p>
- `-` <button onClick={submit} disabled={changePw.isPending || !cur || !nw || !conf} className="…
  `+` <button onClick={submit} disabled={changePw.isPending || !cur || !nw || !conf} className="…
- `-` <div className="mb-4 flex items-center gap-2 text-sm font-bold text-error"><AlertTriangle …
  `+` <div className="mb-4 flex items-center gap-2 text-sm font-bold text-error"><AlertTriangle …
- `-` <p className="mt-1 text-sm text-muted">Löscht unwiderruflich alle Daten: Kunden, Rechnunge…
  `+` <p className="mt-1 text-sm text-muted">Löscht unwiderruflich alle Daten: Kunden, Rechnunge…
- `-` }><p className="text-sm text-body">Möchten Sie das Onboarding wirklich zurücksetzen? Branc…
  `+` }><p className="text-sm text-body">Möchtest du die Einrichtung wirklich zurücksetzen? Bran…
- `-` <p className="text-sm text-body">Geben Sie zur Bestätigung den Organisationsnamen <span cl…
  `+` <p className="text-sm text-body">Gib zur Bestätigung den Organisationsnamen ein <span clas…

## `frontend/src/pages/TechnicianPortalPage.tsx`  (1)

- `-` 'läuft': { label: 'Läuft', cls: 'bg-warning-bg text-warning' },
  `+` 'läuft': { label: 'In Bearbeitung', cls: 'bg-warning-bg text-warning' },

## `frontend/src/pages/VorgangThreadPage.tsx`  (4)

- `-` <div><span className="font-semibold">Erfahrung gut:</span> {rep.experience_good ? 'Ja' : '…
  `+` <div><span className="font-semibold">Lief alles gut:</span> {rep.experience_good ? 'Ja' : …
- `-` return <div className="flex h-full items-center justify-center text-muted">Lädt…</div>
  `+` return <div className="flex h-full items-center justify-center text-muted">Wird geladen…</…
- `-` <Stat label="KVAs" value={data.cost_estimates.length} />
  `+` <Stat label="Angebote" value={data.cost_estimates.length} />
- `-` if (window.confirm('Diesen Vorgang in den gewählten zusammenführen? Anrufe, Termine und KV…
  `+` if (window.confirm('Diesen Vorgang in den gewählten zusammenführen? Anrufe, Termine und An…

## `frontend/src/pages/calls/AppointmentCard.tsx`  (2)

- `-` <span className="flex-1 font-medium">Kategorie, Dauer &amp; Zuweisung</span>
  `+` <span className="flex-1 font-medium">Kategorie, Dauer & Zuweisung</span>
- `-` <div className="mt-0.5">Bleibt als Status in den Aktionen sichtbar.</div>
  `+` <div className="mt-0.5">Bleibt als Status in den Aufgaben sichtbar.</div>

## `frontend/src/pages/calls/CallDetail.tsx`  (2)

- `-` label: cc.case_label || cc.inquiry_subject || cc.summary_title || 'Fall',
  `+` label: cc.case_label || cc.inquiry_subject || cc.summary_title || 'Vorgang',
- `-` return <div className="flex flex-1 items-center justify-center text-muted">Lädt…</div>
  `+` return <div className="flex flex-1 items-center justify-center text-muted">Wird geladen…</…

## `frontend/src/pages/calls/Inbox.tsx`  (5)

- `-` const caseLabel = call.case_label || call.inquiry_subject || 'Fall'
  `+` const caseLabel = call.case_label || call.inquiry_subject || 'Vorgang'
- `-` title={`Fall${caseTicket ? ` ${caseTicket}` : ''} · ${caseLabel} — im Posteingang öffnen`}
  `+` title={`Vorgang${caseTicket ? ` ${caseTicket}` : ''} · ${caseLabel} — im Posteingang öffne…
- `-` {done && <TaskBtn icon={RotateCcw} label="Wiederöffnen" onClick={() => onSetState('open')}…
  `+` {done && <TaskBtn icon={RotateCcw} label="Wieder öffnen" onClick={() => onSetState('open')…
- `-` <div className="text-sm font-extrabold text-text">Keine offenen Aktionen</div>
  `+` <div className="text-sm font-extrabold text-text">Keine offenen Aufgaben</div>
- `-` <div className="mt-0.5 text-[12.5px] text-muted">Kiki hat alles im Griff.</div>
  `+` <div className="mt-0.5 text-[12.5px] text-muted">Kiki meldet sich, sobald etwas reinkommt.…

## `frontend/src/pages/calls/Transcript.tsx`  (2)

- `-` <span className="text-sm text-muted">Lädt Aufnahme…</span>
  `+` <span className="text-sm text-muted">Aufnahme wird geladen…</span>
- `-` <span className="text-[13.5px]">Wählen Sie einen Anruf aus.</span>
  `+` <span className="text-[13.5px]">Wähle einen Anruf aus.</span>

## `frontend/src/pages/calls/Workspace.tsx`  (7)

- `-` // Spec: an OUTBOUND screen must NOT offer create-appointment / KVA / change-customer
  `+` // Spec: an OUTBOUND screen must NOT offer create-appointment / Angebot / change-customer
- `-` <span className="flex-1 text-left">Anderem Fall zuordnen</span>
  `+` <span className="flex-1 text-left">Anderem Vorgang zuordnen</span>
- `-` <SectionLabel>Offene Aktion</SectionLabel>
  `+` <SectionLabel>Offene Aufgabe</SectionLabel>
- `-` <SectionLabel>Aktion erstellen</SectionLabel>
  `+` <SectionLabel>Aufgabe erstellen</SectionLabel>
- `-` <PrimaryAction icon={Receipt} label="Kostenvoranschlag" tone="money" onClick={onKva} disab…
  `+` <PrimaryAction icon={Receipt} label="Angebot" tone="money" onClick={onKva} disabled={!onKv…
- `-` title="Zum Fall (alle Anfragen, Termine, KVA, Rechnungen, Techniker)"
  `+` title="Zum Vorgang (alle Anfragen, Termine, Angebot, Rechnungen, Techniker)"
- `-` Fall {call.case_number ?? ''}
  `+` Vorgang {call.case_number ?? ''}

## `frontend/src/pages/calls/log/LogDrawer.tsx`  (6)

- `-` // card + create-actions (Termin / KVA / Rechnung) + Zuständig live up top, then the
  `+` // card + create-actions (Termin / Angebot / Rechnung) + Zuständig live up top, then the
- `-` {state === 'loading' ? 'Lädt Aufnahme…' : 'Aufnahme abspielen'}
  `+` {state === 'loading' ? 'Aufnahme wird geladen…' : 'Aufnahme abspielen'}
- `-` <div className="p-10 text-center text-sm text-muted">Lädt…</div>
  `+` <div className="p-10 text-center text-sm text-muted">Wird geladen…</div>
- `-` KVA
  `+` Angebot
- `-` {link.title || (link.kind === 'fall' ? 'Fall' : 'Anfrage')}
  `+` {link.title || (link.kind === 'fall' ? 'Vorgang' : 'Anfrage')}
- `-` <span className="whitespace-nowrap font-bold text-ai">Nächste Aktion:</span>
  `+` <span className="whitespace-nowrap font-bold text-ai">Nächste Aufgabe:</span>

## `frontend/src/pages/calls/log/LogTable.tsx`  (4)

- `-` {/* 6 — Fall / Anfrage (case) */}
  `+` {/* 6 — Vorgang / Anfrage (case) */}
- `-` title={`${link.kind === 'fall' ? 'Fall' : 'Anfrage'} öffnen${link.title ? ` · ${link.title…
  `+` title={`${link.kind === 'fall' ? 'Vorgang' : 'Anfrage'} öffnen${link.title ? ` · ${link.ti…
- `-` <span className="truncate">{link.number ?? (link.kind === 'fall' ? 'Fall' : 'Anfrage')}</s…
  `+` <span className="truncate">{link.number ?? (link.kind === 'fall' ? 'Vorgang' : 'Anfrage')}…
- `-` <th className={th}>Fall / Anfrage</th>
  `+` <th className={th}>Vorgang / Anfrage</th>

## `frontend/src/pages/calls/shared.ts`  (2)

- `-` kva_to_send: 'KVA senden',
  `+` kva_to_send: 'Angebot senden',
- `-` kva_pending_acceptance: 'KVA-Antwort offen',
  `+` kva_pending_acceptance: 'Angebot-Antwort offen',

## `frontend/src/pages/cases/CaseDetailPane.tsx`  (22)

- `-` // tiles · record TABLES (Anfragen / Termine / Kostenvoranschläge / Rechnungen /
  `+` // tiles · record TABLES (Anfragen / Termine / Angebote / Rechnungen /
- `-` 'läuft': { label: 'Läuft', variant: 'info' },
  `+` 'läuft': { label: 'In Bearbeitung', variant: 'info' },
- `-` <span className={cn('ml-auto shrink-0 rounded-full px-2 py-0.5 text-[11px] font-bold', ton…
  `+` <span className={cn('ml-auto shrink-0 rounded-full px-2 py-0.5 text-[11px] font-bold', ton…
- `-` onSuccess: () => { qc.invalidateQueries({ queryKey: ['pe'] }); flash('Aktion entfernt') },
  `+` onSuccess: () => { qc.invalidateQueries({ queryKey: ['pe'] }); flash('Aufgabe entfernt') }…
- `-` if (!caseId) return <div className="grid flex-1 place-items-center bg-bg text-[17px] text-…
  `+` if (!caseId) return <div className="grid flex-1 place-items-center bg-bg text-[17px] text-…
- `-` if (isLoading || !data) return <div className="grid flex-1 place-items-center bg-bg text-m…
  `+` if (isLoading || !data) return <div className="grid flex-1 place-items-center bg-bg text-m…
- `-` summary_title: cs.label ?? 'Fall',
  `+` summary_title: cs.label ?? 'Vorgang',
- `-` <div className="mt-0.5 text-[16px] text-body">{cs.label ?? 'Fall'} · <span className="font…
  `+` <div className="mt-0.5 text-[16px] text-body">{cs.label ?? 'Vorgang'} · <span className="f…
- `-` <button onClick={() => setProjOpen((o) => !o)} className="text-xs font-bold text-muted hov…
  `+` <button onClick={() => setProjOpen((o) => !o)} className="text-xs font-bold text-muted hov…
- `-` {currentProject && <button onClick={() => { patchCase.mutate({ project_id: '' }); setProjO…
  `+` {currentProject && <button onClick={() => { patchCase.mutate({ project_id: '' }); setProjO…
- `-` <div className="mb-2.5 text-[13px] font-bold text-muted">Wie ist der Stand?</div>
  `+` <div className="mb-2.5 text-[13px] font-bold text-muted">Status</div>
- `-` <h2 className="font-poster text-[20px] font-extrabold text-text">Was ist zu tun?</h2>
  `+` <h2 className="font-poster text-[20px] font-extrabold text-text">Nächste Schritte</h2>
- `-` <div className="text-[13.5px] text-muted">Kiki hat das für Sie vorbereitet</div>
  `+` <div className="text-[13.5px] text-muted">Kiki hat das für dich vorbereitet</div>
- `-` <div className="mt-3 text-[17px] font-extrabold text-text">Keine offenen Aktionen</div>
  `+` <div className="mt-3 text-[17px] font-extrabold text-text">Keine offenen Aufgaben</div>
- `-` <div className="mt-1 text-[13px] text-muted">Kiki hat alles im Griff.</div>
  `+` <div className="mt-1 text-[13px] text-muted">Kiki meldet sich, sobald etwas reinkommt.</di…
- `-` <QuickTile label="Kostenvoranschlag" icon={Receipt} tone="ai" onClick={goKva} disabled={!c…
  `+` <QuickTile label="Angebot" icon={Receipt} tone="ai" onClick={goKva} disabled={!customerId}…
- `-` ) : <EmptyHint text="Noch keine Anfragen in diesem Fall." />}
  `+` ) : <EmptyHint text="Noch keine Anfragen in diesem Vorgang." />}
- `-` <BigCard title="Kostenvoranschläge" icon={Receipt} accent="ai" count={data.cost_estimates.…
  `+` <BigCard title="Angebote" icon={Receipt} accent="ai" count={data.cost_estimates.length} ac…
- `-` <td className="px-3 py-2.5 font-mono text-xs text-muted">{k.number ?? 'KVA'}</td>
  `+` <td className="px-3 py-2.5 font-mono text-xs text-muted">{k.number ?? 'Angebot'}</td>
- `-` ) : <EmptyHint text="Noch keine Kostenvoranschläge." />}
  `+` ) : <EmptyHint text="Noch keine Angebote." />}
- `-` <p className="text-sm text-muted">Der Termin muss erst im Kalender bestätigt werden — dana…
  `+` <p className="text-sm text-muted">Der Termin muss erst im Kalender bestätigt werden — dana…
- `-` <button onClick={() => copyLink(j.url)} title="Techniker-Link kopieren" className="inline-…
  `+` <button onClick={() => copyLink(j.url)} title="Techniker-Link kopieren" className="inline-…

## `frontend/src/pages/cases/CaseList.tsx`  (6)

- `-` completed: { label: 'Fertig', cls: 'bg-success-bg text-success' },
  `+` completed: { label: 'Abgeschlossen', cls: 'bg-success-bg text-success' },
- `-` <div className="mt-0.5 truncate text-[14.5px] text-muted">{c.title || 'Fall'}</div>
  `+` <div className="mt-0.5 truncate text-[14.5px] text-muted">{c.title || 'Vorgang'}</div>
- `-` { value: 'completed', label: 'Fertig', dot: 'var(--success)', count: cases.filter((c) => c…
  `+` { value: 'completed', label: 'Abgeschlossen', dot: 'var(--success)', count: cases.filter((…
- `-` <h1 className="font-poster text-[26px] font-extrabold text-text">Meine Fälle</h1>
  `+` <h1 className="font-poster text-[26px] font-extrabold text-text">Meine Vorgänge</h1>
- `-` <div className="mt-2.5 text-[15px] font-bold text-body">Keine Fälle gefunden</div>
  `+` <div className="mt-2.5 text-[15px] font-bold text-body">Keine Vorgänge gefunden</div>
- `-` <div className="mt-1 text-[13.5px] text-muted">Versuchen Sie einen anderen Filter.</div>
  `+` <div className="mt-1 text-[13.5px] text-muted">Versuche einen anderen Filter.</div>

## `frontend/src/pages/posteingang/CallDrawer.tsx`  (5)

- `-` {state === 'loading' ? 'Lädt Aufnahme…' : 'Aufnahme abspielen'}
  `+` {state === 'loading' ? 'Aufnahme wird geladen…' : 'Aufnahme abspielen'}
- `-` <div style={{ padding: 40, textAlign: 'center', color: 'var(--muted)', fontSize: 14 }}>Läd…
  `+` <div style={{ padding: 40, textAlign: 'center', color: 'var(--muted)', fontSize: 14 }}>Wir…
- `-` {/* Read-only Fall indicator (triage moved to the Anrufe cockpit). */}
  `+` {/* Read-only Vorgang indicator (triage moved to the Anrufe cockpit). */}
- `-` <span>Noch keinem Fall zugeordnet — im Anruf-Cockpit zuordnen.</span>
  `+` <span>Noch keinem Vorgang zugeordnet — im Anruf-Cockpit zuordnen.</span>
- `-` <span style={{ fontFamily: 'var(--font-poster)', fontWeight: 700, color: 'var(--ai)', whit…
  `+` <span style={{ fontFamily: 'var(--font-poster)', fontWeight: 700, color: 'var(--ai)', whit…

## `frontend/src/pages/posteingang/api.ts`  (4)

- `-` appointment_cancelled: { type: 'storno', accent: 'var(--error)', label: 'Storno', variant:…
  `+` appointment_cancelled: { type: 'storno', accent: 'var(--error)', label: 'Storno', variant:…
- `-` kva_to_send: { type: 'kva', accent: 'var(--ai)', label: 'KVA', variant: 'ai', title: (a) =…
  `+` kva_to_send: { type: 'kva', accent: 'var(--ai)', label: 'Angebot', variant: 'ai', title: (…
- `-` problem: (isCase ? latest.case_label : latest.inquiry_subject) || latest.summary_title || …
  `+` problem: (isCase ? latest.case_label : latest.inquiry_subject) || latest.summary_title || …
- `-` items.push({ kind: 'kva', label: 'KVA', detail: k.total != null ? `${k.total} €` : '', don…
  `+` items.push({ kind: 'kva', label: 'Angebot', detail: k.total != null ? `${k.total} €` : '',…

## `frontend/src/pages/posteingang/parts.tsx`  (1)

- `-` <Play size={11} /> Aufnahme &amp; Transkript
  `+` <Play size={11} /> Aufnahme & Transkript

## `frontend/src/pages/projectTabs.tsx`  (6)

- `-` <button onClick={() => navigate(newUrl)} className="inline-flex items-center gap-1.5 round…
  `+` <button onClick={() => navigate(newUrl)} className="inline-flex items-center gap-1.5 round…
- `-` <th className="px-4 py-3">KVA-Nr.</th><th className="px-4 py-3">Datum</th><th className="p…
  `+` <th className="px-4 py-3">Angebot-Nr.</th><th className="px-4 py-3">Datum</th><th classNam…
- `-` <EmptyState>Noch keine Kostenvoranschläge für dieses Projekt.</EmptyState>
  `+` <EmptyState>Noch keine Angebote für dieses Projekt.</EmptyState>
- `-` title={hasNoCases ? 'Zuerst einen Fall zum Projekt hinzufügen' : undefined}
  `+` title={hasNoCases ? 'Zuerst einen Vorgang zum Projekt hinzufügen' : undefined}
- `-` Fügen Sie dem Projekt zuerst einen Fall hinzu, um Mitarbeiter zuzuweisen.
  `+` Fügen Sie dem Projekt zuerst einen Vorgang hinzu, um Mitarbeiter zuzuweisen.
- `-` {!docs.length && <EmptyState>Noch keine Dokumente — ziehen Sie Dateien in das Feld oben.</…
  `+` {!docs.length && <EmptyState>Noch keine Dokumente — zieh Dateien in das Feld oben.</EmptyS…

## `supabase/migrations/0077_case_number_vg_prefix.sql`  (10)

- `-` 
  `+` -- 0077_case_number_vg_prefix.sql
- `-` 
  `+` -- Rename the case (Vorgang) number prefix FL- → VG- to match the German UI wording
- `-` 
  `+` -- ("Fall" → "Vorgang", global rule 2). The numeric sequence and org token are
- `-` 
  `+` -- untouched; only the human-readable prefix changes (FL-KC007-0001 → VG-KC007-0001).
- `-` 
  `+` --
- `-` 
  `+` -- Safe: data-only UPDATE, idempotent, scoped to rows that still carry the old prefix.
- `-` 
  `+` -- gen_case_number() now mints VG- (app/services/common.py); this aligns existing rows.
- `-` 
  `+` update public.cases
- `-` 
  `+` set    number = 'VG-' || substring(number from 4)
- `-` 
  `+` where  number like 'FL-%';

## `supabase/migrations/0078_cost_estimate_kva_to_ag_prefix.sql`  (12)

- `-` 
  `+` -- 0078_cost_estimate_kva_to_ag_prefix.sql
- `-` 
  `+` -- KVA → Angebot product-wide (Amber's call). The former "kva" doc-type is now
- `-` 
  `+` -- branded "Angebot", so its Aktenzeichen prefix changes KVA-…  →  AG-…
- `-` 
  `+` -- (e.g. KVA-2026-00001 → AG-2026-00001). The doc_type key stays "kva" in the DB;
- `-` 
  `+` -- gen_number() now mints AG- (app/services/cost_estimates.py).
- `-` 
  `+` --
- `-` 
  `+` -- Safe: data-only UPDATE, idempotent, scoped to kva-type rows that still carry KVA-.
- `-` 
  `+` -- Run manually in Supabase against UAT (Amber executes migrations).
- `-` 
  `+` update public.cost_estimates
- `-` 
  `+` set    number = 'AG-' || substring(number from 5)
- `-` 
  `+` where  type = 'kva'
- `-` 
  `+` and  number like 'KVA-%';