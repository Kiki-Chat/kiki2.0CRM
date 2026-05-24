import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronLeft,
  ChevronRight,
  Clock,
  LayoutGrid,
  MapPin,
  Plus,
  Truck,
  User,
  Wrench,
} from 'lucide-react'
import { useState } from 'react'

import { apiFetch } from '../lib/api'
import { cn } from '../lib/utils'

// ─── Types ───────────────────────────────────────────────────────────────────
interface Appt {
  id: string
  title: string | null
  scheduled_at: string | null
  duration_minutes: number | null
  status: string
  location: { raw?: string } | string | null
  customer_name: string | null
  employee_name: string | null
  vehicle_id: string | null
  tool_id: string | null
}
interface Vehicle {
  id: string
  name: string
  model: string | null
  license_plate: string | null
  capacity_hours: number | null
  assigned_employee_id: string | null
  color: string | null
}
interface Tool {
  id: string
  name: string
  category: string | null
  assigned_employee_id: string | null
}
interface BoardData {
  date: string
  appointments: Appt[]
  vehicles: Vehicle[]
  tools: Tool[]
}

const WD = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa']
const pad = (n: number) => String(n).padStart(2, '0')
const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const addDays = (d: Date, n: number) => {
  const r = new Date(d)
  r.setDate(r.getDate() + n)
  return r
}
const hm = (iso: string | null) => (iso ? new Date(iso).toTimeString().slice(0, 5) : '')
const locStr = (l: Appt['location']) => (!l ? null : typeof l === 'string' ? l : l.raw ?? null)
const UNASSIGNED = 'NONE'

export function PlanningBoardPage() {
  const qc = useQueryClient()
  const [selected, setSelected] = useState(() => ymd(new Date()))
  const [stripStart, setStripStart] = useState(() => new Date())
  const [view, setView] = useState<'day' | 'timeline'>('day')
  const [activeAppt, setActiveAppt] = useState<Appt | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const flash = (m: string) => {
    setToast(m)
    setTimeout(() => setToast(null), 4000)
  }

  const stripDays = Array.from({ length: 14 }, (_, i) => addDays(stripStart, i))

  // Strip counts: all appointments in the visible 14-day window.
  const stripFrom = new Date(`${ymd(stripStart)}T00:00:00.000Z`).toISOString()
  const stripTo = new Date(`${ymd(addDays(stripStart, 14))}T00:00:00.000Z`).toISOString()
  const { data: stripAppts = [] } = useQuery({
    queryKey: ['appointments', stripFrom, stripTo],
    queryFn: () => apiFetch<Appt[]>(`/api/appointments?from=${stripFrom}&to=${stripTo}`),
  })
  const countFor = (d: Date) =>
    stripAppts.filter((a) => a.scheduled_at?.slice(0, 10) === ymd(d) && a.status !== 'cancelled').length

  const { data: board } = useQuery({
    queryKey: ['planning-board', selected],
    queryFn: () => apiFetch<BoardData>(`/api/planning-board?date=${selected}`),
  })
  const appts = board?.appointments ?? []
  const vehicles = board?.vehicles ?? []
  const tools = board?.tools ?? []

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))

  const assign = useMutation({
    mutationFn: ({ id, field, value }: { id: string; field: 'vehicle_id' | 'tool_id'; value: string | null }) =>
      apiFetch(`/api/appointments/${id}`, { method: 'PATCH', body: JSON.stringify({ [field]: value }) }),
    onMutate: async ({ id, field, value }) => {
      await qc.cancelQueries({ queryKey: ['planning-board', selected] })
      const prev = qc.getQueryData<BoardData>(['planning-board', selected])
      if (prev) {
        qc.setQueryData<BoardData>(['planning-board', selected], {
          ...prev,
          appointments: prev.appointments.map((a) => (a.id === id ? { ...a, [field]: value } : a)),
        })
      }
      return { prev }
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(['planning-board', selected], ctx.prev)
      flash('Zuweisung fehlgeschlagen.')
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ['planning-board', selected] }),
  })

  const moveSelected = (delta: number) => {
    const next = addDays(new Date(`${selected}T12:00:00`), delta)
    setSelected(ymd(next))
    if (next < stripStart || next >= addDays(stripStart, 14)) setStripStart(next)
  }

  const onDragStart = (e: DragStartEvent) => {
    const id = String(e.active.id).split('|')[1]
    setActiveAppt(appts.find((a) => a.id === id) ?? null)
  }
  const onDragEnd = (e: DragEndEvent) => {
    setActiveAppt(null)
    const { active, over } = e
    if (!over) return
    const [aSec, apptId] = String(active.id).split('|')
    const [oSec, colKey] = String(over.id).split('|')
    if (aSec !== oSec) return
    const field = aSec === 'veh' ? 'vehicle_id' : 'tool_id'
    const value = colKey === UNASSIGNED ? null : colKey
    const appt = appts.find((a) => a.id === apptId)
    if (!appt) return
    if ((appt[field] ?? null) === value) return
    assign.mutate({ id: apptId, field, value })
  }

  const selectedDateObj = new Date(`${selected}T12:00:00`)

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <LayoutGrid size={26} className="text-green-primary" />
          <div>
            <h1 className="text-2xl font-bold text-text">Planungstafel</h1>
            <p className="mt-0.5 text-sm text-muted">Termine Fahrzeugen und Werkzeug zuweisen</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1">
            <button onClick={() => moveSelected(-1)} className="rounded-md border border-border p-2 text-body hover:bg-alt">
              <ChevronLeft size={16} />
            </button>
            <button
              onClick={() => {
                setSelected(ymd(new Date()))
                setStripStart(new Date())
              }}
              className="rounded-md border border-border px-3 py-2 text-sm font-medium text-body hover:bg-alt"
            >
              Heute
            </button>
            <button onClick={() => moveSelected(1)} className="rounded-md border border-border p-2 text-body hover:bg-alt">
              <ChevronRight size={16} />
            </button>
          </div>
          <input
            type="date"
            value={selected}
            onChange={(e) => {
              if (!e.target.value) return
              setSelected(e.target.value)
              setStripStart(new Date(`${e.target.value}T12:00:00`))
            }}
            className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-green-primary"
          />
          <div className="flex gap-0.5 rounded-lg border border-border bg-alt p-1">
            {(['day', 'timeline'] as const).map((v) => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={cn(
                  'rounded-md px-3 py-1.5 text-sm transition-colors',
                  view === v ? 'bg-surface font-semibold text-text shadow-e1' : 'font-medium text-muted',
                )}
              >
                {v === 'day' ? 'Tag' : 'Timeline'}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Date strip */}
      <div className="mb-5 flex gap-2 overflow-x-auto pb-2">
        {stripDays.map((d) => {
          const isSel = ymd(d) === selected
          const count = countFor(d)
          return (
            <button
              key={ymd(d)}
              onClick={() => setSelected(ymd(d))}
              className={cn(
                'flex min-w-[84px] flex-col items-center rounded-lg border px-3 py-2 transition-colors',
                isSel ? 'border-green-primary bg-surface shadow-e1' : 'border-border bg-surface hover:bg-alt',
              )}
            >
              <span className="text-[11px] font-medium uppercase text-muted">{WD[d.getDay()]}</span>
              <span className="text-lg font-bold text-text">{d.getDate()}.</span>
              {count > 0 ? (
                <span className="mt-0.5 inline-flex items-center gap-1 text-[11px] font-medium text-green-deep">
                  <span className="h-1.5 w-1.5 rounded-full bg-green-primary" />
                  {count} {count === 1 ? 'Termin' : 'Termine'}
                </span>
              ) : (
                <span className="mt-0.5 text-[11px] text-faint">—</span>
              )}
              {isSel && <span className="mt-1 h-0.5 w-8 rounded-full bg-green-primary" />}
            </button>
          )
        })}
      </div>

      {toast && (
        <div className="mb-3 rounded-md bg-error-bg px-3 py-2 text-sm font-medium text-error">{toast}</div>
      )}

      <p className="mb-4 text-sm font-medium text-body">
        {selectedDateObj.toLocaleDateString('de-DE', {
          weekday: 'long',
          day: 'numeric',
          month: 'long',
          year: 'numeric',
        })}
      </p>

      {view === 'timeline' ? (
        <div className="rounded-xl border border-dashed border-border py-20 text-center text-sm text-muted">
          Timeline-Ansicht folgt im nächsten Schritt.
        </div>
      ) : (
        <DndContext sensors={sensors} onDragStart={onDragStart} onDragEnd={onDragEnd}>
          {/* FAHRZEUGE */}
          <Section
            icon={<Truck size={16} />}
            title="FAHRZEUGE"
            hint="Termin in die Fahrzeugspalte ziehen"
            onAdd={() => flash('„Fahrzeug hinzufügen" wird im nächsten Schritt aktiviert.')}
            addLabel="Fahrzeug hinzufügen"
          >
            <Column
              id={`veh|${UNASSIGNED}`}
              title="Nicht zugewiesen"
              subtitle="Termine ohne Fahrzeug"
              count={appts.filter((a) => !a.vehicle_id).length}
            >
              {appts.filter((a) => !a.vehicle_id).map((a) => (
                <ApptCard key={a.id} dragId={`veh|${a.id}`} appt={a} />
              ))}
            </Column>
            {vehicles.map((v) => (
              <Column
                key={v.id}
                id={`veh|${v.id}`}
                title={v.name}
                subtitle={v.model ?? v.license_plate ?? ''}
                capacity={`— / ${v.capacity_hours ?? 8}h`}
                count={appts.filter((a) => a.vehicle_id === v.id).length}
                color={v.color}
              >
                {appts.filter((a) => a.vehicle_id === v.id).map((a) => (
                  <ApptCard key={a.id} dragId={`veh|${a.id}`} appt={a} />
                ))}
              </Column>
            ))}
          </Section>

          {/* WERKZEUG */}
          <Section
            icon={<Wrench size={16} />}
            title="WERKZEUG"
            hint="Termin in die Werkzeugspalte ziehen"
            onAdd={() => flash('„Werkzeug hinzufügen" wird im nächsten Schritt aktiviert.')}
            addLabel="Werkzeug hinzufügen"
          >
            <Column
              id={`tool|${UNASSIGNED}`}
              title="Kein Werkzeug erforderlich"
              subtitle="Termine ohne Werkzeugzuweisung"
              count={appts.filter((a) => !a.tool_id).length}
            >
              {appts.filter((a) => !a.tool_id).map((a) => (
                <ApptCard key={a.id} dragId={`tool|${a.id}`} appt={a} />
              ))}
            </Column>
            {tools.map((t) => (
              <Column
                key={t.id}
                id={`tool|${t.id}`}
                title={t.name}
                subtitle={t.category ?? ''}
                count={appts.filter((a) => a.tool_id === t.id).length}
              >
                {appts.filter((a) => a.tool_id === t.id).map((a) => (
                  <ApptCard key={a.id} dragId={`tool|${a.id}`} appt={a} />
                ))}
              </Column>
            ))}
          </Section>

          <DragOverlay>{activeAppt && <ApptCardBody appt={activeAppt} dragging />}</DragOverlay>
        </DndContext>
      )}
    </div>
  )
}

// ─── Section ─────────────────────────────────────────────────────────────────
function Section({
  icon,
  title,
  hint,
  addLabel,
  onAdd,
  children,
}: {
  icon: React.ReactNode
  title: string
  hint: string
  addLabel: string
  onAdd: () => void
  children: React.ReactNode
}) {
  return (
    <div className="mb-8">
      <div className="mb-3 flex items-center gap-2 text-muted">
        {icon}
        <span className="text-xs font-bold uppercase tracking-wide text-body">{title}</span>
        <span className="text-xs">{hint}</span>
      </div>
      <div className="flex items-start gap-3 overflow-x-auto pb-2">
        {children}
        <button
          onClick={onAdd}
          className="flex min-h-[120px] min-w-[180px] flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-border text-sm font-medium text-muted hover:bg-alt"
        >
          <Plus size={18} />
          {addLabel}
        </button>
      </div>
    </div>
  )
}

// ─── Column (droppable) ──────────────────────────────────────────────────────
function Column({
  id,
  title,
  subtitle,
  count,
  capacity,
  color,
  children,
}: {
  id: string
  title: string
  subtitle?: string
  count: number
  capacity?: string
  color?: string | null
  children: React.ReactNode
}) {
  const { setNodeRef, isOver } = useDroppable({ id })
  const hasItems = Array.isArray(children) ? children.length > 0 : !!children
  return (
    <div
      ref={setNodeRef}
      className={cn(
        'flex w-[280px] shrink-0 flex-col rounded-xl border bg-surface p-3 transition-colors',
        isOver ? 'border-green-primary ring-2 ring-green-primary/40' : 'border-border',
      )}
    >
      <div className="mb-3 flex items-start justify-between gap-2 border-b border-border-faint pb-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            {color && <span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} />}
            <span className="truncate text-sm font-bold text-text">{title}</span>
          </div>
          {subtitle && <div className="truncate text-xs text-muted">{subtitle}</div>}
          {capacity && <div className="mt-0.5 text-xs text-muted">{capacity}</div>}
        </div>
        <span className="shrink-0 rounded-full bg-alt px-2 py-0.5 text-xs font-semibold text-muted">{count}</span>
      </div>
      <div className="flex flex-1 flex-col gap-2">
        {children}
        {isOver && (
          <div className="rounded-lg border-2 border-dashed border-green-primary/60 py-4 text-center text-xs font-medium text-green-deep">
            Hier ablegen
          </div>
        )}
        {!hasItems && !isOver && (
          <div className="py-6 text-center text-xs text-faint">Hierher ziehen</div>
        )}
      </div>
    </div>
  )
}

// ─── Appointment card (draggable) ────────────────────────────────────────────
function ApptCard({ dragId, appt }: { dragId: string; appt: Appt }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: dragId })
  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className={cn('cursor-grab touch-none', isDragging && 'opacity-40')}
    >
      <ApptCardBody appt={appt} />
    </div>
  )
}

function ApptCardBody({ appt, dragging }: { appt: Appt; dragging?: boolean }) {
  const loc = locStr(appt.location)
  return (
    <div
      className={cn(
        'rounded-lg border border-border bg-surface p-3 shadow-e1',
        dragging && 'rotate-1 shadow-e3',
      )}
    >
      <div className="flex items-center gap-1.5 text-xs text-muted">
        <Clock size={12} />
        {hm(appt.scheduled_at)} · {appt.duration_minutes ?? 60} min
      </div>
      <div className="mt-1 flex items-center gap-1.5 text-sm font-semibold text-text">
        <User size={13} className="text-muted" />
        {appt.customer_name ?? appt.title ?? 'Termin'}
      </div>
      {loc && (
        <div className="mt-1 flex items-center gap-1.5 text-xs text-muted">
          <MapPin size={12} />
          <span className="truncate">{loc}</span>
        </div>
      )}
    </div>
  )
}
