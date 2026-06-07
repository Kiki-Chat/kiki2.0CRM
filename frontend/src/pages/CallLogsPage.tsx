// Call Logs ("Anrufe") — 3-pane cockpit. This file is the thin orchestrator:
// it owns the LEFT inbox's queries/mutations/state/realtime exactly as before
// and composes the presentational modules in ./calls. The center+right detail
// orchestration lives in ./calls/CallDetail. No data shapes / endpoints changed.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Inbox, ListChecks, Search } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { apiFetch } from '../lib/api'
import { supabase } from '../lib/supabase'
import { FilterPopover, PagerNumbered, Segmented } from './calls/atoms'
import { CallDetail } from './calls/CallDetail'
import { ActionRow, CallRow, EmptyAktionen } from './calls/Inbox'
import { ResizeHandle, useColumnResize } from './calls/resize'
import { NoCallSelected } from './calls/Transcript'
import {
  type ActionItem,
  type CallListItem,
  displayName,
  type Employee,
  type InboxFilters,
  matchesDateFilter,
} from './calls/shared'

const PAGE_SIZE = 8

export function CallLogsPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [rightOpen, setRightOpen] = useState(true)
  // Deep-link seeding (dashboard CTAs): ?direction=&status=&tab=.
  const [filters, setFilters] = useState<InboxFilters>(() => {
    const d = searchParams.get('direction')
    const s = searchParams.get('status')
    return {
      dir: d === 'inbound' || d === 'outbound' ? d : 'all',
      status: s === 'open' || s === 'in_progress' || s === 'completed' ? s : 'all',
      date: 'all',
      from: '',
      to: '',
    }
  })
  const [tab, setTab] = useState<'anfragen' | 'aktionen'>(() =>
    searchParams.get('tab') === 'aktionen' ? 'aktionen' : 'anfragen',
  )

  const me = useQuery({
    queryKey: ['me'],
    queryFn: () => apiFetch<{ org_id: string; role?: string | null }>('/api/me'),
  })
  const orgId = me.data?.org_id
  const isSuperAdmin = me.data?.role === 'super_admin'

  const callsQuery = useQuery({
    queryKey: ['calls'],
    queryFn: () => apiFetch<{ calls: CallListItem[] }>('/api/calls?limit=100'),
  })
  const calls = useMemo(() => callsQuery.data?.calls ?? [], [callsQuery.data])

  const actionsQuery = useQuery({
    queryKey: ['actions', 'pending'],
    queryFn: () => apiFetch<ActionItem[]>('/api/actions/pending'),
    refetchInterval: 30_000,
    staleTime: 10_000,
  })
  const actions = actionsQuery.data ?? []
  const actionsCount = actions.length

  const employeesQuery = useQuery({
    queryKey: ['employees'],
    queryFn: () => apiFetch<Employee[]>('/api/employees'),
  })
  const employees = employeesQuery.data ?? []

  const assignInquiry = useMutation({
    mutationFn: ({ inquiryId, employeeId }: { inquiryId: string; employeeId: string | null }) =>
      apiFetch(`/api/inquiries/${inquiryId}/assign`, {
        method: 'PATCH',
        body: JSON.stringify({ employee_id: employeeId }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['calls'] })
      qc.invalidateQueries({ queryKey: ['callInquiry'] })
    },
  })

  // Gmail-style mark-read on open (idempotent; only fire when currently unread).
  const markRead = useMutation({
    mutationFn: (callId: string) => apiFetch(`/api/calls/${callId}/mark-read`, { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['calls'] })
      qc.invalidateQueries({ queryKey: ['dashboard', 'overview'] })
    },
  })
  useEffect(() => {
    if (!selectedId) return
    const selected = calls.find((c) => c.id === selectedId)
    if (selected && selected.read_at === null) markRead.mutate(selectedId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, calls])

  // Realtime new-call invalidation.
  useEffect(() => {
    const sb = supabase
    if (!orgId || !sb) return
    const channel = sb
      .channel(`org:${orgId}:calls`)
      .on('broadcast', { event: 'new_call' }, () => qc.invalidateQueries({ queryKey: ['calls'] }))
      .subscribe()
    return () => {
      sb.removeChannel(channel)
    }
  }, [orgId, qc])

  // Auto-select the first call once loaded.
  useEffect(() => {
    if (!selectedId && calls.length) setSelectedId(calls[0].id)
  }, [calls, selectedId])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return calls.filter((c) => {
      if (filters.dir !== 'all' && c.direction !== filters.dir) return false
      if (filters.status !== 'all' && c.inquiry_status !== filters.status) return false
      if (!matchesDateFilter(c, filters)) return false
      if (q && !displayName(c).toLowerCase().includes(q) && !(c.summary_title ?? '').toLowerCase().includes(q))
        return false
      return true
    })
  }, [calls, search, filters])

  // Reset to page 1 when the result set changes.
  useEffect(() => {
    setPage(1)
  }, [search, filters])
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const pageClamped = Math.min(page, pages)
  const paged = filtered.slice((pageClamped - 1) * PAGE_SIZE, pageClamped * PAGE_SIZE)

  const listResize = useColumnResize('hk-calls-list-w', 340, { min: 260, max: 540, side: 'left' })
  const selectedEmergency = calls.find((c) => c.id === selectedId)?.emergency_flag ?? false

  return (
    <div className="flex h-full min-h-0 font-poster">
      <aside
        style={{ width: listResize.width }}
        className="flex flex-shrink-0 flex-col border-r border-border bg-bg"
      >
        <div className="border-b border-border bg-surface p-4">
          <Segmented
            full
            value={tab}
            onChange={(v) => setTab(v as 'anfragen' | 'aktionen')}
            options={[
              { value: 'anfragen', label: 'Anfragen', icon: Inbox, badge: calls.length },
              { value: 'aktionen', label: 'Aktionen', icon: ListChecks, badge: actionsCount || null, badgeTone: 'red' },
            ]}
          />
          {tab === 'anfragen' && (
            <div className="mt-3 flex gap-2">
              <div className="relative flex-1">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
                <input
                  type="search"
                  name="call-inquiry-search"
                  autoComplete="off"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Suchen…"
                  className="w-full rounded-lg border border-border bg-alt py-2 pl-9 pr-3 text-sm text-body outline-none focus:border-green-primary"
                />
              </div>
              <FilterPopover filters={filters} setFilters={setFilters} />
            </div>
          )}
        </div>

        {tab === 'anfragen' ? (
          <>
            <div className="scroll flex-1 space-y-2 overflow-y-auto p-2.5">
              {paged.map((c) => (
                <CallRow
                  key={c.id}
                  call={c}
                  active={c.id === selectedId}
                  employees={employees}
                  onSelect={() => setSelectedId(c.id)}
                  onAssign={(employeeId) => {
                    if (!c.inquiry_id) return
                    assignInquiry.mutate({ inquiryId: c.inquiry_id, employeeId })
                  }}
                  assigning={assignInquiry.isPending}
                />
              ))}
              {!callsQuery.isLoading && !filtered.length && <p className="p-3 text-sm text-muted">Keine Anrufe.</p>}
            </div>
            <PagerNumbered page={pageClamped} pages={pages} onPage={setPage} />
          </>
        ) : actions.length ? (
          <div className="scroll flex-1 space-y-2 overflow-y-auto p-2.5">
            {actions.map((item) => (
              <ActionRow
                key={`${item.kind}:${item.id}`}
                item={item}
                onSelect={() => {
                  // A reschedule counter-proposal is approved/declined on the call's
                  // action card (Genehmigen/Ablehnen) — open that call rather than the
                  // customer page, which had no way to act on it.
                  if (item.kind === 'alt_time_proposal' && item.call_id) {
                    setTab('anfragen')
                    setSelectedId(item.call_id)
                    return
                  }
                  if (item.customer_id) navigate(`/customers/${item.customer_id}`)
                }}
              />
            ))}
          </div>
        ) : (
          <EmptyAktionen />
        )}
      </aside>

      <ResizeHandle onMouseDown={listResize.onMouseDown} />

      {selectedId ? (
        <CallDetail
          callId={selectedId}
          isSuperAdmin={isSuperAdmin}
          emergency={selectedEmergency}
          rightOpen={rightOpen}
          onToggleRight={() => setRightOpen((o) => !o)}
          onDeleted={() => setSelectedId(null)}
        />
      ) : (
        <NoCallSelected />
      )}
    </div>
  )
}
