import { useQuery } from '@tanstack/react-query'
import {
  ArrowRightLeft,
  ArrowUpRight,
  CalendarClock,
  Clock,
  Euro,
  History,
  Phone,
  Unlink,
  X,
  type LucideIcon,
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { Tag } from '../../components/ui/Tag'
import { apiFetch } from '../../lib/api'
import { fmtDurationLong, type TimelineEvent, type TimelineEventKind } from '../calls/shared'
import { relativeTimeDe } from '../../lib/datetime'
import { cn } from '../../lib/utils'
import { CASE_STATUS } from '../cases/types'
import { CASE_STATUS_RAIL, resolveInquiryForCallEvent } from './useCustomerVorgaenge'
import type { CaseCardRow } from './types'

interface CaseUmbrellaResponse {
  case: CaseCardRow & { emergency?: boolean }
  timeline: TimelineEvent[]
  calls: { id: string; inquiry_id: string | null; summary_title: string | null; direction: string | null; duration_seconds: number | null }[]
}

const TL: Record<TimelineEventKind, { Icon: LucideIcon; label: string; cls: string }> = {
  call_created: { Icon: Phone, label: 'Anruf', cls: 'bg-success-bg text-success' },
  inquiry_status_changed: { Icon: History, label: 'Status', cls: 'bg-info-bg text-info' },
  appointment_created: { Icon: CalendarClock, label: 'Termin', cls: 'bg-green-tint-100 text-green-deep' },
  appointment_rescheduled: { Icon: CalendarClock, label: 'Termin', cls: 'bg-warning-bg text-warning' },
  appointment_confirmed: { Icon: CalendarClock, label: 'Termin', cls: 'bg-success-bg text-success' },
  appointment_rejected: { Icon: CalendarClock, label: 'Termin', cls: 'bg-error-bg text-error' },
  appointment_cancelled: { Icon: CalendarClock, label: 'Termin', cls: 'bg-error-bg text-error' },
  alternative_proposed: { Icon: CalendarClock, label: 'Termin', cls: 'bg-warning-bg text-warning' },
  kva_sent: { Icon: Euro, label: 'Angebot', cls: 'bg-ai-bg text-ai' },
  kva_accepted: { Icon: Euro, label: 'Angebot', cls: 'bg-ai-bg text-ai' },
  kva_rejected: { Icon: Euro, label: 'Angebot', cls: 'bg-ai-bg text-ai' },
  assignment_changed: { Icon: History, label: 'Zuweisung', cls: 'bg-info-bg text-info' },
}

interface Props {
  caseRow: CaseCardRow
  onClose: () => void
  onTransfer: (inquiryId: string, fromCaseId: string) => void
  onLoosen: (inquiryId: string) => void
}

export function VorgangDetailModal({ caseRow, onClose, onTransfer, onLoosen }: Props) {
  const navigate = useNavigate()
  const { data, isLoading } = useQuery({
    queryKey: ['caseUmbrella', caseRow.id],
    queryFn: () => apiFetch<CaseUmbrellaResponse>(`/api/cases/${caseRow.id}`),
  })

  const st = CASE_STATUS.find((s) => s.value === caseRow.status) ?? CASE_STATUS[0]
  const rail = CASE_STATUS_RAIL[caseRow.status] ?? CASE_STATUS_RAIL.planning
  const timeline = data?.timeline ?? []
  const calls = data?.calls ?? []

  return (
    <div className="fixed inset-0 z-[55] flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm sm:p-8" onClick={onClose}>
      <div
        className="flex w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-border bg-surface shadow-e3"
        style={{ maxHeight: '82vh' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex-shrink-0 border-b border-border p-5" style={{ borderLeft: `3px solid ${rail}` }}>
          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 flex-wrap items-center gap-2.5">
              <h2 className="text-lg font-bold leading-snug text-text">{caseRow.label || 'Vorgang'}</h2>
              <Tag variant={st.tone}>{st.label}</Tag>
            </div>
            <div className="flex flex-shrink-0 items-center gap-2">
              <button
                type="button"
                onClick={() => navigate(`/cases?case=${caseRow.id}`)}
                className="flex items-center gap-1.5 rounded-md bg-green-primary px-3 py-1.5 text-xs font-semibold text-white hover:brightness-110"
              >
                <ArrowUpRight size={14} />
                Vorgang öffnen
              </button>
              <button type="button" onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted hover:bg-alt">
                <X size={16} />
              </button>
            </div>
          </div>
          {caseRow.ai_summary && <p className="mt-2 text-sm leading-relaxed text-muted">{caseRow.ai_summary}</p>}
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-faint">
            <span className="flex items-center gap-1">
              <Phone size={14} />
              {caseRow.call_count ?? 0} Anrufe
            </span>
            <span className="flex items-center gap-1">
              <Clock size={14} />
              {caseRow.last_activity_at ? relativeTimeDe(caseRow.last_activity_at) : '—'}
            </span>
            <span className="font-mono">{timeline.length || caseRow.entry_count || 0} Einträge</span>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {isLoading ? (
            <p className="text-sm text-muted">Lade Verlauf…</p>
          ) : timeline.length === 0 ? (
            <p className="text-sm text-muted">Noch keine Aktivitäten.</p>
          ) : (
            <div className="relative pt-1">
              <span className="absolute bottom-4 left-[18px] top-2 w-0.5 rounded bg-border" aria-hidden />
              {timeline.map((ev) => {
                const k = TL[ev.kind] ?? { Icon: History, label: 'Ereignis', cls: 'bg-alt text-muted' }
                const isCall = ev.kind === 'call_created'
                const inquiryId = isCall ? resolveInquiryForCallEvent(ev.entity_id ?? '', calls) : null
                const dur = ev.extras?.duration_seconds as number | undefined
                return (
                  <div key={ev.id} className="relative mb-3 flex gap-3.5">
                    <div className="flex w-9 flex-shrink-0 justify-center">
                      <span className={cn('z-10 flex h-9 w-9 items-center justify-center rounded-full ring-4 ring-surface', k.cls)}>
                        <k.Icon size={18} />
                      </span>
                    </div>
                    <div className="min-w-0 flex-1 rounded-xl border border-border bg-surface p-3.5 shadow-e1">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="text-[10px] font-bold uppercase tracking-wide text-muted">{k.label}</div>
                          <div className="mt-0.5 text-sm font-bold text-text">{ev.description}</div>
                        </div>
                        <span className="flex-shrink-0 font-mono text-[11px] text-faint">{relativeTimeDe(ev.timestamp)}</span>
                      </div>
                      <div className="mt-2.5 flex items-center justify-between gap-2">
                        <span className="text-[11px] text-faint">
                          {ev.actor_name}
                          {dur != null ? ` · ${fmtDurationLong(dur)}` : ''}
                        </span>
                        {isCall && inquiryId && (
                          <span className="flex items-center gap-1.5">
                            <button
                              type="button"
                              onClick={() => onTransfer(inquiryId, caseRow.id)}
                              className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-medium text-muted hover:border-green-primary hover:bg-green-tint-50 hover:text-green-deep"
                            >
                              <ArrowRightLeft size={12} />
                              Verschieben
                            </button>
                            <button
                              type="button"
                              onClick={() => onLoosen(inquiryId)}
                              className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-medium text-muted hover:border-error hover:bg-error-bg hover:text-error"
                            >
                              <Unlink size={12} />
                              Lösen
                            </button>
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
