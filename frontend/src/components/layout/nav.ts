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

import type { Lang } from '../../lib/i18n'

export interface NavLeaf {
  to: string
  icon?: LucideIcon
  label: Record<Lang, string>
  badgeKey?: 'calls'
}

export interface NavGroupDef {
  icon: LucideIcon
  label: Record<Lang, string>
  children: NavLeaf[]
}

export type NavEntry = NavLeaf | NavGroupDef

export function isGroup(e: NavEntry): e is NavGroupDef {
  return 'children' in e
}

export const NAV: NavEntry[] = [
  { to: '/', icon: LayoutDashboard, label: { de: 'Dashboard', en: 'Dashboard' } },
  { to: '/calls', icon: Phone, label: { de: 'Anrufe', en: 'Calls' }, badgeKey: 'calls' },
  { to: '/customers', icon: Users, label: { de: 'Kunden', en: 'Customers' } },
  { to: '/calendar', icon: Calendar, label: { de: 'Kalender', en: 'Calendar' } },
  {
    icon: Briefcase,
    label: { de: 'Aufträge', en: 'Work Orders' },
    children: [
      { to: '/projects', label: { de: 'Projekte', en: 'Projects' } },
      { to: '/planning-board', label: { de: 'Planungstafel', en: 'Planning Board' } },
    ],
  },
  {
    icon: Wallet,
    label: { de: 'Finanzen', en: 'Finance' },
    children: [
      { to: '/cost-estimates', label: { de: 'Kostenvoranschläge', en: 'Cost Estimates' } },
      { to: '/invoices', label: { de: 'Rechnungen', en: 'Invoices' } },
      { to: '/catalog', label: { de: 'Katalog', en: 'Catalog' } },
    ],
  },
  { to: '/employees', icon: HardHat, label: { de: 'Mitarbeiter', en: 'Employees' } },
]
