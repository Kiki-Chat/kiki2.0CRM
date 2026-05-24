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

import { Card } from '../components/ui/Card'
import { KpiCard } from '../components/ui/KpiCard'
import { Tag } from '../components/ui/Tag'
import { apiFetch } from '../lib/api'
import { isSupabaseConfigured } from '../lib/env'
import { cn } from '../lib/utils'

interface OverviewData {
  kpis: { open_inquiries: number; total_customers: number; upcoming_appointments: number }
  open_tasks: Array<{ id: string; title: string | null; type: string | null; status: string }>
  upcoming_appointments: Array<{
    id: string
    title: string | null
    scheduled_at: string | null
    status: string
  }>
}

const TABS = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'calls', label: 'Calls', icon: Phone },
  { id: 'finance', label: 'Finance', icon: Euro },
  { id: 'time', label: 'Time Tracking', icon: Clock },
  { id: 'ai', label: 'AI Insights', icon: Sparkles },
] as const

export function DashboardPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]['id']>('overview')

  return (
    <div className="p-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-text">Dashboard</h1>
        <p className="mt-1 text-sm text-muted">
          {new Date().toLocaleDateString('en-GB', {
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
        {tab === 'overview' ? (
          <OverviewTab />
        ) : (
          <Card className="text-sm text-muted">This tab ships in a later phase.</Card>
        )}
      </div>
    </div>
  )
}

function OverviewTab() {
  const { data, isLoading, error } = useQuery<OverviewData>({
    queryKey: ['dashboard-overview'],
    queryFn: () => apiFetch<OverviewData>('/api/dashboard/overview'),
    enabled: isSupabaseConfigured,
  })

  if (!isSupabaseConfigured) {
    return (
      <Card className="text-sm text-muted">
        Connect Supabase and the backend API to load live dashboard data.
      </Card>
    )
  }

  if (isLoading) return <Card className="text-sm text-muted">Loading overview…</Card>
  if (error)
    return (
      <Card className="text-sm text-error">
        Could not load overview: {(error as Error).message}
      </Card>
    )

  const kpis = data?.kpis
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <KpiCard
          label="Open Inquiries"
          value={kpis?.open_inquiries ?? 0}
          icon={Sparkles}
          sub="awaiting action"
        />
        <KpiCard
          label="Total Customers"
          value={kpis?.total_customers ?? 0}
          icon={Users2}
          sub="in this organization"
        />
        <KpiCard
          label="Upcoming Appointments"
          value={kpis?.upcoming_appointments ?? 0}
          icon={Calendar}
          sub="next 5 scheduled"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <h2 className="mb-3 text-sm font-bold text-text">Open Tasks</h2>
          {data?.open_tasks.length ? (
            <ul className="space-y-2">
              {data.open_tasks.map((t) => (
                <li key={t.id} className="flex items-center gap-2.5 rounded-md p-2 hover:bg-alt">
                  <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-green-primary" />
                  <span className="flex-1 truncate text-sm text-text">
                    {t.title ?? 'Untitled'}
                  </span>
                  {t.type && <Tag variant="info">{t.type}</Tag>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">No open tasks.</p>
          )}
        </Card>

        <Card>
          <h2 className="mb-3 text-sm font-bold text-text">Upcoming Appointments</h2>
          {data?.upcoming_appointments.length ? (
            <ul className="space-y-2">
              {data.upcoming_appointments.map((a) => (
                <li key={a.id} className="flex items-center gap-2.5 rounded-md p-2 hover:bg-alt">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm text-text">{a.title ?? 'Appointment'}</div>
                    <div className="text-xs text-muted">
                      {a.scheduled_at
                        ? new Date(a.scheduled_at).toLocaleString('en-GB')
                        : '—'}
                    </div>
                  </div>
                  <Tag variant="green">{a.status}</Tag>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">No upcoming appointments.</p>
          )}
        </Card>
      </div>
    </div>
  )
}
