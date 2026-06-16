import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  CalendarClock,
  Euro,
  History,
  Layers,
  MessageSquare,
  Phone,
  Sparkles,
  User,
  type LucideIcon,
} from 'lucide-react'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { GroupingReviewModal, MoveMenu, type GroupProposal, type MoveTarget } from '../components/cases/grouping'
import { Tag } from '../components/ui/Tag'
import { apiFetch } from '../lib/api'
import { fmtDate, fmtDateTime } from '../lib/datetime'
import { cn } from '../lib/utils'

interface CaseInquiry {
  id: string
  number: string | null
  subject: string | null
  title: string | null
  status: string
  case_confidence?: number | null
  case_reason?: string | null
}
interface TLEvent {
  id: string
  kind: string
  timestamp: string
  actor_name: string
  description: string
  extras: Record<string, unknown>
}
interface CaseBundle {
  case: {
    id: string
    number: string | null
    label: string | null
    status: string
    customer: { id: string; full_name: string | null; phone: string | null } | null
    created_at: string | null
  }
  inquiries: CaseInquiry[]
  timeline: TLEvent[]
  calls: unknown[]
  appointments: unknown[]
  cost_estimates: unknown[]
  open_count: number
}

const STATUS: Record<string, { label: string; variant: 'info' | 'warning' | 'success' | 'neutral' }> = {
  open: { label: 'Offen', variant: 'info' },
  in_progress: { label: 'In Bearbeitung', variant: 'warning' },
  completed: { label: 'Abgeschlossen', variant: 'success' },
  closed: { label: 'Geschlossen', variant: 'neutral' },
}
const INQ_STATUS: Record<string, { label: string; variant: 'info' | 'warning' | 'success' | 'neutral' }> = {
  open: { label: 'Neu', variant: 'info' },
  in_progress: { label: 'In Bearbeitung', variant: 'warning' },
  completed: { label: 'Erledigt', variant: 'success' },
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
}

export function CaseDetailPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [proposal, setProposal] = useState<GroupProposal | null>(null)
  const { data, isLoading } = useQuery({
    queryKey: ['caseDetail', id],
    queryFn: () => apiFetch<CaseBundle>(`/api/cases/${id}`),
    enabled: !!id,
  })
  // The customer's other cases = the move targets for "verschieben".
  const { data: allCases } = useQuery({
    queryKey: ['cases'],
    queryFn: () => apiFetch<{ id: string; number: string | null; title: string; customer_id: string | null }[]>('/api/cases'),
    enabled: !!id,
  })
  const customerId = data?.case.customer?.id ?? null
  const propose = useMutation({
    mutationFn: () => apiFetch<GroupProposal>(`/api/customers/${customerId}/cases/propose`, { method: 'POST' }),
    onSuccess: (p) => setProposal(p),
  })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['caseDetail', id] })
    qc.invalidateQueries({ queryKey: ['cases'] })
  }
  if (isLoading || !data) {
    return <div className="flex h-full items-center justify-center text-muted">Lädt…</div>
  }
  const cs = data.case
  const st = STATUS[cs.status] ?? { label: cs.status, variant: 'neutral' as const }
  const moveTargets: MoveTarget[] = (allCases ?? [])
    .filter((c) => customerId && c.customer_id === customerId)
    .map((c) => ({ id: c.id, label: c.title, number: c.number }))
  return (
    <div className="mx-auto max-w-5xl space-y-5 p-4 md:p-6 lg:p-8">
      <button
        onClick={() => (cs.customer ? navigate(`/customers/${cs.customer.id}`) : navigate('/customers'))}
        className="flex items-center gap-1.5 text-sm text-muted hover:text-body"
      >
        <ArrowLeft size={15} /> {cs.customer ? `Zurück zu ${cs.customer.full_name ?? 'Kunde'}` : 'Zurück'}
      </button>

      {/* HEADER */}
      <div className="rounded-lg border border-border bg-surface p-6 shadow-e1">
        <div className="flex items-center gap-2 text-xs">
          <span className="inline-flex items-center gap-1 rounded-md bg-ai-bg px-2 py-0.5 font-mono font-semibold text-ai">
            <Layers size={12} /> Fall {cs.number ?? '—'}
          </span>
          <Tag variant={st.variant}>{st.label}</Tag>
        </div>
        <h1 className="mt-2 truncate text-2xl font-bold text-text">{cs.label || 'Fall'}</h1>
        {cs.customer && (
          <button
            onClick={() => navigate(`/customers/${cs.customer!.id}`)}
            className="mt-1 flex items-center gap-1.5 text-sm text-muted hover:text-body"
          >
            <User size={14} /> {cs.customer.full_name ?? 'Kunde'}
            {cs.customer.phone ? ` · ${cs.customer.phone}` : ''}
          </button>
        )}
        <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-border pt-5">
          <Stat label="Anfragen" value={data.inquiries.length} />
          <Stat label="Anrufe" value={data.calls.length} />
          <Stat label="Termine" value={data.appointments.length} />
          <Stat label="KVAs" value={data.cost_estimates.length} />
          <Stat label="offene Punkte" value={data.open_count} highlight={data.open_count > 0} />
        </div>
      </div>

      {/* MEMBER INQUIRIES — with per-inquiry move + customer-wide KI-Gruppierung */}
      <div className="rounded-lg border border-border bg-surface p-5 shadow-e1">
        <div className="mb-4 flex items-center justify-between gap-2">
          <h2 className="text-sm font-bold text-text">Anfragen in diesem Fall ({data.inquiries.length})</h2>
          {customerId && (
            <button
              onClick={() => propose.mutate()}
              disabled={propose.isPending}
              className="flex items-center gap-1.5 rounded-md border border-ai-bg px-3 py-1.5 text-xs font-semibold text-ai hover:bg-ai-bg disabled:opacity-50"
              title="Ähnliche Anfragen dieses Kunden per KI zu Fällen bündeln"
            >
              <Sparkles size={14} /> {propose.isPending ? 'Analysiere…' : 'KI-Gruppierung'}
            </button>
          )}
        </div>
        <div className="space-y-2">
          {data.inquiries.map((i) => {
            const ist = INQ_STATUS[i.status] ?? { label: i.status, variant: 'neutral' as const }
            return (
              <div
                key={i.id}
                className="group relative rounded-lg border border-border transition hover:border-green-primary hover:bg-alt"
              >
                <div onClick={() => navigate(`/vorgang/${i.id}`)} className="cursor-pointer p-3 pr-9">
                  <div className="flex items-center gap-2">
                    <Tag variant={ist.variant}>{ist.label}</Tag>
                    <span className="flex-1 truncate text-sm font-semibold text-text">{i.subject || i.title || 'Anfrage'}</span>
                    <span className="font-mono text-xs text-muted">{i.number}</span>
                  </div>
                </div>
                <MoveMenu inquiryId={i.id} currentCaseId={cs.id} cases={moveTargets} onMoved={refresh} />
              </div>
            )
          })}
          {data.inquiries.length === 0 && <p className="py-4 text-sm text-muted">Keine Anfragen in diesem Fall.</p>}
        </div>
      </div>

      {/* UMBRELLA TIMELINE */}
      <div className="rounded-lg border border-border bg-surface p-5 shadow-e1">
        <h2 className="mb-4 text-sm font-bold text-text">Gesamter Verlauf ({data.timeline.length})</h2>
        {data.timeline.length === 0 ? (
          <p className="py-4 text-sm text-muted">Noch keine Aktivitäten.</p>
        ) : (
          <div className="flex flex-col">
            {data.timeline.map((ev, idx) => {
              const k = TL[ev.kind] ?? { Icon: History, cls: 'bg-alt text-muted' }
              const last = idx === data.timeline.length - 1
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
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <div className="rounded-lg border border-border bg-surface px-5 py-3 text-xs text-muted">Eröffnet: {fmtDate(cs.created_at)}</div>

      {proposal && customerId && (
        <GroupingReviewModal
          customerId={customerId}
          proposal={proposal}
          onClose={() => setProposal(null)}
          onApplied={() => {
            setProposal(null)
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
