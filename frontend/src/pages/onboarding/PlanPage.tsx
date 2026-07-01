import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CalendarClock, Check, Loader2, ShieldCheck } from 'lucide-react'

import { cn } from '../../lib/utils'
import { createOnboardingCheckout, getOnboardingPlans, type PlanOption } from '../../lib/onboardingApi'
import { OnboardingLayout } from './OnboardingLayout'
import {
  CALENDLY_URL,
  PLAN_FEATURES,
  PLAN_ORDER,
  PLAN_TAGLINE,
  RECOMMENDED_PLAN,
} from './constants'
import { resolveSessionToken, withSession } from './session'

function euro(cents: number): string {
  return new Intl.NumberFormat('de-DE', {
    style: 'currency',
    currency: 'EUR',
    minimumFractionDigits: cents % 100 === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(cents / 100)
}

export function PlanPage() {
  const navigate = useNavigate()
  const [plans, setPlans] = useState<PlanOption[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [interval, setInterval] = useState<'month' | 'year'>('month')
  const [busyPlan, setBusyPlan] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Session token from the URL (?s=<token>) — resilient to refresh/back; the funnel
  // resumes the same lead instead of restarting.
  const token = useMemo(() => resolveSessionToken(window.location.search), [])

  useEffect(() => {
    if (!token) {
      navigate('/onboarding', { replace: true })
      return
    }
    getOnboardingPlans()
      .then(setPlans)
      .catch((e) => setLoadError(e instanceof Error ? e.message : 'Tarife konnten nicht geladen werden.'))
  }, [navigate, token])

  const ordered = useMemo(() => {
    if (!plans) return []
    return [...plans].sort((a, b) => PLAN_ORDER.indexOf(a.plan_title as never) - PLAN_ORDER.indexOf(b.plan_title as never))
  }, [plans])

  async function choose(plan: PlanOption) {
    if (!token) {
      navigate('/onboarding', { replace: true })
      return
    }
    setError(null)
    setBusyPlan(plan.plan_title)
    try {
      const { url } = await createOnboardingCheckout({
        token,
        plan_title: plan.plan_title,
        interval,
        return_origin: window.location.origin,
      })
      window.location.href = url
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Checkout konnte nicht gestartet werden.')
      setBusyPlan(null)
    }
  }

  return (
    <OnboardingLayout step={2}>
      <div className="mx-auto w-full max-w-3xl lg:max-w-none">
        <h1 className="text-2xl font-bold text-text">Wähle deinen Tarif</h1>
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-muted">
          <span className="inline-flex items-center gap-1.5">
            <ShieldCheck size={15} className="text-green-primary" /> 30 Tage Geld-zurück-Garantie
          </span>
          <a
            href={CALENDLY_URL}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 text-green-deep underline-offset-2 hover:underline"
          >
            <CalendarClock size={15} /> Lieber zuerst eine Demo? Termin buchen
          </a>
        </div>

        {/* Monthly / yearly toggle */}
        <div className="mt-5 inline-flex items-center rounded-full border border-border bg-alt p-1 text-sm">
          <button
            onClick={() => setInterval('month')}
            className={cn('rounded-full px-4 py-1.5 font-medium', interval === 'month' ? 'bg-green-primary text-white' : 'text-body')}
          >
            Monatlich
          </button>
          <button
            onClick={() => setInterval('year')}
            className={cn('rounded-full px-4 py-1.5 font-medium', interval === 'year' ? 'bg-green-primary text-white' : 'text-body')}
          >
            Jährlich
            <span className="ml-1.5 rounded-full bg-green-tint-100 px-1.5 py-0.5 text-[10px] font-bold text-green-deep">
              2 Monate gratis
            </span>
          </button>
        </div>

        {loadError && <div className="mt-6 text-sm text-error">{loadError}</div>}
        {!plans && !loadError && (
          <div className="mt-10 flex items-center gap-2 text-muted">
            <Loader2 size={16} className="animate-spin" /> Tarife werden geladen…
          </div>
        )}

        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-3">
          {ordered.map((p) => {
            const recommended = p.plan_title === RECOMMENDED_PLAN
            const perMonth = interval === 'year' ? Math.round(p.annual_cents / 12) : p.monthly_cents
            const busy = busyPlan === p.plan_title
            return (
              <div
                key={p.plan_title}
                className={cn(
                  'relative flex flex-col rounded-2xl border bg-surface p-5',
                  recommended ? 'border-green-primary ring-1 ring-green-primary shadow-e1' : 'border-border',
                )}
              >
                {recommended && (
                  <span className="absolute -top-2.5 left-5 rounded-full bg-green-primary px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white shadow">
                    Empfehlung
                  </span>
                )}
                <div className="text-base font-bold text-text">{p.plan_title.replace('Kiki ', '')}</div>
                <div className="text-xs text-muted">{PLAN_TAGLINE[p.plan_title] ?? ''}</div>

                <div className="mt-3 flex items-baseline gap-1">
                  <span className="text-3xl font-bold leading-none text-text">{euro(perMonth)}</span>
                  <span className="text-sm text-muted">/ Monat</span>
                </div>
                <div className="mt-1 text-xs text-muted">
                  {interval === 'year' ? `${euro(p.annual_cents)} jährlich · zzgl. MwSt.` : 'zzgl. 19 % MwSt.'}
                </div>

                <div className="mt-3 border-t border-border pt-3 text-xs font-semibold text-text">
                  {p.included_minutes} Freiminuten{' '}
                  <span className="font-normal text-muted">· dann {euro(p.overage_cents_per_min)}/Min.</span>
                </div>
                <div className="mt-1 text-xs text-muted">{p.seats} Benutzer</div>

                <ul className="mt-3 flex-1 space-y-1.5">
                  {(PLAN_FEATURES[p.plan_title] ?? []).map((f) => (
                    <li key={f} className="flex items-start gap-2 text-xs text-body">
                      <Check size={13} className="mt-0.5 shrink-0 text-green-deep" />
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>

                <button
                  onClick={() => choose(p)}
                  disabled={busy}
                  className={cn(
                    'mt-5 inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition disabled:opacity-60',
                    recommended
                      ? 'bg-green-primary text-white hover:brightness-110'
                      : 'border border-green-primary text-green-deep hover:bg-green-tint-100',
                  )}
                >
                  {busy && <Loader2 size={15} className="animate-spin" />}
                  {busy ? 'Weiterleitung…' : 'Auswählen'}
                </button>
              </div>
            )
          })}
        </div>

        {error && <div className="mt-4 text-sm text-error">{error}</div>}

        <button
          onClick={() => navigate(token ? withSession('/onboarding', token) : '/onboarding')}
          className="mt-6 text-sm text-muted underline-offset-2 hover:text-green-deep hover:underline"
        >
          ← Zurück
        </button>
      </div>
    </OnboardingLayout>
  )
}
