import {
  LayoutDashboard,
  Layers,
  Phone,
  Users,
  Calendar,
  CalendarClock,
  Briefcase,
  Wallet,
  HardHat,
  type LucideIcon,
} from 'lucide-react'

export interface NavLeaf {
  to: string
  icon?: LucideIcon
  label: string
  badgeKey?: 'calls'
  /** Hidden from non-admin (employee) users. Backend still enforces; this is
   * cosmetic so employees don't see a link to a page they can't use. */
  adminOnly?: boolean
  /** Hidden from admins. The admin login represents the COMPANY, not a person,
   * so personal surfaces (e.g. "Meine Abwesenheit") belong to employee logins
   * only — admins manage absences via Mitarbeiter instead. */
  employeeOnly?: boolean
  /** Entitlement feature key (Phase 2). When the org's plan doesn't grant it the
   * item stays VISIBLE but locked (soft preview + upgrade CTA), not hidden. */
  feature?: string
}

export interface NavGroupDef {
  icon: LucideIcon
  label: string
  children: NavLeaf[]
}

export type NavEntry = NavLeaf | NavGroupDef

export function isGroup(e: NavEntry): e is NavGroupDef {
  return 'children' in e
}

export const NAV: NavEntry[] = [
  { to: '/', icon: LayoutDashboard, label: 'Übersicht' },
  { to: '/cases', icon: Layers, label: 'Vorgänge', feature: 'cases' },
  { to: '/calls', icon: Phone, label: 'Anrufe', badgeKey: 'calls' },
  { to: '/customers', icon: Users, label: 'Kontakte' },
  { to: '/calendar', icon: Calendar, label: 'Kalender', feature: 'calendar' },
  { to: '/meine-abwesenheit', icon: CalendarClock, label: 'Meine Abwesenheit', employeeOnly: true },
  {
    icon: Briefcase,
    label: 'Aufträge',
    children: [
      { to: '/projects', label: 'Projekte', feature: 'projects' },
      { to: '/planning-board', label: 'Planungstafel', feature: 'planning' },
    ],
  },
  {
    icon: Wallet,
    label: 'Finanzen',
    children: [
      { to: '/cost-estimates', label: 'Angebote', feature: 'finance' },
      { to: '/invoices', label: 'Rechnungen', feature: 'finance' },
      { to: '/catalog', label: 'Artikel', feature: 'finance' },
    ],
  },
  { to: '/employees', icon: HardHat, label: 'Mitarbeiter', adminOnly: true },
]
