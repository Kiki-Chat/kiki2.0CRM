import { useQuery } from '@tanstack/react-query'
import { Clock, Euro, LayoutDashboard, Phone, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { AnrufeTab } from '../components/dashboard/AnrufeTab'
import { FinanzenTab } from '../components/dashboard/FinanzenTab'
import { KiInsightsTab } from '../components/dashboard/KiInsightsTab'
import { KiNutzungTab } from '../components/dashboard/KiNutzungTab'
import { Card } from '../components/ui/Card'
import kikiAvatar from '../assets/kiki-avatar.png'
import { apiFetch } from '../lib/api'
import { isSupabaseConfigured } from '../lib/env'
import { useMe } from '../lib/useMe'
import { cn } from '../lib/utils'

// The overview tab now leads with call performance (Gesamtanrufe / Beantwortet /
// Durchschnittsdauer + graphs, via <AnrufeTab/>). The hero bubble still needs the
// two "heute" counts, so this is all we read from /api/dashboard/overview.
interface OverviewData {
  kpis: {
    calls_today: number
    inquiries_today: number
  }
}

const TABS = [
  { id: 'overview', label: 'Übersicht', icon: LayoutDashboard },
  { id: 'finanzen', label: 'Finanzen', icon: Euro },
  { id: 'ki-nutzung', label: 'KI-Nutzung', icon: Clock },
  { id: 'ki-insights', label: 'KI-Insights', icon: Sparkles },
] as const

// Current hour in Europe/Berlin, regardless of the viewer's own timezone — so
// the greeting + date always reflect German business time.
function berlinHour(date: Date): number {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/Berlin',
    hour: '2-digit',
    hour12: false,
  }).formatToParts(date)
  return Number(parts.find((p) => p.type === 'hour')?.value ?? '0') % 24
}

function greetingFor(hour: number): string {
  if (hour >= 5 && hour < 12) return 'Guten Morgen' // 05:00–12:00
  if (hour >= 12 && hour < 15) return 'Guten Mittag' // 12:00–15:00
  if (hour >= 15 && hour < 18) return 'Guten Tag' // 15:00–18:00
  if (hour >= 18 && hour < 21) return 'Guten Abend' // 18:00–21:00
  return 'Gute Nacht' // 21:00–05:00
}

export function DashboardPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]['id']>('overview')
  const { me } = useMe()
  // Per Amber: the prominent greeting name = the real COMPANY name (org_name),
  // not a hardcoded person. Falls back to the user's own name, then a generic.
  const company = me?.org_name ?? me?.full_name ?? 'Willkommen'
  // Greeting is personalised to the logged-in user (their own name); the company
  // name stays the prominent identity below it. Falls back to no name if unset.
  const person = me?.full_name?.trim() || null
  const now = new Date()
  const greeting = greetingFor(berlinHour(now))
  const today = now.toLocaleDateString('de-DE', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'Europe/Berlin',
  })

  return (
    <div className="p-8 font-poster">
      <div className="mb-6">
        <p className="text-[15px] font-semibold text-muted">{greeting}{person && person !== company ? `, ${person}` : ','}</p>
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
        {tab === 'finanzen' && <FinanzenTab />}
        {tab === 'ki-nutzung' && <KiNutzungTab />}
        {tab === 'ki-insights' && <KiInsightsTab />}
      </div>
    </div>
  )
}

function OverviewTab({ company }: { company: string }) {
  const navigate = useNavigate()
  // The hero bubble shows today's tallies; the stats + graphs below come from
  // <AnrufeTab/> (its own period-filtered query). We only read the two "heute"
  // counts here, so a slow/failed overview fetch just leaves the bubble at 0 —
  // it never blocks the call-stats block from rendering.
  const { data } = useQuery<OverviewData>({
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

  const kpis = data?.kpis
  const callsToday = kpis?.calls_today ?? 0
  const actionsToday = kpis?.inquiries_today ?? 0

  return (
    <div className="space-y-5">
      {/* ── Hero (poster stays; "Anfragen" → "Aktionen") ─────────────────── */}
      <section className="relative overflow-hidden rounded-2xl border border-border bg-gradient-to-br from-green-tint-50 via-surface to-surface shadow-e1">
        {/* soft glow behind the avatar */}
        <div
          aria-hidden
          className="kiki-glow pointer-events-none absolute right-[130px] top-1/2 hidden h-[340px] w-[340px] rounded-full bg-green-primary/20 blur-3xl lg:block"
        />
        <div className="relative z-10 max-w-[600px] p-8 sm:p-10">
          <div className="inline-flex items-center gap-2 text-xs font-extrabold uppercase tracking-[0.08em] text-green-deep">
            <span className="h-1.5 w-1.5 rounded-full bg-green-primary shadow-[0_0_0_4px_var(--green-tint-100)]" />
            HeyKiki
          </div>
          <h2 className="mt-3 text-2xl font-extrabold leading-tight tracking-tight text-text sm:text-[28px]">
            Kiki, die erste KI‑Sekretärin für{' '}
            <span className="text-green-primary">Handwerksbetriebe</span>
          </h2>

          <div className="speech-bubble relative mt-5 max-w-[480px] rounded-2xl rounded-bl-md border border-border bg-surface p-4 shadow-e1">
            <p className="text-[15px] leading-relaxed text-body">
              Hey <strong className="font-bold text-text">{company}</strong>, ich habe heute{' '}
              <span className="font-extrabold text-info">
                {callsToday} {callsToday === 1 ? 'Anruf' : 'Anrufe'}
              </span>{' '}
              und{' '}
              <span className="font-extrabold text-green-primary">
                {actionsToday} {actionsToday === 1 ? 'Aktion' : 'Aktionen'}
              </span>{' '}
              empfangen. Wie soll ich fortfahren?
            </p>
          </div>

          <div className="mt-6 flex flex-wrap gap-3">
            <button
              onClick={() => navigate('/calls?direction=inbound&status=open&tab=anfragen')}
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-alt px-4 py-2.5 text-sm font-bold text-text transition hover:border-green-tint-200 hover:bg-green-tint-50"
            >
              <Phone size={15} /> {callsToday} {callsToday === 1 ? 'Anruf' : 'Anrufe'} ansehen
            </button>
            <button
              onClick={() => navigate('/calls?status=open&tab=aktionen')}
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-alt px-4 py-2.5 text-sm font-bold text-text transition hover:border-green-tint-200 hover:bg-green-tint-50"
            >
              <Sparkles size={15} /> {actionsToday} {actionsToday === 1 ? 'Aktion' : 'Aktionen'} ansehen
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

      {/* ── Call performance — the new headline stats + graphs ───────────── */}
      <AnrufeTab />
    </div>
  )
}
