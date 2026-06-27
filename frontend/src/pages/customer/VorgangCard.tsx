import { ArrowUpRight, Clock, Phone } from 'lucide-react'

import { Tag } from '../../components/ui/Tag'
import { relativeTimeDe } from '../../lib/datetime'
import { cn } from '../../lib/utils'
import { CASE_STATUS } from '../cases/types'
import { CASE_STATUS_RAIL } from './useCustomerVorgaenge'
import type { CaseCardRow } from './types'

interface Props {
  c: CaseCardRow
  onClick: () => void
}

export function VorgangCard({ c, onClick }: Props) {
  const st = CASE_STATUS.find((s) => s.value === c.status) ?? CASE_STATUS[0]
  const rail = CASE_STATUS_RAIL[c.status] ?? CASE_STATUS_RAIL.planning
  const summary = c.ai_summary ?? ''
  const last = c.last_activity_at ? relativeTimeDe(c.last_activity_at) : '—'

  return (
    <button
      type="button"
      onClick={onClick}
      className="flex flex-col rounded-lg border border-border bg-surface p-2.5 text-left shadow-e1 transition-all hover:-translate-y-0.5 hover:border-green-primary hover:shadow-e2"
      style={{ borderLeft: `3px solid ${rail}` }}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[13px] font-bold text-text">{c.label || 'Vorgang'}</span>
        <ArrowUpRight size={14} className="flex-shrink-0 text-faint" />
      </div>
      <div className="mt-1 flex items-center gap-2">
        <Tag variant={st.tone}>{st.label}</Tag>
        {summary && <span className="truncate text-[11px] text-muted">{summary}</span>}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-[11px] text-faint">
        <span className="flex items-center gap-1">
          <Phone size={12} />
          {c.call_count ?? 0} Anrufe
        </span>
        <span className="flex items-center gap-1">
          <Clock size={12} />
          {last}
        </span>
        <span className="font-mono">{c.entry_count ?? 0} Einträge</span>
      </div>
    </button>
  )
}
