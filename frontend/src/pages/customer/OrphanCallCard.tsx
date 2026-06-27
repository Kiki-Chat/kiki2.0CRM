import { ArrowUpRight, CornerUpRight, PhoneIncoming, PhoneOutgoing, Sparkles } from 'lucide-react'

import { fmtDurationLong } from '../calls/shared'
import { fmtClockUhr } from '../../lib/datetime'
import { cn } from '../../lib/utils'
import type { InquiryRow } from './types'

function dirMeta(direction: string | null | undefined) {
  const out = direction === 'outbound'
  return out
    ? { Icon: PhoneOutgoing, bg: 'bg-info-bg text-info', label: 'Ausgehend' }
    : { Icon: PhoneIncoming, bg: 'bg-success-bg text-success', label: 'Eingehend' }
}

interface Props {
  inquiry: InquiryRow
  onOpen: () => void
  onAssign: () => void
}

export function OrphanCallCard({ inquiry, onOpen, onAssign }: Props) {
  const pc = inquiry.primary_call
  const d = dirMeta(pc?.direction)
  const title = pc?.summary_title || inquiry.subject || inquiry.title || 'Anfrage'
  const when = pc?.started_at ? fmtClockUhr(pc.started_at) : '—'

  return (
    <div className="flex flex-col rounded-lg border border-border bg-surface p-2.5 shadow-e1 transition-all hover:border-green-primary hover:shadow-e2">
      <button type="button" onClick={onOpen} className="flex w-full items-center gap-2.5 text-left">
        <span className={cn('flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg', d.bg)}>
          <d.Icon size={14} />
        </span>
        <div className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-bold text-text">{title}</span>
          <span className="mt-0.5 flex items-center gap-2 text-[11px] text-faint">
            <span className="font-mono">{when}</span>
            <span>·</span>
            <span className="font-mono">{fmtDurationLong(pc?.duration_seconds ?? null)}</span>
          </span>
        </div>
        <ArrowUpRight size={14} className="flex-shrink-0 text-faint" />
      </button>
      <p className="mt-2 line-clamp-3 text-sm text-muted">
        {inquiry.subject || inquiry.title || 'Keine Zusammenfassung.'}
      </p>
      <div className="mt-2.5 flex items-center justify-between border-t border-border-faint pt-2">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            onAssign()
          }}
          className="inline-flex items-center gap-1.5 text-xs font-semibold text-green-deep hover:underline"
        >
          <CornerUpRight size={14} />
          Zu Vorgang zuordnen
        </button>
        {inquiry.case_confidence != null && (
          <span className="flex items-center gap-1 text-[11px] text-ai" title={inquiry.case_reason ?? ''}>
            <Sparkles size={14} />
          </span>
        )}
      </div>
    </div>
  )
}
