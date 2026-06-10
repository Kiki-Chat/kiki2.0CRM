import { useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Loader2, Plus, Send, Sparkles, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import kikiAvatar from '../../assets/kiki-avatar.png'
import { apiFetch } from '../../lib/api'
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
  if (tool === 'create_appointment' && appt?.id) {
    const date = typeof appt.scheduled_at === 'string' ? appt.scheduled_at.slice(0, 10) : ''
    return { route: `/calendar${date ? `?date=${date}&appointment=${appt.id}` : ''}`, label: 'Termin im Kalender geöffnet' }
  }
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
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

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
        body: JSON.stringify({ message: text, history }),
      })
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

  const confirmAction = async (msgId: string, idx: number, action: ActionState) => {
    setError(null)
    updateAction(msgId, idx, 'running', 'Wird ausgeführt…')
    try {
      const res = await apiFetch<{ ok: boolean; result: Record<string, unknown> }>(
        '/api/copilot/confirm',
        { method: 'POST', body: JSON.stringify({ tool: action.tool, args: action.args }) },
      )
      const errMsg = res.result && typeof res.result.error === 'string' ? res.result.error : null
      const ok = res.ok && !errMsg
      if (!ok) {
        updateAction(msgId, idx, 'failed', errMsg || 'Fehlgeschlagen')
        return
      }
      updateAction(msgId, idx, 'done', 'Erledigt ✓')
      // Make the change VISIBLE live: refresh every query (the open page updates
      // in place) and jump to the created object when we know where it lives.
      void qc.invalidateQueries()
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

      {/* Thread */}
      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-3 py-4">
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
