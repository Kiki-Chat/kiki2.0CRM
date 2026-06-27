import { Check, Lock } from 'lucide-react'
import { Outlet, useNavigate } from 'react-router-dom'

import { FEATURE_META, shortPlanName } from '../lib/entitlements'
import { useMe } from '../lib/useMe'

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
          Auf {shortPlanName(meta.minPlan)} upgraden
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
