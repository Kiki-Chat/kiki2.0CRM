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
  data_collection: Record<string, string> | null
  customer_id: string | null
  read_at: string | null
  created_at: string | null
  customers: { full_name: string | null } | null
  inquiry_id: string | null
  inquiry_status: 'open' | 'in_progress' | 'completed' | null
  emergency_flag: boolean
  assigned_employee_id: string | null
  assigned_employee_initials: string | null
}

export interface CallDetailData extends CallListItem {
  summary: string | null
  transcript: TranscriptTurn[] | null
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
    | 'kva_to_send'
    | 'kva_pending_acceptance'
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
  kva_to_send: 'KVA senden',
  kva_pending_acceptance: 'KVA-Antwort offen',
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

// Date/time formatters live in lib/datetime (pinned to Europe/Berlin so times don't
// render in the viewer's browser tz). Re-exported here so the many call-log modules
// that import them from './shared' keep working unchanged.
export { fmtTime, relativeTimeDe, absoluteTimeDe } from '../../lib/datetime'

export const isMeaningful = (v?: string | null) =>
  !!v && !['unbekannt', 'keiner', 'anonymous'].includes(v.toLowerCase())

export function displayName(c: CallListItem): string {
  return (
    (isMeaningful(c.customers?.full_name) && c.customers!.full_name!) ||
    (isMeaningful(c.data_collection?.customer_name) && c.data_collection!.customer_name!) ||
    (isMeaningful(c.caller_number) && c.caller_number!) ||
    'Unbekannt'
  )
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
