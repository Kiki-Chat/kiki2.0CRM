# HeyKiki — Call Logs ("Anrufe") · Design Brief

> **For the design team.** This explains *what the Call Logs screen does and why*, grounded in the
> current implementation (`frontend/src/pages/CallLogsPage.tsx` + `frontend/src/pages/calls/AppointmentCard.tsx`),
> so an improved design can keep every meaning intact while making it more UI/UX-rich.
> German-only UI · light **and** dark mode (built on CSS-var design tokens) · brand = `green-primary`.

---

## 1. What this screen is — purpose & intent

"Anrufe" is the **operator's inbox for everything Kiki (the AI phone assistant) handled**. Kiki
answers/places calls, transcribes them, extracts structured data, and creates a follow-up **"Anfrage"**
(inquiry). A human at the Handwerksbetrieb (tradesperson business) then **triages each call and decides
the next step** — assign it, mark it done, send a cost estimate, book an appointment.

The screen must let a busy person answer one question fast:
**"What came in, what needs me, and what do I do about it?"**

## 2. Information architecture — a 3-pane "triage cockpit"

All three panes are **drag-resizable** and each width **persists per user** (localStorage).

| Pane | Role | Mental model |
|---|---|---|
| **Left** | The inbox list | "What came in / what's owed" |
| **Center** | The conversation | "What was actually said" (transcript + recording) |
| **Right** | The workspace | "What I do about it" (actions / details / history) |

---

## 3. Left pane — the inbox

**Two tabs at the top:**
- **Anfragen** (default) — every call as a row, with a count badge. Searchable + filterable list.
- **Aktionen** — only the items that *need a decision* (a separate worklist), with a **red count badge**
  when > 0. Empty state is reassuring: *"Keine offenen Aktionen. Kiki hat alles im Griff."*

**Search + filters (Anfragen tab only):**
- **Search** → live, **client-side** filter over the **customer name + the call's one-line summary**.
  (It filters the visible list; it is *not* a global search.)
- **Richtung** → Alle / **Eingehend (inbound)** / **Ausgehend (outbound)**.
- **Status** → Alle / Offen / In Bearbeitung / Abgeschlossen.

**Each call row** encodes a lot at a glance:
- **Direction = border color:** **inbound → green border, outbound → amber/yellow border**, plus a small
  incoming/outgoing phone icon.
- **Assigned employee = a colored initials circle** (left). Color is hashed from the employee, so the same
  person is always the same color; **"?" = unassigned**. Clicking it opens a dropdown to (re)assign —
  *inline, without leaving the list*.
- **Unread = bold text + a thick green left accent** (Gmail style). Read rows go muted.
- **One line:** the customer **name or number** (falls back name → collected name → number → "Unbekannt"),
  and under it the **call's one-sentence summary**.
- **Status = a pill:** **Offen (blue) · In Bearbeitung (amber) · Erledigt (green)** — three states, distinct colors.
- **Emergency = a red, *blinking* "NOTDIENST" badge.** **This is the ONLY element allowed to pulse/blink** —
  blinking is reserved exclusively for emergencies so it always means "urgent."
- Meta: time · duration.

**Aktionen cards** (the worklist): a **priority dot** (high = red, normal = green), a **kind chip**
(Terminbestätigung / KVA senden / KVA-Antwort offen / Rückruf / Alternativtermin), the summary, and the
customer name. Click → that customer's profile.

---

## 4. Center pane — the conversation

- **Header:** name · direction · time · duration.
- **Zusammenfassung (AI summary) preview:** a 2-line clamp at the very top with a sparkle icon, so the
  operator gets the gist before reading anything. **"Mehr anzeigen"** jumps to the full summary on the right.
- **Recording:** a lazy **"Aufnahme laden"** button → once loaded, an audio player with **play/pause, seek,
  volume, playback-speed, and download** (today via the browser-native control — a strong candidate for a
  **custom, branded player** in the redesign).
- **Transcript = a chat thread:** **Kiki** (the assistant) on one side with a bot icon and green bubbles;
  the **caller** on the other with a user icon and neutral bubbles. While the recording plays, **the current
  line highlights and auto-scrolls in sync** with the audio — a signature interaction worth elevating.

---

## 5. Right pane — the workspace (3 sub-tabs)

Header shows the inquiry **title + status tag + type tag** (and the NOTDIENST badge if it's an emergency).

**Tab 1 — Aktionen (the "do something" tab):**
- **Zugewiesen an** — assign to an employee.
- **OFFENE AKTIONEN card** (when Kiki booked a pending appointment) — Bestätigen / Ablehnen /
  Alternative vorschlagen.
- **Status-Aktionen** — the verbs the operator can take, each color-toned:
  - **Als erledigt markieren** (green) / Wieder öffnen
  - **In Bearbeitung setzen** (amber)
  - **Bearbeiten** (opens an edit form: title, type, notes, status)
  - **Kostenvoranschlag erstellen** (prepares a cost estimate)
  - **Termin erstellen** (create-appointment form)
  - **Anfrage löschen** (destructive, red)

**Tab 2 — Details (the "who & what" tab):**
- **Zusammenfassung** (collapsible, full text + "Vollständige Zusammenfassung").
- **Kunde** card — name, **customer number** → "Profil öffnen".
- **Contact channels** — E-Mail, **Telefon**, **Adresse**, and **Kanal** (channel, e.g. "Telefon").
- **Erfasste Daten** (what Kiki extracted): **Betreff** (subject), **Stimmung** (the caller's mood/sentiment),
  **Nächste Schritte** (next action).
- **Anfrage-Info** — created, source (KI-Telefonassistent), direction.

**Tab 3 — Verlauf (the "what happened" timeline):**
A vertical, color-dotted **audit timeline** of every action taken on this inquiry — call created, status
changed, appointment confirmed/rejected, alternative proposed, KVA sent/accepted/rejected, assignment
changed — each with a **relative timestamp** and an **actor chip** that visually separates *Kiki did X*
(green) from *an employee did X* (blue) from *system* (grey).

---

## 6. The semantic color system — preserve the *meaning*, restyle the *look*

This is the screen's most important asset. The redesign can change every pixel **but should keep these
meanings consistent** (and ideally *unify* them — today they're spread across borders, pills, dots, chips):

| Meaning | Today's encoding |
|---|---|
| Inbound vs outbound | green vs amber (border + icon) |
| Status: Offen / In Bearbeitung / Erledigt | blue / amber / green |
| Emergency | red, **blinking** (and only this blinks) |
| Priority high | red dot |
| Kiki vs employee vs system (history) | green / blue / grey chips |
| Unread | green left accent + bold |
| KVA / money flow (timeline) | purple |

---

## 7. Design goals for the improved version

- **Reduce density & cognitive load.** Three resizable panes packed with small text feels like a power-tool.
  Give it breathing room, clearer hierarchy, and a calmer default.
- **Unify the visual language.** Direction (borders), status (pills), priority (dots), emergency (badge) use
  different shapes/scales — a single, coherent token system makes a row instantly parseable.
- **Make a row scannable in < 1 second** — the eye should land on *who · what · status · who-owns-it ·
  how-urgent* without effort.
- **A custom, branded audio player** (explicit play / speed / download / scrubber), tied to the transcript sync.
- **Elevate the transcript** — it's the emotional core ("what Kiki said"); make it feel like a premium chat,
  with the live playback highlight as a hero interaction.
- **Strong empty / loading / error states**, and a clearer "nothing selected" state.
- **Responsive plan** — today it assumes a wide desktop; define what happens on narrow screens (e.g.,
  list → detail drill-down).
- **Stay consistent with the new dashboard** (green-primary brand, poster/Manrope aesthetic, dark-green rail,
  generous cards).

## 8. Constraints to respect (so it stays functional + on-brand)

- **German-only UI**, **light + dark mode** (build on CSS-var design tokens, never hardcoded colors).
- Keep the **three statuses**, the **inbound/outbound + emergency semantics**, the **inline employee-assign**,
  the **transcript↔audio sync**, the **3 right-pane tabs**, and the **deep-links**
  (the dashboard links here as `/calls?direction=inbound&status=open&tab=…`).
- Blinking/pulsing **stays reserved for emergencies only**.

---

## Appendix — current component & data map (for engineers)

**Files:** `frontend/src/pages/CallLogsPage.tsx` (~2,000 lines, the whole screen) ·
`frontend/src/pages/calls/AppointmentCard.tsx` (the OFFENE AKTIONEN pending-appointment card).

**Key in-file components:** `CallLogsPage` (3-pane shell + tabs + filters/search) · `CallListCard` (row) ·
`AktionenList` / `ActionListCard` · `NotdienstBadge` · `CallDetail` (right-pane shell) · `Transcript`
(center: summary + audio + chat) · `ActionsTab` / `ActionRow` · `DetailsTab` / `ContactCard` / `DetailRow` ·
`VerlaufTab` (timeline) · `ProcessRequestModal` / `CreateAppointmentModal`.

**Data endpoints:** `GET /api/calls` (list) · `GET /api/calls/:id` (detail) · `POST /api/calls/:id/inquiry` ·
`GET /api/calls/:id/audio` · `GET /api/calls/:id/timeline` · `GET /api/actions/pending` · `GET /api/employees` ·
`PATCH /api/inquiries/:id` (status/assign) · `POST /api/calls/:id/mark-read`.

**Live data tells (so mockups stay realistic):** a call carries `direction` (inbound/outbound),
`inquiry_status` (open/in_progress/completed), `emergency_flag`, `assigned_employee_initials`, a
`summary_title` (the one-liner), and a `data_collection` bag with `customer_sentiment` (mood),
`next_action`, `issue_summary`, `customer_address`, etc.
