import { useQuery } from '@tanstack/react-query'
import {
  Calendar,
  Clock,
  Euro,
  LayoutDashboard,
  Phone,
  Sparkles,
  Users2,
} from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { AnrufeTab } from '../components/dashboard/AnrufeTab'
import { FinanzenTab } from '../components/dashboard/FinanzenTab'
import { KiInsightsTab } from '../components/dashboard/KiInsightsTab'
import { KiNutzungTab } from '../components/dashboard/KiNutzungTab'
import { Card } from '../components/ui/Card'
import { KpiCard } from '../components/ui/KpiCard'
import { Tag } from '../components/ui/Tag'
import { apiFetch } from '../lib/api'
import { isSupabaseConfigured } from '../lib/env'
import { cn } from '../lib/utils'

interface OverviewData {
  kpis: { open_inquiries: number; total_customers: number; upcoming_appointments: number }
  open_tasks: Array<{
    id: string
    title: string | null
    type: string | null
    status: string
    customer_id: string | null
  }>
  upcoming_appointments: Array<{
    id: string
    title: string | null
    scheduled_at: string | null
    status: string
  }>
}

const TABS = [
  { id: 'overview', label: 'Übersicht', icon: LayoutDashboard },
  { id: 'anrufe', label: 'Anrufe', icon: Phone },
  { id: 'finanzen', label: 'Finanzen', icon: Euro },
  { id: 'ki-nutzung', label: 'KI-Nutzung', icon: Clock },
  { id: 'ki-insights', label: 'KI-Insights', icon: Sparkles },
] as const

export function DashboardPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]['id']>('overview')

  return (
    <div className="p-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-text">Dashboard</h1>
        <p className="mt-1 text-sm text-muted">
          {new Date().toLocaleDateString('de-DE', {
            weekday: 'long',
            day: 'numeric',
            month: 'long',
            year: 'numeric',
          })}
        </p>
      </div>

      <div className="mb-6 flex w-fit gap-0.5 rounded-lg border border-border bg-alt p-1">
        {TABS.map((t) => {
          const active = tab === t.id
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                'flex items-center gap-1.5 rounded-md px-4 py-2 text-sm transition-colors',
                active
                  ? 'bg-surface font-semibold text-text shadow-e1'
                  : 'font-medium text-muted',
              )}
            >
              <t.icon size={14} className={active ? 'text-green-deep' : 'text-muted'} />
              {t.label}
            </button>
          )
        })}
      </div>

      <div key={tab} style={{ animation: 'fadeUp 220ms ease' }}>
        {tab === 'overview' && <OverviewTab />}
        {tab === 'anrufe' && <AnrufeTab />}
        {tab === 'finanzen' && <FinanzenTab />}
        {tab === 'ki-nutzung' && <KiNutzungTab />}
        {tab === 'ki-insights' && <KiInsightsTab />}
      </div>
    </div>
  )
}

function OverviewTab() {
  const navigate = useNavigate()
  // Each open task is an open inquiry tied to a customer → open that customer
  // (its activity timeline shows the inquiry). Fall back to the Anrufe list
  // when the inquiry has no linked customer.
  const goToTask = (customerId: string | null) =>
    navigate(customerId ? `/customers/${customerId}` : '/calls')
  // Open the calendar focused on the appointment's date with its detail modal
  // (CalendarPage reads ?date= & ?appointment=). Local date keeps the month in
  // sync with the calendar's own (local-tz) rendering.
  const goToAppointment = (id: string, scheduledAt: string | null) => {
    const date = scheduledAt ? new Date(scheduledAt).toLocaleDateString('en-CA') : null
    navigate(`/calendar?appointment=${id}${date ? `&date=${date}` : ''}`)
  }
  const { data, isLoading, error } = useQuery<OverviewData>({
    queryKey: ['dashboard-overview'],
    queryFn: () => apiFetch<OverviewData>('/api/dashboard/overview'),
    enabled: isSupabaseConfigured,
  })

  if (!isSupabaseConfigured) {
    return (
      <Card className="text-sm text-muted">
        Verbinden Sie Supabase und die Backend-API, um Live-Daten zu laden.
      </Card>
    )
  }

  if (isLoading) return <Card className="text-sm text-muted">Übersicht wird geladen…</Card>
  if (error)
    return (
      <Card className="text-sm text-error">
        Übersicht konnte nicht geladen werden: {(error as Error).message}
      </Card>
    )

  const kpis = data?.kpis
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <KpiCard label="Offene Anfragen" value={kpis?.open_inquiries ?? 0} icon={Sparkles} sub="warten auf Bearbeitung" onClick={() => navigate('/calls')} />
        <KpiCard label="Kunden gesamt" value={kpis?.total_customers ?? 0} icon={Users2} sub="in dieser Organisation" onClick={() => navigate('/customers')} />
        <KpiCard label="Anstehende Termine" value={kpis?.upcoming_appointments ?? 0} icon={Calendar} sub="nächste 5 geplant" onClick={() => navigate('/calendar')} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <h2 className="mb-3 text-sm font-bold text-text">Offene Aufgaben</h2>
          {data?.open_tasks.length ? (
            <ul className="space-y-2">
              {data.open_tasks.map((t) => (
                <li
                  key={t.id}
                  onClick={() => goToTask(t.customer_id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      goToTask(t.customer_id)
                    }
                  }}
                  className="flex cursor-pointer items-center gap-2.5 rounded-md p-2 hover:bg-alt"
                >
                  <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-green-primary" />
                  <span className="flex-1 truncate text-sm text-text">{t.title ?? 'Ohne Titel'}</span>
                  {t.type && <Tag variant="info">{t.type}</Tag>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">Keine offenen Aufgaben.</p>
          )}
        </Card>

        <Card>
          <h2 className="mb-3 text-sm font-bold text-text">Anstehende Termine</h2>
          {data?.upcoming_appointments.length ? (
            <ul className="space-y-2">
              {data.upcoming_appointments.map((a) => (
                <li
                  key={a.id}
                  onClick={() => goToAppointment(a.id, a.scheduled_at)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      goToAppointment(a.id, a.scheduled_at)
                    }
                  }}
                  className="flex cursor-pointer items-center gap-2.5 rounded-md p-2 hover:bg-alt"
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm text-text">{a.title ?? 'Termin'}</div>
                    <div className="text-xs text-muted">
                      {a.scheduled_at ? new Date(a.scheduled_at).toLocaleString('de-DE') : '—'}
                    </div>
                  </div>
                  <Tag variant="green">{a.status}</Tag>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">Keine anstehenden Termine.</p>
          )}
        </Card>
      </div>
    </div>
  )
}
