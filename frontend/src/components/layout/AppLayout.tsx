import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'

import { applyAccent } from '../../lib/accent'
import { apiFetch } from '../../lib/api'
import { useMe } from '../../lib/useMe'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'

export function AppLayout() {
  const [collapsed, setCollapsed] = useState(false)
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
      <Sidebar collapsed={collapsed} badges={{ calls: unreadCalls }} />
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <Topbar collapsed={collapsed} onToggleCollapse={() => setCollapsed((c) => !c)} />
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
        {(contactLine || me?.org_email) && (
          <footer className="flex flex-wrap items-center justify-center gap-x-2 gap-y-0.5 border-t border-border bg-surface px-4 py-2 text-center text-xs text-muted">
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
    </div>
  )
}
