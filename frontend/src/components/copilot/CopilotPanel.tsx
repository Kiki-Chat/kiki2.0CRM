import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, History, Loader2, Plus, Send, Sparkles, Trash2, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import kikiAvatar from '../../assets/kiki-avatar.png'
import { apiFetch } from '../../lib/api'
import {
  LIVE_FILL_EVENT,
  clearLiveFill,
  requestLiveFill,
  type LiveFillPayload,
  type LiveFillStatus,
} from '../../lib/liveFill'
import { useMe } from '../../lib/useMe'
import { cn } from '../../lib/utils'

/**
 * Hey Kiki — the CRM assistant as a DOCKED side panel (Gemini-in-Docs style).
 * Opened from the Topbar "Hey Kiki" button; on desktop it shares the screen
 * with the CRM (flex sibling — the page reflows next to it), on small screens
 * it overlays from the right. Replaces the old floating bubble (CopilotWidget).
 *
 * Talks to POST /api/copilot/chat:
 *  - reads are answered inline,
 *  - writes come back as proposed actions → Bestätigen runs /api/copilot/confirm,
 *    then the panel makes the change VISIBLE live: it invalidates all queries
 *    (the open page refreshes in place) and navigates to the created object
 *    (new invoice/KVA/customer/appointment) so the user watches it appear,
 *  - client actions (navigate_to) jump straight to the requested page.
 */

interface ProposedAction {
  tool: string
  args: Record<string, unknown>
  kind: string
  description: string
}
interface ClientAction {
  tool: string
  args: Record<string, string>
}
interface ChatResponse {
  content: string
  actions: ProposedAction[]
  client_actions: ClientAction[]
  conversation_id?: string | null
}
interface ConversationRow {
  id: string
  title: string | null
  updated_at: string
}
interface StoredMessage {
  id: string
  role: 'user' | 'assistant'
  content: string | null
  actions: { actions?: ProposedAction[] } | null
}
type ActionStatus = 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
type ActionState = ProposedAction & { status: ActionStatus; note?: string }
interface Msg {
  id: string
  role: 'user' | 'kiki'
  content: string
  actions?: ActionState[]
  /** Short system-style lines under the bubble, e.g. "→ Seite geöffnet". */
  steps?: string[]
}

let _seq = 0
const uid = () => `m${Date.now()}_${_seq++}`

/** Strip simple markdown emphasis so plain bubbles read cleanly. */
const clean = (s: string) => s.replace(/\*\*(.+?)\*\*/g, '$1')

const SUGGESTIONS = [
  'Wie viele offene Aufgaben habe ich?',
  'Bring mich zu den Anrufen',
  'Erstelle eine Rechnung',
  'Lege einen Termin an',
]

function actionSummary(a: ProposedAction): string {
  const s = (k: string) => String(a.args[k] ?? '')
  switch (a.tool) {
    case 'create_customer':
      return `Neuen Kontakt anlegen: ${s('name')}`
    case 'update_customer':
      return 'Kontaktdaten ändern'
    case 'create_inquiry':
      return `Anfrage anlegen: ${s('title')}`
    case 'set_inquiry_status':
      return `Anfrage-Status → ${s('status')}`
    case 'create_appointment': {
      const at = s('scheduled_at').replace('T', ' ').slice(0, 16)
      return `Termin anlegen${a.args.title ? ': ' + s('title') : ''}${at ? ' (' + at + ')' : ''}`
    }
    case 'update_appointment': {
      const at = s('scheduled_at').replace('T', ' ').slice(0, 16)
      return `Termin ändern${at ? ' → ' + at : ''}`
    }
    case 'create_cost_estimate':
      return `Kostenvoranschlag erstellen${a.args.subject ? ': ' + s('subject') : ''}`
    case 'create_invoice':
      return `Rechnung erstellen${a.args.subject ? ': ' + s('subject') : ''}`
    case 'report_problem':
      return `Problem melden: ${s('summary')}`
    case 'update_org_profile':
      return 'Stammdaten ändern'
    default:
      return a.description || a.tool
  }
}

/** Where to take the user after a confirmed write, so they SEE the result. */
function resultRoute(tool: string, result: Record<string, unknown>): { route: string; label: string } | null {
  const obj = (k: string) => (result?.[k] && typeof result[k] === 'object' ? (result[k] as Record<string, unknown>) : null)
  const inv = obj('invoice')
  if (tool === 'create_invoice' && inv?.id) return { route: `/invoices/${inv.id}`, label: `Rechnung ${inv.number ?? ''} geöffnet` }
  const ce = obj('cost_estimate')
  if (tool === 'create_cost_estimate' && ce?.id) return { route: `/cost-estimates/${ce.id}`, label: `KVA ${ce.number ?? ''} geöffnet` }
  const cust = obj('customer')
  if ((tool === 'create_customer' || tool === 'update_customer') && cust?.id)
    return { route: `/customers/${cust.id}`, label: 'Kontakt geöffnet' }
  const appt = obj('appointment')
  if ((tool === 'create_appointment' || tool === 'update_appointment') && appt?.id) {
    const date = typeof appt.scheduled_at === 'string' ? appt.scheduled_at.slice(0, 10) : ''
    return { route: `/calendar${date ? `?date=${date}&appointment=${appt.id}` : ''}`, label: 'Termin im Kalender geöffnet' }
  }
  const proj = obj('project')
  if (tool === 'create_project' && proj?.id) return { route: `/projects/${proj.id}`, label: 'Projekt geöffnet' }
  return null
}

export function CopilotPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { me, isLoading: meLoading } = useMe()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Server-side chat session: every turn is persisted; previous chats reopen
  // from the history view.
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [view, setView] = useState<'chat' | 'history'>('chat')
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const { data: historyData, refetch: refetchHistory } = useQuery({
    queryKey: ['copilot', 'conversations'],
    queryFn: () => apiFetch<{ conversations: ConversationRow[] }>('/api/copilot/conversations'),
    enabled: open && view === 'history',
  })

  const openConversation = async (id: string) => {
    try {
      const res = await apiFetch<{ conversation: { id: string }; messages: StoredMessage[] }>(
        `/api/copilot/conversations/${id}`,
      )
      setConversationId(res.conversation.id)
      setMessages(
        res.messages.map((m) => ({
          id: m.id,
          role: m.role === 'assistant' ? ('kiki' as const) : ('user' as const),
          content: m.content || '',
          // Historical action cards are display-only — confirming would replay
          // a stale write; the user re-asks if it's still needed.
          actions: m.actions?.actions?.length
            ? m.actions.actions.map((a) => ({
                ...a,
                status: 'cancelled' as const,
                note: 'Aus früherem Chat — bei Bedarf erneut anfordern.',
              }))
            : undefined,
        })),
      )
      setView('chat')
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Chat konnte nicht geladen werden.')
    }
  }

  const deleteConversation = async (id: string) => {
    try {
      await apiFetch(`/api/copilot/conversations/${id}`, { method: 'DELETE' })
      if (id === conversationId) newChat()
      void refetchHistory()
    } catch {
      /* best-effort */
    }
  }

  const greeting = (): Msg => {
    const company = me?.org_name?.trim() || ''
    return {
      id: uid(),
      role: 'kiki',
      content: `Hallo${company ? ' ' + company : ''}! Ich bin Kiki. Frag mich etwas, lass mich dich irgendwohin bringen („Bring mich zu …“) oder etwas anlegen — z. B. eine Rechnung, einen Termin oder einen Kontakt. Änderungen führe ich erst nach deiner Bestätigung aus, und du siehst sie sofort auf dem Bildschirm.`,
    }
  }

  useEffect(() => {
    if (open && messages.length === 0 && !meLoading) setMessages([greeting()])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, messages.length, me, meLoading])

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, loading])

  const newChat = () => {
    setMessages([greeting()])
    setInput('')
    setError(null)
    setConversationId(null)
    setView('chat')
  }

  const updateAction = (msgId: string, idx: number, status: ActionStatus, note?: string) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === msgId && m.actions
          ? { ...m, actions: m.actions.map((a, i) => (i === idx ? { ...a, status, note } : a)) }
          : m,
      ),
    )
  }
  const appendStep = (msgId: string, step: string) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === msgId ? { ...m, steps: [...(m.steps ?? []), step] } : m)),
    )
  }

  const send = async (preset?: string) => {
    const text = (preset ?? input).trim()
    if (!text || loading) return
    const history = messages
      .filter((m) => m.content)
      .map((m) => ({ role: m.role === 'kiki' ? 'assistant' : 'user', content: m.content }))
    setMessages((prev) => [...prev, { id: uid(), role: 'user', content: text }])
    setInput('')
    setError(null)
    setLoading(true)
    try {
      const res = await apiFetch<ChatResponse>('/api/copilot/chat', {
        method: 'POST',
        body: JSON.stringify({ message: text, history, conversation_id: conversationId }),
      })
      if (res.conversation_id) setConversationId(res.conversation_id)
      const msgId = uid()
      const actions = res.actions?.length
        ? res.actions.map((a) => ({ ...a, status: 'pending' as const }))
        : undefined
      setMessages((prev) => [...prev, { id: msgId, role: 'kiki', content: res.content, actions }])
      for (const ca of res.client_actions || []) {
        if (ca.tool === 'navigate_to' && typeof ca.args.route === 'string') {
          navigate(ca.args.route)
          appendStep(msgId, `→ Seite geöffnet: ${ca.args.route}`)
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Es ist ein Fehler aufgetreten.')
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  // Form-backed creates get the "takeover" treatment: navigate to the real
  // form and let it fill itself live (see lib/liveFill.ts). Falls back to the
  // direct API path when the live fill fails or never reports back.
  const LIVE_FILL_TOOLS: Record<string, string> = {
    create_invoice: '/invoices/new',
    create_cost_estimate: '/cost-estimates/new',
    create_appointment: '/calendar',
  }

  // Everything else acts "in sight": Kiki first opens the page where the change
  // will land, THEN executes — the result appears in front of the user (the
  // affected queries refetch; creates additionally jump to the new object).
  const WATCH_ROUTES: Record<string, string> = {
    update_appointment: '/calendar',
    create_customer: '/customers',
    update_customer: '/customers',
    create_inquiry: '/calls',
    set_inquiry_status: '/calls',
    update_org_profile: '/settings/stammdaten',
    create_employee: '/employees',
    create_project: '/projects',
  }

  // Refresh only the queries a tool actually touches — a blanket invalidate
  // reloads every open page at once, which reads as flicker mid-conversation.
  const QUERY_KEYS_BY_TOOL: Record<string, string[][]> = {
    create_invoice: [['invoices'], ['dashboard']],
    create_cost_estimate: [['cost-estimates'], ['dashboard']],
    create_appointment: [['appointments'], ['pendingAppointment'], ['actions', 'pending'], ['dashboard']],
    update_appointment: [['appointments'], ['pendingAppointment'], ['actions', 'pending'], ['dashboard']],
    create_customer: [['customers'], ['customers-options']],
    update_customer: [['customers'], ['customers-options'], ['customer']],
    create_inquiry: [['calls'], ['actions', 'pending'], ['dashboard']],
    set_inquiry_status: [['calls'], ['actions', 'pending'], ['dashboard']],
    update_org_profile: [['settings'], ['me']],
    create_employee: [['employees'], ['employees-full']],
    create_project: [['projects']],
  }
  const refreshAfter = (tool: string) => {
    const keys = QUERY_KEYS_BY_TOOL[tool]
    if (!keys) {
      void qc.invalidateQueries()
      return
    }
    for (const k of keys) void qc.invalidateQueries({ queryKey: k })
  }

  const confirmLive = (msgId: string, idx: number, action: ActionState, route: string) => {
    updateAction(msgId, idx, 'running', 'Kiki öffnet das Formular und füllt es live aus…')
    requestLiveFill({ tool: action.tool, args: action.args } as LiveFillPayload)
    appendStep(msgId, `→ Formular geöffnet: ${route}`)
    navigate(route)

    let settled = false
    const onStatus = (e: Event) => {
      const detail = (e as CustomEvent<LiveFillStatus>).detail
      if (!detail || detail.tool !== action.tool || settled) return
      if (detail.status === 'started') {
        // The form took over — cancel the fallback so the write can never run
        // TWICE (script still animating past 60s used to double-execute it).
        // The script always settles with done/failed from here on.
        clearTimeout(timeout)
        return
      }
      settled = true
      window.removeEventListener(LIVE_FILL_EVENT, onStatus)
      clearTimeout(timeout)
      if (detail.status === 'done') {
        updateAction(msgId, idx, 'done', 'Erledigt ✓')
        appendStep(msgId, `→ ${detail.note || 'Live ausgefüllt & gespeichert'}`)
        refreshAfter(action.tool)
      } else {
        // Live fill failed → run the regular API path so the action still lands.
        appendStep(msgId, `→ Live-Ausfüllen nicht möglich (${detail.note || 'Fehler'}) — führe direkt aus…`)
        void confirmViaApi(msgId, idx, action)
      }
    }
    const timeout = setTimeout(() => {
      if (settled) return
      settled = true
      window.removeEventListener(LIVE_FILL_EVENT, onStatus)
      // The form never picked the request up — withdraw it BEFORE the direct
      // write, or a later-mounting form would consume the stale payload and
      // create the document a second time.
      clearLiveFill()
      void confirmViaApi(msgId, idx, action)
    }, 60_000)
    window.addEventListener(LIVE_FILL_EVENT, onStatus)
  }

  const confirmAction = (msgId: string, idx: number, action: ActionState) => {
    setError(null)
    const liveRoute = LIVE_FILL_TOOLS[action.tool]
    if (liveRoute) {
      confirmLive(msgId, idx, action, liveRoute)
      return
    }
    const watchRoute = WATCH_ROUTES[action.tool]
    if (watchRoute && !location.pathname.startsWith(watchRoute)) {
      navigate(watchRoute)
      appendStep(msgId, `→ Seite geöffnet: ${watchRoute}`)
    }
    void confirmViaApi(msgId, idx, action)
  }

  const confirmViaApi = async (msgId: string, idx: number, action: ActionState) => {
    updateAction(msgId, idx, 'running', 'Wird ausgeführt…')
    try {
      const res = await apiFetch<{ ok: boolean; result: Record<string, unknown> }>(
        '/api/copilot/confirm',
        {
          method: 'POST',
          // conversation_id links the executed write to this chat in the audit
          // trail (the 0042 column was never populated — audit 2026-06-11).
          body: JSON.stringify({
            tool: action.tool,
            args: action.args,
            conversation_id: conversationId,
          }),
        },
      )
      const errMsg = res.result && typeof res.result.error === 'string' ? res.result.error : null
      const ok = res.ok && !errMsg
      if (!ok) {
        updateAction(msgId, idx, 'failed', errMsg || 'Fehlgeschlagen')
        return
      }
      updateAction(msgId, idx, 'done', 'Erledigt ✓')
      // Make the change VISIBLE live: refresh the affected queries (the open
      // page updates in place) and jump to the created object when we know
      // where it lives.
      refreshAfter(action.tool)
      const target = resultRoute(action.tool, res.result || {})
      if (target) {
        navigate(target.route)
        appendStep(msgId, `→ ${target.label}`)
      }
    } catch (e) {
      updateAction(msgId, idx, 'failed', e instanceof Error ? e.message : 'Fehlgeschlagen')
    }
  }

  if (!open) return null

  return (
    <aside
      className={cn(
        // Mobile/tablet: overlay from the right. Desktop (lg+): docked flex
        // sibling — the CRM content reflows next to it (Gemini-style).
        'fixed inset-y-0 right-0 z-50 flex w-full max-w-[420px] flex-col border-l border-border bg-surface shadow-2xl',
        'lg:static lg:z-auto lg:w-[400px] lg:max-w-none lg:shrink-0 lg:shadow-none',
        'print:hidden',
      )}
      aria-label="Hey Kiki Assistent"
    >
      {/* Header */}
      <div className="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-sidebar px-4">
        <img src={kikiAvatar} alt="Kiki" className="h-8 w-8 rounded-full bg-white object-cover ring-1 ring-border" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-sm font-bold text-text">
            Hey Kiki <Sparkles size={13} className="text-ai" />
          </div>
          <div className="text-[11px] text-muted">Dein CRM-Assistent</div>
        </div>
        <button
          onClick={() => setView((v) => (v === 'history' ? 'chat' : 'history'))}
          className={cn(
            'rounded-lg p-1.5 transition hover:bg-alt hover:text-text',
            view === 'history' ? 'bg-ai-bg text-ai' : 'text-muted',
          )}
          aria-label="Frühere Chats"
          title="Frühere Chats"
        >
          <History size={18} />
        </button>
        <button
          onClick={newChat}
          className="rounded-lg p-1.5 text-muted transition hover:bg-alt hover:text-text"
          aria-label="Neuer Chat"
          title="Neuer Chat"
        >
          <Plus className="h-4.5 w-4.5" size={18} />
        </button>
        <button
          onClick={onClose}
          className="rounded-lg p-1.5 text-muted transition hover:bg-alt hover:text-text"
          aria-label="Schließen"
          title="Schließen"
        >
          <X size={18} />
        </button>
      </div>

      {/* History view */}
      {view === 'history' && (
        <div className="flex-1 space-y-1.5 overflow-y-auto px-3 py-4">
          <div className="mb-2 px-1 text-xs font-bold uppercase tracking-wide text-muted">Frühere Chats</div>
          {(historyData?.conversations ?? []).length === 0 && (
            <p className="px-1 text-sm text-faint">Noch keine gespeicherten Chats.</p>
          )}
          {(historyData?.conversations ?? []).map((c) => (
            <div
              key={c.id}
              className={cn(
                'group flex items-center gap-2 rounded-lg border border-border px-3 py-2 transition hover:bg-alt',
                c.id === conversationId && 'border-ai/40 bg-ai-bg/40',
              )}
            >
              <button onClick={() => void openConversation(c.id)} className="min-w-0 flex-1 text-left">
                <div className="truncate text-sm font-medium text-text">{c.title || 'Chat'}</div>
                <div className="text-[11px] text-muted">
                  {new Date(c.updated_at).toLocaleString('de-DE', {
                    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
                    timeZone: 'Europe/Berlin',
                  })}
                </div>
              </button>
              <button
                onClick={() => void deleteConversation(c.id)}
                title="Chat löschen"
                className="rounded p-1 text-muted opacity-0 transition hover:text-error group-hover:opacity-100"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Thread */}
      <div ref={scrollRef} className={cn('flex-1 space-y-3 overflow-y-auto px-3 py-4', view !== 'chat' && 'hidden')}>
        {messages.map((m) =>
          m.role === 'user' ? (
            <div key={m.id} className="flex justify-end">
              <div className="max-w-[88%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-green-primary px-3 py-2 text-sm text-white">
                {m.content}
              </div>
            </div>
          ) : (
            <div key={m.id} className="flex gap-2">
              <img src={kikiAvatar} alt="" className="mt-0.5 h-6 w-6 shrink-0 rounded-full bg-white object-cover" />
              <div className="min-w-0 max-w-[88%] flex-1 space-y-2">
                {m.content && (
                  <div className="whitespace-pre-wrap rounded-2xl rounded-tl-sm bg-alt px-3 py-2 text-sm text-text">
                    {clean(m.content)}
                  </div>
                )}
                {m.actions?.map((a, i) => (
                  <div key={i} className="rounded-xl border border-border bg-surface p-3 shadow-e1">
                    <div className="flex items-start gap-2">
                      {a.status === 'done' ? (
                        <CheckCircle2 size={15} className="mt-0.5 shrink-0 text-success" />
                      ) : a.status === 'running' ? (
                        <Loader2 size={15} className="mt-0.5 shrink-0 animate-spin text-ai" />
                      ) : (
                        <Sparkles size={15} className="mt-0.5 shrink-0 text-ai" />
                      )}
                      <div className="text-xs font-medium text-text">{actionSummary(a)}</div>
                    </div>
                    {a.status === 'pending' ? (
                      <div className="mt-2 flex gap-2">
                        <button
                          onClick={() => confirmAction(m.id, i, a)}
                          className="rounded-lg bg-green-primary px-3 py-1.5 text-xs font-medium text-white transition hover:brightness-110"
                        >
                          Bestätigen
                        </button>
                        <button
                          onClick={() => updateAction(m.id, i, 'cancelled', 'Abgebrochen')}
                          className="rounded-lg border border-border px-3 py-1.5 text-xs text-body transition hover:bg-alt"
                        >
                          Abbrechen
                        </button>
                      </div>
                    ) : (
                      <div
                        className={cn(
                          'mt-1.5 text-xs',
                          a.status === 'done' ? 'text-green-deep' : a.status === 'failed' ? 'text-error' : 'text-muted',
                        )}
                      >
                        {a.note}
                      </div>
                    )}
                  </div>
                ))}
                {m.steps?.map((s, i) => (
                  <div key={i} className="pl-1 text-[11px] font-medium text-ai">
                    {s}
                  </div>
                ))}
              </div>
            </div>
          ),
        )}

        {loading && (
          <div className="flex gap-2">
            <img src={kikiAvatar} alt="" className="h-6 w-6 rounded-full bg-white object-cover" />
            <div className="flex items-center gap-2 rounded-2xl rounded-tl-sm bg-alt px-3 py-2.5 text-xs text-muted">
              <Loader2 size={13} className="animate-spin text-ai" />
              Kiki arbeitet…
            </div>
          </div>
        )}
        {error && (
          <div className="rounded-lg bg-error-bg px-3 py-2 text-xs text-error">{error}</div>
        )}

        {/* Suggestion chips while the thread is fresh */}
        {!loading && messages.length <= 1 && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => void send(s)}
                className="rounded-full border border-border bg-surface px-3 py-1.5 text-xs text-body transition hover:bg-alt"
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Composer */}
      <div className="shrink-0 border-t border-border bg-surface p-3">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void send()
              }
            }}
            placeholder="Frag Kiki etwas oder gib eine Aufgabe…"
            rows={1}
            className="max-h-28 flex-1 resize-none rounded-xl border border-border bg-alt px-3 py-2 text-sm text-text placeholder:text-muted focus:border-green-primary focus:outline-none"
          />
          <button
            onClick={() => void send()}
            disabled={!input.trim() || loading}
            className="rounded-xl bg-green-primary p-2.5 text-white transition hover:brightness-110 disabled:opacity-40"
            aria-label="Senden"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
        <div className="mt-1.5 text-center text-[10px] text-muted">
          Kiki nutzt KI · Änderungen nur nach Bestätigung
        </div>
      </div>
    </aside>
  )
}
