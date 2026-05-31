import {
  LayoutDashboard,
  Phone,
  Users,
  Calendar,
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
  { to: '/calls', icon: Phone, label: 'Anrufe', badgeKey: 'calls' },
  { to: '/customers', icon: Users, label: 'Kunden' },
  { to: '/calendar', icon: Calendar, label: 'Kalender' },
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
      { to: '/catalog', label: 'Katalog' },
    ],
  },
  { to: '/employees', icon: HardHat, label: 'Mitarbeiter', adminOnly: true },
]
