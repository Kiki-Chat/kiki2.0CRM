import {
  LayoutDashboard,
  Inbox,
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
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/posteingang', icon: Inbox, label: 'Posteingang' },
  { to: '/calls', icon: Phone, label: 'Anrufe', badgeKey: 'calls' },
  { to: '/customers', icon: Users, label: 'Kontakte' },
  { to: '/calendar', icon: Calendar, label: 'Kalender' },
  { to: '/meine-abwesenheit', icon: CalendarClock, label: 'Meine Abwesenheit', employeeOnly: true },
  {
    icon: Briefcase,
    label: 'Aufträge',
    children: [
      { to: '/projects', label: 'Projekte' },
      { to: '/planning-board', label: 'Planungstafel' },
    ],
  },
  {
    icon: Wallet,
    label: 'Finanzen',
    children: [
      { to: '/cost-estimates', label: 'Kostenvoranschläge' },
      { to: '/invoices', label: 'Rechnungen' },
      { to: '/catalog', label: 'Artikel' },
    ],
  },
  { to: '/employees', icon: HardHat, label: 'Mitarbeiter', adminOnly: true },
]
