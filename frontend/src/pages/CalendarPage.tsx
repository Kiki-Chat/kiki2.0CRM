import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import type { EventDropArg } from '@fullcalendar/core'
import deLocale from '@fullcalendar/core/locales/de'
import dayGridPlugin from '@fullcalendar/daygrid'
import interactionPlugin, { type EventResizeDoneArg } from '@fullcalendar/interaction'
import listPlugin from '@fullcalendar/list'
import FullCalendar from '@fullcalendar/react'
import timeGridPlugin from '@fullcalendar/timegrid'
import { Check, ChevronDown, Loader2, Plus, RefreshCw, Upload } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { ConfirmDialog } from '../components/kiki/shared'
import { Modal } from '../components/ui/Modal'
import { apiFetch, apiUpload } from '../lib/api'
import {
  consumeLiveFill,
  emitLiveFillStatus,
  LIVE_FILL_REQUEST_EVENT,
  sleep,
  type LiveFillPayload,
} from '../lib/liveFill'
import { useMe } from '../lib/useMe'
import { cn } from '../lib/utils'
import { AvailabilityRail } from './calendar/AvailabilityRail'
import { SpurenView } from './calendar/SpurenView'
import { type Absence, buildColorMap, initials } from './calendar/shared'

// ─── Types ───────────────────────────────────────────────────────────────────
interface Appointment {
  id: string
  title: string | null
  scheduled_at: string | null
  duration_minutes: number | null
  status: string
  category: string | null
  source: string | null
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
  // Linking for tentative "Vorschlag" (pending) suggestions surfaced on the grid.
  source_conversation_id?: string | null
  case_id?: string | null
  call_id?: string | null
}
interface Employee {
  id: string
  display_name: string
  is_active?: boolean
  is_technician?: boolean
  calendar_color?: string | null
  activity_area?: string | null
  open_tickets?: number
  present?: boolean
}
interface AvailTech {
  id: string
  display_name: string
  available: boolean
  open_tickets: number
  is_current?: boolean
}
interface CustomerOption {
  id: string
  full_name: string | null
  // Adresse and the appointment's Ort are the same place — carried here so the
  // create form can prefill the Ort from the customer's stored address.
  address?: { raw?: string } | string | null
}
// ─── Constants ───────────────────────────────────────────────────────────────
const UNASSIGNED_COLOR = '#78756F'
// Google-imported events render as read-only "blocked time" — distinct slate.
const GOOGLE_BLOCK_COLOR = '#64748B'
const PROJECT_STATUS_COLOR: Record<string, string> = {
  planning: '#9CA3AF',
  active: '#2D6B3D',
  completed: '#2563EB',
  archived: '#B0A59A',
}

interface ProjectRow {
  id: string
  title: string
  status: string
  start_date: string | null
  end_date: string | null
}
const STATUS_LABEL: Record<string, string> = {
  pending: 'Vorschlag',
  confirmed: 'Bestätigt',
  cancelled: 'Storniert',
  completed: 'Erledigt',
}

const pad = (n: number) => String(n).padStart(2, '0')
const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const hm = (d: Date) => `${pad(d.getHours())}:${pad(d.getMinutes())}`

function useEmployeeColors(employees: Employee[]): (empId: string | null) => string {
  // Prefer each employee's own calendar_color, fall back to a stable palette.
  return useMemo(() => buildColorMap(employees), [employees])
}

// ─── Page ────────────────────────────────────────────────────────────────────
type Filter = 'all' | 'mine' | 'unassigned' | string

export function CalendarPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const calRef = useRef<FullCalendar | null>(null)
  const focusedApptRef = useRef(false)
  const [range, setRange] = useState<{ from: string; to: string } | null>(null)
  const [filter, setFilter] = useState<Filter>(() => searchParams.get('employee') || 'all')
  const [detail, setDetail] = useState<Appointment | null>(null)
  const [createAt, setCreateAt] = useState<Date | null>(null)
  const [editAppt, setEditAppt] = useState<Appointment | null>(null)
  const [importMsg, setImportMsg] = useState<string | null>(null)
  const [mode, setMode] = useState<'appointments' | 'projects'>('appointments')
  const [calView, setCalView] = useState<'kalender' | 'spuren'>('kalender')
  const [spurenDate, setSpurenDate] = useState<Date>(() => new Date())
  // Drag/resize lands here until the user confirms — moving a confirmed
  // appointment fires the real reschedule call+email server-side, so it must
  // never happen from an accidental drag.
  const [pendingMove, setPendingMove] = useState<{
    appt: Appointment
    newStart: Date
    newDuration: number
    revert: () => void
  } | null>(null)

  const { data: employees = [] } = useQuery({
    queryKey: ['employees'],
    queryFn: () => apiFetch<Employee[]>('/api/employees'),
  })
  const { me, isAdmin } = useMe()
  const colorFor = useEmployeeColors(employees)

  // Hey-Kiki live fill: a confirmed copilot create_appointment lands here via
  // lib/liveFill — open the real create modal and let it fill itself visibly
  // (same takeover pattern as the invoice/Angebot forms). Consumed on mount AND on
  // the request event, because the user may already be on /calendar.
  const [liveFill, setLiveFill] = useState<LiveFillPayload | null>(null)
  useEffect(() => {
    const tryConsume = () => {
      const lf = consumeLiveFill('create_appointment')
      if (!lf) return
      const at = lf.args.scheduled_at ? new Date(lf.args.scheduled_at) : new Date()
      if (calRef.current && lf.args.scheduled_at) calRef.current.getApi().gotoDate(at)
      setLiveFill(lf)
      setCreateAt(at)
    }
    tryConsume()
    window.addEventListener(LIVE_FILL_REQUEST_EVENT, tryConsume)
    return () => window.removeEventListener(LIVE_FILL_REQUEST_EVENT, tryConsume)
  }, [])

  const myEmployeeId = useMemo(() => {
    if (!me?.full_name) return null
    const match = employees.find(
      (e) => e.display_name.trim().toLowerCase() === me.full_name!.trim().toLowerCase(),
    )
    return match?.id ?? null
  }, [me, employees])

  const { data: appointments = [] } = useQuery({
    queryKey: ['appointments', range?.from, range?.to],
    queryFn: () => apiFetch<Appointment[]>(`/api/appointments?from=${range!.from}&to=${range!.to}`),
    enabled: !!range,
    // The calendar is a shared, multi-user surface — poll so edits made by another
    // user/account appear here without a manual reload.
    refetchInterval: 30_000,
  })

  // Absences (admin only) for the master calendar: shown as blocked time on the
  // lanes + week/month and fed into the availability rail.
  const { data: absences = [] } = useQuery({
    queryKey: ['calendar-absences', range?.from, range?.to],
    queryFn: () => apiFetch<Absence[]>(`/api/employees/absences?from=${range!.from}&to=${range!.to}`),
    enabled: !!range && isAdmin,
    staleTime: 60_000,
  })

  // FIX 1 — calendar connection state, to gate the push button (provider-aware).
  // /api/settings/oauth/connections is require_org, so employees can read it too.
  const { data: oauthState } = useQuery({
    queryKey: ['oauth-connections'],
    queryFn: () =>
      apiFetch<{ purposes?: { calendar?: { provider: string } | null } }>(
        '/api/settings/oauth/connections',
      ),
    staleTime: 5 * 60 * 1000,
  })
  const calendarProvider = oauthState?.purposes?.calendar?.provider ?? null

  // Deep-link focus: the dashboard "Anstehende Termine" rows link here with
  // ?date=<YYYY-MM-DD>&appointment=<id>. Jump the calendar to that date so the
  // event is in view; once that month's appointments load, open the matching
  // appointment's detail modal exactly once.
  useEffect(() => {
    const dateStr = searchParams.get('date')
    if (dateStr && calRef.current) calRef.current.getApi().gotoDate(dateStr)
    focusedApptRef.current = false
  }, [searchParams])

  useEffect(() => {
    const apptId = searchParams.get('appointment')
    if (!apptId || focusedApptRef.current) return
    const appt = appointments.find((a) => a.id === apptId)
    if (appt) {
      setDetail(appt)
      focusedApptRef.current = true
    }
  }, [appointments, searchParams])

  const events = useMemo(
    () =>
      appointments
        .filter((a) => {
          // Pending appointments are tentative "Vorschläge" (e.g. a slot the caller
          // asked Kiki for) — shown on the grid as a distinct, non-draggable event
          // so the team can confirm/adjust them in place, deep-linked to the call.
          // Cancelled and time-less rows still never render.
          if (!a.scheduled_at || a.status === 'cancelled') return false
          // Google-imported events are external "blocked time" — always shown,
          // independent of the employee filter (they block everyone).
          if (a.source === 'google_import') return true
          if (filter === 'all') return true
          if (filter === 'mine') return a.assigned_employee_id === myEmployeeId
          if (filter === 'unassigned') return !a.assigned_employee_id
          return a.assigned_employee_id === filter
        })
        .map((a) => {
          const start = new Date(a.scheduled_at!)
          const end = new Date(start.getTime() + (a.duration_minutes ?? 60) * 60000)
          // Org Google imports AND an employee's personal busy are external
          // "blocked time" — grey, read-only, no customer detail surfaced.
          const isExternal = a.source === 'google_import' || a.source === 'employee_busy'
          const isTentative = a.status === 'pending'
          const color = isExternal ? GOOGLE_BLOCK_COLOR : colorFor(a.assigned_employee_id)
          const base = a.title ?? 'Termin'
          const title = isExternal
            ? a.source === 'employee_busy'
              ? '🔒 Gebucht'
              : `🔒 ${a.title ?? 'Google-Termin'}`
            : a.customer_name
              ? `${(isTentative ? '✎ ' : '') + base} · ${a.customer_name}`
              : (isTentative ? '✎ ' : '') + base
          return {
            id: a.id,
            title,
            start: start.toISOString(),
            end: end.toISOString(),
            backgroundColor: color,
            borderColor: color,
            // External blocks AND tentative suggestions are read-only on the grid:
            // a drag must never silently mutate an unconfirmed slot (confirm/adjust
            // happens via the detail modal). Confirmed CRM events stay draggable.
            editable: !isExternal && !isTentative,
            classNames: isTentative ? ['cal-tentative'] : [],
            extendedProps: { appt: a, external: isExternal },
          }
        }),
    [appointments, filter, myEmployeeId, colorFor],
  )

  // Approved absences as soft all-day background bars on the week/month calendar.
  const absenceEvents = useMemo(
    () =>
      absences
        .filter((ab) => !ab.status || ab.status === 'approved')
        .map((ab) => ({
          id: `ab-${ab.id}`,
          title: `${ab.employee_name ?? 'Abwesend'}${ab.type === 'block' ? ' · Blockiert' : ''}`,
          start: ab.starts_at,
          end: ab.ends_at,
          display: 'background' as const,
          backgroundColor: 'rgba(120,117,111,0.18)',
          extendedProps: { absence: true },
        })),
    [absences],
  )
  const calEvents = useMemo(() => [...events, ...absenceEvents], [events, absenceEvents])

  // Which employees get a lane in the Spuren view — follows the dropdown filter.
  const spurenEmployees = useMemo(() => {
    const active = employees.filter((e) => e.is_active !== false)
    if (filter !== 'all' && filter !== 'mine' && filter !== 'unassigned') {
      return active.filter((e) => e.id === filter)
    }
    if (filter === 'mine' && myEmployeeId) return active.filter((e) => e.id === myEmployeeId)
    return active
  }, [employees, filter, myEmployeeId])

  // Spuren has no FullCalendar to fire datesSet, so drive the fetch range from the
  // chosen day (appointments + absences load for exactly that day).
  useEffect(() => {
    if (calView !== 'spuren') return
    const from = new Date(spurenDate)
    from.setHours(0, 0, 0, 0)
    const to = new Date(spurenDate)
    to.setHours(23, 59, 59, 999)
    setRange({ from: from.toISOString(), to: to.toISOString() })
  }, [calView, spurenDate])

  // Project timeline: each project rendered as a bar spanning start_date → end_date.
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiFetch<ProjectRow[]>('/api/projects'),
    enabled: mode === 'projects',
    staleTime: 5 * 60 * 1000,
  })
  const projectEvents = useMemo(
    () =>
      projects
        .filter((p) => p.start_date)
        .map((p) => {
          const end = p.end_date
            ? new Date(new Date(p.end_date).getTime() + 86400000).toISOString().slice(0, 10)
            : undefined
          const color = PROJECT_STATUS_COLOR[p.status] ?? UNASSIGNED_COLOR
          return {
            id: p.id,
            title: p.title,
            start: p.start_date!,
            end,
            allDay: true,
            backgroundColor: color,
            borderColor: color,
            extendedProps: { projectId: p.id },
          }
        }),
    [projects],
  )

  const filterLabel =
    filter === 'all'
      ? 'Alle Termine'
      : filter === 'mine'
        ? 'Nur meine'
        : filter === 'unassigned'
          ? 'Nicht zugewiesen'
          : employees.find((e) => e.id === filter)?.display_name ?? 'Filter'

  const importIcs = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      return apiUpload<{ created: number; skipped: number; total: number }>(
        '/api/appointments/import-ics',
        fd,
      )
    },
    onSuccess: (r) => {
      setImportMsg(`${r.created} Termine importiert${r.skipped ? `, ${r.skipped} übersprungen` : ''}.`)
      qc.invalidateQueries({ queryKey: ['appointments'] })
      setTimeout(() => setImportMsg(null), 5000)
    },
    onError: () => {
      setImportMsg('Import fehlgeschlagen.')
      setTimeout(() => setImportMsg(null), 5000)
    },
  })

  // Persist a confirmed drag/resize. Until this PATCH succeeds the event sits at
  // its dropped position; on error we revert it back.
  const moveAppt = useMutation({
    mutationFn: (m: { id: string; scheduled_at: string; duration_minutes: number }) =>
      apiFetch(`/api/appointments/${m.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ scheduled_at: m.scheduled_at, duration_minutes: m.duration_minutes }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['appointments'] })
      qc.invalidateQueries({ queryKey: ['pendingAppointment'] })
      qc.invalidateQueries({ queryKey: ['actions', 'pending'] })
      setPendingMove(null)
      setImportMsg('Termin verschoben — der Kunde wird über die Änderung informiert.')
      setTimeout(() => setImportMsg(null), 5000)
    },
    onError: (e: unknown) => {
      pendingMove?.revert()
      setPendingMove(null)
      setImportMsg(e instanceof Error ? e.message : 'Verschieben fehlgeschlagen.')
      setTimeout(() => setImportMsg(null), 5000)
    },
  })

  const onEventChange = (info: EventDropArg | EventResizeDoneArg) => {
    const appt = info.event.extendedProps.appt as Appointment | undefined
    const start = info.event.start
    if (!appt || !start) {
      info.revert()
      return
    }
    const end = info.event.end
    const newDuration = end
      ? Math.max(15, Math.round((end.getTime() - start.getTime()) / 60000))
      : appt.duration_minutes ?? 60
    setPendingMove({ appt, newStart: start, newDuration, revert: info.revert })
  }

  const syncCal = useMutation({
    mutationFn: () =>
      apiFetch<{ fetched: number; created: number; updated: number; cancelled: number; detached: number }>(
        '/api/calendar/sync',
        { method: 'POST' },
      ),
    onSuccess: (r) => {
      setImportMsg(`Synchronisiert: ${r.fetched} Termine geprüft.`)
      setTimeout(() => setImportMsg(null), 5000)
      qc.invalidateQueries({ queryKey: ['appointments'] })
    },
    onError: (e: unknown) => {
      setImportMsg(e instanceof Error ? e.message : 'Synchronisierung fehlgeschlagen.')
      setTimeout(() => setImportMsg(null), 5000)
    },
  })

  return (
    <div className="flex h-full flex-col p-8">
      {/* Header */}
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold text-text">Kalender</h1>
          <div className="flex gap-1 rounded-md border border-border bg-alt p-1">
            <button onClick={() => setMode('appointments')} className={cn('rounded px-3 py-1 text-sm', mode === 'appointments' ? 'bg-surface font-medium text-text shadow-e1' : 'text-muted')}>Termine</button>
            <button onClick={() => setMode('projects')} className={cn('rounded px-3 py-1 text-sm', mode === 'projects' ? 'bg-surface font-medium text-text shadow-e1' : 'text-muted')}>Vorgangs-Verlauf</button>
          </div>
          {mode === 'appointments' && (
            <div className="flex gap-1 rounded-md border border-border bg-alt p-1">
              <button onClick={() => setCalView('kalender')} className={cn('rounded px-3 py-1 text-sm', calView === 'kalender' ? 'bg-surface font-medium text-text shadow-e1' : 'text-muted')}>Kalender</button>
              <button onClick={() => setCalView('spuren')} className={cn('rounded px-3 py-1 text-sm', calView === 'spuren' ? 'bg-surface font-medium text-text shadow-e1' : 'text-muted')}>Spuren</button>
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {mode === 'appointments' && (
          <>
          {/* Filter dropdown */}
          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
              <button className="inline-flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-2 text-sm font-medium text-body hover:bg-alt">
                {filter !== 'all' && filter !== 'mine' && filter !== 'unassigned' && (
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: colorFor(filter) }} />
                )}
                {filterLabel}
                <ChevronDown size={15} className="text-muted" />
              </button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content
                align="start"
                sideOffset={6}
                className="z-50 min-w-52 rounded-lg border border-border bg-surface p-1 shadow-e2"
              >
                <FilterItem label="Alle Termine" active={filter === 'all'} onSelect={() => setFilter('all')} />
                {myEmployeeId && (
                  <FilterItem label="Nur meine" active={filter === 'mine'} onSelect={() => setFilter('mine')} />
                )}
                <FilterItem
                  label="Nicht zugewiesen"
                  active={filter === 'unassigned'}
                  onSelect={() => setFilter('unassigned')}
                />
                {employees.length > 0 && (
                  <>
                    <div className="px-2 pb-1 pt-2 text-xs font-semibold uppercase tracking-wide text-muted">
                      Mitarbeiter
                    </div>
                    {employees.map((e) => (
                      <FilterItem
                        key={e.id}
                        label={e.display_name}
                        color={colorFor(e.id)}
                        active={filter === e.id}
                        onSelect={() => setFilter(e.id)}
                      />
                    ))}
                  </>
                )}
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>

          <button
            onClick={() => syncCal.mutate()}
            disabled={syncCal.isPending}
            title="Google-Kalender synchronisieren (neue Termine + Löschungen abgleichen)"
            className="inline-flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-2 text-sm font-medium text-body hover:bg-alt disabled:opacity-60"
          >
            <RefreshCw size={15} className={syncCal.isPending ? 'animate-spin' : ''} />
            {syncCal.isPending ? 'Synchronisiert…' : 'Synchronisieren'}
          </button>
          <button
            onClick={() => {
              const d = new Date()
              d.setHours(9, 0, 0, 0)
              // 9:00 today may already be in the past — backdating is rejected,
              // so default to the next full hour from now in that case.
              if (d.getTime() <= Date.now()) {
                d.setTime(Date.now())
                d.setMinutes(0, 0, 0)
                d.setHours(d.getHours() + 1)
              }
              setCreateAt(d)
            }}
            className="inline-flex items-center gap-2 rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110"
          >
            <Plus size={16} /> Neuer Termin
          </button>
          <button
            onClick={() => fileRef.current?.click()}
            className="inline-flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-2 text-sm font-medium text-body hover:bg-alt"
          >
            <Upload size={15} /> ICS-Import
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".ics,text/calendar"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) importIcs.mutate(f)
              e.target.value = ''
            }}
          />
          </>
          )}
        </div>
      </div>

      {importMsg && (
        <div className="mb-3 rounded-md bg-green-tint-50 px-3 py-2 text-sm font-medium text-green-deep">
          {importMsg}
        </div>
      )}

      {/* Calendar + availability rail */}
      <div className="flex min-h-0 flex-1 gap-4">
        {mode === 'appointments' && calView === 'spuren' ? (
          <div className="min-h-0 flex-1">
            <SpurenView
              date={spurenDate}
              employees={spurenEmployees}
              appointments={appointments}
              absences={absences}
              colorFor={colorFor}
              onSelectAppt={(a) => setDetail(a)}
              onDateChange={setSpurenDate}
            />
          </div>
        ) : (
          <div className="min-h-0 flex-1 rounded-xl border border-border bg-surface p-4">
            <FullCalendar
              ref={calRef}
              plugins={[dayGridPlugin, timeGridPlugin, listPlugin, interactionPlugin]}
              initialView="timeGridWeek"
              locale={deLocale}
              firstDay={1}
              height="100%"
              headerToolbar={{
                left: 'prev,next today',
                center: 'title',
                right: 'timeGridWeek,dayGridMonth,timeGridDay,listWeek',
              }}
              buttonText={{ listWeek: 'Terminübersicht' }}
              slotMinTime="06:00:00"
              slotMaxTime="21:00:00"
              scrollTime="07:30:00"
              nowIndicator
              dayMaxEvents={3}
              eventDisplay="block"
              eventTimeFormat={{ hour: '2-digit', minute: '2-digit', hour12: false }}
              dayHeaderContent={(arg) => {
                if (!arg.view.type.startsWith('timeGrid')) return arg.text
                return (
                  <>
                    <span className="cal-dow">{arg.date.toLocaleDateString('de-DE', { weekday: 'short' })}</span>
                    <span className="cal-day">{arg.date.getDate()}</span>
                  </>
                )
              }}
              eventContent={(arg) => {
                if (arg.event.display === 'background') return undefined
                const appt = arg.event.extendedProps.appt as Appointment | undefined
                const external = !!arg.event.extendedProps.external
                const empId = appt?.assigned_employee_id ?? null
                return (
                  <div className="flex items-center gap-1 overflow-hidden px-0.5 py-px">
                    {!external && empId && (
                      <span
                        className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[8px] font-bold text-white ring-1 ring-white/50"
                        style={{ background: colorFor(empId) }}
                      >
                        {initials(appt?.employee_name)}
                      </span>
                    )}
                    {arg.timeText && <span className="shrink-0 font-semibold">{arg.timeText}</span>}
                    <span className="truncate">{arg.event.title}</span>
                  </div>
                )
              }}
              events={mode === 'projects' ? projectEvents : calEvents}
              eventDrop={onEventChange}
              eventResize={onEventChange}
              datesSet={(info) =>
                setRange({ from: info.start.toISOString(), to: info.end.toISOString() })
              }
              dateClick={(info) => {
                if (mode === 'projects') return
                const d = info.date
                if (info.allDay) d.setHours(9, 0, 0, 0)
                setCreateAt(d)
              }}
              eventClick={(info) => {
                if (mode === 'projects') {
                  navigate(`/projects/${info.event.extendedProps.projectId}`)
                  return
                }
                const appt = info.event.extendedProps.appt as Appointment
                if (appt) setDetail(appt)
              }}
            />
          </div>
        )}
        {mode === 'appointments' && isAdmin && (
          <AvailabilityRail
            employees={employees}
            appointments={appointments}
            absences={absences}
            colorFor={colorFor}
            at={new Date()}
          />
        )}
      </div>

      {detail && (
        <AppointmentDetailModal
          appt={detail}
          color={colorFor(detail.assigned_employee_id)}
          calendarProvider={calendarProvider}
          employees={employees}
          onClose={() => setDetail(null)}
          onReschedule={() => { setEditAppt(detail); setDetail(null) }}
        />
      )}
      {(createAt || editAppt) && (
        <CreateAppointmentModal
          at={editAppt?.scheduled_at ? new Date(editAppt.scheduled_at) : (createAt ?? new Date())}
          edit={editAppt ?? undefined}
          liveFill={liveFill ?? undefined}
          employees={employees}
          appointments={appointments}
          colorFor={colorFor}
          onClose={() => { setCreateAt(null); setEditAppt(null); setLiveFill(null) }}
          onCreated={(created) => {
            setCreateAt(null)
            setEditAppt(null)
            setLiveFill(null)
            qc.invalidateQueries({ queryKey: ['appointments'] })
            // Reflect a calendar reschedule back to the call card + worklist.
            qc.invalidateQueries({ queryKey: ['pendingAppointment'] })
            qc.invalidateQueries({ queryKey: ['actions', 'pending'] })
            // A Kiki live fill ends by showing the finished appointment.
            if (created) setDetail(created)
          }}
        />
      )}

      <ConfirmDialog
        open={!!pendingMove}
        onOpenChange={(v) => {
          if (!v && pendingMove && !moveAppt.isPending) {
            pendingMove.revert()
            setPendingMove(null)
          }
        }}
        title="Termin verschieben?"
        message={
          pendingMove
            ? `„${pendingMove.appt.title ?? 'Termin'}“${pendingMove.appt.customer_name ? ` (${pendingMove.appt.customer_name})` : ''} auf ${pendingMove.newStart.toLocaleDateString('de-DE', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Europe/Berlin' })}, ${hm(pendingMove.newStart)} Uhr (${pendingMove.newDuration} Min) verschieben? Der Kunde wird über die Änderung informiert (Anruf/E-Mail je nach Einstellung in der Kiki-Zentrale).`
            : ''
        }
        confirmLabel="Verschieben"
        busy={moveAppt.isPending}
        onConfirm={() => {
          if (!pendingMove) return
          moveAppt.mutate({
            id: pendingMove.appt.id,
            scheduled_at: pendingMove.newStart.toISOString(),
            duration_minutes: pendingMove.newDuration,
          })
        }}
      />
    </div>
  )
}

function FilterItem({
  label,
  active,
  color,
  onSelect,
}: {
  label: string
  active: boolean
  color?: string
  onSelect: () => void
}) {
  return (
    <DropdownMenu.Item
      onSelect={onSelect}
      className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm text-body outline-none data-[highlighted]:bg-alt"
    >
      {color ? (
        <span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} />
      ) : (
        <span className="w-2.5" />
      )}
      <span className="flex-1">{label}</span>
      {active && <Check size={14} className="text-green-primary" />}
    </DropdownMenu.Item>
  )
}

// ─── Detail modal ────────────────────────────────────────────────────────────
function locStr(l: Appointment['location']): string | null {
  if (!l) return null
  return typeof l === 'string' ? l : l.raw ?? null
}

const CAL_PROVIDER_LABEL: Record<string, string> = {
  google: 'Google Kalender',
  microsoft: 'Outlook-Kalender',
  calendly: 'Calendly',
}
// Only Google has a write/push path today (events.insert). Outlook-write isn't
// implemented and Calendly is booking/read-only — so neither is pushable.
const PUSHABLE_CAL_PROVIDERS = new Set(['google'])

function AppointmentDetailModal({
  appt,
  color,
  calendarProvider,
  employees,
  onClose,
  onReschedule,
}: {
  appt: Appointment
  color: string
  calendarProvider: string | null
  employees: Employee[]
  onClose: () => void
  onReschedule: () => void
}) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const start = appt.scheduled_at ? new Date(appt.scheduled_at) : null
  const loc = locStr(appt.location)
  const [pushMsg, setPushMsg] = useState<string | null>(null)
  // Pushable = CRM-native (echo-loop guard: imported google_import events get NO
  // push affordance) AND confirmed (never push tentative/pending bookings).
  const pushable = appt.source === 'crm' && appt.status === 'confirmed'
  const alreadyPushed = !!appt.google_event_id
  const providerLabel = calendarProvider
    ? CAL_PROVIDER_LABEL[calendarProvider] ?? 'Kalender'
    : null
  const canPush = !!calendarProvider && PUSHABLE_CAL_PROVIDERS.has(calendarProvider)
  const pushDisabledReason = !calendarProvider
    ? 'Kein Kalender verbunden – bitte zuerst in den Einstellungen einen Kalender verbinden.'
    : `Übertragung an ${providerLabel} wird noch nicht unterstützt.`
  const push = useMutation({
    mutationFn: () =>
      apiFetch<{ success: boolean; google_event_id?: string }>(
        `/api/calendar/push/${appt.id}`,
        { method: 'POST' },
      ),
    onSuccess: () => {
      setPushMsg(`✓ Zu ${providerLabel ?? 'Kalender'} hinzugefügt.`)
      qc.invalidateQueries({ queryKey: ['appointments'] })
    },
    onError: (e: unknown) =>
      setPushMsg(e instanceof Error ? e.message : 'Übertragung fehlgeschlagen.'),
  })
  const afterMutate = () => {
    qc.invalidateQueries({ queryKey: ['appointments'] })
    // Same appointment row drives the call's open-action card + the worklist —
    // refresh them so a calendar cancel/change reflects back there.
    qc.invalidateQueries({ queryKey: ['pendingAppointment'] })
    qc.invalidateQueries({ queryKey: ['actions', 'pending'] })
    onClose()
  }
  // Cancel keeps the row (status='cancelled'); Delete hard-removes it. Both
  // propagate to Google (events.delete) server-side when the event was pushed.
  const cancel = useMutation({
    mutationFn: () => apiFetch(`/api/appointments/${appt.id}/cancel`, { method: 'POST' }),
    onSuccess: afterMutate,
    onError: (e: unknown) => setPushMsg(e instanceof Error ? e.message : 'Stornieren fehlgeschlagen.'),
  })
  // Confirm a tentative "Vorschlag" (pending) straight from the calendar. Backend
  // requires an assigned employee + a concrete time (else 409, surfaced here).
  const confirm = useMutation({
    mutationFn: () => apiFetch(`/api/appointments/${appt.id}/confirm`, { method: 'POST' }),
    onSuccess: afterMutate,
    onError: (e: unknown) => setPushMsg(e instanceof Error ? e.message : 'Bestätigen fehlgeschlagen.'),
  })
  const del = useMutation({
    mutationFn: () => apiFetch(`/api/appointments/${appt.id}`, { method: 'DELETE' }),
    onSuccess: afterMutate,
    onError: (e: unknown) => setPushMsg(e instanceof Error ? e.message : 'Löschen fehlgeschlagen.'),
  })
  // Techniker-Einsatz: nach der Terminbestätigung wird der Techniker hier
  // eingesetzt — er bekommt den Auftrags-Link (Einsatzbericht, Fotos) per E-Mail.
  const [dispatchEmp, setDispatchEmp] = useState(appt.assigned_employee_id ?? '')
  const [dispatchMsg, setDispatchMsg] = useState<string | null>(null)
  // Phase 1.5: technicians ranked for THIS slot — available first, 'verplant'
  // flagged — so a clashing technician is obvious (backend also 409s on conflict).
  const { data: availTechs } = useQuery({
    queryKey: ['available-technicians', appt.id],
    queryFn: () => apiFetch<AvailTech[]>(`/api/appointments/${appt.id}/available-technicians`),
    enabled: appt.source !== 'google_import' && appt.status === 'confirmed',
    staleTime: 30_000,
  })
  const selectedBusy = !!availTechs?.find((t) => t.id === dispatchEmp && !t.available)
  const techOptions: AvailTech[] =
    availTechs ??
    employees
      .filter((e) => e.is_technician && e.is_active !== false)
      .map((e) => ({ id: e.id, display_name: e.display_name, available: true, open_tickets: 0 }))
  const dispatch = useMutation({
    mutationFn: () =>
      apiFetch<{ success: boolean; email_status: string }>(
        `/api/appointments/${appt.id}/dispatch-technician`,
        { method: 'POST', body: JSON.stringify({ employee_id: dispatchEmp }) },
      ),
    onSuccess: (r) => {
      setDispatchMsg(
        r.email_status === 'sent'
          ? '✓ Auftrags-Link per E-Mail an den Techniker gesendet.'
          : 'Techniker zugewiesen — E-Mail konnte nicht gesendet werden (bitte erneut versuchen).',
      )
      qc.invalidateQueries({ queryKey: ['appointments'] })
    },
    onError: (e: unknown) =>
      setDispatchMsg(e instanceof Error ? e.message : 'Einsatz konnte nicht gesendet werden.'),
  })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={appt.title ?? 'Termin'}>
      <div className="space-y-3 text-sm">
        <div className="flex items-center gap-2">
          <span className="h-3 w-3 rounded-full" style={{ background: color }} />
          <span className="font-medium text-text">{appt.employee_name ?? 'Nicht zugewiesen'}</span>
          <span className="ml-auto rounded-full bg-alt px-2 py-0.5 text-xs font-medium text-muted">
            {STATUS_LABEL[appt.status] ?? appt.status}
          </span>
        </div>
        {start && (
          <DetailRow label="Zeit">
            {start.toLocaleDateString('de-DE', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Europe/Berlin' })} ·{' '}
            {hm(start)} Uhr ({appt.duration_minutes ?? 60} Min)
          </DetailRow>
        )}
        {appt.customer_name && <DetailRow label="Kunde">{appt.customer_name}</DetailRow>}
        {appt.customer_phone && <DetailRow label="Telefon">{appt.customer_phone}</DetailRow>}
        {/* Adresse and Ort are the same place: show ONE row. The appointment's
            own location wins; fall back to the customer's stored address. */}
        {(loc ?? appt.customer_address) && (
          <DetailRow label="Adresse">{loc ?? appt.customer_address}</DetailRow>
        )}
        {appt.notes && <DetailRow label="Notizen">{appt.notes}</DetailRow>}
        {appt.status === 'pending' && (
          <div className="rounded-md border border-dashed border-orange-300 bg-orange-50 px-3 py-2.5">
            <p className="text-xs font-medium text-orange-800">
              Terminvorschlag — vom Kunden gewünscht, noch nicht bestätigt. Bitte prüfen und bestätigen
              oder den Termin anpassen.
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <button
                onClick={() => confirm.mutate()}
                disabled={confirm.isPending}
                className="rounded-md bg-green-primary px-3 py-1.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
              >
                {confirm.isPending ? 'Wird bestätigt…' : 'Bestätigen'}
              </button>
              {appt.call_id && (
                <button
                  onClick={() => { onClose(); navigate(`/calls?call_id=${appt.call_id}`) }}
                  className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-body hover:bg-alt"
                >
                  Zum Anruf
                </button>
              )}
            </div>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
          {pushable && (
            alreadyPushed ? (
              <span className="text-sm font-medium text-success">✓ Im Kalender</span>
            ) : canPush ? (
              <button
                onClick={() => push.mutate()}
                disabled={push.isPending}
                className="flex-1 rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
              >
                {push.isPending ? 'Wird übertragen…' : `Zu ${providerLabel} hinzufügen`}
              </button>
            ) : (
              <button
                disabled
                title={pushDisabledReason}
                className="flex-1 cursor-not-allowed rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white opacity-50"
              >
                Zum Kalender hinzufügen
              </button>
            )
          )}
          <button
            onClick={onReschedule}
            className="flex-1 rounded-md bg-warning px-4 py-2 text-sm font-semibold text-white hover:brightness-110"
          >
            Verschieben / Bearbeiten
          </button>
        </div>
        {pushable && !canPush && !alreadyPushed && <p className="text-xs text-muted">{pushDisabledReason}</p>}
        {pushMsg && <p className="text-xs text-muted">{pushMsg}</p>}
        {appt.source !== 'google_import' && appt.status === 'confirmed' && (
          <div className="border-t border-border pt-3">
            <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
              Techniker einsetzen
            </div>
            <div className="flex gap-2">
              <select
                value={dispatchEmp}
                onChange={(e) => setDispatchEmp(e.target.value)}
                className="min-w-0 flex-1 rounded-md border border-border bg-alt px-3 py-2 text-sm text-text outline-none focus:border-green-primary"
              >
                <option value="">Techniker wählen…</option>
                {techOptions.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.display_name} — {t.available ? 'verfügbar' : 'verplant'}
                    {t.open_tickets ? ` · ${t.open_tickets} offen` : ''}
                  </option>
                ))}
              </select>
              <button
                onClick={() => dispatch.mutate()}
                disabled={!dispatchEmp || dispatch.isPending}
                className="shrink-0 rounded-md bg-green-primary px-3 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
              >
                {dispatch.isPending ? 'Sendet…' : 'Auftrag senden'}
              </button>
            </div>
            {selectedBusy && (
              <p className="mt-1.5 text-xs font-medium text-amber-600">
                Dieser Techniker ist zu diesem Zeitpunkt bereits verplant — bitte einen verfügbaren wählen.
              </p>
            )}
            <p className="mt-1.5 text-xs text-muted">
              Der Techniker erhält per E-Mail einen Link mit allen Einsatzdaten und füllt dort den
              Einsatzbericht aus (Start/Ende, Fragen, Fotos) — ohne Anmeldung. Der Bericht erscheint im Vorgang.
            </p>
            {dispatchMsg && <p className="mt-1 text-xs font-medium text-green-deep">{dispatchMsg}</p>}
          </div>
        )}
        <div className="flex items-center justify-between border-t border-border pt-3">
          <button
            onClick={() => cancel.mutate()}
            disabled={cancel.isPending}
            className="rounded-md border border-border bg-surface px-3 py-1.5 text-sm font-medium text-body hover:bg-alt disabled:opacity-60"
          >
            {cancel.isPending ? 'Storniert…' : 'Stornieren'}
          </button>
          <button
            onClick={() => { if (window.confirm('Diesen Termin endgültig löschen?')) del.mutate() }}
            disabled={del.isPending}
            className="rounded-md border border-red-200 px-3 py-1.5 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-60"
          >
            {del.isPending ? 'Wird gelöscht…' : 'Löschen'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-0.5 text-text">{children}</div>
    </div>
  )
}

// ─── Create modal ────────────────────────────────────────────────────────────
const inputCls =
  'w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary'

function CreateAppointmentModal({
  at,
  edit,
  liveFill,
  employees,
  appointments = [],
  colorFor,
  onClose,
  onCreated,
}: {
  at: Date
  edit?: Appointment
  liveFill?: LiveFillPayload
  employees: Employee[]
  appointments?: Appointment[]
  colorFor: (id: string | null) => string
  onClose: () => void
  onCreated: (created?: Appointment) => void
}) {
  const [customerId, setCustomerId] = useState(edit?.customer_id ?? '')
  const [title, setTitle] = useState(edit?.title ?? '')
  const [date, setDate] = useState(edit?.scheduled_at ? ymd(new Date(edit.scheduled_at)) : ymd(at))
  const [time, setTime] = useState(edit?.scheduled_at ? hm(new Date(edit.scheduled_at)) : hm(at))
  const [duration, setDuration] = useState(edit?.duration_minutes ?? 60)
  const [assigned, setAssigned] = useState(edit?.assigned_employee_id ?? '')
  const [location, setLocation] = useState(edit ? (locStr(edit.location) ?? '') : '')
  const [error, setError] = useState<string | null>(null)

  // Non-blocking double-booking hint: how many active appointments overlap the
  // chosen window. Whether that is fine is governed by the Terminregeln
  // ("Parallele Termine") — we only surface the overlap, never block.
  const overlapCount = useMemo(() => {
    if (!date || !time) return 0
    const start = new Date(`${date}T${time}`).getTime()
    const end = start + duration * 60000
    return appointments.filter((a) => {
      if (a.id === edit?.id || !a.scheduled_at) return false
      if (a.status === 'cancelled' || a.status === 'completed') return false
      const s = new Date(a.scheduled_at).getTime()
      const e = s + (a.duration_minutes ?? 60) * 60000
      return start < e && end > s
    }).length
  }, [appointments, date, time, duration, edit?.id])

  const { data: customerData } = useQuery({
    queryKey: ['customers-options'],
    queryFn: () => apiFetch<{ customers: CustomerOption[] }>('/api/customers?limit=500'),
  })
  const customers = customerData?.customers ?? []

  // No backdating: block saving a NEW appointment whose date/time is already in
  // the past (the server rejects it with 422 too). Edits are exempt so a past
  // appointment stays editable.
  const isPast = useMemo(() => {
    if (edit || !date || !time) return false
    return new Date(`${date}T${time}`).getTime() <= Date.now()
  }, [edit, date, time])

  // Hey-Kiki takeover: fill the form visibly (customer → title typed →
  // employee), then save with the exact same payload that was animated.
  const [kikiFilling, setKikiFilling] = useState(false)
  const liveFillStarted = useRef(false)

  // Adresse → Ort: when a customer is selected, prefill the Ort from their stored
  // address so the user never re-types an address the customer already has. Only
  // fills an EMPTY field (never stomps a typed/edited Ort), and stays out of the
  // way of the Kiki live-fill takeover (which drives the field itself).
  useEffect(() => {
    if (kikiFilling || !customerId) return
    const addr = locStr(customers.find((c) => c.id === customerId)?.address ?? null)
    if (addr) setLocation((prev) => (prev.trim() ? prev : addr))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId, customerData])
  useEffect(() => {
    if (!liveFill || liveFillStarted.current || edit || !customerData) return
    liveFillStarted.current = true
    const run = async () => {
      setKikiFilling(true)
      // Tell the panel the takeover is live — it cancels its 60s fallback so
      // the write can never execute twice (panel + script).
      emitLiveFillStatus({ tool: 'create_appointment', status: 'started' })
      try {
        const args = liveFill.args || {}
        await sleep(700)

        // 1) Customer: UUID directly, otherwise EXACT unique name match —
        // ambiguous/no match fails over to the API path (server-side resolve).
        const ref = String(args.customer_id || args.customer || '').trim()
        let cid = ''
        if (/^[0-9a-f-]{36}$/i.test(ref)) {
          cid = ref
        } else if (ref) {
          const needle = ref.toLowerCase()
          const hits = (customerData.customers ?? []).filter(
            (c) => (c.full_name || '').trim().toLowerCase() === needle,
          )
          if (hits.length !== 1) {
            throw new Error(
              hits.length === 0
                ? `Kunde „${ref}“ nicht eindeutig gefunden`
                : `Mehrere Kunden namens „${ref}“ — bitte eindeutig wählen`,
            )
          }
          cid = hits[0].id
        }
        if (cid) {
          setCustomerId(cid)
          await sleep(600)
        }

        // 2) Title — typed character by character.
        const wantedTitle = String(args.title || 'Termin').trim()
        for (let i = 1; i <= wantedTitle.length; i++) {
          setTitle(wantedTitle.slice(0, i))
          await sleep(18)
        }
        await sleep(300)

        // 3) Time, duration, location, employee.
        const start = args.scheduled_at ? new Date(args.scheduled_at) : at
        setDate(ymd(start))
        setTime(hm(start))
        await sleep(400)
        const dur = Number(args.duration_minutes ?? 60)
        setDuration(dur)
        const loc = String(args.location || '')
        if (loc) {
          setLocation(loc)
          await sleep(300)
        }
        const emp = String(args.assigned_employee_id || '')
        if (emp) {
          setAssigned(emp)
          await sleep(300)
        }
        await sleep(700)

        // 4) Save — payload built here (state closures would be stale).
        const created = await apiFetch<Appointment>('/api/appointments', {
          method: 'POST',
          body: JSON.stringify({
            customer_id: cid || null,
            title: wantedTitle,
            scheduled_at: start.toISOString(),
            duration_minutes: dur,
            location: loc || null,
            notes: args.notes ? String(args.notes) : null,
            color: colorFor(emp || null),
            assigned_employee_id: emp || null,
          }),
        })
        // The raw insert row carries no joined names — patch them in so the
        // detail modal that opens next shows the customer immediately.
        if (cid && !created.customer_name) {
          created.customer_name =
            (customerData.customers ?? []).find((c) => c.id === cid)?.full_name ?? null
        }
        emitLiveFillStatus({
          tool: 'create_appointment',
          status: 'done',
          note: 'Termin direkt ausgefüllt & gespeichert',
        })
        onCreated(created)
      } catch (e) {
        emitLiveFillStatus({
          tool: 'create_appointment',
          status: 'failed',
          note: e instanceof Error ? e.message : 'Formular konnte nicht ausgefüllt werden',
        })
        onClose()
      } finally {
        setKikiFilling(false)
      }
    }
    void run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveFill, customerData, edit])

  const create = useMutation({
    mutationFn: () => {
      const body = JSON.stringify({
        customer_id: customerId || null,
        title: title || 'Termin',
        scheduled_at: new Date(`${date}T${time}`).toISOString(),
        duration_minutes: duration,
        location: location || null,
        color: colorFor(assigned || null),
        assigned_employee_id: assigned || null,
      })
      return edit
        ? apiFetch(`/api/appointments/${edit.id}`, { method: 'PATCH', body })
        : apiFetch('/api/appointments', { method: 'POST', body })
    },
    onSuccess: () => onCreated(),
    onError: () => setError(edit ? 'Termin konnte nicht geändert werden.' : 'Termin konnte nicht erstellt werden.'),
  })

  return (
    <Modal
      open
      onOpenChange={(o) => !o && !kikiFilling && onClose()}
      title={edit ? 'Termin verschieben / bearbeiten' : 'Neuer Termin'}
      widthClass="max-w-xl"
      footer={
        <div className="flex gap-3">
          <button
            disabled={!date || isPast || create.isPending || kikiFilling}
            onClick={() => create.mutate()}
            className="flex-1 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
          >
            {create.isPending ? 'Speichert…' : edit ? 'Änderungen speichern' : 'Termin speichern'}
          </button>
          <button
            onClick={onClose}
            disabled={kikiFilling}
            className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body disabled:opacity-50"
          >
            Abbrechen
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        {kikiFilling && (
          <div className="flex items-center gap-2 rounded-lg border border-ai/30 bg-ai-bg px-4 py-2.5 text-sm font-semibold text-ai shadow-e1">
            <Loader2 size={15} className="animate-spin" />
            Kiki füllt den Termin aus … bitte kurz zusehen, gespeichert wird automatisch.
          </div>
        )}
        {error && <div className="rounded-md bg-error-bg px-3 py-2 text-sm text-error">{error}</div>}
        {isPast && (
          <div className="rounded-md bg-error-bg px-3 py-2 text-sm text-error">
            Dieser Termin liegt in der Vergangenheit. Bitte Datum und Uhrzeit in der Zukunft wählen.
          </div>
        )}
        {overlapCount > 0 && (
          <div className="rounded-md bg-warning-bg px-3 py-2 text-sm text-warning">
            Zur gewählten Zeit {overlapCount === 1 ? 'existiert bereits 1 Termin' : `existieren bereits ${overlapCount} Termine`}.
            Ob parallele Termine zulässig sind, regeln die Terminregeln („Parallele Termine“) — du kannst trotzdem speichern.
          </div>
        )}
        <div>
          <div className="mb-1.5 text-xs font-semibold text-body">Kunde</div>
          <select value={customerId} onChange={(e) => setCustomerId(e.target.value)} className={inputCls}>
            <option value="">— Privat (kein Kunde) —</option>
            {customers.map((c) => (
              <option key={c.id} value={c.id}>
                {c.full_name ?? 'Unbenannt'}
              </option>
            ))}
          </select>
        </div>
        <div>
          <div className="mb-1.5 text-xs font-semibold text-body">Titel</div>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="z. B. Vor-Ort-Termin"
            className={inputCls}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <div className="mb-1.5 text-xs font-semibold text-body">Datum *</div>
            <input
              type="date"
              value={date}
              min={edit ? undefined : ymd(new Date())}
              onChange={(e) => setDate(e.target.value)}
              className={inputCls}
            />
          </div>
          <div>
            <div className="mb-1.5 text-xs font-semibold text-body">Uhrzeit *</div>
            <input type="time" value={time} onChange={(e) => setTime(e.target.value)} className={inputCls} />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <div className="mb-1.5 text-xs font-semibold text-body">Dauer</div>
            <select value={duration} onChange={(e) => setDuration(Number(e.target.value))} className={inputCls}>
              {[30, 60, 90, 120, 180].map((m) => (
                <option key={m} value={m}>
                  {m} Min
                </option>
              ))}
            </select>
          </div>
          <div>
            <div className="mb-1.5 text-xs font-semibold text-body">Mitarbeiter</div>
            <select value={assigned} onChange={(e) => setAssigned(e.target.value)} className={inputCls}>
              <option value="">Nicht zugewiesen</option>
              {employees.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.display_name}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div>
          <div className="mb-1.5 text-xs font-semibold text-body">Adresse</div>
          <input
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            placeholder="Straße, Nr., PLZ Ort"
            className={inputCls}
          />
          <p className="mt-1 text-[11px] text-muted">
            Wird mit der Kundenadresse synchronisiert.
          </p>
        </div>
      </div>
    </Modal>
  )
}
