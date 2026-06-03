import { useQuery } from '@tanstack/react-query'
import {
  Calendar,
  Clock,
  Euro,
  FileText,
  LayoutDashboard,
  ListChecks,
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
import kikiAvatar from '../assets/kiki-avatar.png'
import { apiFetch } from '../lib/api'
import { isSupabaseConfigured } from '../lib/env'
import { useMe } from '../lib/useMe'
import { cn } from '../lib/utils'

interface OverviewData {
  kpis: {
    open_inquiries: number
    total_customers: number
    upcoming_appointments: number
    calls_today: number
    inquiries_today: number
    kva_pending: number
  }
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

function greetingFor(hour: number): string {
  if (hour < 11) return 'Guten Morgen'
  if (hour < 18) return 'Guten Tag'
  return 'Guten Abend'
}

export function DashboardPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]['id']>('overview')
  const { me } = useMe()
  // Per Amber: the prominent greeting name = the real COMPANY name (org_name),
  // not a hardcoded person. Falls back to the user's own name, then a generic.
  const company = me?.org_name ?? me?.full_name ?? 'Willkommen'
  const now = new Date()
  const greeting = greetingFor(now.getHours())
  const today = now.toLocaleDateString('de-DE', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })

  return (
    <div className="p-8">
      <div className="mb-6">
        <p className="text-[15px] font-semibold text-muted">{greeting},</p>
        <h1 className="text-3xl font-extrabold tracking-tight text-text">{company}</h1>
        <p className="mt-1 text-sm text-muted">{today}</p>
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
        {tab === 'overview' && <OverviewTab company={company} />}
        {tab === 'anrufe' && <AnrufeTab />}
        {tab === 'finanzen' && <FinanzenTab />}
        {tab === 'ki-nutzung' && <KiNutzungTab />}
        {tab === 'ki-insights' && <KiInsightsTab />}
      </div>
    </div>
  )
}

function OverviewTab({ company }: { company: string }) {
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
  const callsToday = kpis?.calls_today ?? 0
  const inquiriesToday = kpis?.inquiries_today ?? 0

  return (
    <div className="space-y-5">
      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden rounded-2xl border border-border bg-gradient-to-br from-green-tint-50 via-surface to-surface shadow-e1">
        {/* soft glow behind the avatar */}
        <div
          aria-hidden
          className="kiki-glow pointer-events-none absolute right-[130px] top-1/2 hidden h-[340px] w-[340px] rounded-full bg-green-primary/20 blur-3xl lg:block"
        />
        <div className="relative z-10 max-w-[600px] p-7 sm:p-9">
          <div className="inline-flex items-center gap-2 text-xs font-extrabold uppercase tracking-[0.08em] text-green-deep">
            <span className="h-1.5 w-1.5 rounded-full bg-green-primary shadow-[0_0_0_4px_var(--green-tint-100)]" />
            HeyKiki
          </div>
          <h2 className="mt-3 text-2xl font-extrabold leading-tight tracking-tight text-text sm:text-[28px]">
            Kiki, die erste KI‑Bürokraft für{' '}
            <span className="text-green-primary">Handwerksbetriebe</span>
          </h2>

          <div className="mt-4 rounded-2xl border border-border bg-surface/85 p-4 shadow-e1 backdrop-blur">
            <p className="text-[15px] leading-relaxed text-body">
              Hey <strong className="font-bold text-text">{company}</strong>, ich habe heute{' '}
              <span className="font-extrabold text-info">
                {callsToday} {callsToday === 1 ? 'Anruf' : 'Anrufe'}
              </span>{' '}
              und{' '}
              <span className="font-extrabold text-green-primary">
                {inquiriesToday} {inquiriesToday === 1 ? 'Anfrage' : 'Anfragen'}
              </span>{' '}
              empfangen. Wie soll ich fortfahren?
            </p>
          </div>

          <div className="mt-4 flex flex-wrap gap-3">
            <button
              onClick={() => navigate('/calls')}
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-alt px-4 py-2.5 text-sm font-bold text-text transition hover:border-green-tint-200 hover:bg-green-tint-50"
            >
              <Phone size={15} /> {callsToday} Anrufe ansehen
            </button>
            <button
              onClick={() => navigate('/calls?status=open&tab=anfragen')}
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-alt px-4 py-2.5 text-sm font-bold text-text transition hover:border-green-tint-200 hover:bg-green-tint-50"
            >
              <Sparkles size={15} /> {inquiriesToday} Anfragen ansehen
            </button>
          </div>
        </div>

        {/* avatar bleeding off the right edge (clipped by overflow-hidden) */}
        <img
          src={kikiAvatar}
          alt="Kiki"
          className="kiki-live pointer-events-none absolute bottom-0 right-[-24px] hidden h-[300px] w-auto select-none lg:block xl:right-2"
        />
      </section>

      {/* ── KPI row ──────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <KpiCard
          label="Offene Anfragen"
          value={kpis?.open_inquiries ?? 0}
          icon={Sparkles}
          sub="warten auf Bearbeitung"
          onClick={() => navigate('/calls?status=open&tab=anfragen')}
        />
        <KpiCard
          label="Kunden gesamt"
          value={kpis?.total_customers ?? 0}
          icon={Users2}
          sub="in dieser Organisation"
          onClick={() => navigate('/customers')}
        />
        <KpiCard
          label="KVA pending"
          value={kpis?.kva_pending ?? 0}
          icon={FileText}
          sub="Kostenvoranschläge offen"
          onClick={() => navigate('/cost-estimates')}
        />
      </div>

      {/* ── Panels ───────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <div className="mb-2 flex items-center gap-3">
            <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-green-tint-100 text-green-deep">
              <ListChecks size={17} />
            </div>
            <div className="min-w-0">
              <h2 className="text-base font-bold text-text">Offene Aufgaben</h2>
              <p className="text-xs text-muted">Von Kiki erkannt · warten auf Freigabe</p>
            </div>
          </div>
          {data?.open_tasks.length ? (
            <ul className="space-y-0.5">
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
          <div className="mb-2 flex items-center gap-3">
            <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-green-tint-100 text-green-deep">
              <Calendar size={17} />
            </div>
            <div className="min-w-0">
              <h2 className="text-base font-bold text-text">Anstehende Termine</h2>
              <p className="text-xs text-muted">Nächste 5 geplant</p>
            </div>
          </div>
          {data?.upcoming_appointments.length ? (
            <ul className="space-y-0.5">
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
