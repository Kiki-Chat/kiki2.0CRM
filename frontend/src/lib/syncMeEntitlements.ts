import type { QueryClient } from '@tanstack/react-query'

import { featuresForPlan } from './entitlements'
import type { Me } from './useMe'

/** After a billing/plan change, patch the shared ['me'] cache so sidebar + paywall re-gate immediately. */
export function syncMeEntitlements(qc: QueryClient, planTitle: string | null | undefined) {
  qc.setQueryData<Me>(['me'], (old) =>
    old
      ? {
          ...old,
          plan_title: planTitle ?? null,
          features: featuresForPlan(planTitle),
        }
      : old,
  )
  void qc.refetchQueries({ queryKey: ['me'] })
}
