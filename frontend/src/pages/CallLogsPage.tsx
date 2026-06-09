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
import { cn } from '../lib/utils'
import { useMediaQuery } from '../lib/useMediaQuery'
import { useMe } from '../lib/useMe'
import { FilterPopover, PagerNumbered, Segmented } from './calls/atoms'
import { CallDetail } from './calls/CallDetail'
import { ActionRow, CallRow, EmptyAktionen } from './calls/Inbox'
import { RescheduleApprovalModal } from './calls/Modals'
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
  // Customer-proposed reschedule being approved/declined in the popup.
  const [reschedule, setReschedule] = useState<{ id: string; name: string | null; time: string | null } | null>(null)
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

  const { me, role } = useMe()
  const orgId = me?.org_id
  const isSuperAdmin = role === 'super_admin'
  // Below `lg` the 3-pane cockpit (inbox | transcript | workspace ≈ 700px of
  // fixed panes) can't fit, so we switch to single-pane navigation: the inbox
  // is full-width, and selecting a call swaps in the detail with a back button.
  const isWide = useMediaQuery('(min-width: 1024px)')

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

  // Aktionen to-do controls: Übernehmen / Erledigt / Löschen / reopen.
  const setActionState = useMutation({
    mutationFn: ({ action_key, status }: { action_key: string; status: 'open' | 'claimed' | 'done' | 'dismissed' }) =>
      apiFetch('/api/actions/state', { method: 'POST', body: JSON.stringify({ action_key, status }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['actions', 'pending'] }),
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

  // Auto-select the first call once loaded — DESKTOP ONLY. On mobile we want to
  // land on the inbox list, not jump straight into a call's detail pane.
  useEffect(() => {
    if (isWide && !selectedId && calls.length) setSelectedId(calls[0].id)
  }, [calls, selectedId, isWide])

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
        style={isWide ? { width: listResize.width } : undefined}
        className={cn(
          'flex-col border-r border-border bg-bg',
          isWide ? 'flex flex-shrink-0' : selectedId ? 'hidden' : 'flex w-full',
        )}
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
                onSetState={(status) => setActionState.mutate({ action_key: item.action_key, status })}
                onSelect={() => {
                  // Customer-proposed reschedule → approve/decline in a popup right
                  // here (pre-filled with the proposed slot). One click moves +
                  // confirms the appointment — no need to find the call.
                  if (item.kind === 'alt_time_proposal' && item.proposal_role === 'customer') {
                    setReschedule({ id: item.id, name: item.customer_name, time: item.due_at })
                    return
                  }
                  // Route each Aktion to the surface where it can actually be acted
                  // on — not blanket-to the customer card (the old fallback, which
                  // had no way to confirm an appointment or send a KVA).
                  switch (item.kind) {
                    // Appointment decisions (confirm / reschedule approval) and the
                    // "Termin storniert" notice live on the call's inline card → open
                    // that call (falls through to the customer card if no call linked).
                    case 'termin_anfrage':
                    case 'alt_time_proposal':
                    case 'appointment_cancelled':
                      if (item.call_id) {
                        setTab('anfragen')
                        setSelectedId(item.call_id)
                        return
                      }
                      break
                    // Cost estimates: open the KVA itself (send / review decision).
                    case 'kva_to_send':
                    case 'kva_pending_acceptance':
                      navigate(`/cost-estimates/${item.id}`)
                      return
                    // Missed call owed a callback: the customer card has the number.
                    case 'callback_owed':
                      break
                  }
                  // Fallback: the customer card (used for callback_owed and for any
                  // appointment action whose call_id couldn't be resolved).
                  if (item.customer_id) navigate(`/customers/${item.customer_id}`)
                }}
              />
            ))}
          </div>
        ) : (
          <EmptyAktionen />
        )}
      </aside>

      {isWide && <ResizeHandle onMouseDown={listResize.onMouseDown} />}

      {selectedId ? (
        <CallDetail
          callId={selectedId}
          isSuperAdmin={isSuperAdmin}
          emergency={selectedEmergency}
          rightOpen={rightOpen}
          onToggleRight={() => setRightOpen((o) => !o)}
          onDeleted={() => setSelectedId(null)}
          isWide={isWide}
          onBack={() => setSelectedId(null)}
        />
      ) : (
        isWide && <NoCallSelected />
      )}

      <RescheduleApprovalModal
        open={!!reschedule}
        appointmentId={reschedule?.id ?? null}
        customerName={reschedule?.name ?? null}
        proposedTime={reschedule?.time ?? null}
        onClose={() => setReschedule(null)}
        onResolved={() => {
          qc.invalidateQueries({ queryKey: ['actions', 'pending'] })
          qc.invalidateQueries({ queryKey: ['appointments'] })
          qc.invalidateQueries({ queryKey: ['calls'] })
          qc.invalidateQueries({ queryKey: ['pendingAppointment'] })
        }}
      />
    </div>
  )
}
