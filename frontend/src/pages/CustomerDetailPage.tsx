import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  AtSign,
  CalendarClock,
  ChevronDown,
  ChevronLeft,
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
  Search,
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
  title: string | null
  type: string | null
  status: string
  notes?: string | null
  created_at: string
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
  address: { raw?: string } | string | null
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
const fmt = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'
const fmtDay = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' }) : '—'
const addrStr = (a: Customer['address']) => (!a ? '—' : typeof a === 'string' ? a : a.raw ?? '—')
const dotFor = (s: string) =>
  s === 'confirmed' || s === 'completed' ? 'bg-success' : s === 'cancelled' ? 'bg-error' : 'bg-warning'

export function CustomerDetailPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [editOpen, setEditOpen] = useState(false)
  const [newInquiry, setNewInquiry] = useState(false)
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
    return <div className="flex h-full items-center justify-center text-muted">Lädt…</div>
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
        <InquiriesPanel customer={customer} onNew={() => setNewInquiry(true)} />
        <AppointmentsPanel customer={customer} onNew={() => setNewAppt(true)} />
      </div>

      {/* ACTIVITIES */}
      <CustomerTimeline events={timeline} />
      <ActivitiesTimeline customer={customer} docs={docs} onTranscript={() => navigate('/calls')} />

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
      <NewInquiryModal
        open={newInquiry}
        customerId={id}
        onClose={() => setNewInquiry(false)}
        onSaved={() => {
          setNewInquiry(false)
          refresh()
        }}
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

function InquiriesPanel({ customer, onNew }: { customer: Customer; onNew: () => void }) {
  const [tab, setTab] = useState<'inquiries' | 'projects'>('inquiries')
  const [q, setQ] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const inquiries = customer.inquiries ?? []
  const open = inquiries.filter((i) => i.status !== 'completed').length
  const done = inquiries.filter((i) => i.status === 'completed').length
  const filtered = inquiries.filter((i) => (i.title ?? '').toLowerCase().includes(q.toLowerCase()))

  return (
    <Panel
      title={
        <div className="flex gap-4">
          <button
            onClick={() => setTab('inquiries')}
            className={cn('border-b-2 pb-1', tab === 'inquiries' ? 'border-green-primary text-green-deep' : 'border-transparent text-muted')}
          >
            Anfragen ({inquiries.length})
          </button>
          <button
            onClick={() => setTab('projects')}
            className={cn('border-b-2 pb-1', tab === 'projects' ? 'border-green-primary text-green-deep' : 'border-transparent text-muted')}
          >
            Projekte (0)
          </button>
        </div>
      }
      action={tab === 'inquiries' ? <NewBtn label="Neue Anfrage" onClick={onNew} /> : undefined}
    >
      {tab === 'projects' ? (
        <p className="py-8 text-center text-sm text-muted">Keine Projekte.</p>
      ) : (
        <>
          <div className="mb-3 flex items-center gap-2">
            <Tag variant="info">{open} offen</Tag>
            <Tag variant="success">{done} erledigt</Tag>
          </div>
          <div className="relative mb-3">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
            <input
              type="search"
              name="customer-inquiry-search"
              autoComplete="off"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Anfragen durchsuchen…"
              className="w-full rounded-md border border-border bg-alt py-2 pl-9 pr-3 text-sm text-body outline-none focus:border-green-primary"
            />
          </div>
          <div className="space-y-2">
            {filtered.map((i) => {
              const st = STATUS_TAG[i.status] ?? { label: i.status, variant: 'neutral' as const }
              const isOpen = expanded === i.id
              return (
                <div key={i.id} className="rounded-lg border border-border">
                  <button
                    onClick={() => setExpanded(isOpen ? null : i.id)}
                    className="flex w-full items-center gap-3 p-3 text-left"
                  >
                    <Tag variant={st.variant}>{st.label}</Tag>
                    <span className="flex-1 truncate text-sm font-medium text-text">{i.title ?? 'Anfrage'}</span>
                    <span className="text-xs text-faint">{fmtDay(i.created_at)}</span>
                    <ChevronDown size={15} className={cn('text-muted transition-transform', isOpen && 'rotate-180')} />
                  </button>
                  {isOpen && (
                    <div className="space-y-1.5 border-t border-border px-3 py-3 text-sm text-muted">
                      {i.number && <div className="font-mono text-xs">{i.number}</div>}
                      {i.type && <div>Kategorie: <span className="capitalize text-body">{i.type}</span></div>}
                      <div className="whitespace-pre-wrap text-body">{i.notes ?? 'Keine Notizen.'}</div>
                    </div>
                  )}
                </div>
              )
            })}
            {!filtered.length && <p className="py-6 text-center text-sm text-muted">Keine Anfragen.</p>}
          </div>
        </>
      )}
    </Panel>
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

interface Activity {
  icon: typeof Phone
  color: string
  date: string | null
  label: string
  desc: string
  tag: string
  transcript?: boolean
}

const TL_ICON: Record<TimelineEventKind, { Icon: LucideIcon; cls: string }> = {
  call_created: { Icon: Phone, cls: 'bg-success-bg text-success' },
  inquiry_status_changed: { Icon: MessageSquare, cls: 'bg-info-bg text-info' },
  appointment_created: { Icon: CalendarClock, cls: 'bg-green-tint-100 text-green-deep' },
  appointment_rescheduled: { Icon: CalendarClock, cls: 'bg-warning-bg text-warning' },
  appointment_confirmed: { Icon: CalendarClock, cls: 'bg-success-bg text-success' },
  appointment_rejected: { Icon: CalendarClock, cls: 'bg-error-bg text-error' },
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

function ActivitiesTimeline({
  customer,
  docs,
  onTranscript,
}: {
  customer: Customer
  docs: DocRow[]
  onTranscript: () => void
}) {
  const scroller = useRef<HTMLDivElement>(null)
  const items: Activity[] = []
  for (const c of customer.calls ?? [])
    items.push({ icon: Phone, color: 'text-success bg-success-bg', date: c.started_at, label: 'Anruf (KI)', desc: c.summary_title ?? 'Anruf', tag: 'call', transcript: true })
  for (const i of customer.inquiries ?? [])
    items.push({ icon: MessageSquare, color: 'text-info bg-info-bg', date: i.created_at, label: 'Neue Anfrage', desc: i.title ?? 'Anfrage', tag: i.type ?? 'info' })
  for (const k of customer.cost_estimates ?? [])
    items.push({ icon: Euro, color: 'text-warning bg-warning-bg', date: k.created_at, label: 'Kostenvoranschlag', desc: k.number ?? 'KVA', tag: 'kva' })
  for (const d of docs)
    items.push({ icon: FileText, color: 'text-warning bg-warning-bg', date: d.uploaded_at, label: 'Dokument', desc: d.name ?? 'Datei', tag: d.category ?? 'Dokument' })
  items.sort((a, b) => (b.date ?? '').localeCompare(a.date ?? ''))

  const scroll = (dir: number) => scroller.current?.scrollBy({ left: dir * 320, behavior: 'smooth' })

  return (
    <div className="rounded-lg border border-border bg-surface p-5 shadow-e1">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-bold text-text">Aktivitäten ({items.length})</h2>
        <div className="flex gap-1">
          <button onClick={() => scroll(-1)} className="rounded-md border border-border p-1.5 text-muted hover:bg-alt">
            <ChevronLeft size={15} />
          </button>
          <button onClick={() => scroll(1)} className="rounded-md border border-border p-1.5 text-muted hover:bg-alt">
            <ChevronRight size={15} />
          </button>
        </div>
      </div>
      <div ref={scroller} className="flex gap-3 overflow-x-auto pb-2">
        {items.map((a, i) => (
          <div key={i} className="w-64 flex-shrink-0 rounded-lg border border-border p-3">
            <div className={cn('mb-2 flex h-8 w-8 items-center justify-center rounded-full', a.color)}>
              <a.icon size={15} />
            </div>
            <div className="text-xs text-faint">{fmtDay(a.date)}</div>
            <div className="text-sm font-semibold text-text">{a.label}</div>
            <p className="mt-0.5 line-clamp-2 text-xs text-muted">{a.desc}</p>
            <div className="mt-2 flex items-center justify-between">
              <span className="rounded-full bg-alt px-2 py-0.5 text-[10px] font-semibold text-muted">{a.tag}</span>
              {a.transcript && (
                <button onClick={onTranscript} className="text-[11px] font-semibold text-green-deep hover:underline">
                  Zum Transkript
                </button>
              )}
            </div>
          </div>
        ))}
        {!items.length && <p className="py-6 text-sm text-muted">Keine Aktivitäten.</p>}
      </div>
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

function NewInquiryModal({ open, customerId, onClose, onSaved }: { open: boolean; customerId: string; onClose: () => void; onSaved: () => void }) {
  const [title, setTitle] = useState('')
  const [type, setType] = useState('info')
  const [notes, setNotes] = useState('')
  const save = useMutation({
    mutationFn: () =>
      apiFetch('/api/inquiries', {
        method: 'POST',
        body: JSON.stringify({ customer_id: customerId, title, type, notes }),
      }),
    onSuccess: onSaved,
  })
  return (
    <Modal
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Neue Anfrage"
      footer={
        <button
          disabled={!title || save.isPending}
          onClick={() => save.mutate()}
          className="w-full rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
        >
          Anfrage erstellen
        </button>
      }
    >
      <div className="space-y-4">
        <div>
          <div className="mb-1.5 text-xs font-semibold text-body">Titel *</div>
          <input value={title} onChange={(e) => setTitle(e.target.value)} className={inputCls} />
        </div>
        <div>
          <div className="mb-1.5 text-xs font-semibold text-body">Kategorie</div>
          <div className="flex flex-wrap gap-2">
            {['appointment', 'offer', 'info', 'recall'].map((c) => (
              <button
                key={c}
                onClick={() => setType(c)}
                className={cn('rounded-md border px-3 py-1.5 text-sm font-medium capitalize', type === c ? 'border-green-primary bg-green-primary text-white' : 'border-border text-body hover:bg-alt')}
              >
                {c}
              </button>
            ))}
          </div>
        </div>
        <div>
          <div className="mb-1.5 text-xs font-semibold text-body">Notiz</div>
          <textarea rows={4} value={notes} onChange={(e) => setNotes(e.target.value)} className={inputCls} />
        </div>
      </div>
    </Modal>
  )
}

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
