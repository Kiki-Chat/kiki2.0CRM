import { Plus, Send, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, PointerEvent as ReactPointerEvent } from 'react'
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
const POS_KEY = 'kiki-copilot-pos'
const LAUNCHER = 64 // px — launcher diameter (h-16 w-16)
const PANEL_W = 370 // px — open chat panel width
const MARGIN = 16 // px — min gap kept from any viewport edge
type Pos = { x: number; y: number } // launcher top-left, viewport px
let _seq = 0
const uid = () => `m${Date.now()}_${_seq++}`

/** Read a previously dragged launcher position from localStorage. */
function loadPos(): Pos | null {
  try {
    const raw = localStorage.getItem(POS_KEY)
    if (!raw) return null
    const p = JSON.parse(raw) as Pos
    if (typeof p?.x === 'number' && typeof p?.y === 'number') return p
  } catch {
    /* ignore malformed value */
  }
  return null
}

/** Strip simple markdown emphasis so plain bubbles read cleanly. */
const clean = (s: string) => s.replace(/\*\*(.+?)\*\*/g, '$1')

function actionSummary(a: ProposedAction): string {
  if (a.tool === 'create_customer') return `Neuen Kunden anlegen: ${String(a.args.name ?? '')}`
  return a.description || a.tool
}

export function CopilotWidget() {
  const { me, isLoading: meLoading } = useMe()
  const navigate = useNavigate()
  const [open, setOpen] = useState(() => localStorage.getItem(OPEN_KEY) === '1')
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pos, setPos] = useState<Pos | null>(() => loadPos())
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{ startX: number; startY: number; baseX: number; baseY: number; moved: boolean } | null>(null)
  const posRef = useRef<Pos | null>(null)
  const suppressClickRef = useRef(false)

  useEffect(() => {
    posRef.current = pos
  }, [pos])

  useEffect(() => {
    localStorage.setItem(OPEN_KEY, open ? '1' : '0')
  }, [open])

  const greeting = (): Msg => {
    // Greet the ACCOUNT HOLDER = the company (org_name), dynamic per org — like the Dashboard.
    const company = me?.org_name?.trim() || ''
    return {
      id: uid(),
      role: 'kiki',
      content: `Hallo${company ? ' ' + company : ''}! Ich bin Kiki, dein CRM-Assistent. Frag mich z. B. „Wie viele offene Aufgaben habe ich?“ oder „Zeig mir die Anrufe“.`,
    }
  }

  // Greeting on first open — wait until the user has loaded so we greet them by
  // name instead of a nameless "Hallo!" (the name flashes in once /api/me resolves).
  useEffect(() => {
    if (open && messages.length === 0 && !meLoading) setMessages([greeting()])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, messages.length, me, meLoading])

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

  // ─── Draggable launcher ──────────────────────────────────────────────────
  const clampPos = (x: number, y: number): Pos => ({
    x: Math.max(MARGIN, Math.min(x, window.innerWidth - LAUNCHER - MARGIN)),
    y: Math.max(MARGIN, Math.min(y, window.innerHeight - LAUNCHER - MARGIN)),
  })

  // Keep a dragged bubble on-screen across viewport resizes.
  useEffect(() => {
    const onResize = () => setPos((p) => (p ? clampPos(p.x, p.y) : p))
    onResize()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const startDrag = (e: ReactPointerEvent) => {
    if (e.pointerType === 'mouse' && e.button !== 0) return
    const rect = wrapperRef.current?.getBoundingClientRect()
    const baseX = pos?.x ?? rect?.left ?? window.innerWidth - LAUNCHER - 24
    const baseY = pos?.y ?? rect?.top ?? window.innerHeight - LAUNCHER - 24
    dragRef.current = { startX: e.clientX, startY: e.clientY, baseX, baseY, moved: false }
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }
  const moveDrag = (e: ReactPointerEvent) => {
    const d = dragRef.current
    if (!d) return
    const dx = e.clientX - d.startX
    const dy = e.clientY - d.startY
    if (!d.moved && (Math.abs(dx) > 4 || Math.abs(dy) > 4)) d.moved = true
    if (d.moved) {
      const next = clampPos(d.baseX + dx, d.baseY + dy)
      posRef.current = next
      setPos(next)
    }
  }
  const endDrag = (e: ReactPointerEvent) => {
    const d = dragRef.current
    dragRef.current = null
    if (!d) return
    try {
      ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
    } catch {
      /* pointer already released */
    }
    if (d.moved) {
      suppressClickRef.current = true // swallow the click that follows a drag
      if (posRef.current) localStorage.setItem(POS_KEY, JSON.stringify(posRef.current))
    } else {
      setOpen(true) // a tap/click with no movement opens the chat
    }
  }

  // When a custom position is set, place the wrapper there — clamped so the open
  // panel never spills off-screen; otherwise fall back to the bottom-right dock.
  const wrapperStyle: CSSProperties | undefined = pos
    ? (() => {
        const w = open ? PANEL_W : LAUNCHER
        const h = open ? Math.min(560, Math.round(window.innerHeight * 0.8)) : LAUNCHER
        return {
          left: Math.max(MARGIN, Math.min(pos.x, window.innerWidth - w - MARGIN)),
          top: Math.max(MARGIN, Math.min(pos.y, window.innerHeight - h - MARGIN)),
        }
      })()
    : undefined

  return (
    <div
      ref={wrapperRef}
      style={wrapperStyle}
      className={`fixed z-50 flex flex-col items-end gap-3 print:hidden ${pos ? '' : 'bottom-6 right-6'}`}
    >
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
          onPointerDown={startDrag}
          onPointerMove={moveDrag}
          onPointerUp={endDrag}
          onClick={() => {
            if (suppressClickRef.current) {
              suppressClickRef.current = false
              return
            }
            setOpen(true)
          }}
          className="relative h-16 w-16 cursor-grab touch-none overflow-hidden rounded-full bg-white shadow-xl ring-2 ring-green-primary transition hover:scale-105 active:cursor-grabbing"
          aria-label="Kiki Assistent öffnen"
          title="Kiki öffnen · ziehen zum Verschieben"
        >
          <img src={kikiAvatar} alt="Kiki" className="h-full w-full object-cover" draggable={false} />
        </button>
      )}
    </div>
  )
}
