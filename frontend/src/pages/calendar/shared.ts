// Shared types + helpers for the admin team calendar (Spuren lanes, week/month
// circles, and the "Jetzt verfügbar" rail). All times are handled as Date in the
// browser's local zone (the app runs in Europe/Berlin); display goes through
// lib/datetime where a string is needed.

export interface Appointment {
  id: string
  title: string | null
  scheduled_at: string | null
  duration_minutes: number | null
  status: string
  category: string | null
  source: string | null // 'crm' | 'google_import' | 'employee_busy' | 'ics'
  google_event_id: string | null
  color: string | null
  location: { raw?: string } | string | null
  notes: string | null
  customer_id: string | null
  assigned_employee_id: string | null
  customer_name: string | null
  customer_phone: string | null
  customer_address: string | null
  employee_name: string | null
}

export interface CalEmployee {
  id: string
  display_name: string
  is_active?: boolean
  is_technician?: boolean
  calendar_color?: string | null
  activity_area?: string | null
  open_tickets?: number
  present?: boolean
  absence_type?: string | null
}

export interface Absence {
  id: string
  employee_id: string
  employee_name?: string | null
  type: string // vacation | illness | training | home_office | other | block
  starts_at: string
  ends_at: string
  all_day?: boolean
  status?: string // only 'approved' counts as busy
}

export const EMP_COLORS = ['#2D6B3D', '#2563EB', '#7C3AED', '#DB2777', '#D97706', '#0891B2', '#65A30D']
export const UNASSIGNED_COLOR = '#78756F'
export const GOOGLE_BLOCK_COLOR = '#64748B'

// External "busy" rows that block a person but are NOT real CRM appointments.
export const BUSY_SOURCES = new Set(['google_import', 'employee_busy'])

export function initials(name?: string | null): string {
  if (!name) return '–'
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '–'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

// Stable per-employee colour: the employee's own calendar_color when set, else a
// palette colour by roster position (so colours don't reshuffle on every render).
export function buildColorMap(emps: CalEmployee[]): (id: string | null) => string {
  const map = new Map<string, string>()
  emps.forEach((e, i) => map.set(e.id, e.calendar_color || EMP_COLORS[i % EMP_COLORS.length]))
  return (id: string | null) => (id && map.get(id)) || UNASSIGNED_COLOR
}

export type BusyReason = 'termin' | 'gebucht' | 'blockiert' | 'urlaub' | null

export const BUSY_LABEL: Record<Exclude<BusyReason, null>, string> = {
  termin: 'Termin',
  gebucht: 'Gebucht',
  blockiert: 'Blockiert',
  urlaub: 'Abwesend',
}

function apptInterval(a: Appointment): [number, number] | null {
  if (!a.scheduled_at) return null
  const s = new Date(a.scheduled_at).getTime()
  return [s, s + (a.duration_minutes ?? 60) * 60000]
}

// Why an employee is busy at `at`, or null when free. Checks approved absences
// (block → 'blockiert', else 'urlaub') and overlapping appointments (external
// busy → 'gebucht', else a real 'termin'). Mirrors the backend availability engine.
export function busyReasonAt(
  empId: string,
  at: Date,
  appts: Appointment[],
  absences: Absence[],
): BusyReason {
  const t = at.getTime()
  for (const ab of absences) {
    if (ab.employee_id !== empId || (ab.status && ab.status !== 'approved')) continue
    if (new Date(ab.starts_at).getTime() <= t && t <= new Date(ab.ends_at).getTime()) {
      return ab.type === 'block' ? 'blockiert' : 'urlaub'
    }
  }
  for (const a of appts) {
    if (a.assigned_employee_id !== empId || a.status === 'cancelled') continue
    const iv = apptInterval(a)
    if (!iv) continue
    if (iv[0] <= t && t < iv[1]) return BUSY_SOURCES.has(a.source ?? '') ? 'gebucht' : 'termin'
  }
  return null
}

export function sameLocalDay(iso: string, day: Date): boolean {
  const d = new Date(iso)
  return (
    d.getFullYear() === day.getFullYear() &&
    d.getMonth() === day.getMonth() &&
    d.getDate() === day.getDate()
  )
}
