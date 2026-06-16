// Anrufe — the call log. A read-only, full-width chronological stream of every call
// Kiki took or made, grouped under date dividers (Heute · Gestern · "Mittwoch, 4. Juni"),
// newest first — like a phone messages app. Click a row → detail drawer (actions +
// audio + summary + collapsible transcript).
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
import { LogTable } from './calls/log/LogTable'
import {
  callMatches,
  dayDividerLabel,
  dayKeyOf,
  DEFAULT_FILTERS,
  type LogFilters as LogFiltersT,
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

  // Chronological day groups for the date-divider timeline. `filtered` is already
  // newest-first, so consecutive same-day calls fold into one divider (newest day on top).
  const dayGroups = useMemo(() => {
    const out: { key: string; label: string; calls: CallListItem[] }[] = []
    for (const c of filtered) {
      const iso = c.started_at || c.created_at
      const key = dayKeyOf(iso)
      const last = out[out.length - 1]
      if (last && last.key === key) last.calls.push(c)
      else out.push({ key, label: dayDividerLabel(iso, nowMs), calls: [c] })
    }
    return out
  }, [filtered, nowMs])

  const isEmpty = !callsQuery.isLoading && dayGroups.length === 0

  return (
    <div className="scroll h-full overflow-y-auto bg-bg font-poster">
      {toast && (
        <div className="fixed bottom-6 left-1/2 z-[90] -translate-x-1/2 rounded-lg bg-text px-4 py-2 text-sm font-semibold text-bg shadow-e3">
          {toast}
        </div>
      )}

      <div className="mx-auto max-w-[1500px] px-4 py-7 sm:px-6 lg:px-8">
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
          <LogTable
            dayGroups={dayGroups}
            selectedId={selectedId}
            employeeName={employeeName}
            onSelect={(id) => setSelectedId(id)}
            onOpenCase={(to) => navigate(to)}
          />
        )}
      </div>

      <LogDrawer callId={selectedId} onClose={() => setSelectedId(null)} flash={flash} />
    </div>
  )
}
