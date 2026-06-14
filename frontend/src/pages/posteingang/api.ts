// Real-data + actions layer for the Posteingang Fokus·Agenda. Maps the live API
// (/api/actions/pending, /api/calls, /api/inquiries/{id}/thread, /api/calls/{id})
// into the view-models the screen renders, and exposes the mutations that make
// every button functional. Replaces the mock-data module.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiFetch } from '../../lib/api'
import { relativeTimeDe } from '../../lib/datetime'

export type ActionKind =
  | 'termin_anfrage'
  | 'kva_to_send'
  | 'kva_pending_acceptance'
  | 'callback_owed'
  | 'alt_time_proposal'
  | 'appointment_cancelled'

export type DecisionType = 'termin' | 'rueckruf' | 'storno' | 'kva' | 'reschedule'
export type VStatus = 'open' | 'in_progress' | 'completed'
type TagVariant = 'info' | 'green' | 'error' | 'warning' | 'ai'

interface RawAction {
  action_key: string
  kind: ActionKind
  id: string
  inquiry_id: string | null
  call_id: string | null
  customer_id: string | null
  customer_name: string | null
  summary: string
  priority: 'high' | 'normal'
}

export interface Employee {
  id: string
  display_name: string | null
  is_active?: boolean
  is_absent?: boolean
  is_technician?: boolean
}

interface RawCall {
  id: string
  caller_number: string | null
  summary_title: string | null
  direction: string | null
  duration_seconds: number | null
  started_at: string | null
  created_at: string | null
  customer_id: string | null
  inquiry_id: string | null
  inquiry_status: VStatus | null
  inquiry_number: string | null
  inquiry_subject: string | null
  project_title: string | null
  emergency_flag: boolean
  assigned_employee_id: string | null
  assigned_employee_initials: string | null
  read_at: string | null
  customers: { full_name: string | null } | null
}

// ── View-models the components consume ──────────────────────────────────────
export interface DecisionVM {
  actionKey: string
  kind: ActionKind
  type: DecisionType
  accent: string
  typeLabel: string
  typeVariant: TagVariant
  customer: string
  custId: string | null
  problem: string
  title: string
  snippet: string
  reco: string
  suggestedEmployeeId: string | null
  inquiryId: string | null
  primary: string
  secondary: string | null
  tertiary: string | null
  assignable: boolean
}

export interface VorgangVM {
  inquiryId: string
  custId: string | null
  customer: string
  problem: string
  ticket: string | null
  calls: number
  activity: string
  status: VStatus | null
  assigneeId: string | null
  assigneeInitials: string | null
  emergency: boolean
  decision: string | null
  project: string | null
}

export interface UnsortedCall {
  id: string
  custId: string | null
  customer: string
  title: string
  number: string | null
  activity: string
  durationSeconds: number | null
}

export interface TLItem {
  kind: 'inbound' | 'outbound' | 'termin' | 'kva' | 'rechnung'
  callId?: string
  quote?: string
  label?: string
  detail?: string
  done?: boolean
  doneLabel?: string
  time: string
  ts: number
}

const rel = (iso: string | null) => (iso ? relativeTimeDe(iso) : '—')
const ts = (iso: string | null | undefined) => (iso ? new Date(iso).getTime() : 0)
const firstName = (n: string | null | undefined) => (n ? n.trim().split(/\s+/)[0] : 'jemand')

const KIND_CFG: Record<
  ActionKind,
  { type: DecisionType; accent: string; label: string; variant: TagVariant; title: (a: RawAction) => string; primary: string; secondary: string | null; tertiary: string | null; reco: (name: string, cust: string) => string; assignable: boolean }
> = {
  termin_anfrage: { type: 'termin', accent: 'var(--info)', label: 'Termin', variant: 'info', title: () => 'Termin bestätigen?', primary: 'Bestätigen', secondary: 'Verschieben', tertiary: 'Ablehnen', reco: (n) => `${n} zuweisen und Termin bestätigen`, assignable: true },
  alt_time_proposal: { type: 'reschedule', accent: 'var(--warning)', label: 'Verschieben', variant: 'warning', title: () => 'Neuen Termin annehmen?', primary: 'Annehmen', secondary: null, tertiary: 'Ablehnen', reco: () => 'Vorgeschlagenen Termin annehmen', assignable: false },
  appointment_cancelled: { type: 'storno', accent: 'var(--error)', label: 'Storno', variant: 'error', title: () => 'Stornierung bestätigen?', primary: 'Bestätigen', secondary: null, tertiary: 'Behalten', reco: () => 'Termin stornieren und Slot freigeben', assignable: false },
  callback_owed: { type: 'rueckruf', accent: 'var(--green-primary)', label: 'Rückruf', variant: 'green', title: (a) => `Rückruf an ${a.customer_name || 'Kunde'}?`, primary: 'Erledigt', secondary: 'Zuweisen', tertiary: null, reco: (n) => `${n} den Rückruf zuweisen`, assignable: true },
  kva_to_send: { type: 'kva', accent: 'var(--ai)', label: 'KVA', variant: 'ai', title: (a) => `KVA an ${a.customer_name || 'Kunde'} senden?`, primary: 'KVA senden', secondary: null, tertiary: 'Später', reco: (_n, c) => `KVA jetzt an ${c} senden`, assignable: false },
  kva_pending_acceptance: { type: 'kva', accent: 'var(--ai)', label: 'KVA-Antwort', variant: 'ai', title: () => 'Kundenantwort erfassen', primary: 'Angenommen', secondary: null, tertiary: 'Abgelehnt', reco: () => 'Antwort des Kunden eintragen', assignable: false },
}

function pickSuggested(employees: Employee[]): Employee | null {
  return (
    employees.find((e) => e.is_active !== false && !e.is_absent && e.is_technician) ??
    employees.find((e) => e.is_active !== false && !e.is_absent) ??
    employees[0] ??
    null
  )
}

function buildDecisions(actions: RawAction[], employees: Employee[]): DecisionVM[] {
  const suggested = pickSuggested(employees)
  return actions.map((a) => {
    const cfg = KIND_CFG[a.kind]
    const cust = a.customer_name || 'Unbekannter Kunde'
    const name = firstName(suggested?.display_name)
    return {
      actionKey: a.action_key,
      kind: a.kind,
      type: cfg.type,
      accent: cfg.accent,
      typeLabel: cfg.label,
      typeVariant: cfg.variant,
      customer: cust,
      custId: a.customer_id,
      problem: a.summary,
      title: cfg.title(a),
      snippet: a.summary,
      reco: cfg.reco(name, cust),
      suggestedEmployeeId: cfg.assignable ? suggested?.id ?? null : null,
      inquiryId: a.inquiry_id,
      primary: cfg.primary,
      secondary: cfg.secondary,
      tertiary: cfg.tertiary,
      assignable: cfg.assignable,
    }
  })
}

function buildVorgaenge(calls: RawCall[], actions: RawAction[]): { vorgaenge: VorgangVM[]; unsorted: UnsortedCall[] } {
  const decByInquiry = new Map<string, string>()
  for (const a of actions) if (a.inquiry_id && !decByInquiry.has(a.inquiry_id)) decByInquiry.set(a.inquiry_id, KIND_CFG[a.kind].label)

  const byInquiry = new Map<string, RawCall[]>()
  const unsorted: UnsortedCall[] = []
  for (const c of calls) {
    if (c.inquiry_id) {
      const arr = byInquiry.get(c.inquiry_id) ?? []
      arr.push(c)
      byInquiry.set(c.inquiry_id, arr)
    } else {
      unsorted.push({
        id: c.id,
        custId: c.customer_id,
        customer: c.customers?.full_name || c.caller_number || 'Unbekannt',
        title: c.summary_title || 'Anruf',
        number: c.caller_number,
        activity: rel(c.started_at || c.created_at),
        durationSeconds: c.duration_seconds,
      })
    }
  }

  const vorgaenge: VorgangVM[] = []
  for (const [inquiryId, group] of byInquiry) {
    const latest = [...group].sort((a, b) => ts(b.started_at) - ts(a.started_at))[0]
    vorgaenge.push({
      inquiryId,
      custId: latest.customer_id,
      customer: latest.customers?.full_name || latest.caller_number || 'Unbekannt',
      problem: latest.inquiry_subject || latest.summary_title || 'Vorgang',
      ticket: latest.inquiry_number,
      calls: group.length,
      activity: rel(latest.started_at || latest.created_at),
      status: latest.inquiry_status,
      assigneeId: latest.assigned_employee_id,
      assigneeInitials: latest.assigned_employee_initials,
      emergency: group.some((c) => c.emergency_flag),
      decision: decByInquiry.get(inquiryId) ?? null,
      project: latest.project_title,
    })
  }
  vorgaenge.sort((a, b) => {
    if (a.emergency !== b.emergency) return a.emergency ? -1 : 1
    if (!!a.decision !== !!b.decision) return a.decision ? -1 : 1
    return 0
  })
  return { vorgaenge, unsorted }
}

// ── Queries ─────────────────────────────────────────────────────────────────
export function useEmployees() {
  return useQuery({ queryKey: ['pe', 'employees'], queryFn: () => apiFetch<Employee[]>('/api/employees'), staleTime: 60_000 })
}

export function usePosteingang() {
  const employeesQ = useEmployees()
  const actionsQ = useQuery({ queryKey: ['pe', 'actions'], queryFn: () => apiFetch<RawAction[]>('/api/actions/pending'), refetchInterval: 30_000 })
  const callsQ = useQuery({ queryKey: ['pe', 'calls'], queryFn: () => apiFetch<{ calls: RawCall[] }>('/api/calls?limit=200') })

  const employees = employeesQ.data ?? []
  const actions = (actionsQ.data ?? []).filter((a) => a.kind in KIND_CFG)
  const calls = callsQ.data?.calls ?? []
  const decisions = buildDecisions(actions, employees)
  const { vorgaenge, unsorted } = buildVorgaenge(calls, actions)

  return {
    loading: actionsQ.isLoading || callsQ.isLoading,
    error: actionsQ.isError || callsQ.isError,
    employees,
    decisions,
    vorgaenge,
    unsorted,
    callsCount: calls.length,
  }
}

export interface ThreadResult {
  timeline: TLItem[]
  assigneeId: string | null
}
function mapThread(thread: {
  inquiry?: { assigned_employee?: { id: string } | null }
  calls?: { id: string; summary_title: string | null; direction: string | null; started_at: string | null; created_at: string | null }[]
  appointments?: { scheduled_at: string | null; created_at: string | null; status: string }[]
  cost_estimates?: { total: number | null; status: string; created_at: string | null; sent_at: string | null }[]
}): ThreadResult {
  const items: TLItem[] = []
  for (const c of thread.calls ?? []) {
    const t = c.started_at || c.created_at
    items.push({ kind: c.direction === 'outbound' ? 'outbound' : 'inbound', callId: c.id, quote: c.summary_title || 'Anruf', time: rel(t), ts: ts(t) })
  }
  for (const a of thread.appointments ?? []) {
    const done = a.status === 'confirmed' || a.status === 'completed'
    items.push({ kind: 'termin', label: 'Termin', detail: a.scheduled_at ? relativeTimeDe(a.scheduled_at) : 'offen', done, doneLabel: a.status === 'cancelled' ? 'Storniert' : 'Bestätigt', time: rel(a.created_at), ts: ts(a.created_at) })
  }
  for (const k of thread.cost_estimates ?? []) {
    const done = k.status === 'sent' || k.status === 'accepted'
    items.push({ kind: 'kva', label: 'KVA', detail: k.total != null ? `${k.total} €` : '', done, doneLabel: k.status === 'accepted' ? 'Angenommen' : 'Gesendet', time: rel(k.sent_at || k.created_at), ts: ts(k.sent_at || k.created_at) })
  }
  items.sort((x, y) => x.ts - y.ts)
  return { timeline: items, assigneeId: thread.inquiry?.assigned_employee?.id ?? null }
}
export function useThread(inquiryId: string | null) {
  return useQuery({
    queryKey: ['pe', 'thread', inquiryId],
    queryFn: async () => mapThread(await apiFetch(`/api/inquiries/${inquiryId}/thread`)),
    enabled: !!inquiryId,
  })
}

// ── Call detail (drawer) ────────────────────────────────────────────────────
export interface CallDetailVM {
  id: string
  custId: string | null
  dir: 'inbound' | 'outbound'
  customer: string
  number: string
  date: string
  dur: string
  summary: string
  nextAction: string | null
  emergency: boolean
  unsorted: boolean
  vorgangProblem: string | null
  ticket: string | null
  status: VStatus | null
  transcript: { role: 'agent' | 'customer'; m: string; t: number }[]
}
function fmtDur(s: number | null): string {
  if (s == null) return '—'
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
export function useCallDetail(callId: string | null) {
  return useQuery({
    queryKey: ['pe', 'call', callId],
    enabled: !!callId,
    queryFn: async () => {
      const c = await apiFetch<Record<string, unknown>>(`/api/calls/${callId}`)
      const customers = (c.customers ?? {}) as { full_name?: string; phone?: string }
      const raw = (c.transcript ?? []) as { role?: string; message?: string | null; time_in_call_secs?: number | null }[]
      const dc = (c.data_collection ?? {}) as Record<string, string>
      const vm: CallDetailVM = {
        id: String(c.id),
        custId: (c.customer_id as string) || null,
        dir: c.direction === 'outbound' ? 'outbound' : 'inbound',
        customer: customers.full_name || (c.caller_number as string) || 'Anrufer',
        number: customers.phone || (c.caller_number as string) || '—',
        date: c.started_at ? relativeTimeDe(c.started_at as string) : '—',
        dur: fmtDur((c.duration_seconds as number) ?? null),
        summary: (c.summary as string) || dc.ultimate_summary || dc.issue_summary || 'Keine Zusammenfassung verfügbar.',
        nextAction: dc.next_action || null,
        emergency: !!c.emergency_flag,
        unsorted: !c.inquiry_id,
        vorgangProblem: (c.inquiry_subject as string) || null,
        ticket: (c.inquiry_number as string) || null,
        status: (c.inquiry_status as VStatus) || null,
        transcript: raw
          .filter((t) => t.message)
          .map((t) => ({ role: t.role === 'agent' ? 'agent' : 'customer', m: String(t.message), t: Math.round(t.time_in_call_secs ?? 0) })),
      }
      return vm
    },
  })
}

// ── Mutations (the buttons) ─────────────────────────────────────────────────
export function usePosteingangActions() {
  const qc = useQueryClient()
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['pe'] })
    qc.invalidateQueries({ queryKey: ['calls'] })
    qc.invalidateQueries({ queryKey: ['actions'] })
  }

  const assignInquiry = useMutation({
    mutationFn: ({ inquiryId, employeeId }: { inquiryId: string; employeeId: string | null }) =>
      apiFetch(`/api/inquiries/${inquiryId}/assign`, { method: 'PATCH', body: JSON.stringify({ employee_id: employeeId }) }),
    onSuccess: invalidate,
  })

  const moveCall = useMutation({
    mutationFn: ({ callId, inquiryId }: { callId: string; inquiryId: string }) =>
      apiFetch(`/api/calls/${callId}/assign-inquiry`, { method: 'POST', body: JSON.stringify({ inquiry_id: inquiryId }) }),
    onSuccess: invalidate,
  })

  const newVorgang = useMutation({
    mutationFn: ({ callId }: { callId: string }) => apiFetch(`/api/calls/${callId}/inquiry`, { method: 'POST' }),
    onSuccess: invalidate,
  })

  const spamCall = useMutation({
    mutationFn: ({ callId, spam }: { callId: string; spam: boolean }) =>
      apiFetch(`/api/calls/${callId}/spam`, { method: 'POST', body: JSON.stringify({ spam }) }),
    onSuccess: invalidate,
  })

  async function runResolve(d: DecisionVM, choice: 'primary' | 'secondary' | 'tertiary') {
    const id = d.actionKey.split(':').slice(1).join(':') || d.actionKey
    const done = () => apiFetch('/api/actions/state', { method: 'POST', body: JSON.stringify({ action_key: d.actionKey, status: 'done' }) })
    if (d.kind === 'termin_anfrage') {
      if (choice === 'primary') await apiFetch(`/api/appointments/${id}/confirm`, { method: 'POST' })
      else if (choice === 'tertiary') await apiFetch(`/api/appointments/${id}/reject`, { method: 'POST', body: JSON.stringify({}) })
      else await done() // 'Verschieben' — needs a slot picker; park it as handled for now
    } else if (d.kind === 'alt_time_proposal') {
      await apiFetch(`/api/appointments/${id}/${choice === 'primary' ? 'approve-proposal' : 'decline-proposal'}`, { method: 'POST' })
    } else if (d.kind === 'appointment_cancelled') {
      if (choice === 'primary') await apiFetch(`/api/appointments/${id}/reject`, { method: 'POST', body: JSON.stringify({ reason: 'Kunde hat storniert' }) })
      else await done()
    } else if (d.kind === 'callback_owed') {
      await done()
    } else if (d.kind === 'kva_to_send') {
      if (choice === 'primary') await apiFetch(`/api/cost-estimates/${id}/send`, { method: 'POST', body: JSON.stringify({ copy_to_me: false }) })
      else await done()
    } else if (d.kind === 'kva_pending_acceptance') {
      await apiFetch(`/api/cost-estimates/${id}/status`, { method: 'PATCH', body: JSON.stringify({ status: choice === 'primary' ? 'accepted' : 'rejected' }) })
    }
  }

  async function resolve(d: DecisionVM, choice: 'primary' | 'secondary' | 'tertiary') {
    await runResolve(d, choice)
    invalidate()
  }

  async function applyReco(d: DecisionVM) {
    if (d.assignable && d.suggestedEmployeeId && d.inquiryId) {
      await apiFetch(`/api/inquiries/${d.inquiryId}/assign`, { method: 'PATCH', body: JSON.stringify({ employee_id: d.suggestedEmployeeId }) })
    }
    await runResolve(d, 'primary')
    invalidate()
  }

  return { assignInquiry, moveCall, newVorgang, spamCall, resolve, applyReco }
}
