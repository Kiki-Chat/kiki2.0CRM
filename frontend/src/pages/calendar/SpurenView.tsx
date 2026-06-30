import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { cn } from '../../lib/utils'
import {
  type Absence,
  type Appointment,
  type CalEmployee,
  BUSY_SOURCES,
  GOOGLE_BLOCK_COLOR,
  initials,
  sameLocalDay,
} from './shared'

// One column per employee, so a busy time slot never crowds. Lightweight custom
// grid (FullCalendar resource views are a paid tier) — exactly the approved
// "Spuren" mockup.

const DAY_START_H = 7
const DAY_END_H = 19
const PX_PER_H = 46
const TOTAL_H = (DAY_END_H - DAY_START_H) * PX_PER_H

interface Block {
  key: string
  top: number
  height: number
  kind: 'termin' | 'gebucht' | 'absence' | 'block'
  color?: string
  label: string
  sub?: string
  appt?: Appointment
}

function topFor(ms: number, dayStartMs: number): number {
  return ((ms - dayStartMs) / 3_600_000) * PX_PER_H
}

function blocksFor(
  emp: CalEmployee,
  date: Date,
  appts: Appointment[],
  absences: Absence[],
  colorFor: (id: string | null) => string,
): Block[] {
  const dayStart = new Date(date)
  dayStart.setHours(DAY_START_H, 0, 0, 0)
  const dayStartMs = dayStart.getTime()
  const dayEnd = new Date(date)
  dayEnd.setHours(DAY_END_H, 0, 0, 0)
  const out: Block[] = []

  for (const ab of absences) {
    if (ab.employee_id !== emp.id || (ab.status && ab.status !== 'approved')) continue
    const s = new Date(ab.starts_at).getTime()
    const e = new Date(ab.ends_at).getTime()
    if (e < dayStartMs || s > dayEnd.getTime()) continue
    const top = Math.max(0, topFor(s, dayStartMs))
    const bottom = Math.min(TOTAL_H, topFor(e, dayStartMs))
    out.push({
      key: `ab-${ab.id}`,
      top,
      height: Math.max(20, bottom - top),
      kind: ab.type === 'block' ? 'block' : 'absence',
      label: ab.type === 'block' ? 'Blockiert' : 'Abwesend',
    })
  }

  for (const a of appts) {
    if (a.assigned_employee_id !== emp.id) continue
    if (!a.scheduled_at || a.status === 'cancelled' || a.status === 'pending') continue
    if (!sameLocalDay(a.scheduled_at, date)) continue
    const s = new Date(a.scheduled_at).getTime()
    const dur = a.duration_minutes ?? 60
    const top = Math.max(0, topFor(s, dayStartMs))
    const height = Math.max(20, (dur / 60) * PX_PER_H)
    const busy = BUSY_SOURCES.has(a.source ?? '')
    out.push({
      key: `ap-${a.id}`,
      top,
      height,
      kind: busy ? 'gebucht' : 'termin',
      color: busy ? GOOGLE_BLOCK_COLOR : colorFor(emp.id),
      label: busy ? 'Gebucht' : a.title ?? 'Termin',
      sub: busy ? undefined : a.customer_name ?? undefined,
      appt: busy ? undefined : a,
    })
  }
  return out
}

export function SpurenView({
  date,
  employees,
  appointments,
  absences,
  colorFor,
  onSelectAppt,
  onDateChange,
}: {
  date: Date
  employees: CalEmployee[]
  appointments: Appointment[]
  absences: Absence[]
  colorFor: (id: string | null) => string
  onSelectAppt: (a: Appointment) => void
  onDateChange: (d: Date) => void
}) {
  // Lane order: busiest first (most appointments that day = highest "weightage"),
  // then alphabetical. So whoever actually has work on the open day floats to the
  // front instead of being buried in the name-sorted list.
  const dayLoad = (empId: string) =>
    appointments.filter(
      (a) =>
        a.assigned_employee_id === empId &&
        a.scheduled_at &&
        a.status !== 'cancelled' &&
        a.status !== 'pending' &&
        sameLocalDay(a.scheduled_at, date),
    ).length
  const lanes = employees
    .filter((e) => e.is_active !== false)
    .map((e) => ({ e, load: dayLoad(e.id) }))
    .sort((a, b) => b.load - a.load || (a.e.display_name || '').localeCompare(b.e.display_name || ''))
    .map((x) => x.e)
  const shift = (days: number) => {
    const d = new Date(date)
    d.setDate(d.getDate() + days)
    onDateChange(d)
  }
  const hours = Array.from({ length: DAY_END_H - DAY_START_H }, (_, i) => DAY_START_H + i)

  // "Now" line + auto-scroll to the current time (like Google Calendar), but only
  // when the open day IS today.
  const now = new Date()
  const isToday = sameLocalDay(now.toISOString(), date)
  const nowTop = (now.getHours() + now.getMinutes() / 60 - DAY_START_H) * PX_PER_H
  const showNow = isToday && nowTop >= 0 && nowTop <= TOTAL_H
  const scrollRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (isToday && scrollRef.current) {
      scrollRef.current.scrollTop = Math.max(0, nowTop - 120)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [date])

  return (
    <div className="flex h-full min-h-0 flex-col rounded-xl border border-border bg-surface">
      <div className="flex items-center gap-3 border-b border-border px-4 py-3">
        <button onClick={() => shift(-1)} className="rounded-md border border-border p-1.5 text-muted hover:bg-alt">
          <ChevronLeft size={16} />
        </button>
        <button onClick={() => onDateChange(new Date())} className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-body hover:bg-alt">
          Heute
        </button>
        <button onClick={() => shift(1)} className="rounded-md border border-border p-1.5 text-muted hover:bg-alt">
          <ChevronRight size={16} />
        </button>
        <div className="text-sm font-bold text-text">
          {date.toLocaleDateString('de-DE', { weekday: 'long', day: 'numeric', month: 'long' })}
        </div>
      </div>

      {lanes.length === 0 ? (
        <p className="px-4 py-8 text-sm text-muted">Keine Mitarbeiter angelegt.</p>
      ) : (
        <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto">
          <div className="flex min-w-fit">
            {/* time axis */}
            <div className="sticky left-0 z-10 w-12 shrink-0 bg-surface">
              <div className="h-12 border-b border-border" />
              <div className="relative" style={{ height: TOTAL_H }}>
                {hours.map((h) => (
                  <div key={h} className="absolute -translate-y-1/2 pr-1 text-right text-[11px] text-muted" style={{ top: (h - DAY_START_H) * PX_PER_H, right: 0 }}>
                    {String(h).padStart(2, '0')}:00
                  </div>
                ))}
                {showNow && (
                  <div className="absolute right-0 z-20 h-2 w-2 -translate-y-1/2 translate-x-1/2 rounded-full bg-error" style={{ top: nowTop }} />
                )}
              </div>
            </div>
            {/* employee lanes */}
            {lanes.map((e) => {
              const blocks = blocksFor(e, date, appointments, absences, colorFor)
              return (
                <div key={e.id} className="w-[140px] shrink-0 border-l border-border">
                  <div className="flex h-12 flex-col items-center justify-center gap-0.5 border-b border-border px-1">
                    <span className="flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-bold text-white" style={{ background: colorFor(e.id) }}>
                      {initials(e.display_name)}
                    </span>
                    <span className="max-w-full truncate text-[11px] text-muted">
                      {e.display_name}
                      {(e.open_tickets ?? 0) > 0 ? ` · ${e.open_tickets} offen` : ''}
                    </span>
                  </div>
                  <div className="relative" style={{ height: TOTAL_H }}>
                    {hours.map((h) => (
                      <div key={h} className="absolute inset-x-0 border-t border-border-faint" style={{ top: (h - DAY_START_H) * PX_PER_H }} />
                    ))}
                    {showNow && (
                      <div className="pointer-events-none absolute inset-x-0 z-10 border-t-2 border-error" style={{ top: nowTop }} />
                    )}
                    {blocks.map((b) => {
                      if (b.kind === 'termin') {
                        return (
                          <button
                            key={b.key}
                            onClick={() => b.appt && onSelectAppt(b.appt)}
                            className="absolute left-0.5 right-0.5 overflow-hidden rounded-md px-1.5 py-0.5 text-left text-[11px] leading-tight text-white"
                            style={{ top: b.top, height: b.height, background: b.color }}
                          >
                            <span className="block truncate font-medium">{b.label}</span>
                            {b.sub && <span className="block truncate opacity-90">{b.sub}</span>}
                          </button>
                        )
                      }
                      if (b.kind === 'gebucht') {
                        return (
                          <div key={b.key} className="absolute left-0.5 right-0.5 overflow-hidden rounded-md px-1.5 py-0.5 text-[11px] leading-tight text-white" style={{ top: b.top, height: b.height, background: b.color }}>
                            <span className="block truncate">Gebucht</span>
                          </div>
                        )
                      }
                      return (
                        <div
                          key={b.key}
                          className={cn(
                            'absolute left-0.5 right-0.5 overflow-hidden rounded-md px-1.5 py-0.5 text-[11px] leading-tight',
                            b.kind === 'block'
                              ? 'border border-dashed border-border-strong bg-alt text-muted'
                              : 'bg-alt text-muted',
                          )}
                          style={{ top: b.top, height: b.height }}
                        >
                          <span className="block truncate">{b.label}</span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
