// Real-data + actions layer for the Posteingang Fokus·Agenda. Maps the live API
// (/api/actions/pending, /api/calls, /api/inquiries/{id}/thread, /api/calls/{id})
// into the view-models the screen renders, and exposes the mutations that make
// every button functional. Replaces the mock-data module.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiFetch } from '../../lib/api'
import { relativeTimeDe } from '../../lib/datetime'

export type ActionKind =
  | 'termin_anfrage'
  | 'kva_suggested'
  | 'kva_to_send'
  | 'kva_pending_acceptance'
  | 'invoice_suggested'
  | 'invoice_to_send'
  | 'invoice_pending_payment'
  | 'callback_owed'
  | 'alt_time_proposal'
  | 'appointment_cancelled'
  | 'reschedule_unmatched'

export type DecisionType = 'termin' | 'rueckruf' | 'storno' | 'kva' | 'reschedule'
export type VStatus = 'open' | 'in_progress' | 'completed'
type TagVariant = 'info' | 'green' | 'error' | 'warning' | 'ai'

export interface RawAction {
  action_key: string
  kind: ActionKind
  id: string
  inquiry_id: string | null
  call_id: string | null
  customer_id: string | null
  customer_name: string | null
  summary: string
  priority: 'high' | 'normal'
  // When the action is time-bound (a proposed appointment / reschedule slot) the
  // backend carries the slot here as `due_at` — the single most important fact to
  // show before confirming. Null for document-lifecycle actions.
  due_at?: string | null
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
  // grouping = the Fall (case)
  case_id: string | null
  case_number: string | null
  case_label: string | null
  // optional top-layer Projekt (PR-) the case rolls up into — usually null
  project_id: string | null
  project_number: string | null
  project_title: string | null
  emergency_flag: boolean
  assigned_employee_id: string | null
  assigned_employee_initials: string | null
  read_at: string | null
  // The agent's collected fields — already returned by /api/calls (data_collection
  // is in the list select), so the inbox can show a real summary + next action with
  // NO extra fetch. Keys vary (ultimate_summary / issue_summary / next_action / …).
  data_collection: Record<string, string> | null
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
  // The originating call (when resolvable) — lets a decision drill into the call
  // summary/transcript/recording that produced it. Null for actions with no call
  // link (e.g. draft-Angebot reminders, missed-call callbacks).
  callId: string | null
  // Proposed appointment / reschedule slot (ISO) for time-bound decisions. Null otherwise.
  dueAt: string | null
  // Case context (point 2/6): the named Fall this decision belongs to, resolved
  // from the call's project_title / inquiry_subject so the card says WHICH case.
  caseName: string | null
  caseTicket: string | null
  // The case id — lets the inbox link the case chip to /cases?case=<id> so people
  // open the Vorgang without going via the calls page. Null for inquiry-less actions.
  caseId: string | null
  // A real summary of what the case is about + what's going on, taken from the
  // latest call's data_collection (LLM summary). Plus the agent's next action.
  // Both already in the calls list — no extra fetch. Null when no call/summary.
  contextSummary: string | null
  nextAction: string | null
  // Current assignee of the case — surfaced so assignment is its own visible
  // step on the card (point 1: assign ≠ confirm).
  assigneeId: string | null
  primary: string
  secondary: string | null
  tertiary: string | null
  assignable: boolean
  // Notification vs decision intent (Amber 2026-06-26). notify=true → the card
  // carries NO in-card business decision (KVA/Rechnung/Rückruf); it links onward.
  // opensDrawer → the card has an inline call detail to expand in the inbox
  // (appointment / suggestion) vs a notify card that just navigates via `route`.
  // cardCta → the single neutral button label on a notify card.
  notify: boolean
  opensDrawer: boolean
  cardCta: string
  // Where a notify card navigates / what the drawer's onward action opens: the
  // existing document (/cost-estimates/:id, /invoices/:id), the pre-filled
  // create-form (suggestions), or the caller (/customers/:id). Null when there is
  // nowhere to go (pure info). Appointment kinds keep route null (they POST).
  route: string | null
}

export interface CallEntry {
  id: string
  dir: 'inbound' | 'outbound'
  title: string
  time: string
  ts: number
}
export interface VorgangVM {
  key: string
  inquiryId: string
  callEntries: CallEntry[]
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

// Intent split (Amber 2026-06-26): ONLY appointment kinds are actionable on the
// card (confirm/reschedule/cancel — a scheduling decision). KVA/Rechnung and
// Rückruf are NOTIFICATION-only: they carry NO direct business decision (no
// send/accept/mark-paid). A notification either deep-links to the existing
// document, or — when no document exists yet (a call-derived suggestion) — opens
// the call-transcript drawer where the "create" action lives.
//   notify      = no in-card decision; it's a "go check" reminder
//   opensDrawer = the card has an inline call detail to expand (appointment /
//                 suggestion); a plain notify card just navigates via route
//   cardCta     = the single neutral button label shown on a notify card
const KIND_CFG: Record<
  ActionKind,
  { type: DecisionType; accent: string; label: string; variant: TagVariant; title: (a: RawAction) => string; primary: string; secondary: string | null; tertiary: string | null; reco: (name: string, cust: string) => string; assignable: boolean; notify: boolean; opensDrawer: boolean; cardCta: string }
> = {
  // ── Appointment lifecycle — ACTIONABLE (decision drawer) ──────────────────
  termin_anfrage: { type: 'termin', accent: 'var(--info)', label: 'Termin', variant: 'info', title: () => 'Termin bestätigen?', primary: 'Bestätigen', secondary: 'Verschieben', tertiary: 'Ablehnen', reco: (n) => `${n} zuweisen und Termin bestätigen`, assignable: true, notify: false, opensDrawer: true, cardCta: '' },
  alt_time_proposal: { type: 'reschedule', accent: 'var(--warning)', label: 'Verschieben', variant: 'warning', title: () => 'Neuen Termin annehmen?', primary: 'Annehmen', secondary: null, tertiary: 'Ablehnen', reco: () => 'Vorgeschlagenen Termin annehmen', assignable: false, notify: false, opensDrawer: true, cardCta: '' },
  appointment_cancelled: { type: 'storno', accent: 'var(--error)', label: 'Storno', variant: 'error', title: () => 'Termin storniert', primary: 'Verstanden', secondary: null, tertiary: 'Behalten', reco: () => 'Termin stornieren und Slot freigeben', assignable: false, notify: false, opensDrawer: true, cardCta: '' },
  reschedule_unmatched: { type: 'reschedule', accent: 'var(--warning)', label: 'Zuordnen', variant: 'warning', title: () => 'Terminänderung zuordnen', primary: 'Zuordnen', secondary: null, tertiary: 'Erledigt', reco: () => 'Terminänderung manuell einem Termin zuordnen', assignable: false, notify: false, opensDrawer: true, cardCta: '' },

  // ── KVA / Rechnung — NOTIFICATION only (no in-card decision) ──────────────
  // Suggestions have no document yet → expand the call inline (the "create"
  // action lives there). primary = the onward action.
  kva_suggested: { type: 'kva', accent: 'var(--ai)', label: 'Angebot', variant: 'ai', title: () => 'Angebot angefragt', primary: 'Angebot erstellen', secondary: null, tertiary: null, reco: (_n, c) => `Im Anruf erwähnt — Angebot für ${c} prüfen und ggf. erstellen`, assignable: false, notify: true, opensDrawer: true, cardCta: 'Angebot erstellen' },
  invoice_suggested: { type: 'kva', accent: 'var(--ai)', label: 'Rechnung', variant: 'ai', title: () => 'Rechnung angefragt', primary: 'Rechnung erstellen', secondary: null, tertiary: null, reco: (_n, c) => `Im Anruf erwähnt — Rechnung für ${c} prüfen und ggf. erstellen`, assignable: false, notify: true, opensDrawer: true, cardCta: 'Rechnung erstellen' },
  // Existing documents → deep-link to the document (decision happens there).
  kva_to_send: { type: 'kva', accent: 'var(--ai)', label: 'Angebot', variant: 'ai', title: () => 'Angebot bereit — prüfen', primary: 'Angebot prüfen', secondary: null, tertiary: null, reco: (_n, c) => `Angebot für ${c} im Bereich Angebote prüfen`, assignable: false, notify: true, opensDrawer: false, cardCta: 'Angebot prüfen' },
  kva_pending_acceptance: { type: 'kva', accent: 'var(--ai)', label: 'Angebot', variant: 'ai', title: () => 'Angebot — Antwort prüfen', primary: 'Angebot prüfen', secondary: null, tertiary: null, reco: (_n, c) => `Kundenantwort zum Angebot für ${c} prüfen`, assignable: false, notify: true, opensDrawer: false, cardCta: 'Angebot prüfen' },
  invoice_to_send: { type: 'kva', accent: 'var(--ai)', label: 'Rechnung', variant: 'ai', title: () => 'Rechnung bereit — prüfen', primary: 'Rechnung prüfen', secondary: null, tertiary: null, reco: (_n, c) => `Rechnung für ${c} im Bereich Rechnungen prüfen`, assignable: false, notify: true, opensDrawer: false, cardCta: 'Rechnung prüfen' },
  invoice_pending_payment: { type: 'kva', accent: 'var(--warning)', label: 'Zahlung', variant: 'warning', title: () => 'Zahlung prüfen', primary: 'Rechnung prüfen', secondary: null, tertiary: null, reco: (_n, c) => `Zahlungseingang für ${c} prüfen`, assignable: false, notify: true, opensDrawer: false, cardCta: 'Rechnung prüfen' },

  // ── Rückruf — NOTIFICATION only (links to the caller) ─────────────────────
  callback_owed: { type: 'rueckruf', accent: 'var(--green-primary)', label: 'Rückruf', variant: 'green', title: () => 'Rückruf offen', primary: 'Anrufer ansehen', secondary: null, tertiary: null, reco: () => 'Verpasster Anruf — Kunde ansehen und zurückrufen', assignable: false, notify: true, opensDrawer: false, cardCta: 'Anrufer ansehen' },
}

function pickSuggested(employees: Employee[]): Employee | null {
  return (
    employees.find((e) => e.is_active !== false && !e.is_absent && e.is_technician) ??
    employees.find((e) => e.is_active !== false && !e.is_absent) ??
    employees[0] ??
    null
  )
}

// Per-inquiry context, derived from the calls list: the Fall's display name +
// ticket + current assignee. Lets each decision card name its case and show who
// it's assigned to (the latest call per inquiry wins).
interface InquiryMeta {
  caseName: string | null
  caseTicket: string | null
  caseId: string | null
  assigneeId: string | null
  contextSummary: string | null
  nextAction: string | null
}
// The agent's summaries are lightly markdown-formatted (** , "- " bullets,
// newlines) — flatten to clean prose for an inline 1-3 line card.
function cleanText(s: string): string {
  return s
    .replace(/\*\*/g, '')
    .replace(/^\s*[-*]\s+/gm, '')
    .replace(/\s*\n+\s*/g, ' · ')
    .replace(/\s{2,}/g, ' ')
    .trim()
}
// The agent stores its summary under varying keys depending on flow. Prefer the
// concise issue_summary for an inline card, then the fuller ultimate_summary,
// then the call's short title.
function callSummary(c: RawCall): string | null {
  const dc = c.data_collection ?? {}
  const raw = dc.issue_summary || dc.ultimate_summary || dc.call_summary || dc.summary || c.summary_title || null
  return raw ? cleanText(raw) : null
}
function buildInquiryMeta(calls: RawCall[]): Map<string, InquiryMeta> {
  const meta = new Map<string, InquiryMeta>()
  const seenTs = new Map<string, number>()
  for (const c of calls) {
    if (!c.inquiry_id) continue
    const t = ts(c.started_at || c.created_at)
    if (meta.has(c.inquiry_id) && t <= (seenTs.get(c.inquiry_id) ?? 0)) continue
    seenTs.set(c.inquiry_id, t)
    const isCase = !!c.case_id
    const dc = c.data_collection ?? {}
    meta.set(c.inquiry_id, {
      caseName: (isCase ? c.case_label : c.inquiry_subject) || c.summary_title || null,
      caseTicket: (isCase ? c.case_number : c.inquiry_number) || null,
      caseId: c.case_id,
      assigneeId: c.assigned_employee_id,
      contextSummary: callSummary(c),
      nextAction: dc.next_action || dc.next_step || null,
    })
  }
  return meta
}

export function buildDecisions(actions: RawAction[], employees: Employee[], meta: Map<string, InquiryMeta>, callsById?: Map<string, RawCall>): DecisionVM[] {
  const suggested = pickSuggested(employees)
  return actions.map((a) => {
    const cfg = KIND_CFG[a.kind]
    const cust = a.customer_name || 'Unbekannter Kunde'
    const name = firstName(suggested?.display_name)
    const info = a.inquiry_id ? meta.get(a.inquiry_id) : undefined
    // Summary/next-action straight from the action's OWN call (most reliable),
    // then the inquiry's latest call, then the terse backend action summary.
    const ownCall = a.call_id ? callsById?.get(a.call_id) : undefined
    const contextSummary =
      (ownCall ? callSummary(ownCall) : null) ?? info?.contextSummary ?? a.summary ?? null
    const nextAction =
      ownCall?.data_collection?.next_action || ownCall?.data_collection?.next_step || info?.nextAction || null
    // Case/Vorgang context — from the inquiry meta, else the action's own call.
    const caseName =
      info?.caseName ??
      (ownCall ? (ownCall.case_id ? ownCall.case_label : ownCall.inquiry_subject) : null) ??
      null
    const caseTicket =
      info?.caseTicket ??
      (ownCall ? (ownCall.case_id ? ownCall.case_number : ownCall.inquiry_number) : null) ??
      null
    const caseId = info?.caseId ?? ownCall?.case_id ?? null
    // Navigation target per intent: suggestions → pre-filled create-form (opened
    // from the transcript drawer); existing KVA/Rechnung → the document detail;
    // Rückruf → the caller. Appointment kinds keep route null (they POST a decision).
    const route =
      a.kind === 'kva_suggested'
        ? `/cost-estimates/new?customer_id=${a.customer_id ?? ''}` +
          (a.inquiry_id ? `&inquiry_id=${a.inquiry_id}` : '') +
          (a.call_id ? `&call_id=${a.call_id}` : '')
        : a.kind === 'invoice_suggested'
          ? `/invoices/new?customer_id=${a.customer_id ?? ''}` + (a.call_id ? `&call_id=${a.call_id}` : '')
          : a.kind === 'kva_to_send' || a.kind === 'kva_pending_acceptance'
            ? `/cost-estimates/${a.id}`
            : a.kind === 'invoice_to_send' || a.kind === 'invoice_pending_payment'
              ? `/invoices/${a.id}`
              : a.kind === 'callback_owed'
                ? (a.customer_id ? `/customers/${a.customer_id}` : null)
                : null
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
      callId: a.call_id,
      dueAt: a.due_at ?? null,
      caseName,
      caseTicket,
      caseId,
      contextSummary,
      nextAction,
      assigneeId: info?.assigneeId ?? null,
      primary: cfg.primary,
      secondary: cfg.secondary,
      tertiary: cfg.tertiary,
      assignable: cfg.assignable,
      notify: cfg.notify,
      opensDrawer: cfg.opensDrawer,
      cardCta: cfg.cardCta,
      route,
    }
  })
}

function buildVorgaenge(calls: RawCall[], actions: RawAction[]): VorgangVM[] {
  const decByInquiry = new Map<string, string>()
  for (const a of actions) if (a.inquiry_id && !decByInquiry.has(a.inquiry_id)) decByInquiry.set(a.inquiry_id, KIND_CFG[a.kind].label)

  // Bundle by TICKET = the case (the AI grouping lives on case_id). Calls with no
  // inquiry are dropped here — triage of unsorted calls now lives in the Anrufe
  // cockpit, not the inbox.
  const byTicket = new Map<string, RawCall[]>()
  for (const c of calls) {
    if (!c.inquiry_id) continue
    const key = c.case_id ?? c.inquiry_id
    const arr = byTicket.get(key) ?? []
    arr.push(c)
    byTicket.set(key, arr)
  }

  const vorgaenge: VorgangVM[] = []
  for (const [key, group] of byTicket) {
    const sorted = [...group].sort((a, b) => ts(b.started_at) - ts(a.started_at))
    const latest = sorted[0]
    const isCase = !!latest.case_id
    const decision = group.map((c) => (c.inquiry_id ? decByInquiry.get(c.inquiry_id) : null)).find(Boolean) || null
    vorgaenge.push({
      key,
      inquiryId: latest.inquiry_id as string,
      callEntries: [...group]
        .sort((a, b) => ts(a.started_at) - ts(b.started_at))
        .map((c) => ({ id: c.id, dir: c.direction === 'outbound' ? 'outbound' : 'inbound', title: c.summary_title || 'Anruf', time: rel(c.started_at || c.created_at), ts: ts(c.started_at) })),
      custId: latest.customer_id,
      customer: latest.customers?.full_name || latest.caller_number || 'Unbekannt',
      problem: (isCase ? latest.case_label : latest.inquiry_subject) || latest.summary_title || 'Vorgang',
      ticket: isCase ? latest.case_number : latest.inquiry_number,
      calls: group.length,
      activity: rel(latest.started_at || latest.created_at),
      status: latest.inquiry_status,
      assigneeId: latest.assigned_employee_id,
      assigneeInitials: latest.assigned_employee_initials,
      emergency: group.some((c) => c.emergency_flag),
      decision,
      project: latest.project_title ?? null,
    })
  }
  // Emergencies first, then bundled (multi-call) tickets, then those needing a decision.
  vorgaenge.sort((a, b) => {
    if (a.emergency !== b.emergency) return a.emergency ? -1 : 1
    if (a.calls > 1 !== b.calls > 1) return a.calls > 1 ? -1 : 1
    if (!!a.decision !== !!b.decision) return a.decision ? -1 : 1
    return (b.callEntries.at(-1)?.ts ?? 0) - (a.callEntries.at(-1)?.ts ?? 0)
  })
  return vorgaenge
}

// ── Queries ─────────────────────────────────────────────────────────────────
export function useEmployees() {
  return useQuery({ queryKey: ['pe', 'employees'], queryFn: () => apiFetch<Employee[]>('/api/employees'), staleTime: 60_000 })
}

export function usePosteingang() {
  const employeesQ = useEmployees()
  // Decisions render from /api/actions/pending alone; the heavy /api/calls fetch
  // only enriches each card with its Fall name/ticket, so it must NOT gate the
  // loading state (that was the dashboard "cards take time to load" lag).
  // staleTime keeps revisits instant (served from cache, refetched in the bg).
  const actionsQ = useQuery({ queryKey: ['pe', 'actions'], queryFn: () => apiFetch<RawAction[]>('/api/actions/pending'), refetchInterval: 30_000, staleTime: 15_000 })
  const callsQ = useQuery({ queryKey: ['pe', 'calls'], queryFn: () => apiFetch<{ calls: RawCall[] }>('/api/calls?limit=200'), staleTime: 60_000 })

  const employees = employeesQ.data ?? []
  const actions = (actionsQ.data ?? []).filter((a) => a.kind in KIND_CFG)
  const calls = callsQ.data?.calls ?? []
  const callsById = new Map(calls.map((c) => [c.id, c]))
  const decisions = buildDecisions(actions, employees, buildInquiryMeta(calls), callsById)
  const vorgaenge = buildVorgaenge(calls, actions)

  return {
    loading: actionsQ.isLoading,
    error: actionsQ.isError || callsQ.isError,
    employees,
    decisions,
    vorgaenge,
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
    items.push({ kind: 'kva', label: 'Angebot', detail: k.total != null ? `${k.total} €` : '', done, doneLabel: k.status === 'accepted' ? 'Angenommen' : 'Gesendet', time: rel(k.sent_at || k.created_at), ts: ts(k.sent_at || k.created_at) })
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

  async function runResolve(d: DecisionVM, choice: 'primary' | 'secondary' | 'tertiary') {
    const id = d.actionKey.split(':').slice(1).join(':') || d.actionKey
    const done = () => apiFetch('/api/actions/state', { method: 'POST', body: JSON.stringify({ action_key: d.actionKey, status: 'done' }) })
    // ONLY appointment kinds resolve via a POST decision here. KVA/Rechnung and
    // Rückruf are notification-only — their card buttons navigate (d.route) and
    // never reach runResolve, so there is no send/accept/mark-paid path on the
    // dashboard (the decision is made in the document's own page).
    if (d.kind === 'termin_anfrage') {
      if (choice === 'primary') await apiFetch(`/api/appointments/${id}/confirm`, { method: 'POST' })
      else if (choice === 'tertiary') await apiFetch(`/api/appointments/${id}/reject`, { method: 'POST', body: JSON.stringify({}) })
      else await done() // 'Verschieben' — needs a slot picker; park it as handled for now
    } else if (d.kind === 'alt_time_proposal') {
      await apiFetch(`/api/appointments/${id}/${choice === 'primary' ? 'approve-proposal' : 'decline-proposal'}`, { method: 'POST' })
    } else if (d.kind === 'appointment_cancelled') {
      // Informational card: the cancellation already happened (status='cancelled').
      // 'Verstanden' just acknowledges it — DON'T POST /reject (requires
      // status='pending' → always 409; would also double-fire a customer cancel).
      await done()
    } else if (d.kind === 'reschedule_unmatched') {
      await done()
    }
  }

  async function resolve(d: DecisionVM, choice: 'primary' | 'secondary' | 'tertiary') {
    await runResolve(d, choice)
    invalidate()
  }

  return { assignInquiry, resolve }
}
