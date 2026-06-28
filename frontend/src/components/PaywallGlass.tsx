import { Check, Lock } from 'lucide-react'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import { FEATURE_META, shortPlanName } from '../lib/entitlements'

/** Paywall: real page renders underneath (read-only GETs succeed); a scrim blurs/dims
 * only the main content column — sidebar + topbar stay interactive for navigation.
 * Height is capped to the viewport so the CTA stays centered on tall pages (e.g. Vorgänge). */
export function PaywallGlass({ feature, children }: { feature: string; children: ReactNode }) {
  const meta = FEATURE_META[feature]
  const navigate = useNavigate()
  if (!meta) return <>{children}</>

  return (
    <div className="relative h-[calc(100dvh-3.5rem)] w-full overflow-hidden">
      <div className="pointer-events-none h-full select-none overflow-hidden" aria-hidden inert>
        {children}
      </div>

      <div className="absolute inset-0 z-30 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm sm:p-8">
        <div
          className="w-full max-w-md rounded-2xl border border-border bg-surface p-8 text-center shadow-e3"
          onClick={(e) => e.stopPropagation()}
        >
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
            type="button"
            onClick={() => navigate('/settings/abrechnung')}
            className="mt-6 w-full rounded-lg bg-green-primary px-4 py-2.5 text-sm font-semibold text-white transition hover:brightness-110"
          >
            Auf {shortPlanName(meta.minPlan)} upgraden
          </button>
          <button
            type="button"
            onClick={() => navigate('/')}
            className="mt-2 w-full rounded-lg px-4 py-2 text-sm font-medium text-muted transition hover:bg-alt"
          >
            Zurück zur Übersicht
          </button>
        </div>
      </div>
    </div>
  )
}
