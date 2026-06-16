// Pure helpers + types for the Anrufe call-log (the read-only call stream that
// replaced the old 3-pane cockpit). No data fetching / no JSX here — everything is
// derived from a CallListItem so the page, the row, and the drawer share one source
// of truth for filtering, case-linking, and date bucketing.
import { BERLIN_TZ } from '../../../lib/datetime'
import { displayName, resolvedCustomerName, type CallListItem } from '../shared'

// ─── Filter model ──────────────────────────────────────────────────────────
// The four "direction" pills fold emergency in as a fourth option (Notdienst),
// because that's how the design book presents them (Alle/Eingehend/Ausgehend/Notdienst).
export type DirPill = 'all' | 'inbound' | 'outbound' | 'emergency'
// Status combines the case workflow status (open/in_progress/completed) with the
// org-level read flag ('unread' = "Neu"), so the dropdown reads Alle/Neu/Offen/In
// Bearbeitung/Erledigt — and the dashboard's ?status=open deep-link still resolves.
export type StatusF = 'all' | 'unread' | 'open' | 'in_progress' | 'completed'
export type DateF = 'all' | 'today' | '7d' | '30d' | 'custom'
// employeeId: 'all' | 'none' (= Niemand/unassigned) | <employee uuid>
export interface LogFilters {
  dir: DirPill
  status: StatusF
  employeeId: string
  date: DateF
  from: string
  to: string
  hideShort: boolean
}

export const DEFAULT_FILTERS: LogFilters = {
  dir: 'all',
  status: 'all',
  employeeId: 'all',
  date: 'all',
  from: '',
  to: '',
  hideShort: false,
}

// Calls shorter than this are hang-ups / mis-dials / test calls — the "Kurze Anrufe
// ausblenden" toggle hides them (HalloPetra's "Kurze Anrufe anzeigen", inverted).
export const SHORT_CALL_SECONDS = 15

// Count of non-default secondary filters (search + direction pills excluded — they
// have their own affordances). Drives the "Filter" reset chip / count badge.
export function activeSecondaryCount(f: LogFilters): number {
  return (
    (f.status !== 'all' ? 1 : 0) +
    (f.employeeId !== 'all' ? 1 : 0) +
    (f.date !== 'all' ? 1 : 0) +
    (f.hideShort ? 1 : 0)
  )
}

// ─── Case + Project linking (post-0073 hierarchy) ────────────────────────────
// Call → Anfrage (ANF-, inquiry_id) → Fall (FL-, case_id) → Projekt (PR-, project_id,
// optional top container). The primary row chip is the Fall (the call's grouping);
// when no Fall yet, it falls back to the Anfrage. The Projekt is a secondary badge
// shown only when the Fall rolls up into one (usually null).
export interface CaseLink {
  to: string
  kind: 'fall' | 'vorgang'
  number: string | null
  title: string | null
}

export function caseLink(c: CallListItem): CaseLink | null {
  if (c.case_id) return { to: `/fall/${c.case_id}`, kind: 'fall', number: c.case_number, title: c.case_label }
  if (c.inquiry_id) return { to: `/vorgang/${c.inquiry_id}`, kind: 'vorgang', number: c.inquiry_number, title: c.inquiry_subject }
  return null
}

export interface ProjectLink {
  to: string
  number: string | null
  title: string | null
}

export function projectLink(c: CallListItem): ProjectLink | null {
  if (c.project_id) return { to: `/projects/${c.project_id}`, number: c.project_number, title: c.project_title }
  return null
}

export const hasCase = (c: CallListItem): boolean => !!(c.inquiry_id || c.case_id)

// Pinned "Braucht Aufmerksamkeit" section = calls with no case yet OR an active
// emergency (Amber's choice: urgent ones never get buried below the day groups).
export const needsAttention = (c: CallListItem): boolean => !hasCase(c) || c.emergency_flag

// Row/drawer title: the caller's real name when we have one, else "Unbekannte
// Nummer" (the number itself still shows on the subline, so we don't repeat it).
export function callerTitle(c: CallListItem): string {
  return resolvedCustomerName(c) || 'Unbekannte Nummer'
}

// The single per-call sentiment signal (dynamic per-org AI field; may be absent).
export const sentimentOf = (c: CallListItem): string | null => {
  const s = c.data_collection?.customer_sentiment
  return s && s.trim() ? s : null
}

// ─── Filtering ────────────────────────────────────────────────────────────
// All date logic runs on Berlin calendar days (via berlinDayKey/dayDiff below), so
// the filter agrees with the day-group buckets and the project-wide Europe/Berlin rule
// — never the viewer's local timezone. `nowMs` is the single render-stable baseline.
function matchesDate(c: CallListItem, f: LogFilters, nowMs: number): boolean {
  if (f.date === 'all') return true
  const iso = c.started_at || c.created_at
  if (!iso) return false
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return false
  const ck = berlinDayKey(t)
  if (f.date === 'custom') {
    if (f.from && ck < f.from) return false
    if (f.to && ck > f.to) return false
    return true
  }
  // today / last-7 / last-30 as inclusive Berlin calendar-day spans (matches bucketOf).
  const span = f.date === 'today' ? 0 : f.date === '7d' ? 6 : 29
  const d = dayDiff(ck, berlinDayKey(nowMs))
  return d >= 0 && d <= span
}

export function callMatches(c: CallListItem, f: LogFilters, q: string, nowMs: number): boolean {
  if (f.dir === 'inbound' && c.direction !== 'inbound') return false
  if (f.dir === 'outbound' && c.direction !== 'outbound') return false
  if (f.dir === 'emergency' && !c.emergency_flag) return false

  if (f.status === 'unread' && c.read_at !== null) return false
  if (f.status === 'open' && c.inquiry_status !== 'open') return false
  if (f.status === 'in_progress' && c.inquiry_status !== 'in_progress') return false
  if (f.status === 'completed' && c.inquiry_status !== 'completed') return false

  if (f.employeeId === 'none' && c.assigned_employee_id) return false
  if (f.employeeId !== 'all' && f.employeeId !== 'none' && c.assigned_employee_id !== f.employeeId) return false

  if (f.hideShort && (c.duration_seconds ?? 0) < SHORT_CALL_SECONDS) return false
  if (!matchesDate(c, f, nowMs)) return false

  if (q) {
    const hay = `${displayName(c)} ${c.summary_title ?? ''} ${c.caller_number ?? ''}`.toLowerCase()
    if (!hay.includes(q)) return false
  }
  return true
}

// ─── Chronological day grouping (Berlin calendar days) ──────────────────────
// "YYYY-MM-DD" of a timestamp as seen on a Berlin wall clock (en-CA gives ISO order).
const berlinDayKey = (ms: number): string =>
  new Intl.DateTimeFormat('en-CA', { timeZone: BERLIN_TZ, year: 'numeric', month: '2-digit', day: '2-digit' }).format(
    new Date(ms),
  )

// Whole-day distance between two Berlin day keys (parsed as UTC midnights so the
// fixed offset cancels out). Positive when `from` is before `to`.
const dayDiff = (fromKey: string, toKey: string): number =>
  Math.round((Date.parse(`${toKey}T00:00:00Z`) - Date.parse(`${fromKey}T00:00:00Z`)) / 86400000)

// Stable Berlin day key used to group rows under one date divider.
export const dayKeyOf = (iso: string | null): string => (iso ? berlinDayKey(Date.parse(iso)) : 'unknown')

// Full weekday + date for the table's Datum column — always the long
// "Sonntag, 14. Juni" form, Berlin-pinned. Distinct from dayDividerLabel, which
// collapses recent days to Heute / Gestern for the section header.
export function fmtDayDate(iso: string | null): string {
  if (!iso) return '—'
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return '—'
  return new Date(t).toLocaleDateString('de-DE', { weekday: 'long', day: 'numeric', month: 'long', timeZone: BERLIN_TZ })
}

// Divider label for a day: Heute / Gestern / "Mittwoch, 4. Juni".
export function dayDividerLabel(iso: string | null, nowMs: number): string {
  if (!iso) return 'Ohne Datum'
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return 'Ohne Datum'
  const d = dayDiff(berlinDayKey(t), berlinDayKey(nowMs))
  if (d <= 0) return 'Heute'
  if (d === 1) return 'Gestern'
  return new Date(t).toLocaleDateString('de-DE', { weekday: 'long', day: 'numeric', month: 'long', timeZone: BERLIN_TZ })
}

// ─── Subject emoji (keyword → emoji; emergency always wins) ─────────────────
const EMOJI_RULES: [RegExp, string][] = [
  [/wartung|service|inspekt|maintenance/i, '🛠️'],
  [/heiz|therme|warm|kalt|boiler|radiator/i, '🔥'],
  [/wasser|rohr|leck|tropf|sanitär|\bbad\b|dusche|abfluss|verstopf|pipe|plumb|leak|burst|flow/i, '🚿'],
  [/strom|elektr|electr|sicherung/i, '⚡'],
  [/dach|roof|ziegel/i, '🏠'],
  [/angebot|kostenvoranschlag|\bkva\b|preis|quote|offer/i, '💰'],
  [/rechnung|invoice|zahlung|payment/i, '🧾'],
  [/storno|absage|cancel|kündig/i, '❌'],
  [/reschedul|verschieb|umbuch/i, '🔄'],
  [/termin|appointment|bestätig|confirm|booking/i, '📅'],
  [/rückruf|callback|melde|nachricht|voicemail/i, '💬'],
  [/werbung|spam|akquise/i, '🚫'],
]

export function subjectEmoji(c: CallListItem): string {
  if (c.emergency_flag) return '🚨'
  const s = `${c.summary_title ?? ''} ${c.inquiry_subject ?? ''}`.toLowerCase()
  for (const [re, e] of EMOJI_RULES) if (re.test(s)) return e
  return '📞'
}
