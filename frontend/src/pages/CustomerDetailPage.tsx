import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  AtSign,
  CalendarClock,
  ChevronRight,
  Download,
  Euro,
  FileText,
  History,
  Image as ImageIcon,
  MapPin,
  MessageSquare,
  Phone,
  Pencil,
  Plus,
  Layers,
  MoreVertical,
  Search,
  Sparkles,
  Upload,
  type LucideIcon,
} from 'lucide-react'
import { useRef, useState, type ReactNode } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { CustomerFormModal } from '../components/CustomerFormModal'
import { Modal } from '../components/ui/Modal'
import { Tag } from '../components/ui/Tag'
import { apiFetch, apiUpload } from '../lib/api'
import { cn } from '../lib/utils'
import type { TimelineEvent, TimelineEventKind } from './calls/shared'

interface Inquiry {
  id: string
  number: string | null
  subject?: string | null
  title: string | null
  type: string | null
  status: string
  notes?: string | null
  created_at: string
  call_count?: number
  open_count?: number
  last_activity_at?: string | null
  case_id?: string | null
  case_confidence?: number | null
  case_reason?: string | null
}
interface CaseRow {
  id: string
  number: string | null
  label: string | null
  status: string
}
interface Appointment {
  id: string
  title: string | null
  scheduled_at: string | null
  status: string
  category: string | null
  notes?: string | null
}
interface Kva {
  id: string
  number: string | null
  status: string
  total: number | null
  created_at: string
}
interface CallRow {
  id: string
  summary_title: string | null
  direction: string | null
  started_at: string | null
}
interface Customer {
  id: string
  full_name: string | null
  email: string | null
  phone: string | null
  address: { raw?: string; street?: string; postal_code?: string; city?: string } | string | null
  customer_number: string | null
  customer_type: string | null
  vat_id: string | null
  notes: string | null
  created_at: string
  updated_at: string
  inquiries: Inquiry[]
  appointments: Appointment[]
  cost_estimates: Kva[]
  calls: CallRow[]
  cases?: CaseRow[]
}
interface DocRow {
  id: string
  name: string | null
  category: string | null
  is_image: boolean
  uploaded_at: string
  url: string | null
}

const TYPE_META: Record<string, { label: string; badge: string }> = {
  new: { label: 'Neukunde', badge: 'bg-info-bg text-info' },
  regular: { label: 'Stammkunde', badge: 'bg-success-bg text-success' },
  supplier: { label: 'Lieferant', badge: 'bg-warning-bg text-warning' },
  property_management: { label: 'Hausverwaltung', badge: 'bg-ai-bg text-ai' },
}
const STATUS_TAG: Record<string, { label: string; variant: 'info' | 'warning' | 'success' | 'neutral' }> = {
  open: { label: 'Neu', variant: 'info' },
  in_progress: { label: 'In Bearbeitung', variant: 'warning' },
  completed: { label: 'Erledigt', variant: 'success' },
}
// All timestamps render in Europe/Berlin (backend stores UTC; without the tz pin
// these showed in the viewer's browser timezone).
const fmt = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Berlin' }) : '—'
const fmtDay = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'Europe/Berlin' }) : '—'
const addrStr = (a: Customer['address']) => {
  if (!a) return '—'
  if (typeof a === 'string') return a
  if (a.raw) return a.raw
  // CSV-imported addresses are {street, postal_code, city} with no `raw`.
  const line = [a.street, [a.postal_code, a.city].filter(Boolean).join(' ')]
    .filter(Boolean)
    .join(', ')
  return line || '—'
}
const dotFor = (s: string) =>
  s === 'confirmed' || s === 'completed' ? 'bg-success' : s === 'cancelled' ? 'bg-error' : 'bg-warning'

export function CustomerDetailPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [editOpen, setEditOpen] = useState(false)
  const [newAppt, setNewAppt] = useState(false)

  const { data: customer, isLoading } = useQuery({
    queryKey: ['customerDetail', id],
    queryFn: () => apiFetch<Customer>(`/api/customers/${id}`),
  })
  const { data: docs = [] } = useQuery({
    queryKey: ['customerDocs', id],
    queryFn: () => apiFetch<DocRow[]>(`/api/customers/${id}/documents`),
  })
  const { data: timeline = [] } = useQuery({
    queryKey: ['customerTimeline', id],
    queryFn: () => apiFetch<TimelineEvent[]>(`/api/customers/${id}/timeline`),
    enabled: !!id,
  })

  if (isLoading || !customer) {
    return <div className="flex h-full items-center justify-center text-muted">Wird geladen…</div>
  }

  const meta = TYPE_META[customer.customer_type ?? 'new'] ?? TYPE_META.new
  const refresh = () => qc.invalidateQueries({ queryKey: ['customerDetail', id] })

  return (
    <div className="mx-auto max-w-7xl space-y-5 p-4 md:p-6 lg:p-8">
      <button
        onClick={() => navigate('/customers')}
        className="flex items-center gap-1.5 text-sm text-muted hover:text-body"
      >
        <ArrowLeft size={15} /> Zurück zur Kundenliste
      </button>

      {/* TOP CARD */}
      <div className="rounded-lg border border-border bg-surface p-6 shadow-e1">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-text">{customer.full_name ?? 'Unbekannt'}</h1>
              {customer.customer_number && (
                <span className="rounded-md bg-alt px-2 py-0.5 font-mono text-xs text-muted">
                  #{customer.customer_number}
                </span>
              )}
            </div>
            <span className={cn('mt-2 inline-block rounded-full px-2.5 py-0.5 text-xs font-bold', meta.badge)}>
              {meta.label}
            </span>
          </div>
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate(`/cost-estimates/new?customer_id=${customer.id}`)}
              className="flex items-center gap-1.5 text-sm font-medium text-green-deep hover:underline"
            >
              <FileText size={15} /> Kostenvoranschlag erstellen
            </button>
            <button
              onClick={() => setEditOpen(true)}
              className="flex items-center gap-2 rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110"
            >
              <Pencil size={15} /> Bearbeiten
            </button>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-1 gap-2 border-t border-border pt-5 text-sm text-muted sm:grid-cols-2">
          <div className="flex items-center gap-2">
            <AtSign size={14} className="text-faint" /> {customer.email ?? '—'}
          </div>
          <div className="flex items-center gap-2">
            <Phone size={14} className="text-faint" /> {customer.phone ?? '—'}
          </div>
          <div className="flex items-center gap-2">
            <MapPin size={14} className="text-faint" /> {addrStr(customer.address)}
            <span className="text-xs text-faint">· — km · — min</span>
          </div>
        </div>

        <div className="mt-4 border-t border-border pt-4">
          <div className="mb-1 text-xs font-bold uppercase tracking-wide text-muted">Notizen</div>
          <p className="whitespace-pre-wrap text-sm text-body">{customer.notes ?? '—'}</p>
        </div>
      </div>

      {/* TWO COLUMNS */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1.3fr_1fr]">
        <InquiriesPanel customer={customer} />
        <AppointmentsPanel customer={customer} onNew={() => setNewAppt(true)} />
      </div>

      {/* VERLAUF — single unified activity timeline (calls, inquiries,
          appointments, KVAs) from the backend. The old frontend-reconstructed
          "Aktivitäten" strip was removed: it duplicated these same events. */}
      <CustomerTimeline events={timeline} />

      {/* FILES */}
      <FilesPanel customerId={id} docs={docs} onChange={() => qc.invalidateQueries({ queryKey: ['customerDocs', id] })} />

      <div className="rounded-lg border border-border bg-surface px-5 py-3 text-xs text-muted">
        Erstellt: {fmt(customer.created_at)} · Zuletzt aktualisiert: {fmt(customer.updated_at)}
      </div>

      <CustomerFormModal
        open={editOpen}
        mode="edit"
        customer={customer}
        onClose={() => setEditOpen(false)}
        onSaved={() => {
          setEditOpen(false)
          refresh()
        }}
        onDeleted={() => navigate('/customers')}
      />
      <NewAppointmentModal
        open={newAppt}
        customer={customer}
        onClose={() => setNewAppt(false)}
        onSaved={() => {
          setNewAppt(false)
          refresh()
        }}
      />
    </div>
  )
}

function Panel({ title, action, children }: { title: ReactNode; action?: ReactNode; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-5 shadow-e1">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-bold text-text">{title}</h2>
        {action}
      </div>
      {children}
    </div>
  )
}

function NewBtn({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1.5 rounded-md bg-green-primary px-3 py-1.5 text-xs font-semibold text-white hover:brightness-110"
    >
      <Plus size={14} /> {label}
    </button>
  )
}

interface Proposal {
  model: string
  n_inquiries: number
  cost: number
  cases: { label: string; members: string[]; confidence: number; reason: string; tier: string }[]
}

function InquiriesPanel({ customer }: { customer: Customer }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const inquiries = customer.inquiries ?? []
  const cases = customer.cases ?? []
  const open = inquiries.filter((i) => i.status !== 'completed').length
  const done = inquiries.filter((i) => i.status === 'completed').length
  const filtered = inquiries.filter((i) =>
    `${i.subject ?? ''} ${i.title ?? ''} ${i.number ?? ''}`.toLowerCase().includes(q.toLowerCase()),
  )
  const refresh = () => qc.invalidateQueries({ queryKey: ['customerDetail', customer.id] })

  // Group filtered inquiries by their case (the binder); the rest stay standalone.
  const caseById = new Map(cases.map((c) => [c.id, c]))
  const grouped = new Map<string, Inquiry[]>()
  const ungrouped: Inquiry[] = []
  for (const i of filtered) {
    if (i.case_id && caseById.has(i.case_id)) {
      grouped.set(i.case_id, [...(grouped.get(i.case_id) ?? []), i])
    } else ungrouped.push(i)
  }

  const propose = useMutation({
    mutationFn: () => apiFetch<Proposal>(`/api/customers/${customer.id}/cases/propose`, { method: 'POST' }),
    onSuccess: (p) => setProposal(p),
  })
  const createCase = useMutation({
    mutationFn: (label: string) =>
      apiFetch(`/api/customers/${customer.id}/cases`, { method: 'POST', body: JSON.stringify({ label }) }),
    onSuccess: refresh,
  })

  return (
    <Panel
      title={`Anfragen (${inquiries.length})`}
      action={
        <div className="flex items-center gap-2">
          <button
            onClick={() => propose.mutate()}
            disabled={propose.isPending || inquiries.length < 2}
            className="flex items-center gap-1.5 rounded-md border border-ai-bg px-3 py-1.5 text-xs font-semibold text-ai hover:bg-ai-bg disabled:opacity-50"
            title="Ähnliche Anfragen per KI zu Fällen bündeln"
          >
            <Sparkles size={14} /> {propose.isPending ? 'Analysiere…' : 'KI-Gruppierung'}
          </button>
          <button
            onClick={() => {
              const l = window.prompt('Neuer Fall — Thema:')
              if (l) createCase.mutate(l)
            }}
            className="flex items-center gap-1.5 rounded-md bg-green-primary px-3 py-1.5 text-xs font-semibold text-white hover:brightness-110"
          >
            <Plus size={14} /> Neuer Fall
          </button>
        </div>
      }
    >
      <>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Tag variant="info">{open} offen</Tag>
          <Tag variant="success">{done} erledigt</Tag>
          {cases.length > 0 && <Tag variant="ai">{cases.length} Fälle</Tag>}
        </div>
        <div className="relative mb-3">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
          <input
            type="search"
            name="customer-vorgang-search"
            autoComplete="off"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Anfragen durchsuchen…"
            className="w-full rounded-md border border-border bg-alt py-2 pl-9 pr-3 text-sm text-body outline-none focus:border-green-primary"
          />
        </div>
        <div className="space-y-3">
          {[...grouped.entries()].map(([cid, items]) => {
            const c = caseById.get(cid)!
            return (
              <div key={cid} className="rounded-xl border border-ai-bg bg-ai-bg/40 p-2">
                <button
                  onClick={() => navigate(`/fall/${cid}`)}
                  className="mb-1.5 flex w-full items-center gap-2 rounded-md px-1 py-1 text-left transition hover:bg-ai-bg"
                  title="Fall öffnen (alle Anfragen)"
                >
                  <Layers size={14} className="flex-shrink-0 text-ai" />
                  <span className="truncate text-sm font-bold text-text">{c.label || 'Fall'}</span>
                  {c.number && <span className="font-mono text-[11px] text-ai">{c.number}</span>}
                  <span className="flex-1" />
                  <span className="text-xs text-muted">{items.length} Anfragen</span>
                  <ChevronRight size={14} className="text-faint" />
                </button>
                <div className="space-y-1.5">
                  {items.map((i) => (
                    <InquiryRow key={i.id} i={i} cases={cases} caseId={cid} onChanged={refresh} />
                  ))}
                </div>
              </div>
            )
          })}
          {ungrouped.map((i) => (
            <InquiryRow key={i.id} i={i} cases={cases} onChanged={refresh} />
          ))}
          {!filtered.length && <p className="py-6 text-center text-sm text-muted">Keine Anfragen.</p>}
        </div>
      </>
      {proposal && (
        <GroupingReviewModal
          customerId={customer.id}
          proposal={proposal}
          onClose={() => setProposal(null)}
          onApplied={() => {
            setProposal(null)
            refresh()
          }}
        />
      )}
    </Panel>
  )
}

function InquiryRow({ i, cases, caseId, onChanged }: { i: Inquiry; cases: CaseRow[]; caseId?: string; onChanged: () => void }) {
  const navigate = useNavigate()
  const st = STATUS_TAG[i.status] ?? { label: i.status, variant: 'neutral' as const }
  const topic = i.subject || i.title || 'Anfrage'
  return (
    <div className="group relative rounded-lg border border-border bg-surface p-3 transition hover:border-green-primary hover:bg-alt">
      <div onClick={() => navigate(caseId ? `/fall/${caseId}` : `/vorgang/${i.id}`)} className="cursor-pointer">
        <div className="flex items-center gap-2 pr-7">
          <Tag variant={st.variant}>{st.label}</Tag>
          <span className="flex-1 truncate text-sm font-semibold text-text">{topic}</span>
          {(i.open_count ?? 0) > 0 && (
            <span className="rounded-full bg-warning-bg px-2 py-0.5 text-xs font-bold text-warning">{i.open_count} offen</span>
          )}
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted">
          <span className="font-mono">{i.number ?? '—'}</span>
          <span aria-hidden>·</span>
          <span>{i.call_count ?? 0} Anrufe</span>
          <span aria-hidden>·</span>
          <span>{fmtDay(i.last_activity_at ?? i.created_at)}</span>
          {i.case_confidence != null && (
            <>
              <span aria-hidden>·</span>
              <span className="rounded bg-ai-bg px-1.5 py-0.5 font-semibold text-ai" title={i.case_reason ?? ''}>
                KI {Math.round((i.case_confidence ?? 0) * 100)}%
              </span>
            </>
          )}
        </div>
      </div>
      <MoveMenu inquiry={i} cases={cases} onMoved={onChanged} />
    </div>
  )
}

function MoveMenu({ inquiry, cases, onMoved }: { inquiry: Inquiry; cases: CaseRow[]; onMoved: () => void }) {
  const [open, setOpen] = useState(false)
  const move = useMutation({
    mutationFn: (body: { case_id?: string | null; new_case_label?: string }) =>
      apiFetch(`/api/inquiries/${inquiry.id}/case`, { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: () => {
      setOpen(false)
      onMoved()
    },
  })
  const others = cases.filter((c) => c.id !== inquiry.case_id)
  return (
    <div className="absolute right-2 top-2">
      <button
        onClick={(e) => {
          e.stopPropagation()
          setOpen((o) => !o)
        }}
        className="rounded p-1 text-faint hover:bg-border"
        title="In anderen Fall verschieben"
      >
        <MoreVertical size={15} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-20 mt-1 w-56 rounded-lg border border-border bg-surface p-1 shadow-e3">
            {inquiry.case_id && (
              <button onClick={() => move.mutate({ case_id: null })} className="block w-full rounded px-2.5 py-1.5 text-left text-sm text-body hover:bg-alt">
                Aus Fall lösen
              </button>
            )}
            {others.length > 0 && <div className="px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-faint">In Vorgang verschieben</div>}
            {others.map((c) => (
              <button key={c.id} onClick={() => move.mutate({ case_id: c.id })} className="block w-full truncate rounded px-2.5 py-1.5 text-left text-sm text-body hover:bg-alt">
                → {c.label || 'Fall'}
              </button>
            ))}
            <button
              onClick={() => {
                const l = window.prompt('Neuer Fall — Thema:')
                if (l) move.mutate({ new_case_label: l })
              }}
              className="block w-full rounded px-2.5 py-1.5 text-left text-sm font-medium text-green-deep hover:bg-alt"
            >
              ＋ Neuer Fall…
            </button>
          </div>
        </>
      )}
    </div>
  )
}

function GroupingReviewModal({
  customerId,
  proposal,
  onClose,
  onApplied,
}: {
  customerId: string
  proposal: Proposal
  onClose: () => void
  onApplied: () => void
}) {
  const merges = proposal.cases.filter((c) => c.members.length >= 2)
  const [picked, setPicked] = useState<Set<number>>(
    () => new Set(merges.map((_, idx) => idx).filter((idx) => merges[idx].tier !== 'low')),
  )
  const toggle = (idx: number) =>
    setPicked((s) => {
      const n = new Set(s)
      if (n.has(idx)) n.delete(idx)
      else n.add(idx)
      return n
    })
  const apply = useMutation({
    mutationFn: () =>
      apiFetch('/api/cases/apply', {
        method: 'POST',
        body: JSON.stringify({ customer_id: customerId, groups: merges.filter((_, idx) => picked.has(idx)) }),
      }),
    onSuccess: onApplied,
  })
  const tierTag = (t: string) =>
    t === 'auto' ? <Tag variant="success">sicher</Tag> : t === 'review' ? <Tag variant="warning">Prüfen</Tag> : <Tag variant="neutral">unsicher</Tag>
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title="KI-Vorschlag: Anfragen zu Fällen bündeln"
      widthClass="max-w-2xl"
      footer={
        <button
          onClick={() => apply.mutate()}
          disabled={apply.isPending || picked.size === 0}
          className="w-full rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
        >
          {picked.size} Fälle übernehmen
        </button>
      }
    >
      <div className="space-y-2">
        <p className="text-xs text-muted">
          {proposal.n_inquiries} Anfragen analysiert ({proposal.model}). Haken = als einen Fall bündeln; einzelne Anfragen
          kannst du danach jederzeit verschieben.
        </p>
        {merges.length === 0 && <p className="py-6 text-center text-sm text-muted">Kein Bündelungsvorschlag — alle Anfragen wirken eigenständig.</p>}
        {merges.map((c, idx) => (
          <label
            key={idx}
            className={cn('flex cursor-pointer gap-3 rounded-lg border p-3', picked.has(idx) ? 'border-green-primary bg-green-tint-100' : 'border-border')}
          >
            <input type="checkbox" checked={picked.has(idx)} onChange={() => toggle(idx)} className="mt-1 flex-shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="flex-1 truncate text-sm font-bold text-text">{c.label}</span>
                {tierTag(c.tier)}
                <span className="text-xs font-bold text-ai">{Math.round(c.confidence * 100)}%</span>
              </div>
              <div className="mt-1 font-mono text-xs text-muted">{c.members.join(', ')}</div>
              <div className="mt-1 text-xs text-body">{c.reason}</div>
            </div>
          </label>
        ))}
      </div>
    </Modal>
  )
}

function AppointmentsPanel({ customer, onNew }: { customer: Customer; onNew: () => void }) {
  const appts = customer.appointments ?? []
  return (
    <Panel title={`Termine (${appts.length})`} action={<NewBtn label="Neuer Termin" onClick={onNew} />}>
      <div className="space-y-2">
        {appts.map((a) => (
          <div key={a.id} className="rounded-lg border border-border p-3">
            <div className="flex items-center gap-2">
              <span className={cn('h-2 w-2 flex-shrink-0 rounded-full', dotFor(a.status))} />
              <span className="flex-1 truncate text-sm font-semibold text-text">{a.title ?? 'Termin'}</span>
            </div>
            <div className="mt-1 text-xs text-muted">{fmt(a.scheduled_at)}</div>
            {a.notes && <p className="mt-1 line-clamp-2 text-xs text-muted">{a.notes}</p>}
          </div>
        ))}
        {!appts.length && <p className="py-6 text-center text-sm text-muted">Keine Termine.</p>}
      </div>
    </Panel>
  )
}

const TL_ICON: Record<TimelineEventKind, { Icon: LucideIcon; cls: string }> = {
  call_created: { Icon: Phone, cls: 'bg-success-bg text-success' },
  inquiry_status_changed: { Icon: MessageSquare, cls: 'bg-info-bg text-info' },
  appointment_created: { Icon: CalendarClock, cls: 'bg-green-tint-100 text-green-deep' },
  appointment_rescheduled: { Icon: CalendarClock, cls: 'bg-warning-bg text-warning' },
  appointment_confirmed: { Icon: CalendarClock, cls: 'bg-success-bg text-success' },
  appointment_rejected: { Icon: CalendarClock, cls: 'bg-error-bg text-error' },
  appointment_cancelled: { Icon: CalendarClock, cls: 'bg-error-bg text-error' },
  alternative_proposed: { Icon: CalendarClock, cls: 'bg-warning-bg text-warning' },
  kva_sent: { Icon: Euro, cls: 'bg-ai-bg text-ai' },
  kva_accepted: { Icon: Euro, cls: 'bg-ai-bg text-ai' },
  kva_rejected: { Icon: Euro, cls: 'bg-ai-bg text-ai' },
  assignment_changed: { Icon: History, cls: 'bg-info-bg text-info' },
}

// Unified customer activity timeline — the SAME event shape as the call-log
// Verlauf tab, fed by GET /api/customers/{id}/timeline (every call, inquiry
// status change, appointment booked/rescheduled/confirmed and KVA for this
// customer, newest first).
function CustomerTimeline({ events }: { events: TimelineEvent[] }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-5 shadow-e1">
      <h2 className="mb-4 text-sm font-bold text-text">Verlauf ({events.length})</h2>
      {!events.length ? (
        <p className="py-6 text-sm text-muted">Noch keine Aktivitäten.</p>
      ) : (
        <div className="flex flex-col">
          {events.map((ev, i) => {
            const k = TL_ICON[ev.kind] ?? { Icon: History, cls: 'bg-alt text-muted' }
            const last = i === events.length - 1
            return (
              <div key={ev.id} className={cn('relative flex items-start gap-3.5', !last && 'pb-5')}>
                {!last && <span className="absolute bottom-0 left-[19px] top-[42px] w-0.5 bg-border" aria-hidden />}
                <span className={cn('z-[1] flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full', k.cls)}>
                  <k.Icon size={18} />
                </span>
                <div className="min-w-0 flex-1 pt-1">
                  <div className="text-sm font-semibold text-text">{ev.description}</div>
                  <div className="mt-0.5 text-xs text-muted">
                    {fmtDay(ev.timestamp)} · {ev.actor_name}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function FilesPanel({ customerId, docs, onChange }: { customerId: string; docs: DocRow[]; onChange: () => void }) {
  const [tab, setTab] = useState<'photos' | 'documents'>('documents')
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const photos = docs.filter((d) => d.is_image)
  const documents = docs.filter((d) => !d.is_image)

  async function upload(files: FileList | null) {
    if (!files?.length) return
    setUploading(true)
    try {
      for (const f of Array.from(files)) {
        const fd = new FormData()
        fd.append('file', f)
        fd.append('category', tab === 'photos' ? 'Foto' : 'Dokument')
        await apiUpload(`/api/customers/${customerId}/documents`, fd)
      }
      onChange()
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="rounded-lg border border-border bg-surface p-5 shadow-e1">
      <div className="mb-4 flex gap-4">
        <button
          onClick={() => setTab('photos')}
          className={cn('flex items-center gap-1.5 border-b-2 pb-1 text-sm font-medium', tab === 'photos' ? 'border-green-primary text-green-deep' : 'border-transparent text-muted')}
        >
          <ImageIcon size={15} /> Fotos ({photos.length})
        </button>
        <button
          onClick={() => setTab('documents')}
          className={cn('flex items-center gap-1.5 border-b-2 pb-1 text-sm font-medium', tab === 'documents' ? 'border-green-primary text-green-deep' : 'border-transparent text-muted')}
        >
          <FileText size={15} /> Dokumente ({documents.length})
        </button>
      </div>

      {/* Upload zone */}
      <div
        onClick={() => fileRef.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault()
          upload(e.dataTransfer.files)
        }}
        className="mb-4 cursor-pointer rounded-lg border-2 border-dashed border-border p-8 text-center hover:bg-alt"
      >
        <Upload size={24} className="mx-auto mb-2 text-faint" />
        <div className="text-sm text-body">{uploading ? 'Lädt hoch…' : 'Datei hierher ziehen oder klicken.'}</div>
        <div className="text-xs text-faint">JPG, PNG, GIF oder PDF (max. 10MB)</div>
        <input
          ref={fileRef}
          type="file"
          multiple
          accept="image/*,application/pdf"
          className="hidden"
          onChange={(e) => upload(e.target.files)}
        />
      </div>

      {tab === 'photos' ? (
        photos.length ? (
          <div className="grid grid-cols-3 gap-3 sm:grid-cols-4">
            {photos.map((p) => (
              <a key={p.id} href={p.url ?? '#'} target="_blank" rel="noreferrer" className="block">
                <img src={p.url ?? ''} alt={p.name ?? ''} className="aspect-square w-full rounded-lg border border-border object-cover" />
              </a>
            ))}
          </div>
        ) : (
          <p className="py-6 text-center text-sm text-muted">Noch keine Fotos.</p>
        )
      ) : documents.length ? (
        <div className="space-y-2">
          {documents.map((d) => (
            <div key={d.id} className="flex items-center gap-3 rounded-lg border border-border p-3">
              <FileText size={16} className="text-warning" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-text">{d.name}</div>
                <div className="text-xs text-muted">{fmtDay(d.uploaded_at)}</div>
              </div>
              {d.category && <Tag variant="info">{d.category}</Tag>}
              {d.url && (
                <a href={d.url} target="_blank" rel="noreferrer" className="rounded-md p-1.5 text-muted hover:bg-alt">
                  <Download size={15} />
                </a>
              )}
            </div>
          ))}
        </div>
      ) : (
        <p className="py-6 text-center text-sm text-muted">Noch keine Dokumente.</p>
      )}
    </div>
  )
}

const inputCls =
  'w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary'

function NewAppointmentModal({ open, customer, onClose, onSaved }: { open: boolean; customer: Customer; onClose: () => void; onSaved: () => void }) {
  const [title, setTitle] = useState('')
  const [date, setDate] = useState('')
  const [time, setTime] = useState('09:00')
  const [duration, setDuration] = useState(60)
  const [location, setLocation] = useState(addrStr(customer.address) === '—' ? '' : addrStr(customer.address))
  const save = useMutation({
    mutationFn: () =>
      apiFetch('/api/appointments', {
        method: 'POST',
        body: JSON.stringify({
          customer_id: customer.id,
          title: title || 'Termin',
          scheduled_at: new Date(`${date}T${time}`).toISOString(),
          duration_minutes: duration,
          location,
        }),
      }),
    onSuccess: onSaved,
  })
  return (
    <Modal
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Neuer Termin"
      footer={
        <button
          disabled={!date || save.isPending}
          onClick={() => save.mutate()}
          className="w-full rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
        >
          Termin speichern
        </button>
      }
    >
      <div className="space-y-4">
        <div>
          <div className="mb-1.5 text-xs font-semibold text-body">Titel</div>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="z. B. Wartung" className={inputCls} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <div className="mb-1.5 text-xs font-semibold text-body">Datum *</div>
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={inputCls} />
          </div>
          <div>
            <div className="mb-1.5 text-xs font-semibold text-body">Uhrzeit *</div>
            <input type="time" value={time} onChange={(e) => setTime(e.target.value)} className={inputCls} />
          </div>
        </div>
        <div>
          <div className="mb-1.5 text-xs font-semibold text-body">Dauer</div>
          <select value={duration} onChange={(e) => setDuration(Number(e.target.value))} className={inputCls}>
            {[30, 60, 90, 120].map((m) => (
              <option key={m} value={m}>
                {m} Min
              </option>
            ))}
          </select>
        </div>
        <div>
          <div className="mb-1.5 text-xs font-semibold text-body">Ort</div>
          <input value={location} onChange={(e) => setLocation(e.target.value)} className={inputCls} />
        </div>
      </div>
    </Modal>
  )
}
