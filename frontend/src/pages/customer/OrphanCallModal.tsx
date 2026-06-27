import { CornerUpRight, PhoneIncoming, PhoneOutgoing, X } from 'lucide-react'

import { fmtDurationLong } from '../calls/shared'
import { fmtClockUhr } from '../../lib/datetime'
import { cn } from '../../lib/utils'
import type { InquiryRow } from './types'

interface Props {
  inquiry: InquiryRow
  onClose: () => void
  onAssign: () => void
}

export function OrphanCallModal({ inquiry, onClose, onAssign }: Props) {
  const pc = inquiry.primary_call
  const out = pc?.direction === 'outbound'
  const DirIcon = out ? PhoneOutgoing : PhoneIncoming
  const title = pc?.summary_title || inquiry.subject || inquiry.title || 'Anfrage'

  return (
    <div className="fixed inset-0 z-[55] flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm sm:p-8" onClick={onClose}>
      <div
        className="flex w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-border bg-surface shadow-e3"
        style={{ maxHeight: '82vh' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex-shrink-0 border-b border-border p-5">
          <div className="flex items-start gap-3">
            <span className={cn('flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl', out ? 'bg-info-bg text-info' : 'bg-success-bg text-success')}>
              <DirIcon size={20} />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-lg font-bold text-text">{title}</h2>
              <div className="mt-0.5 flex items-center gap-2 text-xs text-faint">
                <span className="font-mono">{pc?.started_at ? fmtClockUhr(pc.started_at) : '—'}</span>
                <span>·</span>
                <span className="font-mono">{fmtDurationLong(pc?.duration_seconds ?? null)}</span>
              </div>
            </div>
            <button type="button" onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted hover:bg-alt">
              <X size={16} />
            </button>
          </div>
        </div>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
          <div className="rounded-xl bg-alt p-4 text-sm text-body">
            {inquiry.subject || inquiry.title || inquiry.notes || 'Keine Details.'}
          </div>
          <button
            type="button"
            onClick={onAssign}
            className="flex w-full items-center justify-between gap-2 rounded-xl border border-border bg-surface px-4 py-3 text-left shadow-e1 transition-colors hover:border-green-primary hover:bg-green-tint-50"
          >
            <span className="flex items-center gap-2 text-sm font-semibold text-green-deep">
              <CornerUpRight size={16} />
              Zu Vorgang zuordnen
            </span>
          </button>
        </div>
      </div>
    </div>
  )
}
