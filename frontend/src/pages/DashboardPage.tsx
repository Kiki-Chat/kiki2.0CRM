import { useQuery } from '@tanstack/react-query'
import { Calendar, CheckCircle2, ChevronLeft, ChevronRight, Clock, Euro, FileText, LayoutDashboard, Phone, Sparkles, X } from 'lucide-react'
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
import { usePosteingang, usePosteingangActions, type DecisionVM } from './posteingang/api'

// The overview tab leads with the "Jetzt entscheiden" decision deck (the pending
// decisions from /api/actions/pending) + call performance (<AnrufeTab/>).

const TABS = [
  { id: 'overview', label: 'Übersicht', icon: LayoutDashboard },
  { id: 'finanzen', label: 'Finanzen', icon: Euro },
  { id: 'ki-nutzung', label: 'KI-Nutzung', icon: Clock },
  { id: 'ki-insights', label: 'KI-Auswertung', icon: Sparkles },
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
  const { me, isAdmin } = useMe()
  // Admin login REPRESENTS the company → the headline is the company name (the
  // greeting may add the admin's own first name). Employee login is a PERSON →
  // the headline is THEIR name and the company name is intentionally NOT shown
  // here (the employee portal is personal, not company-branded).
  const company = me?.org_name ?? me?.full_name ?? 'Willkommen'
  const fullName = me?.full_name?.trim() || null
  const firstName = fullName?.split(/\s+/)[0] ?? null
  const headline = isAdmin ? company : (fullName ?? 'Willkommen')
  const greetName = isAdmin ? (firstName && firstName !== company ? firstName : null) : firstName
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
        <p className="text-[15px] font-semibold text-muted">{greeting}{greetName ? `, ${greetName}` : ','}</p>
        <h1 className="text-3xl font-extrabold tracking-tight text-text">{headline}</h1>
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
        {tab === 'overview' && <OverviewTab />}
        {tab === 'finanzen' && <FinanzenTab />}
        {tab === 'ki-nutzung' && <KiNutzungTab />}
        {tab === 'ki-insights' && <KiInsightsTab />}
      </div>
    </div>
  )
}

function OverviewTab() {
  if (!isSupabaseConfigured) {
    return (
      <Card className="text-sm text-muted">
        Verbinde Supabase und die Backend-API, um Live-Daten zu laden.
      </Card>
    )
  }
  return (
    <div className="space-y-5">
      <HeroDeck />
      <AnrufeTab />
    </div>
  )
}

const TYPE_ICON: Record<string, typeof Phone> = {
  termin: Calendar,
  rueckruf: Phone,
  storno: X,
  kva: FileText,
  reschedule: Clock,
}

// The dashboard hero: keeps the brand slogan + 3D Kiki on the right; the left
// column carries a COMPACT "Jetzt entscheiden" stacked deck of the pending
// decisions (/api/actions/pending). The slogan stays the headline; the decision
// count is only a subheading so it never crowds the slogan or the 3D model.
function HeroDeck() {
  const navigate = useNavigate()
  const { isAdmin } = useMe()
  const { decisions, callsCount, loading } = usePosteingang()
  // Employee portal: frame the deck as the person's own to-do list ("Aufgaben");
  // for the admin/company login it stays the org decision queue ("Entscheidungen").
  const taskNoun = isAdmin ? 'Entscheidung' : 'Aufgabe'
  const taskNounPl = isAdmin ? 'Entscheidungen' : 'Aufgaben'
  const { resolve } = usePosteingangActions()
  const { data: cases } = useQuery({
    queryKey: ['cases'],
    queryFn: () => apiFetch<{ id: string }[]>('/api/cases'),
    enabled: isSupabaseConfigured,
    staleTime: 60_000,
  })
  const [index, setIndex] = useState(0)
  const [busy, setBusy] = useState(false)

  const total = decisions.length
  const casesCount = cases?.length ?? 0
  const i = total ? Math.min(index, total - 1) : 0

  async function act(d: DecisionVM, choice: 'primary' | 'secondary' | 'tertiary') {
    if (busy) return
    // AI-suggested KVA/Rechnung: open the pre-filled create-form instead of POSTing.
    if (choice === 'primary' && d.route) {
      navigate(d.route)
      return
    }
    setBusy(true)
    try {
      await resolve(d, choice)
    } finally {
      setBusy(false)
    }
    setIndex((x) => Math.max(0, Math.min(x, total - 2)))
  }

  return (
    <section className="relative overflow-hidden rounded-2xl border border-border bg-gradient-to-br from-green-tint-50 via-surface to-surface shadow-e1">
      <div
        aria-hidden
        className="kiki-glow pointer-events-none absolute right-[130px] top-1/2 hidden h-[340px] w-[340px] rounded-full bg-green-primary/20 blur-3xl lg:block"
      />
      <div className="relative z-10 max-w-[640px] p-6 sm:p-7">
        <div className="inline-flex items-center gap-2 text-[11px] font-extrabold uppercase tracking-[0.08em] text-green-deep">
          <span className="h-1.5 w-1.5 rounded-full bg-green-primary shadow-[0_0_0_4px_var(--green-tint-100)]" />
          HeyKiki
        </div>
        <h2 className="mt-2.5 text-[22px] font-extrabold leading-tight tracking-tight text-text sm:text-[26px]">
          Kiki, die erste KI‑Sekretärin für{' '}
          <span className="text-green-primary">Handwerksbetriebe</span>
        </h2>

        <div className="mt-4 flex items-end justify-between gap-3">
          <div>
            <p className="text-sm font-bold text-text">
              {total === 0
                ? 'Alles erledigt 🎉'
                : `${total} ${total === 1 ? `${taskNoun} wartet` : `${taskNounPl} warten`} auf dich`}
            </p>
            <p className="mt-0.5 text-[11px] font-medium text-muted">
              {callsCount} Anrufe · {casesCount} Vorgänge · {total} offen
            </p>
          </div>
        {total > 1 && (
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setIndex((x) => Math.max(0, x - 1))}
              disabled={i === 0}
              className="grid h-8 w-8 place-items-center rounded-full border border-border bg-surface text-muted transition hover:text-text disabled:opacity-30"
            >
              <ChevronLeft size={16} />
            </button>
            <span className="min-w-[44px] text-center text-xs font-semibold text-muted">{i + 1} / {total}</span>
            <button
              onClick={() => setIndex((x) => Math.min(total - 1, x + 1))}
              disabled={i >= total - 1}
              className="grid h-8 w-8 place-items-center rounded-full border border-border bg-surface text-muted transition hover:text-text disabled:opacity-30"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        )}
      </div>

        <div className="relative mt-3 h-[150px] max-w-[440px]">
        {loading && total === 0 && (
          <div className="flex h-full items-center justify-center text-sm text-muted">Entscheidungen werden geladen…</div>
        )}
        {!loading && total === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-1 text-center">
            <CheckCircle2 size={28} className="text-green-primary" />
            <p className="text-sm font-semibold text-text">Keine offenen Entscheidungen</p>
            <p className="text-xs text-muted">Kiki hat alles abgearbeitet — neue Anrufe erscheinen hier automatisch.</p>
          </div>
        )}
        {decisions.map((d, j) => {
          const p = j - i
          if (p < 0 || p > 2) return null
          const Icon = TYPE_ICON[d.type] ?? Sparkles
          const front = p === 0
          return (
            <div
              key={d.actionKey}
              onClick={() => !front && setIndex(j)}
              className="absolute inset-x-0 top-0 rounded-xl border bg-surface p-3.5 shadow-e1 transition-all duration-300"
              style={{
                transform: `translateY(${p * 12}px) scale(${1 - p * 0.04})`,
                opacity: p === 0 ? 1 : p === 1 ? 0.65 : 0.4,
                zIndex: 30 - p,
                borderColor: front ? d.accent : 'var(--border)',
                pointerEvents: front ? 'auto' : 'none',
              }}
            >
              <div className="flex items-center justify-between gap-2">
                <span
                  className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-bold"
                  style={{ color: d.accent, backgroundColor: `color-mix(in srgb, ${d.accent} 12%, transparent)` }}
                >
                  <Icon size={12} /> {d.typeLabel}
                </span>
                {d.caseTicket && <span className="truncate font-mono text-[11px] text-muted">{d.caseTicket}</span>}
              </div>
              <p className="mt-1.5 truncate text-sm font-bold text-text">{d.title}</p>
              <p className="mt-0.5 truncate text-[11px] text-muted">
                {d.customer}
                {d.caseName ? ` · ${d.caseName}` : ''}
              </p>
              {front && (
                <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                  <button
                    disabled={busy}
                    onClick={() => act(d, 'primary')}
                    className="rounded-lg px-3 py-1.5 text-xs font-bold text-white transition disabled:opacity-50"
                    style={{ backgroundColor: d.accent }}
                  >
                    {d.primary}
                  </button>
                  {d.secondary && (
                    <button
                      disabled={busy}
                      onClick={() => act(d, 'secondary')}
                      className="rounded-lg border border-border bg-alt px-3 py-1.5 text-xs font-semibold text-text transition hover:border-green-tint-200 disabled:opacity-50"
                    >
                      {d.secondary}
                    </button>
                  )}
                  {d.tertiary && (
                    <button
                      disabled={busy}
                      onClick={() => act(d, 'tertiary')}
                      className="rounded-lg border border-border bg-alt px-3 py-1.5 text-xs font-semibold text-muted transition hover:text-text disabled:opacity-50"
                    >
                      {d.tertiary}
                    </button>
                  )}
                  <button
                    onClick={() => navigate('/posteingang')}
                    className="ml-auto self-center text-xs font-medium text-muted hover:text-text"
                  >
                    Alle ansehen →
                  </button>
                </div>
              )}
            </div>
          )
        })}
        </div>
      </div>
      <img
        src={kikiAvatar}
        alt="Kiki"
        className="kiki-live pointer-events-none absolute bottom-0 right-[-24px] hidden h-[280px] w-auto select-none lg:block xl:right-2"
      />
    </section>
  )
}
