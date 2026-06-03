import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import {
  Bot,
  Building2,
  ChevronDown,
  ChevronRight,
  LogOut,
  Search,
  Settings,
} from 'lucide-react'
import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'

import { useAuth } from '../../auth/AuthProvider'
import { useMe } from '../../lib/useMe'
import { cn, initials } from '../../lib/utils'
import { PersonalSettingsModal } from '../PersonalSettingsModal'
import { isGroup, NAV, type NavEntry, type NavLeaf } from './nav'

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
    <NavLink
      to={leaf.to}
      end={leaf.to === '/'}
      className={({ isActive }) => cn('nav-item', isActive && 'active', collapsed && 'justify-center')}
      title={leaf.label}
    >
      {Icon && (
        <span className="nav-ico">
          <Icon size={18} />
        </span>
      )}
      {!collapsed && <span className="flex-1 truncate">{leaf.label}</span>}
      {!collapsed && badge ? <span className="nav-count">{badge}</span> : null}
    </NavLink>
  )
}

export function Sidebar({
  collapsed,
  badges = {},
  onOpenSearch,
}: {
  collapsed: boolean
  badges?: Record<string, number>
  onOpenSearch: () => void
}) {
  const { session, signOut } = useAuth()
  const navigate = useNavigate()
  const [personalOpen, setPersonalOpen] = useState(false)
  // Nav groups default to OPEN so the nested submenus read like the poster
  // design out of the box (the user can still collapse them).
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {}
    for (const e of NAV) if (isGroup(e)) init[e.label] = true
    return init
  })
  // White-label company name + role come from /api/me (ProtectedRoute primes the
  // ['me'] cache, so this is instant). isAdmin drives cosmetic hiding of
  // admin-only nav entries — the backend still enforces every action.
  const { me, isAdmin } = useMe()
  const companyName = me?.org_name
  const companyEmail = me?.org_email
  const companyLogo = me?.org_logo_url

  // Drop admin-only leaves for employees, and employee-only (personal) leaves
  // for admins — plus any group left empty as a result.
  const hideLeaf = (l: NavLeaf) => (!!l.adminOnly && !isAdmin) || (!!l.employeeOnly && isAdmin)
  const visibleNav = NAV.flatMap<NavEntry>((entry) => {
    if (!isGroup(entry)) return hideLeaf(entry) ? [] : [entry]
    const children = entry.children.filter((c) => !hideLeaf(c))
    return children.length ? [{ ...entry, children }] : []
  })

  const email = session?.user.email ?? 'Setup pending'
  const userName = (session?.user.user_metadata?.full_name as string) ?? companyName ?? 'Konto'
  // White-label bottom badge. The admin login REPRESENTS the company (no personal
  // identity) → show company name + contact email + logo. An employee login is a
  // person → show their own name + email (logo stays company-level, top header only).
  const badgeName = isAdmin ? (companyName ?? 'Unternehmen') : userName
  const badgeEmail = isAdmin ? (companyEmail ?? email) : email
  const badgeLogo = isAdmin ? companyLogo : null

  return (
    <aside
      className="rail sticky top-0 z-20 flex h-screen flex-shrink-0 flex-col gap-0.5 transition-[width] duration-200"
      style={{ width: collapsed ? 64 : 240, padding: '18px 14px 14px' }}
    >
      {/* Brand — HeyKiki product mark (company identity lives in the bottom badge). */}
      <div className={cn('mb-3 flex items-center gap-2.5 px-1', collapsed && 'justify-center')}>
        <span className="rail-mark">K</span>
        {!collapsed && <span className="rail-word">HeyKiki</span>}
      </div>

      {/* Kiki fragen — ⌘K command palette over the nav menus + submenus. */}
      <button
        type="button"
        onClick={onOpenSearch}
        className={cn('rail-search mb-2', collapsed && 'justify-center')}
        title="Kiki fragen"
      >
        <Search size={15} className="flex-shrink-0" />
        {!collapsed && (
          <>
            <span>Kiki fragen</span>
            <span className="rail-search-kbd">⌘K</span>
          </>
        )}
      </button>

      {/* Nav */}
      <nav className="-mx-1 flex-1 space-y-0.5 overflow-y-auto overflow-x-hidden px-1">
        {visibleNav.map((entry) => {
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
                className={cn('nav-item', collapsed && 'justify-center')}
                title={entry.label}
              >
                <span className="nav-ico">
                  <Icon size={18} />
                </span>
                {!collapsed && (
                  <>
                    <span className="flex-1 text-left">{entry.label}</span>
                    <span className={cn('nav-caret', open && 'open')}>
                      <ChevronRight size={14} />
                    </span>
                  </>
                )}
              </button>
              {open && !collapsed && (
                <div className="nav-sub">
                  {entry.children.map((child) => (
                    <NavLink
                      key={child.to}
                      to={child.to}
                      className={({ isActive }) => cn('nav-subitem', isActive && 'active')}
                      title={child.label}
                    >
                      <span className="dot" />
                      <span className="flex-1 truncate">{child.label}</span>
                    </NavLink>
                  ))}
                </div>
              )}
            </div>
          )
        })}

        {/* AI configuration — admin-only (Kiki-Zentrale mutations all 403 an
            employee); hide the whole section for non-admins. */}
        {isAdmin && (
          <>
            {!collapsed ? (
              <div className="rail-group">KI-Konfiguration</div>
            ) : (
              <div className="my-2 h-px bg-white/10" />
            )}
            <NavLink
              to="/kiki-zentrale"
              className={({ isActive }) => cn('nav-item', isActive && 'active', collapsed && 'justify-center')}
              title="Kiki-Zentrale"
            >
              <span className="nav-ico kiki">
                <Bot size={18} />
              </span>
              {!collapsed && <span className="flex-1">Kiki-Zentrale</span>}
            </NavLink>
          </>
        )}
      </nav>

      {/* Profile menu */}
      <div className="mt-2">
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button className={cn('rail-account', collapsed && 'justify-center')}>
              {badgeLogo ? (
                <img src={badgeLogo} alt="" className="rail-ava" />
              ) : (
                <span className="rail-ava">{initials(badgeName)}</span>
              )}
              {!collapsed && (
                <>
                  <div className="min-w-0 flex-1 text-left">
                    <div className="rail-nm truncate">{badgeName}</div>
                    <div className="rail-rl truncate">{badgeEmail}</div>
                  </div>
                  <ChevronDown size={13} className="text-white/50" />
                </>
              )}
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content
              align="start"
              sideOffset={8}
              className="z-50 w-56 overflow-hidden rounded-lg border border-border bg-surface p-1 shadow-e3"
            >
              {/* Personal settings belong to the employee login (a person). The
                  admin login represents the COMPANY → it gets Company Settings
                  only (incl. password under Firmeneinstellungen → Passwort). */}
              {!isAdmin && (
                <DropdownMenu.Item
                  onSelect={() => setPersonalOpen(true)}
                  className="flex cursor-pointer items-center gap-2.5 rounded-md px-3 py-2 text-sm text-body outline-none data-[highlighted]:bg-alt"
                >
                  <Settings size={14} /> Persönliche Einstellungen
                </DropdownMenu.Item>
              )}
              {isAdmin && (
                <DropdownMenu.Item
                  onSelect={() => navigate('/settings')}
                  className="flex cursor-pointer items-center gap-2.5 rounded-md px-3 py-2 text-sm text-body outline-none data-[highlighted]:bg-alt"
                >
                  <Building2 size={14} /> Firmeneinstellungen
                </DropdownMenu.Item>
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
