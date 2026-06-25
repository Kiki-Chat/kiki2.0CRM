// Shared types, constants, and pure helpers for the Call Logs screen.
// Extracted verbatim from the original CallLogsPage so behavior is identical;
// the redesign only changes presentation (see ./atoms, ./Inbox, ./Transcript,
// ./Workspace) — never the data shapes or the wiring.

export interface TranscriptTurn {
  role: string
  message: string | null
  time_in_call_secs?: number | null
  tool_calls: (string | null)[]
}

export interface CallListItem {
  id: string
  elevenlabs_conversation_id: string | null
  caller_number: string | null
  summary_title: string | null
  direction: string | null
  duration_seconds: number | null
  started_at: string | null
  // phantom_capture: backend post-call detector — the agent claimed the concern
  // was recorded but no write tool ran; the badge tells staff to re-check.
  data_collection: (Record<string, string> & { phantom_capture?: boolean; next_steps?: string[] }) | null
  customer_id: string | null
  read_at: string | null
  created_at: string | null
  customers: { full_name: string | null } | null
  inquiry_id: string | null
  inquiry_status: 'open' | 'in_progress' | 'completed' | null
  inquiry_number: string | null
  inquiry_subject: string | null
  case_id: string | null
  case_number: string | null
  case_label: string | null
  // Projects merge (item 6): the chip links to the inquiry's Projekt.
  project_id: string | null
  project_number: string | null
  project_title: string | null
  emergency_flag: boolean
  assigned_employee_id: string | null
  assigned_employee_initials: string | null
}

// Our-AI-over-transcript output (calls.enrichment, migration 0077). Best-effort:
// null when AI is disabled or the pass hasn't run — callers fall back to `summary`.
export interface CallEnrichment {
  version?: number
  generated_at?: string
  summary_bullets: string[]
  // 0-3 short imperative German follow-up steps (own compartment under the summary).
  next_steps?: string[]
  intent: {
    wants_kva: boolean
    wants_invoice: boolean
    wants_appointment: boolean
  }
  prefill: {
    service_description: string | null
    address: string | null
    problem: string | null
    preferred_time: string | null
  }
}

export interface CallDetailData extends CallListItem {
  summary: string | null
  transcript: TranscriptTurn[] | null
  enrichment: CallEnrichment | null
  customers: {
    full_name: string | null
    phone: string | null
    email: string | null
    customer_number: string | null
  } | null
}

export interface Inquiry {
  id: string
  number: string | null
  subject: string | null
  title: string | null
  type: string | null
  status: string
  notes: string | null
  assigned_employee_id: string | null
}

export interface Employee {
  id: string
  display_name: string | null
  is_technician?: boolean
}

export interface ActionItem {
  kind:
    | 'termin_anfrage'
    | 'kva_suggested'
    | 'kva_to_send'
    | 'kva_pending_acceptance'
    | 'invoice_suggested'
    | 'invoice_to_send'
    | 'invoice_pending_payment'
    | 'callback_owed'
    | 'alt_time_proposal'
    | 'appointment_cancelled'
  id: string
  inquiry_id: string | null
  call_id: string | null
  customer_name: string | null
  customer_id: string | null
  summary: string
  created_at: string | null
  due_at: string | null
  priority: 'normal' | 'high'
  // alt_time_proposal only: 'customer' = customer counter-proposal (approvable in one
  // click via the reschedule popup); 'team' = we sent an alternative, awaiting reply.
  proposal_role?: 'customer' | 'team' | null
  // Reschedule context (alt_time_proposal / customer): the current slot, the
  // safety-timer deadline (UI flags overdue), and whether the customer abandoned
  // the old slot (true) or keeps it as a fallback.
  original_time?: string | null
  expires_at?: string | null
  replace_intent?: boolean | null
  // To-do state overlaid from action_tasks (claim / done / delete).
  action_key: string
  state: 'open' | 'claimed' | 'done'
  claimed_by_name: string | null
  done_at_task: string | null
}

export type ActionTaskStatus = 'open' | 'claimed' | 'done' | 'dismissed'

export type TimelineEventKind =
  | 'call_created'
  | 'inquiry_status_changed'
  | 'appointment_confirmed'
  | 'appointment_rejected'
  | 'alternative_proposed'
  | 'kva_sent'
  | 'kva_accepted'
  | 'kva_rejected'
  | 'assignment_changed'
  | 'appointment_created'
  | 'appointment_rescheduled'
  | 'appointment_cancelled'

export interface TimelineEvent {
  id: string
  kind: TimelineEventKind
  timestamp: string
  actor_kind: 'kiki' | 'employee' | 'system'
  actor_name: string
  description: string
  entity_id: string | null
  extras: Record<string, unknown>
}

// Right-pane status tag config + the edit-modal category/color choices.
export const STATUS_TAG: Record<string, { label: string; variant: 'info' | 'warning' | 'success' | 'neutral' }> = {
  open: { label: 'Offen', variant: 'info' },
  in_progress: { label: 'In Bearbeitung', variant: 'warning' },
  completed: { label: 'Abgeschlossen', variant: 'success' },
  deleted: { label: 'Gelöscht', variant: 'neutral' },
}
export const CATEGORIES = ['appointment', 'offer', 'info', 'recall']
export const COLORS = ['#2D6B3D', '#2563EB', '#7C3AED', '#DB2777', '#D97706', '#2D9D5C', '#78756F']

// German chip labels per Aktionen-kind. Lives on the client so the wire format
// stays language-neutral.
export const ACTION_KIND_LABEL: Record<ActionItem['kind'], string> = {
  termin_anfrage: 'Terminbestätigung',
  kva_suggested: 'Angebot erstellen',
  kva_to_send: 'Angebot senden',
  kva_pending_acceptance: 'Angebot-Antwort offen',
  invoice_suggested: 'Rechnung erstellen',
  invoice_to_send: 'Rechnung senden',
  invoice_pending_payment: 'Zahlung offen',
  callback_owed: 'Rückruf',
  alt_time_proposal: 'Alternativtermin',
  appointment_cancelled: 'Termin storniert',
}

// Filter types (left inbox) — direction + status + the NEW date filter, all client-side.
export type DirFilter = 'all' | 'inbound' | 'outbound'
export type StatusFilter = 'all' | 'open' | 'in_progress' | 'completed'
export type DateFilter = 'all' | 'today' | '7d' | '30d' | 'custom'
export interface InboxFilters {
  dir: DirFilter
  status: StatusFilter
  date: DateFilter
  from: string
  to: string
}

// Six employee-avatar color pairs (Tailwind), hashed by employee_id so the same
// person is always the same color. Unchanged from the original.
export const EMPLOYEE_AVATAR_PALETTE: { bg: string; text: string }[] = [
  { bg: 'bg-blue-100', text: 'text-blue-800' },
  { bg: 'bg-amber-100', text: 'text-amber-800' },
  { bg: 'bg-purple-100', text: 'text-purple-800' },
  { bg: 'bg-pink-100', text: 'text-pink-800' },
  { bg: 'bg-cyan-100', text: 'text-cyan-800' },
  { bg: 'bg-teal-100', text: 'text-teal-800' },
]

export function avatarColorForEmployee(employeeId: string | null): { bg: string; text: string } {
  if (!employeeId) return { bg: 'bg-alt', text: 'text-faint' }
  let hash = 0
  for (let i = 0; i < employeeId.length; i++) {
    hash = (hash * 33 + employeeId.charCodeAt(i)) >>> 0
  }
  return EMPLOYEE_AVATAR_PALETTE[hash % EMPLOYEE_AVATAR_PALETTE.length]
}

export const fmtDuration = (s: number | null) =>
  s || s === 0 ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}` : '—'

// Spelled-out duration — "2 Min 45 Sek" / "45 Sek" / "2 Min" (Luca: the bare "m"
// abbreviation read as ambiguous; the call-log column shows the words in full).
export const fmtDurationLong = (s: number | null) => {
  if (s == null) return '—'
  const m = Math.floor(s / 60)
  const sec = s % 60
  if (m === 0) return `${sec} Sek`
  if (sec === 0) return `${m} Min`
  return `${m} Min ${sec} Sek`
}

// Date/time formatters live in lib/datetime (pinned to Europe/Berlin so times don't
// render in the viewer's browser tz). Re-exported here so the many call-log modules
// that import them from './shared' keep working unchanged.
export { fmtTime, fmtClock, fmtClockUhr, relativeTimeDe, absoluteTimeDe } from '../../lib/datetime'

export const isMeaningful = (v?: string | null) =>
  !!v && !['unbekannt', 'keiner', 'anonymous'].includes(v.toLowerCase())

// The caller's real name (customer record → AI-collected name), or null when the
// call is from an unidentified number. Shared by displayName (which falls back to the
// number) and the call-log title (which shows "Unbekannte Nummer" instead).
export function resolvedCustomerName(c: CallListItem): string | null {
  return (
    (isMeaningful(c.customers?.full_name) && c.customers!.full_name!) ||
    (isMeaningful(c.data_collection?.customer_name) && c.data_collection!.customer_name!) ||
    null
  )
}

export function displayName(c: CallListItem): string {
  return resolvedCustomerName(c) || (isMeaningful(c.caller_number) && c.caller_number!) || 'Unbekannt'
}

// Client-side date-filter predicate over a call's started_at/created_at.
export function matchesDateFilter(c: CallListItem, f: InboxFilters): boolean {
  if (f.date === 'all') return true
  const iso = c.started_at || c.created_at
  if (!iso) return false
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return false
  if (f.date === 'custom') {
    const from = f.from ? new Date(f.from).setHours(0, 0, 0, 0) : -Infinity
    const to = f.to ? new Date(f.to).setHours(23, 59, 59, 999) : Infinity
    return t >= from && t <= to
  }
  const days = f.date === 'today' ? 1 : f.date === '7d' ? 7 : 30
  const since = Date.now() - days * 24 * 60 * 60 * 1000
  return t >= since
}

// relativeTimeDe / absoluteTimeDe now live in lib/datetime (Berlin-pinned) and are
// re-exported at the top of this file.
