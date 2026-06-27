import { useQuery } from '@tanstack/react-query'
import { Check, Lock, Sparkles } from 'lucide-react'
import { Outlet, useNavigate } from 'react-router-dom'

import { apiFetch } from '../lib/api'
import { FEATURE_META, shortPlanName } from '../lib/entitlements'
import { useMe } from '../lib/useMe'

interface FeatureTeaser { count: number; noun: string }

/**
 * Route-level entitlement gate (Phase 2). Use as a layout route in App.tsx:
 *   <Route element={<FeatureRoute feature="finance" />}>…gated pages…</Route>
 * Renders the page (Outlet) when the org has the feature; otherwise the soft-preview
 * upgrade panel. super_admin bypasses. NOTE: this is the cosmetic/UX gate — the
 * authoritative block is the backend require_entitlement (402) on the data routes.
 */
export function FeatureRoute({ feature }: { feature: string }) {
  const { hasFeature, isLoading } = useMe()
  if (isLoading) return null
  return hasFeature(feature) ? <Outlet /> : <LockedFeature feature={feature} />
}

/** The locked-menu soft preview: what the feature does + which plan unlocks it +
 * a one-click route to the plan switcher. */
export function LockedFeature({ feature }: { feature: string }) {
  const meta = FEATURE_META[feature]
  const navigate = useNavigate()
  // Real count from the org's own data (always-process) → personalises the lock into a
  // "you already have value waiting" hook. Best-effort; hidden when 0.
  const teaserQ = useQuery({
    queryKey: ['entitlements', 'teaser'],
    queryFn: () => apiFetch<Record<string, FeatureTeaser>>('/api/entitlements/teaser'),
    retry: false,
    staleTime: 60_000,
  })
  const teaser = teaserQ.data?.[feature]
  const hasTeaser = (teaser?.count ?? 0) > 0
  if (!meta) return null
  return (
    <div className="flex min-h-[60vh] items-center justify-center p-6">
      <div className="w-full max-w-md rounded-2xl border border-border bg-surface p-8 text-center shadow-sm">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-green-tint-100">
          <Lock size={22} className="text-green-deep" />
        </div>
        <h2 className="mt-4 text-lg font-bold text-text">{meta.label} ist nicht in deinem Tarif enthalten</h2>
        <p className="mt-1 text-sm text-muted">
          Ab <span className="font-semibold text-text">{shortPlanName(meta.minPlan)}</span> verfügbar.
        </p>

        {hasTeaser && (
          <div className="relative mt-5 overflow-hidden rounded-xl border border-green-primary/40">
            <div className="space-y-2 p-3 blur-[3px] select-none" aria-hidden>
              {[0, 1, 2].map((i) => (
                <div key={i} className="flex items-center justify-between">
                  <div className="h-3 w-32 rounded bg-alt" />
                  <div className="h-3 w-12 rounded bg-green-tint-200" />
                </div>
              ))}
            </div>
            <div className="absolute inset-0 flex items-center justify-center bg-surface/55 px-4">
              <p className="flex items-center gap-1.5 text-sm font-semibold text-text">
                <Sparkles size={15} className="shrink-0 text-green-deep" />
                Kiki hat aus deinen Anrufen{' '}
                <span className="text-green-deep">{teaser!.count} {teaser!.noun}</span> vorbereitet
              </p>
            </div>
          </div>
        )}

        <ul className="mx-auto mt-5 max-w-xs space-y-2 text-left">
          {meta.pitch.map((b) => (
            <li key={b} className="flex items-start gap-2 text-sm text-body">
              <Check size={15} className="mt-0.5 shrink-0 text-green-deep" />
              <span>{b}</span>
            </li>
          ))}
        </ul>
        <button
          onClick={() => navigate('/settings/abrechnung')}
          className="mt-6 w-full rounded-lg bg-green-primary px-4 py-2.5 text-sm font-semibold text-white transition hover:brightness-110"
        >
          {hasTeaser ? `Freischalten — auf ${shortPlanName(meta.minPlan)} upgraden` : `Auf ${shortPlanName(meta.minPlan)} upgraden`}
        </button>
        <button
          onClick={() => navigate('/')}
          className="mt-2 w-full rounded-lg px-4 py-2 text-sm font-medium text-muted transition hover:bg-alt"
        >
          Zurück zur Übersicht
        </button>
      </div>
    </div>
  )
}
