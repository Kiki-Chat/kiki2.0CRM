import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'

import { applyAccent } from '../../lib/accent'
import { apiFetch } from '../../lib/api'
import { env } from '../../lib/env'
import { useMe } from '../../lib/useMe'
import { CopilotPanel } from '../copilot/CopilotPanel'
import { CommandPalette } from './CommandPalette'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'

const COPILOT_OPEN_KEY = 'kiki-copilot-open'

export function AppLayout() {
  const [collapsed, setCollapsed] = useState(false)
  // Mobile nav drawer (md=768px breakpoint). Desktop keeps the static rail.
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  // "Hey Kiki" side panel (docked right; opened from the Topbar button).
  const [copilotOpen, setCopilotOpen] = useState(() => localStorage.getItem(COPILOT_OPEN_KEY) === '1')
  useEffect(() => {
    localStorage.setItem(COPILOT_OPEN_KEY, copilotOpen ? '1' : '0')
  }, [copilotOpen])
  const location = useLocation()
  useEffect(() => setMobileNavOpen(false), [location.pathname])
  // Global ⌘K / Ctrl-K command palette ("Kiki fragen") — searches the nav
  // menus + submenus and jumps to a page.
  const [searchOpen, setSearchOpen] = useState(false)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault()
        setSearchOpen((o) => !o)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiFetch<{ organization: { accent_color: string | null } }>('/api/settings'),
    staleTime: 5 * 60 * 1000,
  })
  useEffect(() => {
    applyAccent(settings?.organization?.accent_color)
  }, [settings])

  // P0.4 — Sidebar Anrufe badge sources real unread-calls count.
  // CallLogsPage invalidates this key on mark-read so the badge decrements live.
  const { data: overview } = useQuery({
    queryKey: ['dashboard', 'overview'],
    queryFn: () =>
      apiFetch<{ kpis: { unread_calls: number } }>('/api/dashboard/overview'),
    staleTime: 5 * 60 * 1000,
  })
  const unreadCalls = overview?.kpis?.unread_calls ?? 0

  // White-label footer (B11): the company's OWN contact — no HeyKiki branding.
  // Sourced from /api/me (available to every role), so it works for employees too.
  const { me } = useMe()
  const addr = me?.org_address
  const addressLine = addr
    ? [addr.street, [addr.postal_code || addr.zip, addr.city].filter(Boolean).join(' ').trim()]
        .filter(Boolean)
        .join(', ')
    : ''
  const contactLine = [me?.org_name, addressLine].filter(Boolean).join(' · ')

  return (
    <div className="flex h-screen overflow-hidden bg-bg text-body">
      <Sidebar
        collapsed={collapsed}
        badges={{ calls: unreadCalls }}
        onOpenSearch={() => setSearchOpen(true)}
        mobileNavOpen={mobileNavOpen}
        onClose={() => setMobileNavOpen(false)}
      />
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <Topbar
          collapsed={collapsed}
          onToggleCollapse={() => setCollapsed((c) => !c)}
          onOpenNav={() => setMobileNavOpen(true)}
          copilotOpen={env.copilotEnabled ? copilotOpen : undefined}
          onToggleCopilot={env.copilotEnabled ? () => setCopilotOpen((o) => !o) : undefined}
        />
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
        {(contactLine || me?.org_email) && (
          <footer className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 border-t border-border bg-surface px-8 py-4 text-center text-xs text-muted">
            {contactLine && <span>{contactLine}</span>}
            {me?.org_email && (
              <>
                {contactLine && <span className="text-faint">·</span>}
                <a href={`mailto:${me.org_email}`} className="font-medium text-green-deep hover:underline">
                  {me.org_email}
                </a>
              </>
            )}
          </footer>
        )}
      </div>
      {/* Hey Kiki — docked right panel; the CRM content reflows next to it on
          desktop (Gemini-in-Docs pattern), overlays on small screens. */}
      {env.copilotEnabled && (
        <CopilotPanel open={copilotOpen} onClose={() => setCopilotOpen(false)} />
      )}
      <CommandPalette open={searchOpen} onClose={() => setSearchOpen(false)} />
    </div>
  )
}
