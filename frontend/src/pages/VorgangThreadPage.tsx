import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  CalendarClock,
  Check,
  Euro,
  GitMerge,
  History,
  Link2,
  MessageSquare,
  Pencil,
  Phone,
  PhoneIncoming,
  PhoneOutgoing,
  User,
  Wrench,
  type LucideIcon,
} from 'lucide-react'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { Modal } from '../components/ui/Modal'
import { Tag } from '../components/ui/Tag'
import { apiFetch } from '../lib/api'
import { fmtDateTime, fmtDate } from '../lib/datetime'
import { cn } from '../lib/utils'

// ── Thread shapes (mirror GET /api/inquiries/{id}/thread) ────────────────────
interface ThreadCustomer {
  id: string
  full_name: string | null
  phone: string | null
  email: string | null
  customer_number: string | null
}
interface ThreadCall {
  id: string
  summary_title: string | null
  direction: string | null
  started_at: string | null
  created_at: string | null
  duration_seconds: number | null
  status: string | null
}
interface ThreadAppt { id: string; title: string | null; scheduled_at: string | null; status: string }
interface ThreadKva { id: string; number: string | null; status: string; total: number | null; created_at: string | null }
interface ThreadEvent {
  id: string
  kind: string
  timestamp: string
  actor_name: string
  description: string
  extras: Record<string, unknown>
}
interface RelatedCase {
  relation: string
  case: { id: string; number: string | null; subject: string | null; title: string | null; status: string }
}
interface CaseThread {
  inquiry: {
    id: string
    number: string | null
    subject: string | null
    title: string | null
    type: string | null
    status: string
    notes: string | null
    created_at: string | null
    updated_at: string | null
    customer: ThreadCustomer | null
    assigned_employee: { id: string; display_name: string | null } | null
  }
  timeline: ThreadEvent[]
  calls: ThreadCall[]
  appointments: ThreadAppt[]
  cost_estimates: ThreadKva[]
  related: RelatedCase[]
  open_count: number
}

const STATUS: Record<string, { label: string; variant: 'info' | 'warning' | 'success' | 'neutral' }> = {
  open: { label: 'Offen', variant: 'info' },
  in_progress: { label: 'In Bearbeitung', variant: 'warning' },
  completed: { label: 'Abgeschlossen', variant: 'success' },
  deleted: { label: 'Gelöscht', variant: 'neutral' },
}

const TL: Record<string, { Icon: LucideIcon; cls: string }> = {
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
  technician_dispatched: { Icon: Wrench, cls: 'bg-info-bg text-info' },
  technician_job_started: { Icon: Wrench, cls: 'bg-warning-bg text-warning' },
  technician_report_submitted: { Icon: Wrench, cls: 'bg-success-bg text-success' },
}

// Inline detail block for a submitted Einsatzbericht (extras.report).
function TechReport({ extras }: { extras: Record<string, unknown> }) {
  const rep = (extras?.report ?? {}) as Record<string, unknown>
  const photoCount = Number(extras?.photo_count ?? 0)
  const needs = Array.isArray(rep.needs) ? (rep.needs as string[]) : []
  return (
    <div className="mt-2 space-y-1 rounded-lg border border-border bg-alt/60 p-3 text-xs text-body">
      {typeof rep.description === 'string' && rep.description !== '' && (
        <div><span className="font-semibold">Durchgeführt:</span> {rep.description}</div>
      )}
      {typeof rep.extra_demands === 'string' && rep.extra_demands !== '' && (
        <div><span className="font-semibold">Zusätzliche Wünsche:</span> {rep.extra_demands}</div>
      )}
      {typeof rep.site_visit_notes === 'string' && rep.site_visit_notes !== '' && (
        <div><span className="font-semibold">Vor-Ort:</span> {rep.site_visit_notes}</div>
      )}
      {rep.experience_good != null && (
        <div><span className="font-semibold">Erfahrung gut:</span> {rep.experience_good ? 'Ja' : 'Nein'}</div>
      )}
      {needs.length > 0 && <div><span className="font-semibold">Benötigt:</span> {needs.join(', ')}</div>}
      <div>
        <span className="font-semibold">Status:</span> {rep.job_finished ? 'Auftrag abgeschlossen' : 'Auftrag noch offen'}
        {photoCount > 0 && ` · ${photoCount} Foto${photoCount === 1 ? '' : 's'} (siehe Kunden-Dokumente)`}
      </div>
    </div>
  )
}

const fmtDur = (s: number | null) =>
  s || s === 0 ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')} Min` : '—'

export function VorgangThreadPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [editSubject, setEditSubject] = useState(false)
  const [linkOpen, setLinkOpen] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['caseThread', id],
    queryFn: () => apiFetch<CaseThread>(`/api/inquiries/${id}/thread`),
    enabled: !!id,
  })

  if (isLoading || !data) {
    return <div className="flex h-full items-center justify-center text-muted">Lädt…</div>
  }

  const inq = data.inquiry
  const topic = inq.subject || inq.title || 'Vorgang'
  const st = STATUS[inq.status] ?? { label: inq.status, variant: 'neutral' as const }
  const refresh = () => qc.invalidateQueries({ queryKey: ['caseThread', id] })

  return (
    <div className="mx-auto max-w-5xl space-y-5 p-4 md:p-6 lg:p-8">
      <button
        onClick={() => (inq.customer ? navigate(`/customers/${inq.customer.id}`) : navigate('/customers'))}
        className="flex items-center gap-1.5 text-sm text-muted hover:text-body"
      >
        <ArrowLeft size={15} /> {inq.customer ? `Zurück zu ${inq.customer.full_name ?? 'Kunde'}` : 'Zurück'}
      </button>

      {/* HEADER */}
      <div className="rounded-lg border border-border bg-surface p-6 shadow-e1">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-xs">
              <span className="rounded-md bg-alt px-2 py-0.5 font-mono text-muted">Vorgang {inq.number ?? '—'}</span>
              <Tag variant={st.variant}>{st.label}</Tag>
            </div>
            <div className="mt-2 flex items-center gap-2">
              <h1 className="truncate text-2xl font-bold text-text">{topic}</h1>
              <button
                onClick={() => setEditSubject(true)}
                className="flex-shrink-0 rounded p-1 text-muted hover:bg-alt"
                title="Thema benennen"
              >
                <Pencil size={15} />
              </button>
            </div>
            {inq.customer && (
              <button
                onClick={() => navigate(`/customers/${inq.customer!.id}`)}
                className="mt-1 flex items-center gap-1.5 text-sm text-muted hover:text-body"
              >
                <User size={14} /> {inq.customer.full_name ?? 'Kunde'}
                {inq.customer.phone ? ` · ${inq.customer.phone}` : ''}
              </button>
            )}
          </div>
          <button
            onClick={() => setLinkOpen(true)}
            className="flex flex-shrink-0 items-center gap-1.5 rounded-md border border-border px-3 py-2 text-sm font-medium text-body hover:bg-alt"
          >
            <Link2 size={15} /> Verknüpfen / Zusammenführen
          </button>
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-border pt-5">
          <StatusSwitcher
            current={inq.status}
            onChange={(s) =>
              apiFetch(`/api/inquiries/${id}`, { method: 'PATCH', body: JSON.stringify({ status: s }) }).then(refresh)
            }
          />
          <span className="mx-1 hidden h-5 w-px bg-border sm:block" />
          <Stat label="Anrufe" value={data.calls.length} />
          <Stat label="Termine" value={data.appointments.length} />
          <Stat label="KVAs" value={data.cost_estimates.length} />
          <Stat label="offene Punkte" value={data.open_count} highlight={data.open_count > 0} />
        </div>
      </div>

      {/* RELATED CASES */}
      {data.related.length > 0 && (
        <div className="rounded-lg border border-border bg-surface p-5 shadow-e1">
          <h2 className="mb-3 text-sm font-bold text-text">Verknüpfte Vorgänge</h2>
          <div className="flex flex-wrap gap-2">
            {data.related.map((r) => (
              <button
                key={r.case.id}
                onClick={() => navigate(`/vorgang/${r.case.id}`)}
                className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm hover:border-green-primary hover:bg-alt"
              >
                <Tag variant={r.relation === 'duplicate' ? 'warning' : 'info'}>
                  {r.relation === 'duplicate' ? 'Duplikat' : 'Verwandt'}
                </Tag>
                <span className="font-mono text-xs text-muted">{r.case.number}</span>
                <span className="text-body">{r.case.subject || r.case.title || 'Vorgang'}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* CALLS (in / out) */}
      <div className="rounded-lg border border-border bg-surface p-5 shadow-e1">
        <h2 className="mb-4 text-sm font-bold text-text">Anrufe ({data.calls.length})</h2>
        {data.calls.length === 0 ? (
          <p className="py-4 text-sm text-muted">Keine Anrufe in diesem Vorgang.</p>
        ) : (
          <div className="space-y-2">
            {data.calls.map((c) => {
              const out = c.direction === 'outbound'
              return (
                <div key={c.id} className="flex items-center gap-3 rounded-lg border border-border p-3">
                  <span
                    className={cn(
                      'flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full',
                      out ? 'bg-info-bg text-info' : 'bg-success-bg text-success',
                    )}
                  >
                    {out ? <PhoneOutgoing size={16} /> : <PhoneIncoming size={16} />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-text">
                      {c.summary_title || (out ? 'Ausgehender Anruf' : 'Eingehender Anruf')}
                    </div>
                    <div className="text-xs text-muted">
                      {out ? 'Ausgehend' : 'Eingehend'} · {fmtDateTime(c.started_at || c.created_at)} · {fmtDur(c.duration_seconds)}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* UNIFIED TIMELINE */}
      <div className="rounded-lg border border-border bg-surface p-5 shadow-e1">
        <h2 className="mb-4 text-sm font-bold text-text">Verlauf ({data.timeline.length})</h2>
        {data.timeline.length === 0 ? (
          <p className="py-4 text-sm text-muted">Noch keine Aktivitäten.</p>
        ) : (
          <div className="flex flex-col">
            {data.timeline.map((ev, i) => {
              const k = TL[ev.kind] ?? { Icon: History, cls: 'bg-alt text-muted' }
              const last = i === data.timeline.length - 1
              return (
                <div key={ev.id} className={cn('relative flex items-start gap-3.5', !last && 'pb-5')}>
                  {!last && <span className="absolute bottom-0 left-[19px] top-[42px] w-0.5 bg-border" aria-hidden />}
                  <span className={cn('z-[1] flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full', k.cls)}>
                    <k.Icon size={18} />
                  </span>
                  <div className="min-w-0 flex-1 pt-1">
                    <div className="text-sm font-semibold text-text">{ev.description}</div>
                    <div className="mt-0.5 text-xs text-muted">
                      {fmtDateTime(ev.timestamp)} · {ev.actor_name}
                    </div>
                    {ev.kind === 'technician_report_submitted' && <TechReport extras={ev.extras} />}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <div className="rounded-lg border border-border bg-surface px-5 py-3 text-xs text-muted">
        Eröffnet: {fmtDate(inq.created_at)}
        {inq.assigned_employee?.display_name ? ` · Zugewiesen: ${inq.assigned_employee.display_name}` : ''}
      </div>

      {editSubject && (
        <SubjectModal
          id={id}
          current={inq.subject ?? ''}
          number={inq.number}
          onClose={() => setEditSubject(false)}
          onSaved={() => {
            setEditSubject(false)
            refresh()
          }}
        />
      )}
      {linkOpen && inq.customer && (
        <LinkMergeModal
          caseId={id}
          customerId={inq.customer.id}
          onClose={() => setLinkOpen(false)}
          onDone={() => {
            setLinkOpen(false)
            refresh()
          }}
        />
      )}
    </div>
  )
}

function Stat({ label, value, highlight }: { label: string; value: number; highlight?: boolean }) {
  return (
    <div className={cn('rounded-md px-3 py-1.5 text-sm', highlight ? 'bg-warning-bg' : 'bg-alt')}>
      <span className={cn('font-bold', highlight ? 'text-warning' : 'text-text')}>{value}</span>{' '}
      <span className="text-muted">{label}</span>
    </div>
  )
}

function StatusSwitcher({ current, onChange }: { current: string; onChange: (s: string) => void }) {
  const opts: [string, string][] = [
    ['open', 'Offen'],
    ['in_progress', 'In Bearbeitung'],
    ['completed', 'Abgeschlossen'],
  ]
  return (
    <div className="inline-flex overflow-hidden rounded-md border border-border">
      {opts.map(([v, l]) => (
        <button
          key={v}
          onClick={() => onChange(v)}
          className={cn(
            'px-3 py-1.5 text-xs font-medium',
            current === v ? 'bg-green-primary text-white' : 'bg-surface text-muted hover:bg-alt',
          )}
        >
          {l}
        </button>
      ))}
    </div>
  )
}

function SubjectModal({
  id,
  current,
  number,
  onClose,
  onSaved,
}: {
  id: string
  current: string
  number: string | null
  onClose: () => void
  onSaved: () => void
}) {
  const [val, setVal] = useState(current)
  const save = useMutation({
    mutationFn: () => apiFetch(`/api/inquiries/${id}`, { method: 'PATCH', body: JSON.stringify({ subject: val }) }),
    onSuccess: onSaved,
  })
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title="Thema des Vorgangs benennen"
      footer={
        <button
          onClick={() => save.mutate()}
          disabled={save.isPending}
          className="w-full rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
        >
          Speichern
        </button>
      }
    >
      <div className="space-y-2">
        <div className="text-xs font-semibold text-body">Kurzes Thema, das der Kunde wiedererkennt</div>
        <input
          value={val}
          onChange={(e) => setVal(e.target.value)}
          placeholder="z. B. Dach undicht – Garage"
          className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary"
        />
        <p className="text-xs text-muted">
          Wird dem Vorgang {number ?? ''} zugeordnet. Die Nummer bleibt intern fürs Team — dem Kunden gegenüber wird nur
          das Thema genannt.
        </p>
      </div>
    </Modal>
  )
}

function LinkMergeModal({
  caseId,
  customerId,
  onClose,
  onDone,
}: {
  caseId: string
  customerId: string
  onClose: () => void
  onDone: () => void
}) {
  const [picked, setPicked] = useState<string | null>(null)
  const { data: customer } = useQuery({
    queryKey: ['customerDetail', customerId],
    queryFn: () =>
      apiFetch<{ inquiries: { id: string; number: string | null; subject: string | null; title: string | null; status: string }[] }>(
        `/api/customers/${customerId}`,
      ),
  })
  const others = (customer?.inquiries ?? []).filter((i) => i.id !== caseId)
  const link = useMutation({
    mutationFn: () =>
      apiFetch(`/api/inquiries/${caseId}/link`, {
        method: 'POST',
        body: JSON.stringify({ related_case_id: picked, relation: 'related' }),
      }),
    onSuccess: onDone,
  })
  const merge = useMutation({
    mutationFn: () =>
      apiFetch(`/api/inquiries/${caseId}/merge`, { method: 'POST', body: JSON.stringify({ into_case_id: picked }) }),
    onSuccess: onDone,
  })
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title="Vorgänge verknüpfen oder zusammenführen"
      footer={
        <div className="flex gap-2">
          <button
            disabled={!picked || link.isPending}
            onClick={() => link.mutate()}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-md border border-border py-2.5 text-sm font-semibold text-body hover:bg-alt disabled:opacity-50"
          >
            <Link2 size={15} /> Verknüpfen
          </button>
          <button
            disabled={!picked || merge.isPending}
            onClick={() => {
              if (window.confirm('Diesen Vorgang in den gewählten zusammenführen? Anrufe, Termine und KVAs werden verschoben.'))
                merge.mutate()
            }}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
          >
            <GitMerge size={15} /> Zusammenführen
          </button>
        </div>
      }
    >
      <div className="max-h-72 space-y-1.5 overflow-y-auto">
        <p className="mb-2 text-xs text-muted">Anderen Vorgang dieses Kunden wählen:</p>
        {others.length === 0 && <p className="py-4 text-center text-sm text-muted">Keine weiteren Vorgänge.</p>}
        {others.map((i) => (
          <button
            key={i.id}
            onClick={() => setPicked(i.id)}
            className={cn(
              'flex w-full items-center gap-2 rounded-md border p-2.5 text-left text-sm',
              picked === i.id ? 'border-green-primary bg-green-tint-100' : 'border-border hover:bg-alt',
            )}
          >
            <span className="font-mono text-xs text-muted">{i.number}</span>
            <span className="flex-1 truncate text-body">{i.subject || i.title || 'Vorgang'}</span>
            {picked === i.id && <Check size={15} className="text-green-deep" />}
          </button>
        ))}
      </div>
    </Modal>
  )
}
