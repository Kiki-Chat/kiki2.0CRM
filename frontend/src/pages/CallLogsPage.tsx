// Anrufe — the call log. A read-only, full-width stream of every call Kiki took or
// made: a pinned "Braucht Aufmerksamkeit" section (no case yet / emergencies) on top,
// then day-grouped history (Heute · Gestern · Diese Woche · Dieser Monat · Älter).
// Click a row → detail drawer (transcript · audio · summary + triage). The old 3-pane
// cockpit + Aktionen worklist were retired here; actions now live inside the cases.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Inbox } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { apiFetch } from '../lib/api'
import { supabase } from '../lib/supabase'
import { useMe } from '../lib/useMe'
import { useToast } from '../lib/useToast'
import { LogDrawer } from './calls/log/LogDrawer'
import { LogFilters, type PillCounts } from './calls/log/LogFilters'
import { LogRow } from './calls/log/LogRow'
import {
  BUCKET_LABEL,
  BUCKET_ORDER,
  type Bucket,
  bucketOf,
  callMatches,
  DEFAULT_FILTERS,
  type LogFilters as LogFiltersT,
  needsAttention,
  type StatusF,
} from './calls/log/util'
import type { CallListItem, Employee } from './calls/shared'

const startedMs = (c: CallListItem) => {
  const t = Date.parse(c.started_at || c.created_at || '')
  return Number.isNaN(t) ? 0 : t
}
const byNewest = (a: CallListItem, b: CallListItem) => startedMs(b) - startedMs(a)

export function CallLogsPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { me } = useMe()
  const orgId = me?.org_id

  // Deep-link seeding (dashboard CTAs + projectTabs "Zum Transkript").
  const [selectedId, setSelectedId] = useState<string | null>(() => searchParams.get('call_id'))
  const [search, setSearch] = useState('')
  // Single wall-clock baseline for date filtering + day bucketing (kept out of render
  // so the two always agree and the purity rule is satisfied).
  const [nowMs] = useState(() => Date.now())
  const [filters, setFilters] = useState<LogFiltersT>(() => {
    const d = searchParams.get('direction')
    const s = searchParams.get('status')
    const valid: StatusF[] = ['unread', 'open', 'in_progress', 'completed']
    return {
      ...DEFAULT_FILTERS,
      dir: d === 'inbound' || d === 'outbound' ? d : 'all',
      status: valid.includes(s as StatusF) ? (s as StatusF) : 'all',
    }
  })

  const callsQuery = useQuery({
    queryKey: ['calls'],
    queryFn: () => apiFetch<{ calls: CallListItem[] }>('/api/calls?limit=200'),
  })
  const calls = useMemo(() => callsQuery.data?.calls ?? [], [callsQuery.data])

  const { data: employees = [] } = useQuery({
    queryKey: ['employees'],
    queryFn: () => apiFetch<Employee[]>('/api/employees'),
  })
  const employeeName = useMemo(() => {
    const m = new Map<string, string>()
    for (const e of employees) if (e.display_name) m.set(e.id, e.display_name)
    return m
  }, [employees])

  // Gmail-style mark-read on open (idempotent; only when currently unread).
  const markRead = useMutation({
    mutationFn: (callId: string) => apiFetch(`/api/calls/${callId}/mark-read`, { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['calls'] })
      qc.invalidateQueries({ queryKey: ['dashboard', 'overview'] })
    },
  })
  useEffect(() => {
    if (!selectedId) return
    const sel = calls.find((c) => c.id === selectedId)
    if (sel && sel.read_at === null) markRead.mutate(selectedId)
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

  // Same-route deep-links (?call_id=): open that call's drawer when the param appears
  // or changes. The ref guards against re-opening after the user closes the drawer.
  const appliedCallId = useRef<string | null>(searchParams.get('call_id'))
  useEffect(() => {
    const cid = searchParams.get('call_id')
    if (cid && cid !== appliedCallId.current) {
      appliedCallId.current = cid
      setSelectedId(cid)
    }
  }, [searchParams])

  const { toast, flash } = useToast()

  const q = search.trim().toLowerCase()
  // Pill counts reflect every active filter EXCEPT direction, so each pill shows
  // how many calls it would surface given the other filters.
  const preDir = useMemo(
    () => calls.filter((c) => callMatches(c, { ...filters, dir: 'all' }, q, nowMs)),
    [calls, filters, q, nowMs],
  )
  const counts: PillCounts = useMemo(
    () => ({
      all: preDir.length,
      inbound: preDir.filter((c) => c.direction === 'inbound').length,
      outbound: preDir.filter((c) => c.direction === 'outbound').length,
      emergency: preDir.filter((c) => c.emergency_flag).length,
    }),
    [preDir],
  )

  const filtered = useMemo(
    () => calls.filter((c) => callMatches(c, filters, q, nowMs)).sort(byNewest),
    [calls, filters, q, nowMs],
  )

  // Partition: pinned attention (no case / emergency) vs the day-grouped rest.
  const { attention, groups } = useMemo(() => {
    const att: CallListItem[] = []
    const buckets: Record<Bucket, CallListItem[]> = { today: [], yesterday: [], week: [], month: [], older: [] }
    for (const c of filtered) {
      if (needsAttention(c)) att.push(c)
      else buckets[bucketOf(c.started_at || c.created_at, nowMs)].push(c)
    }
    return { attention: att, groups: buckets }
  }, [filtered, nowMs])

  const renderRow = (c: CallListItem, mixed: boolean) => (
    <LogRow
      key={c.id}
      call={c}
      active={c.id === selectedId}
      mixed={mixed}
      assigneeName={c.assigned_employee_id ? (employeeName.get(c.assigned_employee_id) ?? null) : null}
      onSelect={() => setSelectedId(c.id)}
      onOpenCase={(to) => navigate(to)}
    />
  )

  const nonEmptyGroups = BUCKET_ORDER.filter((b) => groups[b].length > 0)
  const isEmpty = !callsQuery.isLoading && !attention.length && !nonEmptyGroups.length

  return (
    <div className="scroll h-full overflow-y-auto bg-bg font-poster">
      {toast && (
        <div className="fixed bottom-6 left-1/2 z-[90] -translate-x-1/2 rounded-lg bg-text px-4 py-2 text-sm font-semibold text-bg shadow-e3">
          {toast}
        </div>
      )}

      <div className="mx-auto max-w-[1100px] px-4 py-7 sm:px-8">
        {/* header */}
        <div className="mb-6">
          <h1 className="text-[26px] font-extrabold tracking-tight text-text">Anrufe</h1>
          <p className="mt-1 text-[14px] text-muted">
            Jeder Anruf, den Kiki angenommen oder geführt hat — durchsuchbar und direkt bearbeitbar.
          </p>
        </div>

        {/* filters */}
        <div className="mb-6">
          <LogFilters
            filters={filters}
            setFilters={setFilters}
            search={search}
            setSearch={setSearch}
            employees={employees}
            counts={counts}
          />
        </div>

        {callsQuery.isLoading ? (
          <div className="py-16 text-center text-sm text-muted">Anrufe werden geladen…</div>
        ) : isEmpty ? (
          <div className="rounded-2xl border border-dashed border-border py-16 text-center">
            <Inbox size={28} className="mx-auto mb-3 text-faint" />
            <p className="text-sm font-semibold text-body">Keine Anrufe gefunden</p>
            <p className="mt-1 text-[13px] text-muted">Passen Sie die Filter an oder setzen Sie sie zurück.</p>
          </div>
        ) : (
          <div className="flex flex-col gap-6">
            {/* pinned: needs attention */}
            {attention.length > 0 && (
              <section className="overflow-hidden rounded-2xl border border-warning/40 bg-warning-bg/40">
                <div className="flex items-center gap-2 px-4 pb-1.5 pt-3.5">
                  <Inbox size={15} className="text-warning" />
                  <span className="text-[12.5px] font-extrabold uppercase tracking-wider text-warning">Braucht Aufmerksamkeit</span>
                  <span className="text-[12.5px] font-bold text-warning/80">
                    {attention.length} {attention.length === 1 ? 'Anruf' : 'Anrufe'}
                  </span>
                </div>
                <div className="space-y-0.5 p-1.5">{attention.map((c) => renderRow(c, true))}</div>
              </section>
            )}

            {/* day-grouped history */}
            {nonEmptyGroups.map((b) => (
              <section key={b}>
                <div className="mb-2 flex items-center gap-2 px-1">
                  <span className="text-[12px] font-extrabold uppercase tracking-wider text-muted">{BUCKET_LABEL[b]}</span>
                  <span className="text-[12px] font-bold text-faint">{groups[b].length}</span>
                </div>
                <div className="space-y-0.5 rounded-2xl border border-border bg-surface p-1.5">
                  {groups[b].map((c) => renderRow(c, false))}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>

      <LogDrawer callId={selectedId} onClose={() => setSelectedId(null)} flash={flash} />
    </div>
  )
}
