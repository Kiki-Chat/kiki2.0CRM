import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
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
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Clock,
  Filter as FilterIcon,
  LayoutGrid,
  MapPin,
  MoreVertical,
  Pencil,
  Plus,
  Power,
  Truck,
  User,
  UserPlus,
  Wrench,
} from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Modal } from '../components/ui/Modal'
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
  assigned_employee_id: string | null
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
  notes: string | null
  last_seen: string | null
}
interface Tool {
  id: string
  name: string
  category: string | null
  serial_number: string | null
  assigned_employee_id: string | null
  storage_location: string | null
  notes: string | null
  last_seen: string | null
}
interface Employee {
  id: string
  display_name: string
}

const WD = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa']
const COLOR_SWATCHES = [
  '#2D6B3D', '#4A9B3F', '#1E4D2B', '#0891B2', '#2563EB', '#1E3A8A',
  '#7C3AED', '#DB2777', '#DC2626', '#D97706', '#64748B',
]
const TOOL_CATEGORIES = ['Elektrowerkzeug', 'Handwerkzeug', 'Messgerät', 'Schutzausrüstung', 'Sonstiges']
const HOURS = Array.from({ length: 14 }, (_, i) => 7 + i) // 07..20
const HOUR_W = 76
const ROW_H = 56

const pad = (n: number) => String(n).padStart(2, '0')
const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const addDays = (d: Date, n: number) => {
  const r = new Date(d)
  r.setDate(r.getDate() + n)
  return r
}
const hm = (iso: string | null) => (iso ? new Date(iso).toTimeString().slice(0, 5) : '')
const locStr = (l: Appt['location']) => (!l ? null : typeof l === 'string' ? l : l.raw ?? null)
const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString('de-DE', { day: 'numeric', month: 'short', year: 'numeric' }) : '—'
const UNASSIGNED = 'NONE'
const inputCls =
  'w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary'
const labelCls = 'mb-1.5 block text-xs font-semibold text-body'

export function PlanningBoardPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [selected, setSelected] = useState(() => ymd(new Date()))
  const [stripStart, setStripStart] = useState(() => new Date())
  const [view, setView] = useState<'day' | 'timeline'>('day')
  const [activeAppt, setActiveAppt] = useState<Appt | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [filter, setFilter] = useState<{ employee: string; status: string }>({ employee: 'all', status: 'all' })
  // modals
  const [newVehicle, setNewVehicle] = useState(false)
  const [editVehicle, setEditVehicle] = useState<Vehicle | null>(null)
  const [newTool, setNewTool] = useState(false)
  const [editTool, setEditTool] = useState<Tool | null>(null)
  const [detailAppt, setDetailAppt] = useState<Appt | null>(null)
  const [createAt, setCreateAt] = useState<{ at: Date; vehicle_id?: string; tool_id?: string } | null>(null)

  const flash = (m: string) => {
    setToast(m)
    setTimeout(() => setToast(null), 4000)
  }

  const { data: employees = [] } = useQuery({
    queryKey: ['employees'],
    queryFn: () => apiFetch<Employee[]>('/api/employees'),
  })
  const { data: vehicles = [] } = useQuery({
    queryKey: ['vehicles'],
    queryFn: () => apiFetch<Vehicle[]>('/api/vehicles'),
  })
  const { data: tools = [] } = useQuery({
    queryKey: ['tools'],
    queryFn: () => apiFetch<Tool[]>('/api/tools'),
  })

  const stripDays = Array.from({ length: 14 }, (_, i) => addDays(stripStart, i))
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
    queryFn: () => apiFetch<{ appointments: Appt[] }>(`/api/planning-board?date=${selected}`),
  })
  const allAppts = board?.appointments ?? []
  const appts = useMemo(
    () =>
      allAppts.filter(
        (a) =>
          (filter.employee === 'all' || a.assigned_employee_id === filter.employee) &&
          (filter.status === 'all' || a.status === filter.status),
      ),
    [allAppts, filter],
  )

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))

  const assign = useMutation({
    mutationFn: ({ id, field, value }: { id: string; field: 'vehicle_id' | 'tool_id'; value: string | null }) =>
      apiFetch(`/api/appointments/${id}`, { method: 'PATCH', body: JSON.stringify({ [field]: value }) }),
    onMutate: async ({ id, field, value }) => {
      await qc.cancelQueries({ queryKey: ['planning-board', selected] })
      const prev = qc.getQueryData<{ appointments: Appt[] }>(['planning-board', selected])
      if (prev) {
        qc.setQueryData(['planning-board', selected], {
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

  const assignAsset = useMutation({
    mutationFn: ({ kind, id, employeeId }: { kind: 'vehicles' | 'tools'; id: string; employeeId: string | null }) =>
      apiFetch(`/api/${kind}/${id}`, { method: 'PATCH', body: JSON.stringify({ assigned_employee_id: employeeId }) }),
    onMutate: async ({ kind, id, employeeId }) => {
      await qc.cancelQueries({ queryKey: [kind] })
      const prev = qc.getQueryData<(Vehicle | Tool)[]>([kind])
      if (prev) {
        qc.setQueryData<(Vehicle | Tool)[]>(
          [kind],
          prev.map((a) => (a.id === id ? { ...a, assigned_employee_id: employeeId } : a)),
        )
      }
      return { prev, kind }
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData([ctx.kind], ctx.prev)
      flash('Zuweisung fehlgeschlagen.')
    },
    onSuccess: () => flash('Mitarbeiter zugewiesen.'),
    onSettled: (_d, _e, v) => qc.invalidateQueries({ queryKey: [v.kind] }),
  })
  const deactivate = useMutation({
    mutationFn: ({ kind, id }: { kind: 'vehicles' | 'tools'; id: string }) =>
      apiFetch(`/api/${kind}/${id}`, { method: 'DELETE' }),
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: [v.kind] })
      flash('Deaktiviert.')
    },
    onError: () => flash('Aktion fehlgeschlagen.'),
  })

  const moveSelected = (delta: number) => {
    const next = addDays(new Date(`${selected}T12:00:00`), delta)
    setSelected(ymd(next))
    if (next < stripStart || next >= addDays(stripStart, 14)) setStripStart(next)
  }

  const onDragStart = (e: DragStartEvent) =>
    setActiveAppt(appts.find((a) => a.id === String(e.active.id).split('|')[1]) ?? null)
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
    if (!appt || (appt[field] ?? null) === value) return
    assign.mutate({ id: apptId, field, value })
  }

  const showInCalendar = (employeeId: string | null) =>
    navigate(employeeId ? `/calendar?employee=${employeeId}` : '/calendar')

  const selectedDateObj = new Date(`${selected}T12:00:00`)
  const filterActive = filter.employee !== 'all' || filter.status !== 'all'

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
          {/* Filter */}
          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
              <button
                className={cn(
                  'inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm font-medium',
                  filterActive ? 'border-green-primary bg-green-tint-50 text-green-deep' : 'border-border text-body hover:bg-alt',
                )}
              >
                <FilterIcon size={15} /> Filter
              </button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content align="end" sideOffset={6} className="z-50 min-w-56 rounded-lg border border-border bg-surface p-2 shadow-e2">
                <div className="px-2 py-1 text-xs font-semibold uppercase text-muted">Mitarbeiter</div>
                <FilterRow label="Alle" active={filter.employee === 'all'} onClick={() => setFilter((f) => ({ ...f, employee: 'all' }))} />
                {employees.map((e) => (
                  <FilterRow key={e.id} label={e.display_name} active={filter.employee === e.id} onClick={() => setFilter((f) => ({ ...f, employee: e.id }))} />
                ))}
                <div className="my-1 border-t border-border" />
                <div className="px-2 py-1 text-xs font-semibold uppercase text-muted">Status</div>
                {[['all', 'Alle'], ['pending', 'Offen'], ['confirmed', 'Bestätigt'], ['completed', 'Erledigt']].map(([v, l]) => (
                  <FilterRow key={v} label={l} active={filter.status === v} onClick={() => setFilter((f) => ({ ...f, status: v }))} />
                ))}
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
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

      {toast && <div className="mb-3 rounded-md bg-green-tint-50 px-3 py-2 text-sm font-medium text-green-deep">{toast}</div>}

      <p className="mb-4 text-sm font-medium text-body">
        {selectedDateObj.toLocaleDateString('de-DE', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
      </p>

      {view === 'timeline' ? (
        <TimelineView
          appts={appts}
          vehicles={vehicles}
          tools={tools}
          onBlock={setDetailAppt}
          onSlot={(at, row) => setCreateAt({ at, vehicle_id: row.vehicle_id, tool_id: row.tool_id })}
        />
      ) : (
        <DndContext sensors={sensors} onDragStart={onDragStart} onDragEnd={onDragEnd}>
          <Section icon={<Truck size={16} />} title="FAHRZEUGE" hint="Termin in die Fahrzeugspalte ziehen" addLabel="Fahrzeug hinzufügen" onAdd={() => setNewVehicle(true)}>
            <Column id={`veh|${UNASSIGNED}`} title="Nicht zugewiesen" subtitle="Termine ohne Fahrzeug" count={appts.filter((a) => !a.vehicle_id).length}>
              {appts.filter((a) => !a.vehicle_id).map((a) => <ApptCard key={a.id} dragId={`veh|${a.id}`} appt={a} onView={() => setDetailAppt(a)} />)}
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
                assignee={employees.find((e) => e.id === v.assigned_employee_id)?.display_name}
                menu={
                  <ColumnMenu
                    assignedId={v.assigned_employee_id}
                    employees={employees}
                    onEdit={() => setEditVehicle(v)}
                    onAssign={(eid) => assignAsset.mutate({ kind: 'vehicles', id: v.id, employeeId: eid })}
                    onShowCalendar={() => showInCalendar(v.assigned_employee_id)}
                    onDeactivate={() => confirm(`${v.name} deaktivieren?`) && deactivate.mutate({ kind: 'vehicles', id: v.id })}
                  />
                }
              >
                {appts.filter((a) => a.vehicle_id === v.id).map((a) => <ApptCard key={a.id} dragId={`veh|${a.id}`} appt={a} onView={() => setDetailAppt(a)} />)}
              </Column>
            ))}
          </Section>

          <Section icon={<Wrench size={16} />} title="WERKZEUG" hint="Termin in die Werkzeugspalte ziehen" addLabel="Werkzeug hinzufügen" onAdd={() => setNewTool(true)}>
            <Column id={`tool|${UNASSIGNED}`} title="Kein Werkzeug erforderlich" subtitle="Termine ohne Werkzeugzuweisung" count={appts.filter((a) => !a.tool_id).length}>
              {appts.filter((a) => !a.tool_id).map((a) => <ApptCard key={a.id} dragId={`tool|${a.id}`} appt={a} onView={() => setDetailAppt(a)} />)}
            </Column>
            {tools.map((t) => (
              <Column
                key={t.id}
                id={`tool|${t.id}`}
                title={t.name}
                subtitle={t.category ?? ''}
                count={appts.filter((a) => a.tool_id === t.id).length}
                assignee={employees.find((e) => e.id === t.assigned_employee_id)?.display_name}
                menu={
                  <ColumnMenu
                    assignedId={t.assigned_employee_id}
                    employees={employees}
                    onEdit={() => setEditTool(t)}
                    onAssign={(eid) => assignAsset.mutate({ kind: 'tools', id: t.id, employeeId: eid })}
                    onShowCalendar={() => showInCalendar(t.assigned_employee_id)}
                    onDeactivate={() => confirm(`${t.name} deaktivieren?`) && deactivate.mutate({ kind: 'tools', id: t.id })}
                  />
                }
              >
                {appts.filter((a) => a.tool_id === t.id).map((a) => <ApptCard key={a.id} dragId={`tool|${a.id}`} appt={a} onView={() => setDetailAppt(a)} />)}
              </Column>
            ))}
          </Section>

          <DragOverlay>{activeAppt && <ApptCardBody appt={activeAppt} dragging />}</DragOverlay>
        </DndContext>
      )}

      {newVehicle && <VehicleModal employees={employees} onClose={() => setNewVehicle(false)} onSaved={() => { qc.invalidateQueries({ queryKey: ['vehicles'] }); setNewVehicle(false) }} />}
      {editVehicle && <VehicleModal vehicle={editVehicle} employees={employees} onClose={() => setEditVehicle(null)} onSaved={() => { qc.invalidateQueries({ queryKey: ['vehicles'] }); setEditVehicle(null) }} />}
      {newTool && <ToolModal employees={employees} onClose={() => setNewTool(false)} onSaved={() => { qc.invalidateQueries({ queryKey: ['tools'] }); setNewTool(false) }} />}
      {editTool && <ToolModal tool={editTool} employees={employees} onClose={() => setEditTool(null)} onSaved={() => { qc.invalidateQueries({ queryKey: ['tools'] }); setEditTool(null) }} />}
      {detailAppt && <ApptDetailModal appt={detailAppt} vehicles={vehicles} tools={tools} onClose={() => setDetailAppt(null)} />}
      {createAt && (
        <ApptCreateModal
          ctx={createAt}
          employees={employees}
          onClose={() => setCreateAt(null)}
          onCreated={() => { qc.invalidateQueries({ queryKey: ['planning-board', selected] }); qc.invalidateQueries({ queryKey: ['appointments'] }); setCreateAt(null) }}
        />
      )}
    </div>
  )
}

function FilterRow({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <DropdownMenu.Item onSelect={onClick} className="flex cursor-pointer items-center justify-between rounded-md px-2 py-1.5 text-sm text-body outline-none data-[highlighted]:bg-alt">
      {label}
      {active && <span className="h-2 w-2 rounded-full bg-green-primary" />}
    </DropdownMenu.Item>
  )
}

// ─── Column menu ─────────────────────────────────────────────────────────────
function ColumnMenu({
  assignedId,
  employees,
  onEdit,
  onAssign,
  onShowCalendar,
  onDeactivate,
}: {
  assignedId?: string | null
  employees: Employee[]
  onEdit: () => void
  onAssign: (employeeId: string | null) => void
  onShowCalendar: () => void
  onDeactivate: () => void
}) {
  const itemCls = 'flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm text-body outline-none data-[highlighted]:bg-alt'
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button className="rounded-md p-1 text-muted hover:bg-alt">
          <MoreVertical size={16} />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={4} className="z-50 min-w-52 rounded-lg border border-border bg-surface p-1 shadow-e2">
          <DropdownMenu.Item onSelect={onEdit} className={itemCls}><Pencil size={14} /> Bearbeiten</DropdownMenu.Item>
          <DropdownMenu.Sub>
            <DropdownMenu.SubTrigger className={itemCls}>
              <UserPlus size={14} /> Mitarbeiter zuweisen
            </DropdownMenu.SubTrigger>
            <DropdownMenu.Portal>
              <DropdownMenu.SubContent className="z-50 min-w-48 rounded-lg border border-border bg-surface p-1 shadow-e2">
                <DropdownMenu.Item onSelect={() => onAssign(null)} className={itemCls}>
                  — Niemand —
                  {!assignedId && <span className="ml-auto h-2 w-2 rounded-full bg-green-primary" />}
                </DropdownMenu.Item>
                {employees.map((e) => (
                  <DropdownMenu.Item key={e.id} onSelect={() => onAssign(e.id)} className={itemCls}>
                    {e.display_name}
                    {assignedId === e.id && <span className="ml-auto h-2 w-2 rounded-full bg-green-primary" />}
                  </DropdownMenu.Item>
                ))}
              </DropdownMenu.SubContent>
            </DropdownMenu.Portal>
          </DropdownMenu.Sub>
          <DropdownMenu.Item onSelect={onShowCalendar} className={itemCls}><CalendarDays size={14} /> Im Kalender anzeigen</DropdownMenu.Item>
          <div className="my-1 border-t border-border" />
          <DropdownMenu.Item onSelect={onDeactivate} className={cn(itemCls, 'text-error')}><Power size={14} /> Deaktivieren</DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}

// ─── Section ─────────────────────────────────────────────────────────────────
function Section({ icon, title, hint, addLabel, onAdd, children }: { icon: React.ReactNode; title: string; hint: string; addLabel: string; onAdd: () => void; children: React.ReactNode }) {
  return (
    <div className="mb-8">
      <div className="mb-3 flex items-center gap-2 text-muted">
        {icon}
        <span className="text-xs font-bold uppercase tracking-wide text-body">{title}</span>
        <span className="text-xs">{hint}</span>
      </div>
      <div className="flex items-start gap-3 overflow-x-auto pb-2">
        {children}
        <button onClick={onAdd} className="flex min-h-[120px] min-w-[180px] flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-border text-sm font-medium text-muted hover:bg-alt">
          <Plus size={18} />
          {addLabel}
        </button>
      </div>
    </div>
  )
}

// ─── Column (droppable) ──────────────────────────────────────────────────────
function Column({ id, title, subtitle, count, capacity, color, assignee, menu, children }: { id: string; title: string; subtitle?: string; count: number; capacity?: string; color?: string | null; assignee?: string; menu?: React.ReactNode; children: React.ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id })
  const hasItems = Array.isArray(children) ? children.length > 0 : !!children
  return (
    <div ref={setNodeRef} className={cn('flex w-[280px] shrink-0 flex-col rounded-xl border bg-surface p-3 transition-colors', isOver ? 'border-green-primary ring-2 ring-green-primary/40' : 'border-border')}>
      <div className="mb-3 flex items-start justify-between gap-2 border-b border-border-faint pb-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            {color && <span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} />}
            <span className="truncate text-sm font-bold text-text">{title}</span>
          </div>
          {subtitle && <div className="truncate text-xs text-muted">{subtitle}</div>}
          {capacity && <div className="mt-0.5 text-xs text-muted">{capacity}</div>}
          {assignee && (
            <div className="mt-1 flex items-center gap-1 text-xs font-medium text-green-deep">
              <User size={11} /> {assignee}
            </div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <span className="rounded-full bg-alt px-2 py-0.5 text-xs font-semibold text-muted">{count}</span>
          {menu}
        </div>
      </div>
      <div className="flex flex-1 flex-col gap-2">
        {children}
        {isOver && <div className="rounded-lg border-2 border-dashed border-green-primary/60 py-4 text-center text-xs font-medium text-green-deep">Hier ablegen</div>}
        {!hasItems && !isOver && <div className="py-6 text-center text-xs text-faint">Hierher ziehen</div>}
      </div>
    </div>
  )
}

// ─── Appointment card (draggable) ────────────────────────────────────────────
function ApptCard({ dragId, appt, onView }: { dragId: string; appt: Appt; onView?: () => void }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: dragId })
  // Distinguish a click (open details) from a drag (assign): capture the
  // pointer-down position in the capture phase so we don't clobber dnd-kit's own
  // onPointerDown, then treat pointer-up as a click only if it barely moved.
  const downPos = useRef<{ x: number; y: number } | null>(null)
  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      onPointerDownCapture={(e) => {
        downPos.current = { x: e.clientX, y: e.clientY }
      }}
      onClick={(e) => {
        const d = downPos.current
        if (d && Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y) > 6) return
        onView?.()
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onView?.()
        }
      }}
      className={cn('cursor-grab touch-none', isDragging && 'opacity-40')}
    >
      <ApptCardBody appt={appt} />
    </div>
  )
}
function ApptCardBody({ appt, dragging }: { appt: Appt; dragging?: boolean }) {
  const loc = locStr(appt.location)
  return (
    <div className={cn('rounded-lg border border-border bg-surface p-3 shadow-e1', dragging && 'rotate-1 shadow-e3')}>
      <div className="flex items-center gap-1.5 text-xs text-muted"><Clock size={12} />{hm(appt.scheduled_at)} · {appt.duration_minutes ?? 60} min</div>
      <div className="mt-1 flex items-center gap-1.5 text-sm font-semibold text-text"><User size={13} className="text-muted" />{appt.customer_name ?? appt.title ?? 'Termin'}</div>
      {loc && <div className="mt-1 flex items-center gap-1.5 text-xs text-muted"><MapPin size={12} /><span className="truncate">{loc}</span></div>}
    </div>
  )
}

// ─── Timeline view ───────────────────────────────────────────────────────────
interface Row { label: string; sub?: string; color?: string | null; vehicle_id?: string; tool_id?: string; appts: Appt[] }

function TimelineView({ appts, vehicles, tools, onBlock, onSlot }: { appts: Appt[]; vehicles: Vehicle[]; tools: Tool[]; onBlock: (a: Appt) => void; onSlot: (at: Date, row: { vehicle_id?: string; tool_id?: string }) => void }) {
  const rows: Row[] = [
    { label: 'Nicht zugewiesen', appts: appts.filter((a) => !a.vehicle_id && !a.tool_id) },
    ...vehicles.map((v) => ({ label: v.name, sub: v.model ?? undefined, color: v.color, vehicle_id: v.id, appts: appts.filter((a) => a.vehicle_id === v.id) })),
    ...tools.map((t) => ({ label: t.name, sub: t.category ?? undefined, tool_id: t.id, appts: appts.filter((a) => a.tool_id === t.id) })),
  ]

  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-surface">
      <div style={{ minWidth: 180 + HOURS.length * HOUR_W }}>
        {/* Hour header */}
        <div className="flex border-b border-border">
          <div className="w-[180px] shrink-0 border-r border-border px-3 py-2 text-xs font-semibold uppercase text-muted">Asset</div>
          <div className="flex">
            {HOURS.map((h) => (
              <div key={h} className="shrink-0 border-r border-border-faint py-2 text-center text-[11px] text-muted" style={{ width: HOUR_W }}>{pad(h)}:00</div>
            ))}
          </div>
        </div>
        {/* Rows */}
        {rows.map((row, ri) => (
          <div key={ri} className="flex border-b border-border-faint last:border-0">
            <div className="flex w-[180px] shrink-0 flex-col justify-center border-r border-border px-3" style={{ minHeight: ROW_H }}>
              <div className="flex items-center gap-1.5">
                {row.color && <span className="h-2.5 w-2.5 rounded-full" style={{ background: row.color }} />}
                <span className="truncate text-sm font-semibold text-text">{row.label}</span>
              </div>
              {row.sub && <span className="truncate text-xs text-muted">{row.sub}</span>}
            </div>
            <div className="relative" style={{ width: HOURS.length * HOUR_W, minHeight: ROW_H }}>
              {/* hour cells (click to create) */}
              {HOURS.map((h) => (
                <button
                  key={h}
                  onClick={() => { const d = new Date(); d.setHours(h, 0, 0, 0); onSlot(d, { vehicle_id: row.vehicle_id, tool_id: row.tool_id }) }}
                  className="absolute top-0 h-full border-r border-border-faint hover:bg-green-tint-50"
                  style={{ left: (h - 7) * HOUR_W, width: HOUR_W }}
                />
              ))}
              {/* blocks */}
              {row.appts.map((a) => {
                if (!a.scheduled_at) return null
                const dt = new Date(a.scheduled_at)
                const startH = dt.getHours() + dt.getMinutes() / 60
                const left = Math.max(0, (startH - 7) * HOUR_W)
                const width = Math.max(36, ((a.duration_minutes ?? 60) / 60) * HOUR_W - 2)
                return (
                  <button
                    key={a.id}
                    onClick={() => onBlock(a)}
                    className="absolute top-1.5 overflow-hidden rounded-md border-l-[3px] border-green-deep bg-green-tint-100 px-1.5 py-1 text-left"
                    style={{ left, width, height: ROW_H - 12 }}
                    title={`${hm(a.scheduled_at)} ${a.customer_name ?? a.title ?? ''}`}
                  >
                    <div className="truncate text-[11px] font-semibold text-green-deep">{a.customer_name ?? a.title ?? 'Termin'}</div>
                    <div className="truncate text-[10px] text-body">{hm(a.scheduled_at)}</div>
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Vehicle modal ───────────────────────────────────────────────────────────
function VehicleModal({ vehicle, employees, onClose, onSaved }: { vehicle?: Vehicle; employees: Employee[]; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(vehicle?.name ?? '')
  const [model, setModel] = useState(vehicle?.model ?? '')
  const [plate, setPlate] = useState(vehicle?.license_plate ?? '')
  const [cap, setCap] = useState(vehicle?.capacity_hours ?? 8)
  const [emp, setEmp] = useState(vehicle?.assigned_employee_id ?? '')
  const [color, setColor] = useState(vehicle?.color ?? '')
  const [notes, setNotes] = useState(vehicle?.notes ?? '')
  const [active, setActive] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: () =>
      apiFetch(vehicle ? `/api/vehicles/${vehicle.id}` : '/api/vehicles', {
        method: vehicle ? 'PATCH' : 'POST',
        body: JSON.stringify({ name, model: model || null, license_plate: plate || null, capacity_hours: cap, assigned_employee_id: emp || null, color: color || null, notes: notes || null, is_active: active }),
      }),
    onSuccess: onSaved,
    onError: () => setError('Speichern fehlgeschlagen.'),
  })

  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={vehicle ? 'Fahrzeug bearbeiten' : 'Neues Fahrzeug'} widthClass="max-w-lg"
      footer={<div className="flex gap-3"><button onClick={onClose} className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body">Abbrechen</button><button disabled={!name.trim() || save.isPending} onClick={() => save.mutate()} className="flex-1 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">{save.isPending ? 'Speichert…' : 'Speichern'}</button></div>}>
      <div className="space-y-4">
        {error && <div className="rounded-md bg-error-bg px-3 py-2 text-sm text-error">{error}</div>}
        {vehicle?.last_seen !== undefined && (
          <div className="rounded-md bg-alt px-3 py-2 text-xs text-muted">Zuletzt gesehen: <span className="font-medium text-body">{fmtDate(vehicle.last_seen)}</span></div>
        )}
        <div><div className={labelCls}>Name *</div><input value={name} onChange={(e) => setName(e.target.value)} placeholder="z. B. REYB1998" className={inputCls} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><div className={labelCls}>Modell</div><input value={model} onChange={(e) => setModel(e.target.value)} placeholder="BMW Z4" className={inputCls} /></div>
          <div><div className={labelCls}>Kennzeichen</div><input value={plate} onChange={(e) => setPlate(e.target.value)} className={inputCls} /></div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div><div className={labelCls}>Kapazität (h/Tag)</div><input type="number" value={cap} onChange={(e) => setCap(Number(e.target.value))} className={inputCls} /></div>
          <div><div className={labelCls}>Mitarbeiter</div><select value={emp} onChange={(e) => setEmp(e.target.value)} className={inputCls}><option value="">— Niemand —</option>{employees.map((e) => <option key={e.id} value={e.id}>{e.display_name}</option>)}</select></div>
        </div>
        <div>
          <div className={labelCls}>Farbe</div>
          <div className="flex flex-wrap gap-2">{COLOR_SWATCHES.map((c) => <button key={c} type="button" onClick={() => setColor(c)} className={cn('h-7 w-7 rounded-full ring-offset-2 ring-offset-surface', color === c && 'ring-2 ring-green-primary')} style={{ background: c }} />)}</div>
        </div>
        <div><div className={labelCls}>Notizen</div><textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className={inputCls} /></div>
        <label className="flex items-center gap-2 text-sm text-text"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} className="h-4 w-4 accent-green-primary" /> Aktiv</label>
      </div>
    </Modal>
  )
}

// ─── Tool modal ──────────────────────────────────────────────────────────────
function ToolModal({ tool, employees, onClose, onSaved }: { tool?: Tool; employees: Employee[]; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(tool?.name ?? '')
  const [category, setCategory] = useState(tool?.category ?? TOOL_CATEGORIES[0])
  const [serial, setSerial] = useState(tool?.serial_number ?? '')
  const [emp, setEmp] = useState(tool?.assigned_employee_id ?? '')
  const [loc, setLoc] = useState(tool?.storage_location ?? '')
  const [notes, setNotes] = useState(tool?.notes ?? '')
  const [active, setActive] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: () =>
      apiFetch(tool ? `/api/tools/${tool.id}` : '/api/tools', {
        method: tool ? 'PATCH' : 'POST',
        body: JSON.stringify({ name, category, serial_number: serial || null, assigned_employee_id: emp || null, storage_location: loc || null, notes: notes || null, is_active: active }),
      }),
    onSuccess: onSaved,
    onError: () => setError('Speichern fehlgeschlagen.'),
  })

  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={tool ? 'Werkzeug bearbeiten' : 'Neues Werkzeug'} widthClass="max-w-lg"
      footer={<div className="flex gap-3"><button onClick={onClose} className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body">Abbrechen</button><button disabled={!name.trim() || save.isPending} onClick={() => save.mutate()} className="flex-1 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">{save.isPending ? 'Speichert…' : 'Speichern'}</button></div>}>
      <div className="space-y-4">
        {error && <div className="rounded-md bg-error-bg px-3 py-2 text-sm text-error">{error}</div>}
        {tool?.last_seen !== undefined && (
          <div className="rounded-md bg-alt px-3 py-2 text-xs text-muted">Zuletzt gesehen: <span className="font-medium text-body">{fmtDate(tool.last_seen)}</span></div>
        )}
        <div><div className={labelCls}>Name *</div><input value={name} onChange={(e) => setName(e.target.value)} placeholder="z. B. Bosch SE30 Rotationshammer" className={inputCls} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><div className={labelCls}>Kategorie</div><select value={category} onChange={(e) => setCategory(e.target.value)} className={inputCls}>{TOOL_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}</select></div>
          <div><div className={labelCls}>Seriennummer</div><input value={serial} onChange={(e) => setSerial(e.target.value)} className={inputCls} /></div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div><div className={labelCls}>Mitarbeiter</div><select value={emp} onChange={(e) => setEmp(e.target.value)} className={inputCls}><option value="">— Niemand —</option>{employees.map((e) => <option key={e.id} value={e.id}>{e.display_name}</option>)}</select></div>
          <div><div className={labelCls}>Standort</div><input value={loc} onChange={(e) => setLoc(e.target.value)} className={inputCls} /></div>
        </div>
        <div><div className={labelCls}>Notizen</div><textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className={inputCls} /></div>
        <label className="flex items-center gap-2 text-sm text-text"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} className="h-4 w-4 accent-green-primary" /> Aktiv</label>
      </div>
    </Modal>
  )
}

// ─── Appointment detail (timeline) ───────────────────────────────────────────
function ApptDetailModal({ appt, vehicles, tools, onClose }: { appt: Appt; vehicles: Vehicle[]; tools: Tool[]; onClose: () => void }) {
  const loc = locStr(appt.location)
  const veh = vehicles.find((v) => v.id === appt.vehicle_id)
  const tool = tools.find((t) => t.id === appt.tool_id)
  const start = appt.scheduled_at ? new Date(appt.scheduled_at) : null
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={appt.title ?? 'Termin'}>
      <div className="space-y-3 text-sm">
        {start && <Row2 label="Zeit">{start.toLocaleDateString('de-DE', { weekday: 'long', day: 'numeric', month: 'long' })} · {hm(appt.scheduled_at)} Uhr ({appt.duration_minutes ?? 60} Min)</Row2>}
        {appt.customer_name && <Row2 label="Kunde">{appt.customer_name}</Row2>}
        {appt.employee_name && <Row2 label="Mitarbeiter">{appt.employee_name}</Row2>}
        {loc && <Row2 label="Ort">{loc}</Row2>}
        {veh && <Row2 label="Fahrzeug">{veh.name}</Row2>}
        {tool && <Row2 label="Werkzeug">{tool.name}</Row2>}
      </div>
    </Modal>
  )
}
function Row2({ label, children }: { label: string; children: React.ReactNode }) {
  return <div><div className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</div><div className="mt-0.5 text-text">{children}</div></div>
}

// ─── Appointment create (timeline slot) ──────────────────────────────────────
interface CustomerOption { id: string; full_name: string | null }
function ApptCreateModal({ ctx, employees, onClose, onCreated }: { ctx: { at: Date; vehicle_id?: string; tool_id?: string }; employees: Employee[]; onClose: () => void; onCreated: () => void }) {
  const [customerId, setCustomerId] = useState('')
  const [title, setTitle] = useState('')
  const [time, setTime] = useState(`${pad(ctx.at.getHours())}:${pad(ctx.at.getMinutes())}`)
  const [duration, setDuration] = useState(60)
  const [emp, setEmp] = useState('')
  const [error, setError] = useState<string | null>(null)
  const { data: customerData } = useQuery({ queryKey: ['customers-options'], queryFn: () => apiFetch<{ customers: CustomerOption[] }>('/api/customers?limit=500') })
  const customers = customerData?.customers ?? []

  const create = useMutation({
    mutationFn: () => {
      const d = ctx.at
      const iso = new Date(`${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${time}`).toISOString()
      return apiFetch('/api/appointments', { method: 'POST', body: JSON.stringify({ customer_id: customerId || null, title: title || 'Termin', scheduled_at: iso, duration_minutes: duration, assigned_employee_id: emp || null, vehicle_id: ctx.vehicle_id ?? null, tool_id: ctx.tool_id ?? null }) })
    },
    onSuccess: onCreated,
    onError: () => setError('Termin konnte nicht erstellt werden.'),
  })

  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Neuer Termin" widthClass="max-w-lg"
      footer={<div className="flex gap-3"><button onClick={onClose} className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body">Abbrechen</button><button disabled={create.isPending} onClick={() => create.mutate()} className="flex-1 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">{create.isPending ? 'Speichert…' : 'Speichern'}</button></div>}>
      <div className="space-y-4">
        {error && <div className="rounded-md bg-error-bg px-3 py-2 text-sm text-error">{error}</div>}
        <div><div className={labelCls}>Kunde</div><select value={customerId} onChange={(e) => setCustomerId(e.target.value)} className={inputCls}><option value="">— Privat —</option>{customers.map((c) => <option key={c.id} value={c.id}>{c.full_name ?? 'Unbenannt'}</option>)}</select></div>
        <div><div className={labelCls}>Titel</div><input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="z. B. Vor-Ort-Termin" className={inputCls} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><div className={labelCls}>Uhrzeit</div><input type="time" value={time} onChange={(e) => setTime(e.target.value)} className={inputCls} /></div>
          <div><div className={labelCls}>Dauer</div><select value={duration} onChange={(e) => setDuration(Number(e.target.value))} className={inputCls}>{[30, 60, 90, 120].map((m) => <option key={m} value={m}>{m} Min</option>)}</select></div>
        </div>
        <div><div className={labelCls}>Mitarbeiter</div><select value={emp} onChange={(e) => setEmp(e.target.value)} className={inputCls}><option value="">Nicht zugewiesen</option>{employees.map((e) => <option key={e.id} value={e.id}>{e.display_name}</option>)}</select></div>
      </div>
    </Modal>
  )
}
