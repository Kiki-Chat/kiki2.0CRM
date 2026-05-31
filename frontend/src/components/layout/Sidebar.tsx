import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import {
  Bot,
  Building2,
  ChevronDown,
  ChevronRight,
  LogOut,
  Settings,
} from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'

import { useAuth } from '../../auth/AuthProvider'
import { apiFetch } from '../../lib/api'
import { cn, initials } from '../../lib/utils'
import { PersonalSettingsModal } from '../PersonalSettingsModal'
import { isGroup, NAV, type NavLeaf } from './nav'

const leafClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    'flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors',
    isActive
      ? 'bg-green-tint-100 font-semibold text-green-deep'
      : 'text-body hover:bg-alt',
  )

function Leaf({
  leaf,
  collapsed,
  badges,
}: {
  leaf: NavLeaf
  collapsed: boolean
  badges: Record<string, number>
}) {
  const Icon = leaf.icon
  const badge = leaf.badgeKey ? badges[leaf.badgeKey] : undefined
  return (
    <NavLink to={leaf.to} end={leaf.to === '/'} className={leafClass} title={leaf.label}>
      {Icon && <Icon size={16} className="flex-shrink-0" />}
      {!collapsed && <span className="flex-1 truncate">{leaf.label}</span>}
      {!collapsed && badge ? (
        <span className="rounded-full bg-error-bg px-1.5 text-xs font-bold text-error">
          {badge}
        </span>
      ) : null}
    </NavLink>
  )
}

export function Sidebar({
  collapsed,
  badges = {},
}: {
  collapsed: boolean
  badges?: Record<string, number>
}) {
  const { session, signOut } = useAuth()
  const navigate = useNavigate()
  const [personalOpen, setPersonalOpen] = useState(false)
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({})
  // White-label: show WHICH company's CRM this is. org_name comes from /api/me
  // (available to every user incl. employees). ProtectedRoute already primes
  // the ['me'] cache, so this is instant.
  const { data: me } = useQuery({
    queryKey: ['me'],
    queryFn: () => apiFetch<{ org_name: string | null }>('/api/me'),
    staleTime: 5 * 60 * 1000,
  })
  const companyName = me?.org_name

  const email = session?.user.email ?? 'Setup pending'
  const userName = (session?.user.user_metadata?.full_name as string) ?? 'HeyKiki User'
  // NOTE: Super-admin no longer enters via the customer-facing sidebar. The
  // admin surface lives at /admin/* (standalone tree, own login, own layout).

  return (
    <aside
      className="sticky top-0 z-20 flex h-screen flex-shrink-0 flex-col border-r border-border bg-sidebar transition-[width] duration-200"
      style={{ width: collapsed ? 64 : 240 }}
    >
      {/* Logo */}
      <div className="flex items-center gap-2.5 border-b border-border px-4 py-4">
        <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-green-brand to-green-primary text-base font-extrabold text-white">
          K
        </div>
        {!collapsed && (
          <div>
            <div className="text-base font-bold leading-tight text-text">HeyKiki</div>
            <div className="max-w-[150px] truncate text-xs text-muted" title={companyName ?? undefined}>
              {companyName ?? 'CRM Portal'}
            </div>
          </div>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-0.5 overflow-y-auto overflow-x-hidden px-2.5 py-3">
        {NAV.map((entry) => {
          if (!isGroup(entry)) {
            return <Leaf key={entry.to} leaf={entry} collapsed={collapsed} badges={badges} />
          }
          const Icon = entry.icon
          const key = entry.label
          const open = openGroups[key]
          return (
            <div key={key}>
              <button
                onClick={() => setOpenGroups((g) => ({ ...g, [key]: !g[key] }))}
                className="flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm text-body transition-colors hover:bg-alt"
                title={entry.label}
              >
                <Icon size={16} className="flex-shrink-0" />
                {!collapsed && (
                  <>
                    <span className="flex-1 text-left">{entry.label}</span>
                    <ChevronRight
                      size={12}
                      className={cn('text-faint transition-transform', open && 'rotate-90')}
                    />
                  </>
                )}
              </button>
              {open && !collapsed && (
                <div className="space-y-0.5 py-0.5 pl-7">
                  {entry.children.map((child) => (
                    <Leaf key={child.to} leaf={child} collapsed={false} badges={badges} />
                  ))}
                </div>
              )}
            </div>
          )
        })}

        {/* AI configuration — visually separated */}
        <div className="my-3 h-px bg-border" />
        {!collapsed && (
          <div className="px-2 pb-2 text-xs font-bold uppercase tracking-wide text-faint">
            KI-Konfiguration
          </div>
        )}
        <NavLink to="/kiki-zentrale" className={leafClass} title="Kiki-Zentrale">
          <Bot size={16} className="flex-shrink-0 text-ai" />
          {!collapsed && <span className="flex-1">Kiki-Zentrale</span>}
        </NavLink>
      </nav>

      {/* Profile menu */}
      <div className="border-t border-border p-2.5">
        <DropdownMenu.Root>
          <DropdownMenu.Trigger className="flex w-full items-center gap-2.5 rounded-md p-2 transition-colors hover:bg-alt">
            <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-green-tint-200 text-xs font-bold text-green-deep">
              {initials(userName)}
            </div>
            {!collapsed && (
              <>
                <div className="min-w-0 flex-1 text-left">
                  <div className="truncate text-sm font-semibold leading-tight text-text">
                    {userName}
                  </div>
                  <div className="truncate text-xs text-muted">{email}</div>
                </div>
                <ChevronDown size={13} className="text-muted" />
              </>
            )}
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content
              align="start"
              sideOffset={8}
              className="z-50 w-56 overflow-hidden rounded-lg border border-border bg-surface p-1 shadow-e3"
            >
              <DropdownMenu.Item
                onSelect={() => setPersonalOpen(true)}
                className="flex cursor-pointer items-center gap-2.5 rounded-md px-3 py-2 text-sm text-body outline-none data-[highlighted]:bg-alt"
              >
                <Settings size={14} /> Persönliche Einstellungen
              </DropdownMenu.Item>
              <DropdownMenu.Item
                onSelect={() => navigate('/settings')}
                className="flex cursor-pointer items-center gap-2.5 rounded-md px-3 py-2 text-sm text-body outline-none data-[highlighted]:bg-alt"
              >
                <Building2 size={14} /> Firmeneinstellungen
              </DropdownMenu.Item>
              <DropdownMenu.Separator className="my-1 h-px bg-border" />
              <DropdownMenu.Item
                onSelect={() => signOut()}
                className="flex cursor-pointer items-center gap-2.5 rounded-md px-3 py-2 text-sm text-error outline-none data-[highlighted]:bg-error-bg"
              >
                <LogOut size={14} /> Abmelden
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>
      <PersonalSettingsModal open={personalOpen} onClose={() => setPersonalOpen(false)} />
    </aside>
  )
}
