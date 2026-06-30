import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import {
  Bot,
  Building2,
  ChevronDown,
  ChevronRight,
  Lock,
  LogOut,
  Search,
  Settings,
} from 'lucide-react'
import { useEffect, useState } from 'react'
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
  locked,
}: {
  leaf: NavLeaf
  collapsed: boolean
  badges: Record<string, number>
  locked?: boolean
}) {
  const Icon = leaf.icon
  const badge = leaf.badgeKey ? badges[leaf.badgeKey] : undefined
  return (
    <NavLink
      to={leaf.to}
      end={leaf.to === '/'}
      className={({ isActive }) => cn('nav-item', isActive && 'active', collapsed && 'justify-center', locked && 'opacity-60')}
      title={locked ? `${leaf.label} — in höherem Tarif enthalten` : leaf.label}
    >
      {Icon && (
        <span className="nav-ico">
          <Icon size={18} />
        </span>
      )}
      {!collapsed && <span className="flex-1 truncate">{leaf.label}</span>}
      {!collapsed && locked ? (
        <Lock size={13} className="shrink-0 text-faint" />
      ) : !collapsed && badge ? (
        <span className="nav-count">{badge}</span>
      ) : null}
    </NavLink>
  )
}

export function Sidebar({
  collapsed,
  badges = {},
  onOpenSearch,
  mobileNavOpen = false,
  onClose,
}: {
  collapsed: boolean
  badges?: Record<string, number>
  onOpenSearch: () => void
  mobileNavOpen?: boolean
  onClose?: () => void
}) {
  const { session, signOut } = useAuth()
  const navigate = useNavigate()
  const [personalOpen, setPersonalOpen] = useState(false)
  // Close the mobile drawer on Escape.
  useEffect(() => {
    if (!mobileNavOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose?.()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [mobileNavOpen, onClose])
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
  const { me, isAdmin, hasFeature } = useMe()
  // Plan-gated leaves stay VISIBLE but locked (soft preview) when the org's plan
  // doesn't grant the feature — clicking routes to the page, where FeatureRoute shows
  // the upgrade panel. super_admin bypasses (handled in hasFeature).
  const isLocked = (l: NavLeaf) => !!l.feature && !hasFeature(l.feature)
  const companyName = me?.org_name
  const companyEmail = me?.org_email
  const companyLogo = me?.org_logo_url

  // Drop admin-only leaves for employees, and employee-only (personal) leaves
  // for admins — plus any group left empty as a result. Phase 5: also drop leaves
  // the admin has explicitly locked for THIS employee (by nav path).
  const lockedKeys = me?.locked_menu_keys ?? []
  const hideLeaf = (l: NavLeaf) =>
    (!!l.adminOnly && !isAdmin) || (!!l.employeeOnly && isAdmin) || lockedKeys.includes(l.to)
  const visibleNav = NAV.flatMap<NavEntry>((entry) => {
    if (!isGroup(entry)) return hideLeaf(entry) ? [] : [entry]
    const children = entry.children.filter((c) => !hideLeaf(c))
    return children.length ? [{ ...entry, children }] : []
  })

  const email = session?.user.email ?? 'Einrichtung offen'
  // Employee badge name comes from the primed ['me'] cache (full_name) — that is
  // the live value right after the user edits their name; the auth-session
  // metadata can be stale (it is not refreshed on a name change). Fall back to
  // the session metadata, then the email, so it never reverts to "Konto".
  const personName =
    me?.full_name?.trim() ||
    (session?.user.user_metadata?.full_name as string | undefined) ||
    email
  // White-label bottom badge. The admin login REPRESENTS the company (no personal
  // identity) → show company name + contact email + logo. An employee login is a
  // person → show their own NAME + email (logo stays company-level, top header only).
  const badgeName = isAdmin ? (companyName ?? 'Unternehmen') : personName
  const badgeEmail = isAdmin ? (companyEmail ?? email) : email
  const badgeLogo = isAdmin ? companyLogo : null

  // While the mobile drawer is open it is always full-width, so its contents must
  // render expanded regardless of the desktop collapse toggle.
  const railCollapsed = mobileNavOpen ? false : collapsed

  return (
    <>
      {/* Mobile backdrop — closes the drawer on tap. Desktop never shows it. */}
      {mobileNavOpen && (
        <div className="fixed inset-0 z-40 bg-black/40 md:hidden" onClick={onClose} aria-hidden />
      )}
    <aside
      className={cn(
        'rail fixed inset-y-0 left-0 z-50 flex h-screen flex-shrink-0 flex-col gap-0.5 transition-transform duration-200',
        'md:sticky md:top-0 md:z-20 md:transition-[width]',
        mobileNavOpen ? 'translate-x-0' : '-translate-x-full',
        'md:translate-x-0',
      )}
      style={{
        // On mobile the open drawer is always expanded (240); desktop honours collapse.
        width: railCollapsed ? 64 : 240,
        padding: '18px 14px 14px',
      }}
    >
      {/* Brand — HeyKiki product mark (company identity lives in the bottom badge). */}
      <div className={cn('mb-3 flex items-center gap-2.5 px-1', railCollapsed && 'justify-center')}>
        <span className="rail-mark">K</span>
        {!railCollapsed && <span className="rail-word">HeyKiki</span>}
      </div>

      {/* Kiki fragen — ⌘K command palette over the nav menus + submenus. */}
      <button
        type="button"
        onClick={onOpenSearch}
        className={cn('rail-search mb-2', railCollapsed && 'justify-center')}
        title="Kiki fragen"
      >
        <Search size={15} className="flex-shrink-0" />
        {!railCollapsed && (
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
            return <Leaf key={entry.to} leaf={entry} collapsed={railCollapsed} badges={badges} locked={isLocked(entry)} />
          }
          const Icon = entry.icon
          const key = entry.label
          const open = openGroups[key]
          return (
            <div key={key}>
              <button
                onClick={() => setOpenGroups((g) => ({ ...g, [key]: !g[key] }))}
                className={cn('nav-item', railCollapsed && 'justify-center')}
                title={entry.label}
              >
                <span className="nav-ico">
                  <Icon size={18} />
                </span>
                {!railCollapsed && (
                  <>
                    <span className="flex-1 text-left">{entry.label}</span>
                    <span className={cn('nav-caret', open && 'open')}>
                      <ChevronRight size={14} />
                    </span>
                  </>
                )}
              </button>
              {open && !railCollapsed && (
                <div className="nav-sub">
                  {entry.children.map((child) => {
                    const childLocked = isLocked(child)
                    return (
                      <NavLink
                        key={child.to}
                        to={child.to}
                        className={({ isActive }) => cn('nav-subitem', isActive && 'active', childLocked && 'opacity-60')}
                        title={childLocked ? `${child.label} — in höherem Tarif enthalten` : child.label}
                      >
                        <span className="dot" />
                        <span className="flex-1 truncate">{child.label}</span>
                        {childLocked && <Lock size={12} className="shrink-0 text-faint" />}
                      </NavLink>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}

        {/* AI configuration — admin-only (Kiki-Zentrale mutations all 403 an
            employee); hide the whole section for non-admins. */}
        {isAdmin && (
          <>
            {!railCollapsed ? (
              <div className="rail-group">KI-Konfiguration</div>
            ) : (
              <div className="my-2 h-px bg-white/10" />
            )}
            <NavLink
              to="/kiki-zentrale"
              className={({ isActive }) => cn('nav-item', isActive && 'active', railCollapsed && 'justify-center')}
              title="Kiki-Zentrale"
            >
              <span className="nav-ico kiki">
                <Bot size={18} />
              </span>
              {!railCollapsed && <span className="flex-1">Kiki-Zentrale</span>}
            </NavLink>
          </>
        )}
      </nav>

      {/* Profile menu */}
      <div className="mt-2">
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button className={cn('rail-account', railCollapsed && 'justify-center')}>
              {badgeLogo ? (
                <img src={badgeLogo} alt="" className="rail-ava" />
              ) : (
                <span className="rail-ava">{initials(badgeName)}</span>
              )}
              {!railCollapsed && (
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
              className="z-50 w-[calc(100vw-2rem)] overflow-hidden rounded-lg border border-border bg-surface p-1 shadow-e3 sm:w-56"
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
    </>
  )
}
