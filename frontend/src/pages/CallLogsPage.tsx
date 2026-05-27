import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  AtSign,
  Bot,
  Calendar as CalIcon,
  Check,
  CheckCircle,
  ChevronDown,
  Clock,
  Edit3,
  ExternalLink,
  FileText,
  MapPin,
  Phone,
  PhoneIncoming,
  PhoneOutgoing,
  RotateCcw,
  Search,
  Sparkles,
  Trash2,
  User,
  Volume2,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import { Modal } from '../components/ui/Modal'
import { Tag } from '../components/ui/Tag'
import { apiBlobUrl, apiFetch } from '../lib/api'
import { supabase } from '../lib/supabase'
import { cn, initials } from '../lib/utils'
// Wave 2 / Agent 2.4 — inline OFFENE AKTIONEN card at the top of the right panel.
import { AppointmentCard, usePendingAppointment } from './calls/AppointmentCard'

interface TranscriptTurn {
  role: string
  message: string | null
  // Per-turn timestamp from ElevenLabs (seconds from call start). Used to
  // highlight the active turn during audio playback. Older imports may lack
  // it — treat as null and fall back to "no highlight" gracefully.
  time_in_call_secs?: number | null
  tool_calls: (string | null)[]
}
interface CallListItem {
  id: string
  elevenlabs_conversation_id: string | null
  caller_number: string | null
  summary_title: string | null
  direction: string | null
  duration_seconds: number | null
  started_at: string | null
  data_collection: Record<string, string> | null
  customer_id: string | null
  read_at: string | null  // P0.4 — null = unread; non-null = first opened at
  created_at: string | null  // Wave 2.1 — drives the recent-unread glow window
  customers: { full_name: string | null } | null
  // Wave 2 / Agent 2.1 — list-card enrichment fields populated by
  // backend/app/api/routes/calls.py::_enrich_calls_with_inquiries.
  inquiry_id: string | null
  inquiry_status: 'open' | 'in_progress' | 'completed' | null
  emergency_flag: boolean
  assigned_employee_id: string | null
  assigned_employee_initials: string | null
}
interface CallDetail extends CallListItem {
  summary: string | null
  transcript: TranscriptTurn[] | null
  customers: {
    full_name: string | null
    phone: string | null
    email: string | null
    customer_number: string | null
  } | null
}
interface Inquiry {
  id: string
  number: string | null
  title: string | null
  type: string | null
  status: string
  notes: string | null
  assigned_employee_id: string | null
}
interface Employee {
  id: string
  display_name: string | null
}
// Wave 2 / Agent 2.2 — shape of /api/actions/pending list items. Backend
// aggregates open decisions across appointments/KVAs/inquiries. See
// backend/app/api/routes/actions.py for kind semantics.
interface ActionItem {
  kind:
    | 'termin_anfrage'
    | 'kva_to_send'
    | 'kva_pending_acceptance'
    | 'callback_owed'
    | 'alt_time_proposal'
  id: string
  inquiry_id: string | null
  call_id: string | null
  customer_name: string | null
  customer_id: string | null
  summary: string
  created_at: string | null
  due_at: string | null
  priority: 'normal' | 'high'
}
// German chip labels per kind. Lives on the client so the wire format stays
// language-neutral.
const ACTION_KIND_LABEL: Record<ActionItem['kind'], string> = {
  termin_anfrage: 'Terminbestätigung',
  kva_to_send: 'KVA senden',
  kva_pending_acceptance: 'KVA-Antwort offen',
  callback_owed: 'Rückruf',
  alt_time_proposal: 'Alternativtermin',
}

const STATUS_TAG: Record<string, { label: string; variant: 'info' | 'warning' | 'success' | 'neutral' }> = {
  open: { label: 'Offen', variant: 'info' },
  in_progress: { label: 'In Bearbeitung', variant: 'warning' },
  completed: { label: 'Abgeschlossen', variant: 'success' },
  deleted: { label: 'Gelöscht', variant: 'neutral' },
}
const CATEGORIES = ['appointment', 'offer', 'info', 'recall']
const COLORS = ['#2D6B3D', '#2563EB', '#7C3AED', '#DB2777', '#D97706', '#2D9D5C', '#78756F']

const fmtDuration = (s: number | null) =>
  s || s === 0 ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}` : '—'
const fmtTime = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString('de-DE', {
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
      })
    : '—'
const isMeaningful = (v?: string | null) =>
  !!v && !['unbekannt', 'keiner', 'anonymous'].includes(v.toLowerCase())
function displayName(c: CallListItem): string {
  return (
    (isMeaningful(c.customers?.full_name) && c.customers!.full_name!) ||
    (isMeaningful(c.data_collection?.customer_name) && c.data_collection!.customer_name!) ||
    (isMeaningful(c.caller_number) && c.caller_number!) ||
    'Unbekannt'
  )
}

// Wave 2 / Agent 2.1 — list-card enrichment helpers.

// Six pastel-saturated employee avatar colors. Keep this list stable —
// reordering would visually reassign every existing employee. Chosen to
// stay readable against the dark text and to be distinguishable from the
// green-tint family used for the customer avatar in the detail panel so
// the two avatars don't get visually confused.
const EMPLOYEE_AVATAR_PALETTE: { bg: string; text: string }[] = [
  { bg: 'bg-blue-100', text: 'text-blue-800' },
  { bg: 'bg-amber-100', text: 'text-amber-800' },
  { bg: 'bg-purple-100', text: 'text-purple-800' },
  { bg: 'bg-pink-100', text: 'text-pink-800' },
  { bg: 'bg-cyan-100', text: 'text-cyan-800' },
  { bg: 'bg-teal-100', text: 'text-teal-800' },
]

// Stable string hash → palette index. Same employee_id always renders in
// the same color across the list and across page reloads. djb2-ish hash:
// cheap, deterministic, good spread across 6 buckets.
function avatarColorForEmployee(employeeId: string | null): { bg: string; text: string } {
  if (!employeeId) {
    return { bg: 'bg-alt', text: 'text-faint' }  // neutral "?" circle
  }
  let hash = 0
  for (let i = 0; i < employeeId.length; i++) {
    hash = (hash * 33 + employeeId.charCodeAt(i)) >>> 0
  }
  return EMPLOYEE_AVATAR_PALETTE[hash % EMPLOYEE_AVATAR_PALETTE.length]
}

// Map inquiry_status → small chip on the list-card. 'deleted' / null
// inquiries render nothing (no pill at all on the card).
const STATUS_PILL: Record<string, { label: string; cls: string }> = {
  open: { label: 'Offen', cls: 'bg-blue-100 text-blue-800' },
  in_progress: { label: 'In Bearbeitung', cls: 'bg-amber-100 text-amber-800' },
  completed: { label: 'Erledigt', cls: 'bg-green-100 text-green-800' },
}

// Glow window for recent-unread cards. 1 hour matches the brief and keeps
// the visual pulse from accumulating across days of unread calls.
const GLOW_WINDOW_MS = 60 * 60 * 1000
function isRecentUnread(c: CallListItem): boolean {
  if (c.read_at !== null) return false
  const ts = c.created_at ?? c.started_at
  if (!ts) return false
  const created = new Date(ts).getTime()
  if (Number.isNaN(created)) return false
  return Date.now() - created < GLOW_WINDOW_MS
}


export function CallLogsPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  // Wave 2 / Agent 2.2 — LEFT sidebar tab switcher: Anfragen | Aktionen.
  // Simple local state (not a router query param) keeps this self-contained;
  // deep-linking to the Aktionen tab is a follow-up if the team wants it.
  const [tab, setTab] = useState<'anfragen' | 'aktionen'>('anfragen')

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
  const calls = callsQuery.data?.calls ?? []

  // Wave 2 / Agent 2.2 — Aktionen tab data + badge count source. Auto-refetch
  // every 30s so the badge stays roughly fresh without needing a websocket
  // (the underlying tables — appointments/cost_estimates — don't have a
  // realtime channel today). Stale-while-revalidate keeps the badge visible
  // across tab flips so it doesn't flicker.
  const actionsQuery = useQuery({
    queryKey: ['actions', 'pending'],
    queryFn: () => apiFetch<ActionItem[]>('/api/actions/pending'),
    refetchInterval: 30_000,
    staleTime: 10_000,
  })
  const actions = actionsQuery.data ?? []
  const actionsCount = actions.length

  // Wave 2 / Agent 2.1 — shared employees list for the inline assign-
  // employee dropdown on every list-card. Same queryKey as CallDetail
  // uses inside its own useQuery so React Query dedupes / shares cache.
  const employeesQuery = useQuery({
    queryKey: ['employees'],
    queryFn: () => apiFetch<Employee[]>('/api/employees'),
  })
  const employees = employeesQuery.data ?? []

  // Wave 2 / Agent 2.1 — inline assign mutation hits the focused
  // /api/inquiries/{id}/assign route (NOT the generic PATCH, so test
  // coverage and intent stay clear). On success we invalidate both
  // ['calls'] (refreshes the avatar) and ['callInquiry'] (keeps the
  // right-panel Aktionen <select> in sync).
  const assignInquiry = useMutation({
    mutationFn: ({ inquiryId, employeeId }: { inquiryId: string; employeeId: string | null }) =>
      apiFetch(`/api/inquiries/${inquiryId}/assign`, {
        method: 'PATCH',
        body: JSON.stringify({ employee_id: employeeId }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['calls'] })
      queryClient.invalidateQueries({ queryKey: ['callInquiry'] })
    },
  })

    // P0.4 — Gmail-style mark-read on open. Idempotent backend; only fire when
  // the selected call is currently unread to avoid wasted requests on reopens.
  const markRead = useMutation({
    mutationFn: (callId: string) =>
      apiFetch(`/api/calls/${callId}/mark-read`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['calls'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard', 'overview'] })
    },
  })
  useEffect(() => {
    if (!selectedId) return
    const selected = calls.find((c) => c.id === selectedId)
    if (selected && selected.read_at === null) {
      markRead.mutate(selectedId)
    }
    // markRead intentionally excluded from deps — mutation identity is stable
    // and we only want to fire when selectedId / calls change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, calls])

  useEffect(() => {
    const sb = supabase
    if (!orgId || !sb) return
    const channel = sb
      .channel(`org:${orgId}:calls`)
      .on('broadcast', { event: 'new_call' }, () =>
        queryClient.invalidateQueries({ queryKey: ['calls'] }),
      )
      .subscribe()
    return () => {
      sb.removeChannel(channel)
    }
  }, [orgId, queryClient])

  useEffect(() => {
    if (!selectedId && calls.length) setSelectedId(calls[0].id)
  }, [calls, selectedId])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return calls
    return calls.filter(
      (c) =>
        displayName(c).toLowerCase().includes(q) ||
        (c.summary_title ?? '').toLowerCase().includes(q),
    )
  }, [calls, search])

  return (
    <div className="flex h-full min-h-0">
      <aside className="flex w-80 flex-shrink-0 flex-col border-r border-border bg-surface">
        {/* Wave 2 / Agent 2.2 — tab switcher above the existing search bar.
            Anfragen (default, current list) | Aktionen (new pending-decisions
            list). Search bar is intentionally hidden on the Aktionen tab —
            searching aktionen wasn't in scope for v1 (the spec allows the
            simpler path); flagged as a follow-up. */}
        <div className="border-b border-border p-4">
          <div className="mb-3 flex rounded-md bg-alt p-1">
            {(['anfragen', 'aktionen'] as const).map((t) => {
              const isActive = tab === t
              const isAktionen = t === 'aktionen'
              return (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={cn(
                    'flex flex-1 items-center justify-center gap-1.5 rounded py-1.5 text-sm font-semibold transition-colors',
                    isActive ? 'bg-surface text-text shadow-sm' : 'text-muted hover:text-body',
                  )}
                >
                  <span>{isAktionen ? 'Aktionen' : 'Anfragen'}</span>
                  {!isAktionen && (
                    <span
                      className={cn(
                        'rounded-full px-1.5 text-[10px] font-bold',
                        isActive ? 'bg-alt text-muted' : 'bg-surface text-muted',
                      )}
                    >
                      {calls.length}
                    </span>
                  )}
                  {isAktionen && actionsCount > 0 && (
                    <span className="rounded-full bg-red-500 px-1.5 text-[10px] font-bold text-white">
                      {actionsCount}
                    </span>
                  )}
                </button>
              )
            })}
          </div>
          {tab === 'anfragen' && (
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Suchen…"
                className="w-full rounded-md border border-border bg-alt py-2 pl-9 pr-3 text-sm text-body outline-none focus:border-green-primary"
              />
            </div>
          )}
        </div>

        {/* Body — switches between the existing Anfragen list (untouched —
            Agent 2.1's surface) and the new Aktionen list. */}
        {tab === 'anfragen' ? (
          <div className="flex-1 space-y-1 overflow-y-auto p-2">
            {filtered.map((c) => (
              <CallListCard
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
            {!callsQuery.isLoading && !filtered.length && (
              <p className="p-3 text-sm text-muted">Keine Anrufe.</p>
            )}
          </div>
        ) : (
          <AktionenList
            items={actions}
            isLoading={actionsQuery.isLoading}
            onClickItem={(item) => {
              // v1 navigation: customer profile when we have a customer link;
              // otherwise no-op. Deep-linking to the originating call would
              // require an extra fetch (action items don't carry call_id
              // directly because cost_estimates/appointments don't FK to
              // calls in the schema). Flagged as a follow-up.
              if (item.customer_id) {
                navigate(`/customers/${item.customer_id}`)
              }
            }}
          />
        )}
      </aside>

      {selectedId ? (
        <CallDetail callId={selectedId} isSuperAdmin={isSuperAdmin} />
      ) : (
        <div className="flex flex-1 items-center justify-center text-muted">
          <div className="flex flex-col items-center gap-2">
            <Phone size={28} className="text-faint" />
            <span className="text-sm">Wählen Sie einen Anruf aus.</span>
          </div>
        </div>
      )}
    </div>
  )
}

// Wave 2 / Agent 2.1 — list-item card with employee-initial avatar (color-
// hashed by employee_id), status pill, NOTDIENST badge, recent-unread glow,
// and inline assign-employee dropdown.
//
// The wrapping element is a <div role="button"> (not a real <button>) so
// the avatar can be a nested DropdownMenu.Trigger <button> — nested buttons
// are invalid HTML. Avatar click stops propagation so it doesn't ALSO fire
// the card's onSelect.
function CallListCard({
  call,
  active,
  employees,
  onSelect,
  onAssign,
  assigning,
}: {
  call: CallListItem
  active: boolean
  employees: Employee[]
  onSelect: () => void
  onAssign: (employeeId: string | null) => void
  assigning: boolean
}) {
  const isUnread = call.read_at === null
  const recent = isRecentUnread(call)
  const Icon = call.direction === 'outbound' ? PhoneOutgoing : PhoneIncoming
  const palette = avatarColorForEmployee(call.assigned_employee_id)
  const pill = call.inquiry_status ? STATUS_PILL[call.inquiry_status] : null

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSelect()
        }
      }}
      className={cn(
        'relative flex w-full cursor-pointer items-start gap-3 rounded-lg border p-3 text-left transition-colors',
        active
          ? 'border-green-primary/40 bg-green-tint-50'
          : 'border-border bg-surface hover:bg-alt',
        // Recent-unread glow: subtle ring + slow pulse animation. Sits
        // under the active-state border so the selected-card highlight is
        // still visible if a card is BOTH recent-unread AND selected.
        recent && 'ring-2 ring-green-primary/40 animate-pulse',
      )}
    >
      {/* NOTDIENST badge — top-right corner, only shown when emergency_flag
          is true. Absolute-positioned so it doesn't compete with the right-
          aligned phone icon for inline space. */}
      {call.emergency_flag && (
        <span className="absolute right-2 top-2 inline-flex items-center gap-1 rounded-sm bg-error px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-white">
          <AlertTriangle size={9} /> Notdienst
        </span>
      )}

      {/* Employee initials avatar (24px) — opens the assign dropdown. */}
      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <button
            type="button"
            onClick={(e) => e.stopPropagation()}
            disabled={!call.inquiry_id || assigning}
            title={
              call.inquiry_id
                ? 'Mitarbeiter zuweisen'
                : 'Noch keine Anfrage — kann nicht zugewiesen werden'
            }
            className={cn(
              'flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full text-[10px] font-bold transition-transform hover:scale-110 disabled:cursor-not-allowed disabled:opacity-60',
              palette.bg,
              palette.text,
            )}
          >
            {call.assigned_employee_initials ?? '?'}
          </button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content
            align="start"
            sideOffset={4}
            onClick={(e) => e.stopPropagation()}
            className="z-50 max-h-64 w-56 overflow-y-auto rounded-lg border border-border bg-surface p-1 shadow-e3"
          >
            <DropdownMenu.Item
              onSelect={() => onAssign(null)}
              className="flex cursor-pointer items-center justify-between gap-2 rounded-md px-3 py-2 text-sm text-muted outline-none data-[highlighted]:bg-alt"
            >
              <span>— Niemand —</span>
              {!call.assigned_employee_id && <Check size={13} className="text-green-deep" />}
            </DropdownMenu.Item>
            {employees.length > 0 && <DropdownMenu.Separator className="my-1 h-px bg-border" />}
            {employees.map((e) => {
              const ePalette = avatarColorForEmployee(e.id)
              const eInitials = (e.display_name ?? '?')
                .split(' ')
                .filter(Boolean)
                .map((w) => w[0])
                .slice(0, 2)
                .join('')
                .toUpperCase()
              return (
                <DropdownMenu.Item
                  key={e.id}
                  onSelect={() => onAssign(e.id)}
                  className="flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-sm text-body outline-none data-[highlighted]:bg-alt"
                >
                  <span
                    className={cn(
                      'flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full text-[9px] font-bold',
                      ePalette.bg,
                      ePalette.text,
                    )}
                  >
                    {eInitials || '?'}
                  </span>
                  <span className="flex-1 truncate">{e.display_name ?? '—'}</span>
                  {e.id === call.assigned_employee_id && (
                    <Check size={13} className="text-green-deep" />
                  )}
                </DropdownMenu.Item>
              )
            })}
            {!employees.length && (
              <div className="px-3 py-2 text-xs text-muted">Keine Mitarbeiter.</div>
            )}
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>

      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span
            className={cn(
              'truncate text-sm',
              isUnread ? 'font-semibold text-text' : 'font-medium text-muted',
            )}
          >
            {displayName(call)}
          </span>
          <Icon size={13} className="flex-shrink-0 text-muted" />
        </div>
        <div
          className={cn(
            'truncate text-xs',
            isUnread ? 'text-body' : 'text-muted',
          )}
        >
          {call.summary_title ?? 'Anruf'}
        </div>
        {/* Status pill + meta row. Pill sits on the left so the eye
            naturally scans status → time → duration. */}
        <div className="mt-1 flex items-center gap-2 text-[11px] text-faint">
          {pill && (
            <span className={cn('rounded-sm px-1.5 py-0.5 font-semibold', pill.cls)}>
              {pill.label}
            </span>
          )}
          <span>{fmtTime(call.started_at)}</span>
          <span>·</span>
          <span>{fmtDuration(call.duration_seconds)}</span>
        </div>
      </div>
    </div>
  )
}

// Wave 2 / Agent 2.2 — Aktionen list (renders inside the LEFT sidebar when
// the Aktionen tab is active). Pure presentational: parent owns data
// fetching + onClick navigation logic.
function AktionenList({
  items,
  isLoading,
  onClickItem,
}: {
  items: ActionItem[]
  isLoading: boolean
  onClickItem: (item: ActionItem) => void
}) {
  if (isLoading) {
    return <p className="p-3 text-sm text-muted">Lädt…</p>
  }
  if (!items.length) {
    return (
      <div className="flex flex-1 items-center justify-center p-6 text-center">
        <p className="text-sm text-muted">
          Keine offenen Aktionen.<br />
          <span className="text-xs text-faint">Kiki hat alles im Griff.</span>
        </p>
      </div>
    )
  }
  return (
    <div className="flex-1 space-y-1 overflow-y-auto p-2">
      {items.map((item) => (
        <ActionListCard key={`${item.kind}:${item.id}`} item={item} onClick={() => onClickItem(item)} />
      ))}
    </div>
  )
}

function ActionListCard({ item, onClick }: { item: ActionItem; onClick: () => void }) {
  const label = ACTION_KIND_LABEL[item.kind]
  const isHigh = item.priority === 'high'
  const customerName = item.customer_name || 'Unbekannter Kunde'
  // Prefer due_at (next user-visible date — e.g. appointment time), otherwise
  // show the created_at timestamp so the operator has something to anchor on.
  const displayTime = item.due_at || item.created_at
  return (
    <button
      onClick={onClick}
      className={cn(
        'flex w-full items-start gap-3 rounded-lg border p-3 text-left transition-colors',
        'border-border bg-surface hover:bg-alt',
      )}
    >
      {/* Left rail: small priority dot. High = red, normal = green. */}
      <span
        className={cn(
          'mt-1.5 h-2 w-2 flex-shrink-0 rounded-full',
          isHigh ? 'bg-red-500' : 'bg-green-primary',
        )}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-center gap-2">
          <span
            className={cn(
              'rounded-full px-1.5 py-0.5 text-[10px] font-semibold',
              'bg-info-bg text-info',
            )}
          >
            {label}
          </span>
          <span className="truncate text-[11px] text-faint">{fmtTime(displayTime)}</span>
        </div>
        <div className="truncate text-sm font-semibold text-text">{item.summary}</div>
        <div className="truncate text-xs text-muted">{customerName}</div>
      </div>
    </button>
  )
}

function CallDetail({ callId, isSuperAdmin }: { callId: string; isSuperAdmin: boolean }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [tab, setTab] = useState<'actions' | 'details' | 'course'>('actions')
  const [modal, setModal] = useState<'process' | 'appointment' | null>(null)

  const { data: call } = useQuery({
    queryKey: ['call', callId],
    queryFn: () => apiFetch<CallDetail>(`/api/calls/${callId}`),
  })
  const { data: inquiry } = useQuery({
    queryKey: ['callInquiry', callId],
    queryFn: () => apiFetch<Inquiry>(`/api/calls/${callId}/inquiry`, { method: 'POST' }),
  })
  const { data: employees = [] } = useQuery({
    queryKey: ['employees'],
    queryFn: () => apiFetch<Employee[]>('/api/employees'),
  })

  const patchInquiry = useMutation({
    mutationFn: (body: Partial<Inquiry>) =>
      apiFetch<Inquiry>(`/api/inquiries/${inquiry!.id}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['callInquiry', callId] }),
  })

  // Wave 2 / Agent 2.4 — inline OFFENE AKTIONEN appointment card. The query
  // returns `{appointment: null}` when this call has no pending appointment;
  // the card only renders when there's one to act on.
  const pendingAppt = usePendingAppointment(callId)
  // Per-call client-side dismiss: clicking "Ausblenden" hides the card for
  // the rest of this session without changing the appointment status. Keyed
  // by appointment id (not call id) so a re-proposed appointment with a new
  // id still appears.
  const [dismissedApptIds, setDismissedApptIds] = useState<Set<string>>(new Set())
  const pendingAppointment = pendingAppt.data?.appointment ?? null
  const showAppointmentCard =
    !!pendingAppointment && !dismissedApptIds.has(pendingAppointment.id)

  if (!call) {
    return <div className="flex flex-1 items-center justify-center text-muted">Lädt…</div>
  }

  return (
    <>
      <Transcript
        call={call}
        isSuperAdmin={isSuperAdmin}
        onOpenSummary={() => setTab('details')}
      />

      {/* RIGHT PANEL — Wave 2 / Agent 2.3 polish:
          - w-80 (was w-96, ~17% narrower) so the center transcript can
            breathe and long German labels in compressed buttons still fit.
          - Sticky-on-scroll by structure: it's a flex sibling of the
            transcript column in a `flex h-full min-h-0` parent, so it owns
            its own vertical column and stays in view while the transcript's
            internal `overflow-y-auto` scrolls underneath. `sticky top-0` is
            belt-and-braces for any future restructure that might wrap the
            page in a vertical stack — harmless no-op today.
          The Wave 2 / Agent 2.4 OFFENE AKTIONEN appointment card sits at
          the TOP of this aside (above the title block); only present when
          the call has a pending appointment that needs a decision. */}
      <aside className="sticky top-0 flex h-full w-80 flex-shrink-0 flex-col border-l border-border bg-surface">
        {/* Wave 2 / Agent 2.4 — OFFENE AKTIONEN appointment card. */}
        {showAppointmentCard && pendingAppointment && (
          <AppointmentCard
            appointment={pendingAppointment}
            callId={callId}
            onDismiss={() =>
              setDismissedApptIds((prev) => {
                const next = new Set(prev)
                next.add(pendingAppointment.id)
                return next
              })
            }
          />
        )}
        <div className="border-b border-border p-4">
          <div className="mb-2 flex items-start justify-between gap-2">
            <h2 className="text-sm font-bold leading-snug text-text">
              {inquiry?.title ?? call.summary_title ?? 'Anruf'}
            </h2>
          </div>
          <div className="flex items-center gap-2">
            {inquiry && (
              <Tag variant={STATUS_TAG[inquiry.status]?.variant ?? 'neutral'}>
                {STATUS_TAG[inquiry.status]?.label ?? inquiry.status}
              </Tag>
            )}
            {inquiry?.type && <Tag variant="green">{inquiry.type}</Tag>}
          </div>
        </div>

        {/* Tab bar */}
        <div className="flex border-b border-border">
          {(['actions', 'details', 'course'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                'flex-1 border-b-2 px-2 py-2 text-sm font-medium transition-colors',
                tab === t
                  ? 'border-green-primary text-green-deep'
                  : 'border-transparent text-muted hover:text-body',
              )}
            >
              {t === 'actions' ? 'Aktionen' : t === 'details' ? 'Details' : 'Verlauf'}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {tab === 'actions' && (
            <ActionsTab
              inquiry={inquiry}
              employees={employees}
              busy={patchInquiry.isPending}
              onAssign={(id) => patchInquiry.mutate({ assigned_employee_id: id })}
              onStatus={(s) => patchInquiry.mutate({ status: s })}
              onEdit={() => setModal('process')}
              onAppointment={() => setModal('appointment')}
              onKva={
                call.customer_id
                  ? () =>
                      navigate(
                        `/cost-estimates/new?customer_id=${call.customer_id}` +
                          (inquiry?.id ? `&inquiry_id=${inquiry.id}` : ''),
                      )
                  : undefined
              }
            />
          )}
          {tab === 'details' && (
            <DetailsTab
              call={call}
              onOpenCustomer={() => call.customer_id && navigate(`/customers/${call.customer_id}`)}
            />
          )}
          {tab === 'course' && <VerlaufTab callId={call.id} />}
        </div>
      </aside>

      {inquiry && (
        <ProcessRequestModal
          open={modal === 'process'}
          onClose={() => setModal(null)}
          inquiry={inquiry}
          onSave={(body) => {
            patchInquiry.mutate(body)
            setModal(null)
          }}
        />
      )}
      <CreateAppointmentModal
        open={modal === 'appointment'}
        onClose={() => setModal(null)}
        call={call}
        inquiryId={inquiry?.id}
        employees={employees}
        onCreated={() => {
          setModal(null)
          qc.invalidateQueries({ queryKey: ['callInquiry', callId] })
        }}
      />
    </>
  )
}

function Transcript({
  call,
  isSuperAdmin,
  onOpenSummary,
}: {
  call: CallDetail
  isSuperAdmin: boolean
  onOpenSummary: () => void
}) {
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [audioState, setAudioState] = useState<'idle' | 'loading' | 'error'>('idle')
  // Active-turn highlighting synced to audio playback. -1 = no highlight
  // (audio paused, ended, or never started). The index here is into the
  // FULL transcript array, not the post-skip render list.
  const [activeIdx, setActiveIdx] = useState<number>(-1)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const turnRefs = useRef<Map<number, HTMLDivElement>>(new Map())

  useEffect(() => {
    setAudioUrl(null)
    setAudioState('idle')
    setActiveIdx(-1)
  }, [call.id])

  async function loadAudio() {
    setAudioState('loading')
    try {
      setAudioUrl(await apiBlobUrl(`/api/calls/${call.id}/audio`))
      setAudioState('idle')
    } catch {
      setAudioState('error')
    }
  }

  // Memoize so referential identity is stable when call.transcript is null —
  // otherwise the `[] !== []` shift would invalidate every downstream useMemo
  // on every render and re-fire the audio-listener effect for no reason.
  const transcript = useMemo(() => call.transcript ?? [], [call.transcript])

  // Pre-compute the turns that carry a usable timestamp. We need the original
  // indices so the highlight aligns with the rendered <div key={i}>.
  const timedTurns = useMemo(
    () =>
      transcript
        .map((t, i) =>
          typeof t.time_in_call_secs === 'number'
            ? { idx: i, t: t.time_in_call_secs }
            : null,
        )
        .filter((x): x is { idx: number; t: number } => x !== null)
        .sort((a, b) => a.t - b.t),
    [transcript],
  )
  const hasTurnTimings = timedTurns.length > 0

  // Active-turn computation: find the timed turn whose t <= currentTime, but
  // before the next timed turn's t. Linear scan is fine (call transcripts
  // top out around 30-50 turns). Returns -1 when audio is at 0 or before
  // the first timestamp.
  function activeIndexForTime(time: number): number {
    if (!timedTurns.length) return -1
    let chosen = -1
    for (let i = 0; i < timedTurns.length; i++) {
      if (timedTurns[i].t <= time) {
        chosen = timedTurns[i].idx
      } else {
        break
      }
    }
    return chosen
  }

  // Wire audio events. Re-runs when audioUrl changes (i.e. when "Aufnahme laden"
  // resolves). With lazy loading, the <audio> element only exists once audioUrl
  // is set, so we attach the listener via the ref once the element is mounted.
  useEffect(() => {
    const el = audioRef.current
    if (!el) return
    const onTime = () => setActiveIdx(activeIndexForTime(el.currentTime))
    const onClear = () => setActiveIdx(-1)
    el.addEventListener('timeupdate', onTime)
    el.addEventListener('pause', onClear)
    el.addEventListener('ended', onClear)
    return () => {
      el.removeEventListener('timeupdate', onTime)
      el.removeEventListener('pause', onClear)
      el.removeEventListener('ended', onClear)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audioUrl, timedTurns])

  // Smooth-scroll the active turn into view if it's off-screen. Uses
  // scrollIntoView with `block: 'nearest'` so we don't fight the user's
  // own scroll position when the active turn is already visible.
  useEffect(() => {
    if (activeIdx < 0) return
    const node = turnRefs.current.get(activeIdx)
    if (!node) return
    node.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [activeIdx])

  const summary = call.summary?.trim() ? call.summary.trim() : null

  return (
    <section className="flex min-w-0 flex-1 flex-col">
      <header className="border-b border-border bg-surface px-6 py-3">
        <div className="text-sm font-bold text-text">{displayName(call)}</div>
        <div className="text-xs text-muted">
          {call.direction === 'outbound' ? 'Ausgehend' : 'Eingehend'} · {fmtTime(call.started_at)} ·{' '}
          {fmtDuration(call.duration_seconds)}
        </div>
      </header>

      {/* Zusammenfassung preview — surfaced at the TOP of the center panel so
          the operator sees the gist before scrolling the transcript. Compact
          (2-3 lines, truncated via line-clamp). "Mehr anzeigen" opens the
          Details tab on the right which holds the full version + the
          ultimate_summary <details>. Hidden entirely when call.summary is
          null/empty — no empty card. */}
      {summary && (
        <div className="border-b border-border bg-alt px-6 py-2.5">
          <div className="flex items-start gap-2.5">
            <Sparkles size={14} className="mt-0.5 flex-shrink-0 text-ai" />
            <div className="min-w-0 flex-1">
              <div className="mb-0.5 text-[10px] font-bold uppercase tracking-wide text-muted">
                Zusammenfassung
              </div>
              <p className="line-clamp-2 text-xs leading-relaxed text-body">{summary}</p>
            </div>
            <button
              onClick={onOpenSummary}
              className="flex-shrink-0 text-[11px] font-semibold text-green-deep hover:underline"
            >
              Mehr anzeigen
            </button>
          </div>
        </div>
      )}

      <div className="flex items-center gap-3 border-b border-border bg-alt px-6 py-3">
        <Volume2 size={15} className="text-muted" />
        {audioUrl ? (
          <audio ref={audioRef} controls src={audioUrl} className="h-9 w-full max-w-md" />
        ) : (
          <button
            onClick={loadAudio}
            disabled={audioState === 'loading'}
            className="rounded-md border border-border bg-surface px-3 py-1.5 text-sm font-medium text-body hover:bg-alt disabled:opacity-50"
          >
            {audioState === 'loading' ? 'Lädt Aufnahme…' : 'Aufnahme laden'}
          </button>
        )}
        {audioState === 'error' && <span className="text-xs text-error">Nicht verfügbar.</span>}
        {audioUrl && !hasTurnTimings && (
          <span className="text-[11px] text-faint">
            Älterer Anruf — Sprungmarken nicht verfügbar.
          </span>
        )}
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto p-6">
        {transcript.map((turn, i) => {
          const isKiki = turn.role === 'agent'
          const hasMessage = !!(turn.message && turn.message.trim())
          const visibleToolCalls = isSuperAdmin ? turn.tool_calls.filter(Boolean) : []
          // P0.1 follow-up (§4): if a turn has no visible content after tool-call hiding,
          // skip the whole row — don't render a floating bot icon next to an empty bubble.
          if (!hasMessage && visibleToolCalls.length === 0) return null
          const isActive = activeIdx === i
          return (
            <div
              key={i}
              ref={(node) => {
                if (node) turnRefs.current.set(i, node)
                else turnRefs.current.delete(i)
              }}
              className={cn(
                '-mx-2 flex items-end gap-2 rounded-lg px-2 py-1 transition-colors',
                isKiki ? 'flex-row-reverse' : 'flex-row',
                // Subtle wash behind the whole turn while it's spoken. Soft
                // green for Kiki, soft info-tint for the customer — chosen so
                // the bubble (which is already green/alt) stays the focal
                // point and the wash reads as a secondary halo.
                isActive && (isKiki ? 'bg-green-tint-50' : 'bg-info-bg'),
              )}
            >
              <div
                className={cn(
                  'flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-md',
                  isKiki ? 'bg-green-tint-100 text-green-deep' : 'bg-alt text-muted',
                )}
              >
                {isKiki ? <Bot size={13} /> : <User size={13} />}
              </div>
              <div className="max-w-[70%]">
                {hasMessage && (
                  <div
                    className={cn(
                      'rounded-xl px-3.5 py-2 text-sm text-text transition-shadow',
                      isKiki ? 'rounded-br-sm bg-green-tint-100' : 'rounded-bl-sm bg-alt',
                      isActive && 'shadow-e1',
                    )}
                  >
                    {turn.message}
                  </div>
                )}
                {/* Tool-call ⚙ chips: internal debugging only, never shown to customers.
                    Stored on the call so super-admins can still inspect them. */}
                {visibleToolCalls.map((t, j) => (
                    <span
                      key={j}
                      className="mt-1 inline-block rounded-full bg-ai-bg px-2 py-0.5 text-[11px] font-semibold text-ai"
                    >
                      ⚙ {t}
                    </span>
                  ))}
              </div>
            </div>
          )
        })}
        {!transcript.length && <p className="text-sm text-muted">Kein Transkript vorhanden.</p>}
      </div>
    </section>
  )
}

function ActionsTab({
  inquiry,
  employees,
  busy,
  onAssign,
  onStatus,
  onEdit,
  onAppointment,
  onKva,
}: {
  inquiry: Inquiry | undefined
  employees: Employee[]
  busy: boolean
  onAssign: (id: string) => void
  onStatus: (s: string) => void
  onEdit: () => void
  onAppointment: () => void
  onKva?: () => void
}) {
  return (
    <div className="space-y-5">
      <div>
        <div className="mb-1.5 text-[11px] font-bold uppercase tracking-wide text-muted">
          Zugewiesen an
        </div>
        <select
          value={inquiry?.assigned_employee_id ?? ''}
          disabled={busy || !inquiry}
          onChange={(e) => onAssign(e.target.value)}
          className="w-full rounded-md border border-border bg-surface px-3 py-1.5 text-sm text-text outline-none focus:border-green-primary"
        >
          <option value="">— Nicht zugewiesen —</option>
          {employees.map((e) => (
            <option key={e.id} value={e.id}>
              {e.display_name}
            </option>
          ))}
        </select>
      </div>

      <div>
        <div className="mb-1.5 text-[11px] font-bold uppercase tracking-wide text-muted">
          Status-Aktionen
        </div>
        <div className="space-y-1">
          {inquiry?.status === 'completed' ? (
            <ActionRow
              icon={RotateCcw}
              label="Wieder öffnen"
              tone="info"
              onClick={() => onStatus('open')}
              disabled={busy}
            />
          ) : (
            <ActionRow
              icon={CheckCircle}
              label="Als erledigt markieren"
              tone="success"
              onClick={() => onStatus('completed')}
              disabled={busy}
            />
          )}
          <ActionRow
            icon={Clock}
            label="In Bearbeitung setzen"
            tone="warning"
            onClick={() => onStatus('in_progress')}
            disabled={busy}
          />
          <ActionRow icon={Edit3} label="Bearbeiten" onClick={onEdit} disabled={!inquiry} />
          <ActionRow icon={FileText} label="Kostenvoranschlag erstellen" onClick={onKva} disabled={!onKva} />
          <ActionRow icon={CalIcon} label="Termin erstellen" onClick={onAppointment} />
        </div>
      </div>

      <button
        onClick={() => onStatus('deleted')}
        disabled={busy || !inquiry}
        className="flex w-full items-center justify-center gap-2 rounded-md bg-error-bg py-1.5 text-sm font-medium text-error hover:brightness-105 disabled:opacity-50"
      >
        <Trash2 size={14} /> Anfrage löschen
      </button>
    </div>
  )
}

function ActionRow({
  icon: Icon,
  label,
  tone,
  onClick,
  disabled,
  comingSoon,
}: {
  icon: typeof CheckCircle
  label: string
  tone?: 'success' | 'warning' | 'info'
  onClick?: () => void
  disabled?: boolean
  comingSoon?: boolean
}) {
  const toneClass =
    tone === 'success'
      ? 'bg-success-bg text-success'
      : tone === 'warning'
        ? 'bg-warning-bg text-warning'
        : tone === 'info'
          ? 'bg-info-bg text-info'
          : 'bg-alt text-body'
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        // ~36px tall (py-1.5 = 6px + text-sm 20px line-height = 32px content +
        // 4px border = 36px). Compressed from py-2.5 (~46px) so a denser
        // narrower right panel still surfaces all status actions above the fold.
        'flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm font-medium transition-colors hover:brightness-105 disabled:opacity-50',
        toneClass,
      )}
    >
      <Icon size={14} />
      <span className="flex-1 truncate">{label}</span>
      {comingSoon && <span className="text-[10px] font-semibold text-faint">bald</span>}
    </button>
  )
}

function Collapsible({
  title,
  icon: Icon,
  defaultOpen = false,
  children,
}: {
  title: string
  icon?: typeof Sparkles
  defaultOpen?: boolean
  children: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="rounded-lg border border-border bg-surface">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left"
      >
        {Icon && <Icon size={15} className="text-ai" />}
        <span className="flex-1 text-sm font-semibold text-text">{title}</span>
        <ChevronDown
          size={16}
          className={cn('text-muted transition-transform', open && 'rotate-180')}
        />
      </button>
      {open && <div className="border-t border-border px-4 py-3">{children}</div>}
    </div>
  )
}

function ContactCard({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof AtSign
  label: string
  value: string
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-green-tint-200 bg-green-tint-50 p-3">
      <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-md bg-green-tint-100 text-green-deep">
        <Icon size={16} />
      </div>
      <div className="min-w-0">
        <div className="text-[11px] font-bold uppercase tracking-wide text-muted">{label}</div>
        <div className="truncate text-sm font-medium text-text">{value}</div>
      </div>
    </div>
  )
}

function DetailsTab({ call, onOpenCustomer }: { call: CallDetail; onOpenCustomer: () => void }) {
  const dc = call.data_collection ?? {}
  const c = call.customers
  const phone = isMeaningful(c?.phone) ? c!.phone! : isMeaningful(call.caller_number) ? call.caller_number! : null
  return (
    <div className="space-y-4">
      {/* Summary — collapsible, shown once */}
      <Collapsible title="Zusammenfassung" icon={Sparkles} defaultOpen>
        <p className="text-sm leading-relaxed text-body">
          {call.summary ?? 'Keine Zusammenfassung.'}
        </p>
        {dc.ultimate_summary && (
          <details className="mt-3">
            <summary className="cursor-pointer text-xs font-semibold text-green-deep">
              Vollständige Zusammenfassung
            </summary>
            <pre className="mt-2 whitespace-pre-wrap font-sans text-sm leading-relaxed text-body">
              {dc.ultimate_summary}
            </pre>
          </details>
        )}
      </Collapsible>

      {/* Customer — clickable → customer profile */}
      <div>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-bold uppercase tracking-wide text-muted">Kunde</span>
          {call.customer_id && (
            <button
              onClick={onOpenCustomer}
              className="flex items-center gap-1 text-xs font-semibold text-green-deep hover:underline"
            >
              Profil öffnen <ExternalLink size={12} />
            </button>
          )}
        </div>
        <button
          onClick={call.customer_id ? onOpenCustomer : undefined}
          className={cn(
            'flex w-full items-center gap-3 rounded-lg border border-border bg-surface p-3 text-left',
            call.customer_id && 'hover:bg-green-tint-50',
          )}
        >
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-green-tint-100 text-xs font-bold text-green-deep">
            {initials(displayName(call))}
          </div>
          <div className="min-w-0">
            <div className="truncate text-sm font-bold text-text">
              {isMeaningful(c?.full_name) ? c!.full_name : displayName(call)}
            </div>
            {c?.customer_number && (
              <div className="font-mono text-xs text-muted">#{c.customer_number}</div>
            )}
          </div>
        </button>
      </div>

      {/* Contact channels — each once, no repetition */}
      <div className="space-y-2">
        {isMeaningful(c?.email) && <ContactCard icon={AtSign} label="E-Mail" value={c!.email!} />}
        {phone && <ContactCard icon={Phone} label="Telefon" value={phone} />}
        {isMeaningful(dc.customer_address) && (
          <ContactCard icon={MapPin} label="Adresse" value={dc.customer_address!} />
        )}
        <ContactCard icon={Phone} label="Kanal" value="Telefon" />
      </div>

      {/* Extracted fields that aren't contact details */}
      {(isMeaningful(dc.issue_summary) ||
        isMeaningful(dc.customer_sentiment) ||
        isMeaningful(dc.next_action)) && (
        <Section title="Erfasste Daten">
          <dl className="space-y-2.5">
            {isMeaningful(dc.issue_summary) && <DetailRow label="Betreff" value={dc.issue_summary!} />}
            {isMeaningful(dc.customer_sentiment) && (
              <DetailRow label="Stimmung" value={dc.customer_sentiment!} />
            )}
            {isMeaningful(dc.next_action) && (
              <DetailRow label="Nächste Schritte" value={dc.next_action!} />
            )}
          </dl>
        </Section>
      )}

      <Section title="Anfrage-Info">
        <div className="space-y-1 text-sm text-muted">
          <div>Erstellt: {fmtTime(call.started_at)}</div>
          <div>Von: KI-Telefonassistent</div>
          <div>Richtung: {call.direction === 'outbound' ? 'Ausgehend' : 'Eingehend'}</div>
        </div>
      </Section>
    </div>
  )
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] font-semibold uppercase tracking-wide text-faint">{label}</dt>
      <dd className="text-sm text-text">{value}</dd>
    </div>
  )
}

// Wave 3 / Agent 3.2 — unified timeline event shape returned by
// GET /api/calls/{id}/timeline. See backend/app/api/routes/calls.py.
type TimelineEventKind =
  | 'call_created'
  | 'inquiry_status_changed'
  | 'appointment_confirmed'
  | 'appointment_rejected'
  | 'alternative_proposed'
  | 'kva_sent'
  | 'kva_accepted'
  | 'kva_rejected'
  | 'assignment_changed'

interface TimelineEvent {
  id: string
  kind: TimelineEventKind
  timestamp: string
  actor_kind: 'kiki' | 'employee' | 'system'
  actor_name: string
  description: string
  entity_id: string | null
  extras: Record<string, unknown>
}

// Color-coded dot per event kind. Each tuple is (dot bg, dot ring) so the
// dot reads above the timeline rail. Picked to map cleanly to the same
// semantic colors used in the Aktionen-tab status chips and the list-card
// status pills (green = confirmed/positive, red = reject, amber = alt,
// purple = KVA money flow, cyan = assignment).
const TIMELINE_KIND_DOT: Record<TimelineEventKind, string> = {
  call_created: 'bg-blue-500',
  inquiry_status_changed: 'bg-muted',
  appointment_confirmed: 'bg-green-primary',
  appointment_rejected: 'bg-red-500',
  alternative_proposed: 'bg-amber-500',
  kva_sent: 'bg-purple-500',
  kva_accepted: 'bg-purple-600',
  kva_rejected: 'bg-purple-400',
  assignment_changed: 'bg-cyan-500',
}

// Actor-chip styling — distinct visual lane per source so a scan over the
// timeline groups "Kiki did X" rows visually apart from "employee did X".
const ACTOR_CHIP: Record<TimelineEvent['actor_kind'], string> = {
  kiki: 'bg-green-tint-50 text-green-deep',
  employee: 'bg-blue-100 text-blue-800',
  system: 'bg-alt text-faint',
}

// Tight German relative-time formatter. Falls back to absolute date for
// anything older than a week so the scan stays readable across long histories.
function relativeTimeDe(iso: string): string {
  const now = Date.now()
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const diffSec = Math.max(0, Math.round((now - then) / 1000))
  if (diffSec < 60) return 'gerade eben'
  const min = Math.round(diffSec / 60)
  if (min < 60) return `vor ${min} Min`
  const hours = Math.round(min / 60)
  if (hours < 24) return `vor ${hours} Std`
  const days = Math.round(hours / 24)
  if (days < 7) return `vor ${days} ${days === 1 ? 'Tag' : 'Tagen'}`
  // Older than a week — show absolute short date.
  return new Date(iso).toLocaleDateString('de-DE', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

// Absolute timestamp for the tooltip on hover — full precision.
function absoluteTimeDe(iso: string): string {
  return new Date(iso).toLocaleString('de-DE', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function VerlaufTab({ callId }: { callId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['callTimeline', callId],
    queryFn: () => apiFetch<TimelineEvent[]>(`/api/calls/${callId}/timeline`),
    enabled: !!callId,
  })
  const events = data ?? []

  if (isLoading) {
    return <p className="text-sm text-muted">Lade Verlauf …</p>
  }

  if (!events.length) {
    return <p className="text-sm text-muted">Keine Verlaufs-Einträge.</p>
  }

  return (
    <div className="relative pl-5">
      {/* Vertical rail behind every event row. */}
      <div className="absolute left-[7px] top-1 bottom-1 w-px bg-border" aria-hidden="true" />
      <ol className="space-y-3.5">
        {events.map((ev) => (
          <li key={ev.id} className="relative">
            {/* Dot on the rail — sits 5px to the LEFT of the row content
                (the parent has pl-5 = 20px, dot is 10px wide centered at
                the 7px rail → leaves 8px to the row text). */}
            <span
              className={cn(
                'absolute -left-[18px] top-[5px] h-2.5 w-2.5 rounded-full ring-2 ring-surface',
                TIMELINE_KIND_DOT[ev.kind] ?? 'bg-muted',
              )}
              aria-hidden="true"
            />

            <div className="flex flex-col gap-0.5">
              {/* Meta row: relative time + actor chip. */}
              <div className="flex items-center gap-2">
                <time
                  className="text-xs text-muted"
                  dateTime={ev.timestamp}
                  title={absoluteTimeDe(ev.timestamp)}
                >
                  {relativeTimeDe(ev.timestamp)}
                </time>
                <span
                  className={cn(
                    'rounded-full px-1.5 py-0.5 text-[10px] font-medium',
                    ACTOR_CHIP[ev.actor_kind] ?? 'bg-alt text-faint',
                  )}
                >
                  {ev.actor_name}
                </span>
              </div>
              {/* Description row. */}
              <p className="text-sm text-text">{ev.description}</p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}

function Section({
  icon: Icon,
  title,
  accent,
  children,
}: {
  icon?: typeof Sparkles
  title: string
  accent?: boolean
  children: React.ReactNode
}) {
  return (
    <div
      className={cn(
        'rounded-lg border p-4',
        accent ? 'border-ai/20 bg-ai-bg' : 'border-border bg-surface',
      )}
    >
      <div className="mb-2.5 flex items-center gap-2">
        {Icon && <Icon size={14} className={accent ? 'text-ai' : 'text-muted'} />}
        <span className="text-xs font-bold uppercase tracking-wide text-muted">{title}</span>
      </div>
      {children}
    </div>
  )
}

// ─── Modals ──────────────────────────────────────────────────────────────────
function ProcessRequestModal({
  open,
  onClose,
  inquiry,
  onSave,
}: {
  open: boolean
  onClose: () => void
  inquiry: Inquiry
  onSave: (body: Partial<Inquiry>) => void
}) {
  const [title, setTitle] = useState(inquiry.title ?? '')
  const [type, setType] = useState(inquiry.type ?? 'info')
  const [notes, setNotes] = useState(inquiry.notes ?? '')
  const [status, setStatus] = useState(inquiry.status)

  useEffect(() => {
    if (open) {
      setTitle(inquiry.title ?? '')
      setType(inquiry.type ?? 'info')
      setNotes(inquiry.notes ?? '')
      setStatus(inquiry.status)
    }
  }, [open, inquiry])

  return (
    <Modal
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Anfrage bearbeiten"
      footer={
        <div className="flex gap-3">
          <button
            onClick={() => onSave({ title, type, notes, status })}
            className="flex-1 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110"
          >
            Aktualisieren
          </button>
          <button
            onClick={onClose}
            className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body"
          >
            Abbrechen
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        <Field label="Referenz">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary"
          />
        </Field>
        <Field label="Kategorie">
          <div className="flex flex-wrap gap-2">
            {CATEGORIES.map((cat) => (
              <button
                key={cat}
                onClick={() => setType(cat)}
                className={cn(
                  'rounded-md border px-3 py-1.5 text-sm font-medium capitalize',
                  type === cat
                    ? 'border-green-primary bg-green-primary text-white'
                    : 'border-border bg-surface text-body hover:bg-alt',
                )}
              >
                {cat}
              </button>
            ))}
          </div>
        </Field>
        <Field label="Notiz">
          <textarea
            rows={5}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-body outline-none focus:border-green-primary"
          />
        </Field>
        <Field label="Status">
          <div className="flex gap-2">
            {(['open', 'in_progress', 'completed'] as const).map((s) => (
              <button
                key={s}
                onClick={() => setStatus(s)}
                className={cn(
                  'rounded-full px-3 py-1.5 text-sm font-semibold',
                  status === s
                    ? STATUS_TAG[s].variant === 'success'
                      ? 'bg-success text-white'
                      : STATUS_TAG[s].variant === 'warning'
                        ? 'bg-warning text-white'
                        : 'bg-info text-white'
                    : 'bg-alt text-muted',
                )}
              >
                {STATUS_TAG[s].label}
              </button>
            ))}
          </div>
        </Field>
      </div>
    </Modal>
  )
}

function CreateAppointmentModal({
  open,
  onClose,
  call,
  inquiryId,
  employees,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  call: CallDetail
  inquiryId: string | undefined
  employees: Employee[]
  onCreated: () => void
}) {
  const dc = call.data_collection ?? {}
  const [apptType, setApptType] = useState<'customer' | 'private'>('customer')
  const [privateTitle, setPrivateTitle] = useState('')
  const [date, setDate] = useState('')
  const [time, setTime] = useState('09:00')
  const [duration, setDuration] = useState(60)
  const [color, setColor] = useState(COLORS[0])
  const [location, setLocation] = useState('')
  const [assigned, setAssigned] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setApptType('customer')
      setPrivateTitle('')
      setLocation(dc.customer_address ?? call.customers?.phone ?? '')
      setDescription(call.summary ?? dc.ultimate_summary ?? '')
      setError(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const create = useMutation({
    mutationFn: () => {
      const iso = new Date(`${date}T${time}`).toISOString()
      const isPrivate = apptType === 'private'
      return apiFetch('/api/appointments', {
        method: 'POST',
        body: JSON.stringify({
          customer_id: isPrivate ? null : call.customer_id,
          title: isPrivate ? privateTitle || 'Privater Termin' : call.summary_title ?? 'Termin',
          scheduled_at: iso,
          duration_minutes: duration,
          location,
          color,
          assigned_employee_id: assigned || null,
          notes: description,
          inquiry_id: isPrivate ? null : inquiryId ?? null,
        }),
      })
    },
    onSuccess: onCreated,
    onError: () => setError('Termin konnte nicht erstellt werden.'),
  })

  const customerName = isMeaningful(call.customers?.full_name)
    ? call.customers!.full_name
    : displayName(call)

  return (
    <Modal
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Termin erstellen"
      widthClass="max-w-xl"
      footer={
        <div className="flex gap-3">
          <button
            disabled={!date || create.isPending}
            onClick={() => create.mutate()}
            className="flex-1 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
          >
            {create.isPending ? 'Speichert…' : 'Termin speichern'}
          </button>
          <button
            onClick={onClose}
            className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body"
          >
            Abbrechen
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        {/* Appointment type */}
        <div className="grid grid-cols-2 gap-2 rounded-md bg-alt p-1">
          {(['customer', 'private'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setApptType(t)}
              className={cn(
                'rounded-md py-2 text-sm font-semibold transition-colors',
                apptType === t ? 'bg-green-primary text-white' : 'text-muted',
              )}
            >
              {t === 'customer' ? 'Kunde' : 'Privat'}
            </button>
          ))}
        </div>

        {apptType === 'customer' ? (
          <Field label="Kunde">
            <div className="flex items-center gap-2 rounded-md border border-border bg-green-tint-50 px-3 py-2.5">
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-green-tint-100 text-xs font-bold text-green-deep">
                {initials(customerName ?? '?')}
              </div>
              <span className="text-sm font-medium text-text">{customerName}</span>
            </div>
          </Field>
        ) : (
          <Field label="Titel *">
            <input
              value={privateTitle}
              onChange={(e) => setPrivateTitle(e.target.value)}
              placeholder="z. B. Werkstatt-Wartung"
              className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary"
            />
          </Field>
        )}

        <div className="grid grid-cols-2 gap-3">
          <Field label="Datum *">
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary"
            />
          </Field>
          <Field label="Uhrzeit *">
            <input
              type="time"
              value={time}
              onChange={(e) => setTime(e.target.value)}
              className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary"
            />
          </Field>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Dauer">
            <select
              value={duration}
              onChange={(e) => setDuration(Number(e.target.value))}
              className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary"
            >
              {[30, 60, 90, 120].map((m) => (
                <option key={m} value={m}>
                  {m} Min
                </option>
              ))}
            </select>
          </Field>
          <Field label="Farbe">
            <div className="flex items-center gap-2 pt-1.5">
              {COLORS.map((c) => (
                <button
                  key={c}
                  onClick={() => setColor(c)}
                  className={cn(
                    'h-6 w-6 rounded-full transition-transform',
                    color === c && 'ring-2 ring-offset-2 ring-offset-surface',
                  )}
                  style={{ background: c, boxShadow: color === c ? `0 0 0 2px ${c}` : undefined }}
                />
              ))}
            </div>
          </Field>
        </div>

        <Field label="Ort">
          <input
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary"
          />
        </Field>

        <Field label="Zugewiesen an">
          <select
            value={assigned}
            onChange={(e) => setAssigned(e.target.value)}
            className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary"
          >
            <option value="">— Nicht zugewiesen —</option>
            {employees.map((e) => (
              <option key={e.id} value={e.id}>
                {e.display_name}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Fahrzeuge & Werkzeuge">
          <div className="rounded-md border border-dashed border-border px-3 py-2.5 text-xs text-faint">
            Inventar (Planungstafel) — folgt in einer späteren Phase.
          </div>
        </Field>

        <Field label="Beschreibung">
          <textarea
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-body outline-none focus:border-green-primary"
          />
        </Field>

        {error && <div className="text-sm text-error">{error}</div>}
      </div>
    </Modal>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 text-xs font-semibold text-body">{label}</div>
      {children}
    </div>
  )
}
