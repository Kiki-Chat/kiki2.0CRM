import { Search, X } from 'lucide-react'
import { useMemo, useState } from 'react'

import { CASE_STATUS } from '../cases/types'
import { CASE_STATUS_RAIL, filterPickerTargets } from './useCustomerVorgaenge'
import type { CaseCardRow } from './types'

interface Props {
  mode: 'assign' | 'transfer'
  cases: CaseCardRow[]
  fromCaseId?: string
  onClose: () => void
  onPick: (caseId: string) => void
}

export function VorgangAssignPicker({ mode, cases, fromCaseId, onClose, onPick }: Props) {
  const [q, setQ] = useState('')
  const list = useMemo(() => filterPickerTargets(cases, mode, fromCaseId), [cases, mode, fromCaseId])
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    if (!needle) return list
    return list.filter((v) => (v.label ?? '').toLowerCase().includes(needle))
  }, [list, q])

  const title = mode === 'transfer' ? 'In anderen Vorgang verschieben' : 'Anruf einem Vorgang zuordnen'

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center bg-black/40 p-4 pt-20 backdrop-blur-sm" onClick={onClose}>
      <div
        className="flex w-full max-w-md flex-col overflow-hidden rounded-2xl border border-border bg-surface shadow-e3"
        style={{ maxHeight: '80vh' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex flex-shrink-0 items-center justify-between gap-2 border-b border-border px-4 py-3">
          <div className="text-sm font-bold text-text">{title}</div>
          <button type="button" onClick={onClose} className="rounded-md p-1 text-muted hover:bg-alt">
            <X size={16} />
          </button>
        </div>
        <div className="flex-shrink-0 border-b border-border p-2">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Vorgang suchen…"
              className="w-full rounded-md border border-border bg-alt py-2 pl-9 pr-3 text-sm text-body outline-none focus:border-green-primary"
            />
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
          {filtered.length === 0 ? (
            <p className="px-3 py-8 text-center text-sm text-muted">Kein Vorgang gefunden.</p>
          ) : (
            filtered.map((v) => {
              const st = CASE_STATUS.find((s) => s.value === v.status) ?? CASE_STATUS[0]
              return (
                <button
                  key={v.id}
                  type="button"
                  onClick={() => onPick(v.id)}
                  className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-green-tint-50"
                >
                  <span className="h-2 w-2 flex-shrink-0 rounded-full" style={{ background: CASE_STATUS_RAIL[v.status] ?? CASE_STATUS_RAIL.planning }} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold text-text">{v.label || 'Vorgang'}</span>
                    <span className="text-[11px] text-faint">
                      {st.label} · {v.call_count ?? 0} Anrufe
                    </span>
                  </span>
                </button>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}
