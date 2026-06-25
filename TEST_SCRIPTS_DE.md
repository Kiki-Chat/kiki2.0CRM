# Kiki — Test-Skripte (Deutsch) für Anruf-Tests

Skripte zum **lauten Vorlesen**, wenn du Kiki anrufst. Jedes Skript ist bewusst
**dicht** — der Anrufer nennt alles in einem Zug (Name, Telefon, Adresse, Problem,
Raum, Dringlichkeit, Wunschtermin), damit du prüfen kannst, ob der Agent in einem
einzigen Schritt alles korrekt erfasst.

**Verknüpfung mit dem Test-Kunden:** Damit der Anruf auf den Tracking-Kunden
„Vorschau Test" läuft, nenne die Nummer **„plus neun-eins, sieben-acht-acht-sieben,
drei-neun-sieben-acht-drei-neun"** (`+91 7887397839`). Sonst verknüpft der Anruf
über die Anrufer-ID. Namen/Adressen frei austauschbar.

**Kontext:** Firma = Dachdecker (Dach, Dachrinne, Ziegel, Abdichtung …).

---

## 1 — Erstanruf mit Terminwunsch (der dichte „alles auf einmal"-Test)

> „Guten Tag, mein Name ist **Markus Brandt**, B-R-A-N-D-T. Ich bin **Neukunde** und
> rufe zum ersten Mal an. Erreichbar bin ich unter **null-eins-sieben-zwei,
> drei-vier-fünf, sechs-sieben-acht-neun**. Ich wohne in der **Lindenstraße 14,
> 50667 Köln**. Mein Problem: Seit dem letzten Sturm **tropft es durch die Decke im
> Schlafzimmer im Obergeschoss**, direkt über dem Fenster — anscheinend ist das
> **Dach dort undicht**. Es ist **nicht akut gefährlich**, sollte aber bald jemand
> anschauen. Mir würde **nächste Woche Dienstag, der 30. Juni, vormittags um
> 10 Uhr** passen. Können Sie mir dafür bitte einen **Termin** geben?"

**Soll erzeugen:** „Terminbestätigung ausstehend" (grün) im Posteingang **+** ein
gestrichelter **„Vorschlag"** im Kalender, verknüpft mit dem Anruf.

---

## 2 — Erstanruf mit Wunsch nach einem Angebot (Kostenvoranschlag)

> „Hallo, hier ist **Sabine Krüger**, K-R-Ü-G-E-R, Neukundin. Meine Nummer:
> **null-eins-sechs-null, eins-zwei-drei, vier-fünf-sechs-sieben**. Adresse:
> **Gartenweg 8, 50674 Köln**. Ich hätte gern einen **Kostenvoranschlag**: Die
> **Dachrinne am Einfamilienhaus** hängt durch und ist an einer Ecke gerissen, ich
> befürchte sie muss **komplett erneuert** werden, etwa 12 Meter. Können Sie mir
> dafür ein **Angebot** machen und es mir zuschicken?"

**Soll erzeugen:** „Angebot erstellen" (kva_suggested). Danach im Lebenszyklus:
Angebot anlegen → **„Angebot senden"** (sofort, ohne 24-h-Wartezeit) → versendet →
„Angebot-Antwort offen" → angenommen → **„Angebot angenommen — Rechnung erstellen"**
(grün) / abgelehnt → **„Angebot abgelehnt"** (slate, bleibt 40 Tage).

---

## 3 — Notfall / dringend (Emergency-Test)

> „Notfall! Mein Name ist **Thomas Vogel**, V-O-G-E-L. Nummer **null-eins-sieben-fünf,
> neun-acht-sieben, sechs-fünf-vier-drei**. **Hauptstraße 3, 50676 Köln**. Bei uns
> ist gerade im Sturm ein **großes Stück vom Dach abgedeckt**, es **regnet
> ungehindert ins Dachgeschoss-Kinderzimmer** und läuft schon die Wand runter. Das
> ist **akut** — wir brauchen **heute noch** jemanden, eine **Notabdeckung**. Bitte
> so schnell wie möglich!"

**Testet:** Notfall-Kennzeichnung + dringenden Terminwunsch → hochpriorisierte Aktion.

---

## 4 — Bestandskunde will Termin verschieben (Reschedule-Test)

> „Guten Tag, **Markus Brandt** hier, ich hatte einen **Termin am Dienstag, den
> 30. Juni um 10 Uhr** wegen des undichten Dachs. Da ist mir leider etwas
> dazwischengekommen — **können wir das auf Donnerstag, den 2. Juli, nachmittags um
> 14:30 Uhr verschieben?**"

**Soll erzeugen:** Nach dem Verschieben löst der **Rückruf** aus, der die **neue
Zeit nennt und um Bestätigung bittet** (Zusagen/Ablehnen), plus die **orange
„Termin verschoben — Kundenbestätigung ausstehend"**-Aktion (L2: das letzte Wort
liegt bei der Person im CRM).

---

## 5 — Bestandskunde sagt Termin ab (Cancel-Test)

> „Hallo, **Markus Brandt**. Ich muss meinen **Termin am 2. Juli leider ganz
> absagen** — wir lassen das Dach erstmal vom Versicherungsgutachter anschauen.
> Bitte den Termin **stornieren**, danke."

**Soll erzeugen:** die **slate / dunkelgraue „Termin storniert — Team informieren"**-
Aktion (nicht rot).

---

## 6 — Rechnungs-/Zahlungsfrage (Invoice-Pfad)

> „Guten Tag, **Sabine Krüger**. Die **Dachrinne wurde letzte Woche fertig montiert**
> — könnten Sie mir bitte die **Rechnung** dafür zuschicken? Meine Adresse haben
> Sie ja: Gartenweg 8."

**Soll erzeugen:** „Rechnung erstellen" (invoice_suggested) → nach dem Anlegen
**„Rechnung senden"** (sofort) → … → bei Storno die **slate „Rechnung storniert"**-Aktion.

---

## Bonus — unvollständige / „chaotische" Anrufe (testet das Nachfragen)

Diese Skripte lassen **absichtlich Angaben weg**, damit du prüfen kannst, ob der
Agent gezielt nachfragt, statt einfach weiterzumachen.

**7 — ohne Raum & ohne genaue Stelle:**
> „Ja hallo, **Brandt**, mein Dach ist undicht, es kommt Wasser rein. Ich bräuchte
> jemanden." *(Erwartung: fragt nach Raum/Stelle, Adresse, Wunschtermin, Nummer.)*

**8 — ohne Adresse, nuschelig:**
> „Hier ist die Krüger, äh… die Ziegel sind teilweise runtergefallen nach dem Sturm,
> könnt ihr mal vorbeikommen diese Woche?" *(Erwartung: fragt nach Adresse + Nummer +
> konkretem Tag/Uhrzeit.)*

**9 — sehr knapp:**
> „Ich brauch einen Termin." *(Erwartung: fragt strukturiert Name, Nummer, Adresse,
> Problem, Raum, Wunschtermin ab.)*

---

## Prüf-Checkliste (Posteingang `/posteingang` nach dem Anruf)

| Skript | Erwartete Karte | Farbe |
|---|---|---|
| 1 | Terminbestätigung ausstehend (+ Kalender-„Vorschlag") | grün |
| 2 | Angebot erstellen → Angebot senden → … → Angenommen / Abgelehnt | AI / grün / slate |
| 3 | Terminbestätigung (Notfall, hohe Priorität) | grün, hoch |
| 4 | Termin verschoben — Kundenbestätigung ausstehend | 🟠 orange |
| 5 | Termin storniert — Team informieren | ⬛ slate |
| 6 | Rechnung erstellen → Rechnung senden → … / Rechnung storniert | AI / slate |

**Lebenszyklus-Stufen (neu):** Anlegen erscheint **sofort** (keine 24-h-Wartezeit);
ein manuell aus dem Anruf angelegter Termin landet **„Bestätigung ausstehend"** und
wird **in der Aktion bestätigt** → bleibt danach **40 Tage** als „Bestätigt"
sichtbar; abgelehnte Angebote / stornierte Rechnungen bleiben **40 Tage** als
slate-Karte und fallen dann weg.
