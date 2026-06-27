import { Search } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'

import { cn } from '../../lib/utils'
import { OrphanCallCard } from './OrphanCallCard'
import type { CustomerDetail, MasterTab, ModalTarget, StatusFilter } from './types'
import { VorgangCard } from './VorgangCard'
import {
  filterCasesBySearch,
  filterCasesByStatus,
  filterOrphansBySearch,
  groupCasesByActivityDate,
  groupOrphansByDate,
  orphanInquiries,
  statusFilterCounts,
} from './useCustomerVorgaenge'

interface Props {
  customer: CustomerDetail
  onOpenModal: (target: ModalTarget) => void
  onAssignOrphan: (inquiryId: string) => void
}

export function CustomerVorgangSection({ customer, onOpenModal, onAssignOrphan }: Props) {
  const [master, setMaster] = useState<MasterTab>('vorgaenge')
  const [filter, setFilter] = useState<StatusFilter>('all')
  const [search, setSearch] = useState('')

  const cases = customer.cases ?? []
  const counts = useMemo(() => statusFilterCounts(cases), [cases])
  const orphans = useMemo(() => orphanInquiries(customer.inquiries ?? []), [customer.inquiries])

  const filteredCases = useMemo(() => {
    let list = filterCasesByStatus(cases, filter)
    list = filterCasesBySearch(list, search)
    return groupCasesByActivityDate(list)
  }, [cases, filter, search])

  const filteredOrphans = useMemo(() => {
    let list = filterOrphansBySearch(orphans, search)
    return groupOrphansByDate(list)
  }, [orphans, search])

  const chips: [StatusFilter, string][] = [
    ['all', 'Alle'],
    ['open', 'Neu'],
    ['in_progress', 'In Bearb.'],
    ['completed', 'Erledigt'],
  ]

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1 rounded-lg border border-border bg-alt p-0.5">
          <TabBtn active={master === 'vorgaenge'} onClick={() => { setMaster('vorgaenge'); setSearch('') }}>
            Vorgänge <CountBadge n={cases.length} active={master === 'vorgaenge'} />
          </TabBtn>
          <TabBtn active={master === 'lone'} onClick={() => { setMaster('lone'); setSearch('') }}>
            Nicht zugeordnet <CountBadge n={orphans.length} active={master === 'lone'} />
          </TabBtn>
        </div>
        <div className="relative min-w-[200px] max-w-sm flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={master === 'lone' ? 'Anrufe durchsuchen…' : 'Vorgänge durchsuchen…'}
            autoComplete="off"
            className="w-full rounded-md border border-border bg-surface py-2 pl-9 pr-3 text-sm text-body outline-none focus:border-green-primary"
          />
        </div>
      </div>

      {master === 'vorgaenge' && (
        <div className="flex flex-wrap gap-1.5">
          {chips.map(([k, l]) => {
            const on = filter === k
            return (
              <button
                key={k}
                type="button"
                onClick={() => setFilter(k)}
                className={cn(
                  'flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold transition-colors',
                  on ? 'bg-text text-bg' : 'bg-alt text-body hover:bg-border',
                )}
              >
                {l}
                <span className={on ? 'opacity-60' : 'text-faint'}>{counts[k]}</span>
              </button>
            )
          })}
        </div>
      )}

      {master === 'vorgaenge' ? (
        filteredCases.length === 0 ? (
          <p className="py-12 text-center text-sm text-muted">Keine Vorgänge gefunden.</p>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {filteredCases.map((g) => (
              <GroupBlock key={g.label} label={g.label} count={g.items.length}>
                {g.items.map((c) => (
                  <VorgangCard key={c.id} c={c} onClick={() => onOpenModal({ kind: 'vorgang', id: c.id })} />
                ))}
              </GroupBlock>
            ))}
          </div>
        )
      ) : filteredOrphans.length === 0 ? (
        <p className="py-12 text-center text-sm text-muted">Alle Anrufe sind zugeordnet.</p>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {filteredOrphans.map((g) => (
            <GroupBlock key={g.label} label={g.label} count={g.items.length}>
              {g.items.map((inq) => (
                <OrphanCallCard
                  key={inq.id}
                  inquiry={inq}
                  onOpen={() => onOpenModal({ kind: 'call', id: inq.id })}
                  onAssign={() => onAssignOrphan(inq.id)}
                />
              ))}
            </GroupBlock>
          ))}
        </div>
      )}
    </div>
  )
}

function TabBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-semibold transition-colors',
        active ? 'bg-surface text-text shadow-e1' : 'text-muted hover:text-body',
      )}
    >
      {children}
    </button>
  )
}

function CountBadge({ n, active }: { n: number; active: boolean }) {
  return (
    <span className={cn('rounded-full px-1.5 text-xs', active ? 'bg-green-tint-100 text-green-deep' : 'bg-alt text-faint')}>{n}</span>
  )
}

function GroupBlock({ label, count, children }: { label: string; count: number; children: ReactNode }) {
  return (
    <>
      <div className="col-span-full mt-1 flex items-center gap-2">
        <span className="text-[11px] font-bold uppercase tracking-wide text-muted">{label}</span>
        <span className="h-px flex-1 bg-border-faint" />
        <span className="font-mono text-[11px] text-faint">{count}</span>
      </div>
      {children}
    </>
  )
}
