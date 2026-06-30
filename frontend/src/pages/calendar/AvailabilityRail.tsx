import { useMemo } from 'react'

import { cn } from '../../lib/utils'
import {
  type Absence,
  type Appointment,
  type BusyReason,
  type CalEmployee,
  busyReasonAt,
  initials,
} from './shared'

// The always-on "Jetzt verfügbar" rail: every active employee, sorted free-first
// then fewest open tickets, with what they do and why they're busy right now.
// Same three signals as the assignment engine, read at a glance.

const DOT: Record<'free' | 'busy' | 'away', string> = {
  free: 'bg-success',
  busy: 'bg-error',
  away: 'bg-muted',
}

function tone(reason: BusyReason): { dot: string; label: string; text: string } {
  if (reason === null) return { dot: DOT.free, label: 'frei', text: 'text-success' }
  if (reason === 'urlaub') return { dot: DOT.away, label: 'Abwesend', text: 'text-muted' }
  if (reason === 'blockiert') return { dot: 'bg-warning', label: 'Blockiert', text: 'text-muted' }
  if (reason === 'gebucht') return { dot: DOT.busy, label: 'Gebucht', text: 'text-muted' }
  return { dot: DOT.busy, label: 'Termin', text: 'text-muted' }
}

export function AvailabilityRail({
  employees,
  appointments,
  absences,
  colorFor,
  at,
  onSelect,
  activeId,
}: {
  employees: CalEmployee[]
  appointments: Appointment[]
  absences: Absence[]
  colorFor: (id: string | null) => string
  at: Date
  /** Click a person to filter the calendar to them (toggles off if already active). */
  onSelect?: (id: string) => void
  /** The currently-filtered employee id (highlights that row). */
  activeId?: string
}) {
  const rows = useMemo(() => {
    return employees
      .filter((e) => e.is_active !== false)
      .map((e) => ({ e, reason: busyReasonAt(e.id, at, appointments, absences) }))
      .sort((a, b) => {
        const af = a.reason === null ? 0 : 1
        const bf = b.reason === null ? 0 : 1
        if (af !== bf) return af - bf
        const ao = a.e.open_tickets ?? 0
        const bo = b.e.open_tickets ?? 0
        if (ao !== bo) return ao - bo
        return (a.e.display_name || '').localeCompare(b.e.display_name || '')
      })
  }, [employees, appointments, absences, at])

  const freeCount = rows.filter((r) => r.reason === null).length

  return (
    <aside className="flex w-64 shrink-0 flex-col overflow-hidden rounded-xl border border-border bg-surface">
      <div className="border-b border-border px-4 py-3">
        <div className="text-sm font-bold text-text">Jetzt verfügbar</div>
        <div className="mt-0.5 text-xs text-muted">
          {at.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })} Uhr ·{' '}
          {freeCount} von {rows.length} frei
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {rows.length === 0 ? (
          <p className="px-4 py-6 text-sm text-muted">Keine Mitarbeiter angelegt.</p>
        ) : (
          rows.map(({ e, reason }) => {
            const t = tone(reason)
            return (
              <button
                key={e.id}
                type="button"
                onClick={() => onSelect?.(e.id)}
                title={`Kalender auf ${e.display_name} filtern`}
                className={cn(
                  'flex w-full items-center gap-2.5 border-b border-border-faint px-3 py-2.5 text-left transition-colors last:border-0 hover:bg-alt',
                  activeId === e.id && 'bg-green-tint-100',
                )}
              >
                <span
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white"
                  style={{ background: colorFor(e.id) }}
                >
                  {initials(e.display_name)}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-text">{e.display_name}</div>
                  {e.activity_area && (
                    <div className="truncate text-xs text-muted">{e.activity_area}</div>
                  )}
                </div>
                <div className="flex flex-col items-end gap-0.5">
                  <span className={cn('flex items-center gap-1.5 text-xs font-medium', t.text)}>
                    <span className={cn('h-2 w-2 rounded-full', t.dot)} /> {t.label}
                  </span>
                  <span className="text-[11px] text-muted">{e.open_tickets ?? 0} offen</span>
                </div>
              </button>
            )
          })
        )}
      </div>
    </aside>
  )
}
