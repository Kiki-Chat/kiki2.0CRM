/**
 * Wave 3 / Agent 3.1 — compact 7-day mini-calendar inside AppointmentCard.
 *
 * Lives inside the OFFENE AKTIONEN appointment card on the call-detail right
 * panel. Replaces the Agent 2.4 placeholder TODO marker.
 *
 * Visual:
 *   - 7-day grid (Mon-Sun, German short labels Mo Di Mi Do Fr Sa So).
 *   - 14 hour rows (06:00 — 20:00, 1-hour increments).
 *   - Proposed slot (the appointment being viewed) = filled green block.
 *   - Conflicts = red (confirmed) / amber (pending) blocks.
 *   - Today's column has a subtle background tint.
 *   - ◀ ▶ buttons shift the 7-day window by 7 days.
 *
 * Interaction:
 *   - Clicking an empty cell fires `onProposeSlot(start, end)` with a 1-hour
 *     range. The parent populates its alternative-date inputs with this
 *     range and opens the picker — the user still has to click "Alternative
 *     senden" explicitly.
 *   - The proposed slot's start day determines the initial window; if it's
 *     in the past, we anchor on today instead.
 *
 * Sizing constraints (per Wave 3 spec):
 *   - Right panel is `w-80` (320px) — calendar must fit inside that with
 *     padding to spare.
 *   - Total height ~280-340px.
 *   - Day columns 36-40px each.
 *   - Hour rows 18-20px tall.
 *
 * Data:
 *   - TanStack Query against GET /api/appointments/calendar?from=YYYY-MM-DD
 *     &to=YYYY-MM-DD&self_id=... — 60s staleTime, refetches when the window
 *     shifts. The endpoint excludes cancelled/deleted appointments.
 *
 * Deferred (NOT in v1):
 *   - External calendar sync (Google/Microsoft busy slots) waits on the
 *     OAuth bundle in a future session. See the BackendCalendarSlot comment
 *     in appointments.py — the response shape already supports merging.
 */
import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useMemo, useState } from 'react'

import { apiFetch } from '../../lib/api'
import { cn } from '../../lib/utils'

// ─── shapes ──────────────────────────────────────────────────────────────────
interface CalendarSlot {
  id: string
  start_time: string  // ISO
  end_time: string    // ISO
  status: 'pending' | 'confirmed' | string
  is_self: boolean
}

// ─── time helpers ────────────────────────────────────────────────────────────
const HOUR_FROM = 6
const HOUR_TO = 20  // exclusive — last row is 19:00-20:00
const HOUR_COUNT = HOUR_TO - HOUR_FROM  // 14 rows
const DAY_LABELS = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'] as const

const HOUR_ROW_PX = 20  // ~20px per hour row → 14 * 20 = 280px grid
const DAY_COL_PX = 36   // 7 * 36 = 252px + ~32px hour label gutter ≈ 284px

const pad2 = (n: number): string => String(n).padStart(2, '0')

/** Returns the Monday of the week containing `d` (local time). */
const mondayOf = (d: Date): Date => {
  const r = new Date(d)
  r.setHours(0, 0, 0, 0)
  // getDay() — Sun=0, Mon=1, ..., Sat=6. We want offset to Mon (1).
  const diff = (r.getDay() + 6) % 7  // Mon → 0, Sun → 6
  r.setDate(r.getDate() - diff)
  return r
}

const addDays = (d: Date, n: number): Date => {
  const r = new Date(d)
  r.setDate(r.getDate() + n)
  return r
}

const sameDay = (a: Date, b: Date): boolean =>
  a.getFullYear() === b.getFullYear() &&
  a.getMonth() === b.getMonth() &&
  a.getDate() === b.getDate()

const fmtDateYmd = (d: Date): string =>
  `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`

const fmtWindowLabel = (start: Date, end: Date): string => {
  const same = start.getMonth() === end.getMonth() && start.getFullYear() === end.getFullYear()
  if (same) {
    return `${start.getDate()}.–${end.getDate()}. ${start.toLocaleString('de-DE', { month: 'short' })}`
  }
  return `${pad2(start.getDate())}.${pad2(start.getMonth() + 1)} – ${pad2(end.getDate())}.${pad2(end.getMonth() + 1)}`
}

// ─── component ──────────────────────────────────────────────────────────────
export function MiniCalendar({
  proposedStart,
  proposedEnd,
  selfId,
  onProposeSlot,
}: {
  /** ISO start of the appointment currently shown in the card. */
  proposedStart: string | null
  /** ISO end of the appointment currently shown in the card. */
  proposedEnd: string | null
  /** UUID of the proposed appointment so the backend can mark it `is_self`. */
  selfId: string | null
  /** Fires when the user clicks an empty cell. Args are LOCAL Date objects. */
  onProposeSlot: (start: Date, end: Date) => void
}) {
  // Anchor the window on today, OR on the proposed-slot's Monday if the slot
  // sits in a future week (so the user lands on the right week of the grid).
  const initialWeekStart = useMemo(() => {
    const today = new Date()
    if (proposedStart) {
      const p = new Date(proposedStart)
      if (p.getTime() > today.getTime()) {
        return mondayOf(p)
      }
    }
    return mondayOf(today)
  }, [proposedStart])

  const [weekStart, setWeekStart] = useState<Date>(initialWeekStart)
  const weekEnd = useMemo(() => addDays(weekStart, 7), [weekStart])

  const days = useMemo(
    () => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)),
    [weekStart],
  )

  // ── busy-slot fetch ───────────────────────────────────────────────────────
  const busyQuery = useQuery<CalendarSlot[]>({
    queryKey: [
      'mini-calendar',
      fmtDateYmd(weekStart),
      fmtDateYmd(weekEnd),
      selfId,
    ],
    queryFn: () => {
      const params = new URLSearchParams({
        from: fmtDateYmd(weekStart),
        to: fmtDateYmd(weekEnd),
      })
      if (selfId) params.set('self_id', selfId)
      return apiFetch<CalendarSlot[]>(`/api/appointments/calendar?${params.toString()}`)
    },
    staleTime: 60_000,
  })

  // ── proposed-slot overlay ─────────────────────────────────────────────────
  // The proposed slot may or may not be in the fetched busy-slots list (if
  // the appointment is in this org, the backend will include it with
  // is_self=true). When it's outside the visible window we just skip it.
  const proposed = useMemo(() => {
    if (!proposedStart || !proposedEnd) return null
    const s = new Date(proposedStart)
    const e = new Date(proposedEnd)
    return { start: s, end: e }
  }, [proposedStart, proposedEnd])

  const today = useMemo(() => {
    const t = new Date()
    t.setHours(0, 0, 0, 0)
    return t
  }, [])

  // Group busy slots by day-of-week-index (0-6) for cheap render lookups.
  const slotsByDay = useMemo(() => {
    const out: CalendarSlot[][] = Array.from({ length: 7 }, () => [])
    for (const slot of busyQuery.data ?? []) {
      const startDt = new Date(slot.start_time)
      for (let i = 0; i < 7; i++) {
        if (sameDay(startDt, days[i])) {
          out[i].push(slot)
          break
        }
      }
    }
    return out
  }, [busyQuery.data, days])

  /**
   * Map a Date to its top-offset within the hour-grid in px. Clamps to grid
   * bounds (so a 5am appt that ends at 7am renders as a top-edge block).
   */
  const dateToTopPx = (d: Date): number => {
    const h = d.getHours() + d.getMinutes() / 60
    const offset = Math.max(0, Math.min(HOUR_COUNT, h - HOUR_FROM))
    return offset * HOUR_ROW_PX
  }

  const dateToHeightPx = (start: Date, end: Date): number => {
    const top = dateToTopPx(start)
    const bottom = dateToTopPx(end)
    return Math.max(HOUR_ROW_PX * 0.4, bottom - top)
  }

  const handleCellClick = (dayIdx: number, hour: number) => {
    const day = days[dayIdx]
    const start = new Date(day)
    start.setHours(hour, 0, 0, 0)
    if (start.getTime() <= Date.now()) {
      // Past slots aren't valid proposals — the propose-alternative
      // endpoint rejects past-tense start_times with 422.
      return
    }
    const end = new Date(start)
    end.setHours(hour + 1)
    onProposeSlot(start, end)
  }

  const goPrev = () => setWeekStart((s) => addDays(s, -7))
  const goNext = () => setWeekStart((s) => addDays(s, 7))

  return (
    <div className="mt-3 rounded-md border border-border bg-surface p-2">
      {/* Header — window label + navigation */}
      <div className="mb-1.5 flex items-center justify-between">
        <button
          onClick={goPrev}
          className="rounded p-0.5 text-muted transition-colors hover:bg-alt hover:text-body"
          aria-label="Vorherige Woche"
          type="button"
        >
          <ChevronLeft size={14} />
        </button>
        <span className="text-[11px] font-semibold text-body">
          {fmtWindowLabel(days[0], days[6])}
        </span>
        <button
          onClick={goNext}
          className="rounded p-0.5 text-muted transition-colors hover:bg-alt hover:text-body"
          aria-label="Nächste Woche"
          type="button"
        >
          <ChevronRight size={14} />
        </button>
      </div>

      {/* Day labels row */}
      <div className="flex pl-6">
        {days.map((d, i) => {
          const isToday = sameDay(d, today)
          return (
            <div
              key={i}
              className={cn(
                'flex flex-col items-center justify-center text-[10px] font-semibold',
                isToday ? 'text-green-primary' : 'text-muted',
              )}
              style={{ width: DAY_COL_PX }}
            >
              <span>{DAY_LABELS[i]}</span>
              <span className={cn('text-[10px]', isToday ? 'font-bold' : 'font-normal')}>
                {d.getDate()}
              </span>
            </div>
          )
        })}
      </div>

      {/* Hour grid */}
      <div className="relative mt-1 flex">
        {/* Hour gutter labels (left side) */}
        <div className="flex w-6 flex-col">
          {Array.from({ length: HOUR_COUNT }, (_, h) => (
            <div
              key={h}
              className="text-right text-[9px] leading-none text-faint"
              style={{
                height: HOUR_ROW_PX,
                paddingTop: 1,
                paddingRight: 3,
              }}
            >
              {pad2(HOUR_FROM + h)}
            </div>
          ))}
        </div>

        {/* 7 day columns */}
        {days.map((day, dayIdx) => {
          const isToday = sameDay(day, today)
          return (
            <div
              key={dayIdx}
              className={cn(
                'relative border-l border-border-faint',
                isToday && 'bg-green-tint-50/40',
              )}
              style={{ width: DAY_COL_PX, height: HOUR_COUNT * HOUR_ROW_PX }}
            >
              {/* Empty hour cells (click targets) */}
              {Array.from({ length: HOUR_COUNT }, (_, h) => {
                const hour = HOUR_FROM + h
                const cellStart = new Date(day)
                cellStart.setHours(hour, 0, 0, 0)
                const isPast = cellStart.getTime() <= Date.now()
                return (
                  <button
                    key={h}
                    type="button"
                    onClick={() => handleCellClick(dayIdx, hour)}
                    disabled={isPast}
                    className={cn(
                      'absolute left-0 right-0 border-t border-border-faint/60 transition-colors',
                      isPast
                        ? 'cursor-not-allowed bg-alt/30'
                        : 'cursor-pointer hover:bg-green-tint-50',
                    )}
                    style={{
                      top: h * HOUR_ROW_PX,
                      height: HOUR_ROW_PX,
                    }}
                    aria-label={`${DAY_LABELS[dayIdx]} ${pad2(hour)}:00 — Alternative vorschlagen`}
                  />
                )
              })}

              {/* Busy / conflict blocks for this day */}
              {slotsByDay[dayIdx].map((slot) => {
                const sDt = new Date(slot.start_time)
                const eDt = new Date(slot.end_time)
                const top = dateToTopPx(sDt)
                const height = dateToHeightPx(sDt, eDt)
                // is_self → proposed slot (the appointment being viewed in
                // the card). Render as filled green.
                // Otherwise color by status: confirmed=red, pending=amber.
                const isSelf = slot.is_self
                const isConfirmed = slot.status === 'confirmed'
                return (
                  <div
                    key={slot.id}
                    className={cn(
                      'pointer-events-none absolute left-0.5 right-0.5 rounded-sm border text-[8px] font-semibold leading-none',
                      isSelf
                        ? 'border-green-primary bg-green-primary text-white shadow-sm'
                        : isConfirmed
                          ? 'border-error/60 bg-error/85 text-white'
                          : 'border-warning/60 bg-warning/80 text-white',
                    )}
                    style={{ top, height }}
                    title={
                      isSelf
                        ? 'Vorgeschlagener Termin'
                        : isConfirmed
                          ? 'Bestätigter Termin'
                          : 'Ausstehender Termin'
                    }
                  />
                )
              })}

              {/* Overlay: proposed slot when it's NOT in the busy list (e.g.
                  the proposed range was edited locally and hasn't been
                  saved yet, or the appointment is filtered out). */}
              {proposed && sameDay(proposed.start, day) && !slotsByDay[dayIdx].some((s) => s.is_self) && (
                <div
                  className="pointer-events-none absolute left-0.5 right-0.5 rounded-sm border border-green-primary bg-green-primary/85 shadow-sm"
                  style={{
                    top: dateToTopPx(proposed.start),
                    height: dateToHeightPx(proposed.start, proposed.end),
                  }}
                  title="Vorgeschlagener Termin"
                />
              )}
            </div>
          )
        })}
      </div>

      {/* Legend */}
      <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[9px] text-muted">
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm bg-green-primary" />
          Vorschlag
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm bg-error/85" />
          Bestätigt
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm bg-warning/80" />
          Ausstehend
        </span>
      </div>
    </div>
  )
}
