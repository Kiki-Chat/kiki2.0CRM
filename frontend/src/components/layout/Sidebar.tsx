import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { useQuery } from '@tanstack/react-query'
import {
  Bot,
  Building2,
  ChevronDown,
  ChevronRight,
  LogOut,
  Settings,
  ShieldAlert,
} from 'lucide-react'
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

  const email = session?.user.email ?? 'Setup pending'
  const userName = (session?.user.user_metadata?.full_name as string) ?? 'HeyKiki User'

  // P0.6 — Super-admin profile-menu entry: shown ONLY when role='super_admin'.
  // Reuses the shared ['me'] query cache.
  const me = useQuery({
    queryKey: ['me'],
    queryFn: () => apiFetch<{ role: string | null }>('/api/me'),
    staleTime: 5 * 60 * 1000,
    enabled: !!session,
  })
  const isSuperAdmin = me.data?.role === 'super_admin'

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
            <div className="text-xs text-muted">CRM Portal</div>
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
              {isSuperAdmin && (
                <>
                  <DropdownMenu.Separator className="my-1 h-px bg-border" />
                  <DropdownMenu.Item
                    onSelect={() => navigate('/super-admin/orgs')}
                    className="flex cursor-pointer items-center gap-2.5 rounded-md px-3 py-2 text-sm text-ai outline-none data-[highlighted]:bg-alt"
                  >
                    <ShieldAlert size={14} /> Super-Admin
                  </DropdownMenu.Item>
                </>
              )}
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
