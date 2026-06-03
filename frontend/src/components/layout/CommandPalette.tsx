import { CornerDownLeft, Search } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import { useMe } from '../../lib/useMe'
import { cn } from '../../lib/utils'
import { isGroup, NAV, type NavEntry } from './nav'

interface Cmd {
  label: string
  to: string
  group?: string
  adminOnly?: boolean
  employeeOnly?: boolean
}

// Destinations reachable from the app but not part of the primary NAV array —
// still worth jumping to from the palette.
const EXTRA: Cmd[] = [
  { label: 'Kiki-Zentrale', to: '/kiki-zentrale', group: 'KI-Konfiguration', adminOnly: true },
  { label: 'Firmeneinstellungen', to: '/settings', group: 'Einstellungen', adminOnly: true },
  { label: 'Geschäftszeiten', to: '/calendar/business-hours', group: 'Kalender' },
]

function buildIndex(): Cmd[] {
  const out: Cmd[] = []
  for (const entry of NAV as NavEntry[]) {
    if (isGroup(entry)) {
      for (const c of entry.children) {
        out.push({ label: c.label, to: c.to, group: entry.label, adminOnly: c.adminOnly, employeeOnly: c.employeeOnly })
      }
    } else {
      out.push({ label: entry.label, to: entry.to, adminOnly: entry.adminOnly, employeeOnly: entry.employeeOnly })
    }
  }
  out.push(...EXTRA)
  return out
}

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const { isAdmin } = useMe()
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  const all = useMemo(() => buildIndex(), [])
  const visible = useMemo(() => {
    // Mirror the Sidebar's visibility rules so the palette never offers a page
    // the role can't open (the backend still enforces regardless).
    const hide = (c: Cmd) => (!!c.adminOnly && !isAdmin) || (!!c.employeeOnly && isAdmin)
    const q = query.trim().toLowerCase()
    return all.filter((c) => {
      if (hide(c)) return false
      if (!q) return true
      return `${c.group ?? ''} ${c.label}`.toLowerCase().includes(q)
    })
  }, [all, query, isAdmin])

  useEffect(() => {
    if (!open) return
    setQuery('')
    setActive(0)
    const id = requestAnimationFrame(() => inputRef.current?.focus())
    return () => cancelAnimationFrame(id)
  }, [open])

  useEffect(() => {
    setActive(0)
  }, [query])

  if (!open) return null

  const go = (c?: Cmd) => {
    const target = c ?? visible[active]
    if (!target) return
    navigate(target.to)
    onClose()
  }

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((a) => Math.min(a + 1, visible.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => Math.max(a - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      go()
    } else if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-[12vh]"
      role="dialog"
      aria-modal="true"
      aria-label="Kiki fragen"
    >
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div
        className="relative z-10 w-full max-w-lg overflow-hidden rounded-xl border border-border bg-surface shadow-e3"
        onKeyDown={onKeyDown}
      >
        <div className="flex items-center gap-2.5 border-b border-border px-4">
          <Search size={16} className="text-muted" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Menüs und Untermenüs durchsuchen…"
            className="flex-1 bg-transparent py-3.5 text-sm text-text outline-none placeholder:text-faint"
          />
          <kbd className="rounded border border-border bg-alt px-1.5 py-0.5 text-[10px] font-bold text-muted">
            ESC
          </kbd>
        </div>
        <ul className="max-h-[320px] overflow-y-auto p-2">
          {visible.length === 0 ? (
            <li className="px-3 py-6 text-center text-sm text-muted">Nichts gefunden.</li>
          ) : (
            visible.map((c, i) => (
              <li key={`${c.to}-${c.label}`}>
                <button
                  type="button"
                  onMouseEnter={() => setActive(i)}
                  onClick={() => go(c)}
                  className={cn(
                    'flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors',
                    i === active ? 'bg-green-tint-100 text-green-deep' : 'text-body hover:bg-alt',
                  )}
                >
                  <span className="font-medium">{c.label}</span>
                  {c.group && <span className="text-xs text-muted">· {c.group}</span>}
                  {i === active && <CornerDownLeft size={13} className="ml-auto text-muted" />}
                </button>
              </li>
            ))
          )}
        </ul>
      </div>
    </div>
  )
}
