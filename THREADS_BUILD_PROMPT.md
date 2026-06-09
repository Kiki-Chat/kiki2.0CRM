# Build Prompt — "Vorgang" (Case) Threading for KikiJarvis

> Hand this to a build session. It is the spec for tying every activity about one
> matter into a single thread with a case number. Grounded in how Salesforce / Zendesk
> / ServiceNow / Dynamics model cases. **Decisions flagged `[DECIDE]` need Amber's call.**

## Goal
Introduce a **Vorgang (case)** layer so every *matter* for a customer is ONE thread:
the inbound intake call + all follow-up outbound calls (confirmation / reschedule /
cancellation) + the inquiry + appointment(s) + KVA(s) + emails + documents are tied
under one human-readable **case number**. A customer can have several concurrent cases
(e.g. plumbing, heating, gardening) — each is its own clean thread.

## Business rules (the "why")
1. One customer ⇒ many matters ⇒ many cases. Multiple open cases per customer is normal and must stay cleanly separated.
2. **Outbound** follow-up calls belong to the case that triggered them — never an orphan/new record.
3. The "good, talk—" early-hangup confirmation must stay attached to its case AND raise a human follow-up (don't silently rely on the email).
4. Ambiguous matters ("heating bathroom" vs "heating bedroom") **cannot be auto-disambiguated reliably** → default to a NEW case and give staff **Link / Merge** tools (industry standard).
5. **Outbound** call screens must NOT offer intake actions (create appointment / KVA / change customer) — those belong to the **inbound** intake call.
6. A recurring same problem months later must be reachable from the old case (history).

## Data model
Anchor the case on the existing `inquiries` table (it already carries a number) — elevate it to the Vorgang:
- `inquiries.case_number` — `VG-<year>-<NNNN>` per org, the id read out on the phone. `[DECIDE: reuse existing ANF-… vs new VG-… — RECOMMEND new VG-]`
- `inquiries.subject` (short topic, e.g. "Heizung Badezimmer") + `status` lifecycle (`open|in_progress|waiting|resolved|closed`).
- Carry the case id on every related record:
  - `calls.inquiry_id` — the call's case. Inbound intake creates/links it; outbound inherits it. **(This is the key gap today — calls aren't reliably linked, which is why action buttons are dead.)**
  - `appointments.inquiry_id` (exists — ensure ALWAYS set, incl. agent bookings).
  - `cost_estimates.inquiry_id` (exists). Emails/documents → inquiry_id.
- New `case_links(org_id, case_id, related_case_id, relation:'related'|'duplicate', created_by)` for relating distinct cases. **Merge** = move a child's activities to the parent + mark duplicate; **Link** = keep separate but show "related".

## Threading rules (how a call gets its case)
1. **Outbound** (Kiki → customer, triggered by an appointment/case event): ALWAYS inherit the triggering case's `inquiry_id`, stamped at initiation. *(Deterministic — fixes scattered outbound + the `call_id✗` dead buttons.)*
2. **Transfer-to-agent mid-outbound** (confirm → "actually, reschedule"): continue on the SAME case. New matter raised mid-call → open a new **linked** case.
3. **Inbound**: `[DECIDE: simple vs smart]`
   - **SIMPLE (recommended first):** every inbound opens a NEW case; staff Link/Merge later. Surface "possible related open cases" (same customer + fuzzy subject) as a suggestion.
   - **SMART (later phase):** the agent looks up the customer's open cases and asks "Is this about your heating appointment on the 14th?" → attaches to the match.
4. **Recurring problem after a gap:** matched case closed & recent → reopen; old → new case **linked** to the original.

## Cut-off confirmation detection
On an **outbound** confirmation/reschedule call: if duration < ~20s OR no confirmation outcome captured → raise a case Aktion **"Bestätigung nicht abgeschlossen — nachfassen"** (high priority).

## UI
- **Customer page → list of Vorgänge** (cards: `VG-number` · subject · status · last activity · open-Aktionen count).
- **Vorgang detail → one thread:** chronological timeline of every inbound + outbound call (labelled in/out), appointment(s), KVA(s), email(s), document(s); the case's open Aktionen; Link/Merge controls.
- **Call detail:** shows the case it belongs to (`VG-number`, clickable). **Outbound** → minimal outcome panel (Bestätigt / Verschoben / Abgelehnt / Abgebrochen / Nicht erreicht), NOT intake actions. **Inbound** → full intake.
- **Aktionen tab** (already a to-do list): scope/group by case so it shows current cases needing attention, not a flat list.

## Phasing
1. **Foundation** (fixes dead buttons): `calls.inquiry_id` always set; outbound inherits the triggering case; backfill where resolvable; surface the case number.
2. **Case thread UI:** customer→cases list + case→thread view.
3. **Outbound-vs-inbound action sets** + cut-off detection.
4. **Link/Merge tools** + smart inbound matching.

## Acceptance criteria
- confirm → outbound → reschedule (transfer) shows as ONE case thread with both calls.
- A customer with 3 matters shows 3 separate cases, each its own thread.
- Every Aktion opens its case (no dead buttons).
- An early-hangup confirmation raises a "nachfassen" Aktion on the case.
- Outbound call screens don't offer create-appointment / KVA / change-customer.

## KikiJarvis constraints (must honour)
- Migrations additive, applied via Supabase MCP. German-only UI. Backend stores UTC; **display Europe/Berlin** via `frontend/src/lib/datetime`. **Outbound is LIVE in prod** (`OUTBOUND_TEST_SCOPE_ONLY=0`) — anything triggering calls reaches REAL customers; test against `kiki-test-007` / the TobiasDachdecker test org, or flip the guard first. Supabase client is HTTP/1.1 (concurrent-safe — keep it). Gate: `tsc -b` + `npm run build` clean, backend pytest (6 pre-existing reds baseline, no new), live preview render proof, verify the ACTUAL Railway deploy (`deployment list` SUCCESS, not the CLI "complete").
