import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AtSign,
  Bot,
  Calendar as CalIcon,
  CheckCircle,
  ChevronDown,
  Clock,
  Edit3,
  Euro,
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
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import { Modal } from '../components/ui/Modal'
import { Tag } from '../components/ui/Tag'
import { apiBlobUrl, apiFetch } from '../lib/api'
import { supabase } from '../lib/supabase'
import { cn, initials } from '../lib/utils'

interface TranscriptTurn {
  role: string
  message: string | null
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
  customers: { full_name: string | null } | null
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

export function CallLogsPage() {
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [search, setSearch] = useState('')

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
        <div className="border-b border-border p-4">
          <div className="mb-3 flex items-center justify-between">
            <h1 className="text-base font-bold text-text">Anrufe</h1>
            <span className="text-xs text-muted">{calls.length} gesamt</span>
          </div>
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Suchen…"
              className="w-full rounded-md border border-border bg-alt py-2 pl-9 pr-3 text-sm text-body outline-none focus:border-green-primary"
            />
          </div>
        </div>
        <div className="flex-1 space-y-1 overflow-y-auto p-2">
          {filtered.map((c) => {
            const active = c.id === selectedId
            const isUnread = c.read_at === null  // P0.4 — Gmail-style read/unread
            const Icon = c.direction === 'outbound' ? PhoneOutgoing : PhoneIncoming
            return (
              <button
                key={c.id}
                onClick={() => setSelectedId(c.id)}
                className={cn(
                  'flex w-full items-start gap-3 rounded-lg border p-3 text-left transition-colors',
                  active
                    ? 'border-green-primary/40 bg-green-tint-50'
                    : 'border-border bg-surface hover:bg-alt',
                )}
              >
                <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-green-tint-100 text-xs font-bold text-green-deep">
                  {initials(displayName(c))}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span
                      className={cn(
                        'truncate text-sm',
                        isUnread ? 'font-semibold text-text' : 'font-medium text-muted',
                      )}
                    >
                      {displayName(c)}
                    </span>
                    <Icon size={13} className="flex-shrink-0 text-muted" />
                  </div>
                  <div
                    className={cn(
                      'truncate text-xs',
                      isUnread ? 'text-body' : 'text-muted',
                    )}
                  >
                    {c.summary_title ?? 'Anruf'}
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-[11px] text-faint">
                    <span>{fmtTime(c.started_at)}</span>
                    <span>·</span>
                    <span>{fmtDuration(c.duration_seconds)}</span>
                  </div>
                </div>
              </button>
            )
          })}
          {!callsQuery.isLoading && !filtered.length && (
            <p className="p-3 text-sm text-muted">Keine Anrufe.</p>
          )}
        </div>
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

  if (!call) {
    return <div className="flex flex-1 items-center justify-center text-muted">Lädt…</div>
  }

  return (
    <>
      <Transcript call={call} isSuperAdmin={isSuperAdmin} />

      {/* RIGHT PANEL */}
      <aside className="flex w-96 flex-shrink-0 flex-col border-l border-border bg-surface">
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
                'flex-1 border-b-2 px-2 py-2.5 text-sm font-medium transition-colors',
                tab === t
                  ? 'border-green-primary text-green-deep'
                  : 'border-transparent text-muted hover:text-body',
              )}
            >
              {t === 'actions' ? 'Aktionen' : t === 'details' ? 'Details' : 'Verlauf'}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto p-5">
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
          {tab === 'course' && <VerlaufTab customerId={call.customer_id} />}
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

function Transcript({ call, isSuperAdmin }: { call: CallDetail; isSuperAdmin: boolean }) {
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [audioState, setAudioState] = useState<'idle' | 'loading' | 'error'>('idle')

  useEffect(() => {
    setAudioUrl(null)
    setAudioState('idle')
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

  const transcript = call.transcript ?? []
  return (
    <section className="flex min-w-0 flex-1 flex-col">
      <header className="border-b border-border bg-surface px-6 py-3">
        <div className="text-sm font-bold text-text">{displayName(call)}</div>
        <div className="text-xs text-muted">
          {call.direction === 'outbound' ? 'Ausgehend' : 'Eingehend'} · {fmtTime(call.started_at)} ·{' '}
          {fmtDuration(call.duration_seconds)}
        </div>
      </header>
      <div className="flex items-center gap-3 border-b border-border bg-alt px-6 py-3">
        <Volume2 size={15} className="text-muted" />
        {audioUrl ? (
          <audio controls src={audioUrl} className="h-9 w-full max-w-md" />
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
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto p-6">
        {transcript.map((turn, i) => {
          const isKiki = turn.role === 'agent'
          return (
            <div key={i} className={cn('flex items-end gap-2', isKiki ? 'flex-row-reverse' : 'flex-row')}>
              <div
                className={cn(
                  'flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-md',
                  isKiki ? 'bg-green-tint-100 text-green-deep' : 'bg-alt text-muted',
                )}
              >
                {isKiki ? <Bot size={13} /> : <User size={13} />}
              </div>
              <div className="max-w-[70%]">
                {turn.message && (
                  <div
                    className={cn(
                      'rounded-xl px-3.5 py-2 text-sm text-text',
                      isKiki ? 'rounded-br-sm bg-green-tint-100' : 'rounded-bl-sm bg-alt',
                    )}
                  >
                    {turn.message}
                  </div>
                )}
                {/* Tool-call ⚙ chips: internal debugging only, never shown to customers.
                    Stored on the call so super-admins can still inspect them. */}
                {isSuperAdmin &&
                  turn.tool_calls.filter(Boolean).map((t, j) => (
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
    <div className="space-y-6">
      <div>
        <div className="mb-2 text-xs font-bold uppercase tracking-wide text-muted">Zugewiesen an</div>
        <select
          value={inquiry?.assigned_employee_id ?? ''}
          disabled={busy || !inquiry}
          onChange={(e) => onAssign(e.target.value)}
          className="w-full rounded-md border border-border bg-surface px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary"
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
        <div className="mb-2 text-xs font-bold uppercase tracking-wide text-muted">Status-Aktionen</div>
        <div className="space-y-1.5">
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
        className="flex w-full items-center justify-center gap-2 rounded-md bg-error-bg py-2.5 text-sm font-medium text-error hover:brightness-105 disabled:opacity-50"
      >
        <Trash2 size={15} /> Anfrage löschen
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
        'flex w-full items-center gap-2.5 rounded-md px-3 py-2.5 text-left text-sm font-medium transition-colors hover:brightness-105 disabled:opacity-50',
        toneClass,
      )}
    >
      <Icon size={15} />
      <span className="flex-1">{label}</span>
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

interface CustomerDetail {
  inquiries: { id: string; number: string | null; title: string | null; status: string; created_at: string }[]
  appointments: { id: string; title: string | null; scheduled_at: string | null; status: string; category: string | null }[]
  cost_estimates: { id: string; number: string | null; status: string; total: number | null; created_at: string }[]
}

function statusDot(status: string): string {
  return status === 'confirmed' || status === 'completed'
    ? 'bg-success'
    : status === 'cancelled' || status === 'rejected'
      ? 'bg-error'
      : 'bg-warning'
}

function VerlaufTab({ customerId }: { customerId: string | null }) {
  const { data } = useQuery({
    queryKey: ['customerDetail', customerId],
    queryFn: () => apiFetch<CustomerDetail>(`/api/customers/${customerId}`),
    enabled: !!customerId,
  })
  if (!customerId) return <p className="text-sm text-muted">Kein Kunde verknüpft.</p>
  const inquiries = data?.inquiries ?? []
  const appts = data?.appointments ?? []
  const kvas = data?.cost_estimates ?? []
  return (
    <div className="space-y-4">
      <Section title="Durchgeführte Aktionen">
        <div className="space-y-2">
          {inquiries.map((i) => (
            <div key={i.id} className="rounded-lg border border-border p-3">
              <div className="flex items-start justify-between gap-2">
                <span className="text-sm font-medium text-text">{i.title ?? 'Anfrage'}</span>
                <Tag variant={STATUS_TAG[i.status]?.variant ?? 'neutral'}>
                  {STATUS_TAG[i.status]?.label ?? i.status}
                </Tag>
              </div>
              <div className="mt-1 text-xs text-muted">{fmtTime(i.created_at)}</div>
            </div>
          ))}
          {!inquiries.length && <p className="text-sm text-muted">Noch keine Aktionen.</p>}
        </div>
      </Section>

      <Section title={`Termine (${appts.length})`}>
        <div className="space-y-2">
          {appts.map((a) => (
            <div key={a.id} className="rounded-lg border border-border p-3">
              <div className="flex items-center gap-2">
                <span className={cn('h-2 w-2 flex-shrink-0 rounded-full', statusDot(a.status))} />
                <span className="flex-1 truncate text-sm font-medium text-text">
                  {a.title ?? 'Termin'}
                </span>
              </div>
              <div className="mt-1 text-xs text-muted">{fmtTime(a.scheduled_at)}</div>
            </div>
          ))}
          {!appts.length && <p className="text-sm text-muted">Keine Termine.</p>}
        </div>
      </Section>

      <Section title={`Kostenvoranschläge (${kvas.length})`}>
        <div className="space-y-2">
          {kvas.map((k) => (
            <div key={k.id} className="flex items-center gap-2 rounded-lg border border-border p-3">
              <Euro size={14} className="text-green-deep" />
              <span className="flex-1 truncate text-sm font-medium text-text">
                {k.number ?? 'KVA'}
              </span>
              <span className="text-xs text-muted">{fmtTime(k.created_at)}</span>
            </div>
          ))}
          {!kvas.length && <p className="text-sm text-muted">Keine Kostenvoranschläge.</p>}
        </div>
      </Section>
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
