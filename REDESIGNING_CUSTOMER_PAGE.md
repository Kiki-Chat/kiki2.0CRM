# Redesigning the Customer Page — 360° view of one customer

> Status: **PLAN, not built.** Captured 2026-06-27. Build *after* the Vorgang ticket
> engine (phase 2: auto-grouping + merge suggestions + aggregate titling) lands.

## Problem
The customer detail page and the global **Vorgänge** nav menu feel redundant — both
render Vorgang cards with a journey/timeline, so it reads as "the same thing twice."
Plus noise on the customer page: a date section that doesn't belong, and a "Right now"
mislabel.

## Decision: keep both menus, give each ONE job; stop duplicating the journey
- **Vorgänge (nav menu)** = cross-customer **work queue** — all open tickets, filter by
  status/employee. *Not* customer-scoped. Where staff work the backlog.
- **Customer page** = **360° view of ONE customer** — contact info + *that customer's*
  tickets. The customer is the unifying filter.
- **Vorgang detail page** = the single ticket's **full journey** (calls, timeline/
  Verlauf, appointments, offers, invoices). The journey lives **here only**.

These are not actually redundant (all-tickets vs. one-customer's-tickets); the bug was
showing the *journey* in both places.

## Customer-page cleanup
1. **Vorgang cards = compact**, not a mini-timeline: headline (German title) · status ·
   #calls · last activity · one-line **`ai_summary`** (the field added in migration
   `0085` — "what's going on"). Full journey is one click away on the Vorgang detail.
2. **Remove the date section** (noise; dates belong on the ticket timeline).
3. **Keep "Verlauf"/timeline only inside the Vorgang detail.**
4. **Wording:** "Right now" → "Vorgang". Keep "Angebot erstellen" (must land in the
   right Vorgang).
5. **Demote the manual "KI-Gruppierung" button.** Once automatic LLM grouping +
   merge-suggestions (phase 2) are live, grouping is automatic and corrections surface
   in the Posteingang. The button becomes a rarely-used "alles neu gruppieren" fallback
   — move it out of the primary spot.

## Net
- Customer page = clean list of *that customer's* tickets (headline + status + summary).
- Vorgang page = the deep journey.
- Vorgänge menu = the global queue.
- One journey, shown once, in the right place.

## Implementation notes (when building)
- `frontend/src/pages/CustomerDetailPage.tsx`: map the current "Anfragen (N)" section,
  the date block, the "Right now"/"Vorgang" label, and the KI-Gruppierung button.
  Replace the grouped-Anfragen rendering with compact Vorgang cards (title + `ai_summary`
  + counts).
- Reuse the **same Vorgang card component** as the Vorgänge nav list (`CaseList.tsx`)
  for consistency; click → Vorgang detail.
- `ai_summary` needs to flow through the customer endpoint: `backend/app/api/routes/
  customers.py` (~line 273, where each case is serialized with `label`/`title`) should
  also return `ai_summary`.
