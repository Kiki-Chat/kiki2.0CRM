import { Plus, Send, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import kikiAvatar from '../../assets/kiki-avatar.png'
import { apiFetch } from '../../lib/api'
import { useMe } from '../../lib/useMe'

/**
 * Kiki Assistent — a floating chat widget docked at the bottom-right of the CRM.
 * Separate from the ⌘K command palette. Talks to POST /api/copilot/chat:
 *  - reads are answered inline,
 *  - writes come back as proposed actions → confirmed via /api/copilot/confirm,
 *  - client actions (navigation) are performed here with useNavigate.
 * German-only; built on the CSS-var design tokens (light + dark).
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
type ActionState = ProposedAction & { status: 'pending' | 'done' | 'cancelled'; note?: string }
interface Msg {
  id: string
  role: 'user' | 'kiki'
  content: string
  actions?: ActionState[]
}

const OPEN_KEY = 'kiki-copilot-open'
let _seq = 0
const uid = () => `m${Date.now()}_${_seq++}`

/** Strip simple markdown emphasis so plain bubbles read cleanly. */
const clean = (s: string) => s.replace(/\*\*(.+?)\*\*/g, '$1')

function actionSummary(a: ProposedAction): string {
  if (a.tool === 'create_customer') return `Neuen Kunden anlegen: ${String(a.args.name ?? '')}`
  return a.description || a.tool
}

export function CopilotWidget() {
  const { me } = useMe()
  const navigate = useNavigate()
  const [open, setOpen] = useState(() => localStorage.getItem(OPEN_KEY) === '1')
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    localStorage.setItem(OPEN_KEY, open ? '1' : '0')
  }, [open])

  const greeting = (): Msg => {
    const first = me?.full_name?.split(' ')[0] || me?.org_name || ''
    return {
      id: uid(),
      role: 'kiki',
      content: `Hallo${first ? ' ' + first : ''}! Ich bin Kiki, dein CRM-Assistent. Frag mich z. B. „Wie viele offene Aufgaben habe ich?“ oder „Zeig mir die Anrufe“.`,
    }
  }

  // Greeting on first open.
  useEffect(() => {
    if (open && messages.length === 0) setMessages([greeting()])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, messages.length, me])

  const newChat = () => {
    setMessages([greeting()])
    setInput('')
    setError(null)
  }

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, loading])

  const updateAction = (msgId: string, idx: number, status: ActionState['status'], note?: string) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === msgId && m.actions
          ? { ...m, actions: m.actions.map((a, i) => (i === idx ? { ...a, status, note } : a)) }
          : m,
      ),
    )
  }

  const send = async () => {
    const text = input.trim()
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
      const actions = res.actions?.length
        ? res.actions.map((a) => ({ ...a, status: 'pending' as const }))
        : undefined
      setMessages((prev) => [...prev, { id: uid(), role: 'kiki', content: res.content, actions }])
      for (const ca of res.client_actions || []) {
        if (ca.tool === 'navigate_to' && typeof ca.args.route === 'string') navigate(ca.args.route)
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
    try {
      const res = await apiFetch<{ ok: boolean; result: Record<string, unknown> }>(
        '/api/copilot/confirm',
        { method: 'POST', body: JSON.stringify({ tool: action.tool, args: action.args }) },
      )
      const errMsg = res.result && typeof res.result.error === 'string' ? res.result.error : null
      const ok = res.ok && !errMsg
      updateAction(msgId, idx, ok ? 'done' : 'pending', ok ? 'Erledigt ✓' : errMsg || 'Fehlgeschlagen')
    } catch (e) {
      updateAction(msgId, idx, 'pending', e instanceof Error ? e.message : 'Fehlgeschlagen')
    }
  }

  return (
    <div className="fixed bottom-14 left-1/2 z-50 flex -translate-x-1/2 flex-col items-center gap-3 print:hidden">
      {open && (
        <div className="flex h-[560px] max-h-[80vh] w-[370px] max-w-[calc(100vw-2.5rem)] flex-col overflow-hidden rounded-2xl border border-border bg-surface shadow-2xl">
          <div className="flex items-center gap-3 border-b border-border bg-alt px-4 py-3">
            <img src={kikiAvatar} alt="Kiki" className="h-9 w-9 rounded-full bg-white object-cover ring-1 ring-border" />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-text">Kiki Assistent</div>
              <div className="text-xs text-muted">Dein CRM-Assistent</div>
            </div>
            <button
              onClick={newChat}
              className="rounded-lg p-1.5 text-muted transition hover:bg-surface hover:text-text"
              aria-label="Neuer Chat"
              title="Neuer Chat"
            >
              <Plus className="h-5 w-5" />
            </button>
            <button
              onClick={() => setOpen(false)}
              className="rounded-lg p-1.5 text-muted transition hover:bg-surface hover:text-text"
              aria-label="Schließen"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-3 py-4">
            {messages.map((m) =>
              m.role === 'user' ? (
                <div key={m.id} className="flex justify-end">
                  <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-green-primary px-3 py-2 text-sm text-white">
                    {m.content}
                  </div>
                </div>
              ) : (
                <div key={m.id} className="flex gap-2">
                  <img src={kikiAvatar} alt="" className="mt-0.5 h-6 w-6 shrink-0 rounded-full bg-white object-cover" />
                  <div className="max-w-[85%] space-y-2">
                    {m.content && (
                      <div className="whitespace-pre-wrap rounded-2xl rounded-tl-sm bg-alt px-3 py-2 text-sm text-text">
                        {clean(m.content)}
                      </div>
                    )}
                    {m.actions?.map((a, i) => (
                      <div key={i} className="rounded-xl border border-border bg-surface p-3">
                        <div className="text-xs font-medium text-text">{actionSummary(a)}</div>
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
                          <div className={`mt-1.5 text-xs ${a.status === 'done' ? 'text-green-deep' : 'text-muted'}`}>
                            {a.note}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ),
            )}

            {loading && (
              <div className="flex gap-2">
                <img src={kikiAvatar} alt="" className="h-6 w-6 rounded-full bg-white object-cover" />
                <div className="flex items-center gap-1 rounded-2xl rounded-tl-sm bg-alt px-3 py-3">
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted [animation-delay:-0.3s]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted [animation-delay:-0.15s]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted" />
                </div>
              </div>
            )}
            {error && (
              <div className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600 dark:bg-red-950/40 dark:text-red-400">
                {error}
              </div>
            )}
          </div>

          <div className="border-t border-border bg-surface p-3">
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
                placeholder="Frag Kiki etwas…"
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
            <div className="mt-1.5 text-center text-[10px] text-muted">Kiki nutzt KI · nur für CRM-Themen</div>
          </div>
        </div>
      )}

      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="kiki-glow relative h-16 w-16 overflow-hidden rounded-full bg-white shadow-xl ring-2 ring-green-primary transition hover:scale-105"
          aria-label="Kiki Assistent öffnen"
        >
          <img src={kikiAvatar} alt="Kiki" className="h-full w-full object-cover" />
        </button>
      )}
    </div>
  )
}
