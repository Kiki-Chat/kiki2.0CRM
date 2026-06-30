// Technician portal shell — Track A, Phase 4. A toned-down, light CRM for field
// technicians (users.role='technician'). Rendered by ProtectedRoute INSTEAD of the
// full AppLayout, so a technician never sees the office CRM. Tabs (state-driven, so
// it works regardless of URL): Meine Aufträge (own jobs), Mein Kalender (Google
// connect), Abwesenheit. Reuses the existing employee self-service pages — they
// already self-resolve from the logged-in user.
import { useState } from 'react'
import { Calendar, CalendarClock, type LucideIcon, LogOut, Wrench } from 'lucide-react'

import { useAuth } from '../auth/AuthProvider'
import { useMe } from '../lib/useMe'
import { MyAbsencePage } from '../pages/MyAbsencePage'
import { MyCalendarPage } from '../pages/MyCalendarPage'
import { TechnicianJobsPage } from '../pages/TechnicianJobsPage'

type Tab = 'jobs' | 'calendar' | 'absence'
const TABS: { key: Tab; label: string; icon: LucideIcon }[] = [
  { key: 'jobs', label: 'Meine Aufträge', icon: Wrench },
  { key: 'calendar', label: 'Mein Kalender', icon: Calendar },
  { key: 'absence', label: 'Abwesenheit', icon: CalendarClock },
]

export function TechnicianApp() {
  const { signOut } = useAuth()
  const { me } = useMe()
  const [tab, setTab] = useState<Tab>('jobs')
  return (
    <div className="min-h-screen bg-alt">
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-2xl items-center justify-between gap-3 px-4 py-3">
          <div className="min-w-0">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">Techniker-Portal</div>
            <div className="truncate text-base font-bold text-text">{me?.org_name ?? 'HeyKiki'}</div>
          </div>
          <div className="flex items-center gap-3">
            {me?.full_name && <span className="hidden text-sm text-body sm:inline">Hallo {me.full_name}</span>}
            <button
              onClick={() => signOut()}
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm text-body hover:bg-alt"
            >
              <LogOut size={15} /> Abmelden
            </button>
          </div>
        </div>
        <nav className="mx-auto flex max-w-2xl gap-1 overflow-x-auto px-4">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`inline-flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 text-sm ${
                tab === t.key ? 'border-green-deep font-medium text-text' : 'border-transparent text-muted hover:text-body'
              }`}
            >
              <t.icon size={15} /> {t.label}
            </button>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-2xl p-4 pb-12">
        {tab === 'jobs' && <TechnicianJobsPage />}
        {tab === 'calendar' && <MyCalendarPage />}
        {tab === 'absence' && <MyAbsencePage />}
      </main>
    </div>
  )
}
