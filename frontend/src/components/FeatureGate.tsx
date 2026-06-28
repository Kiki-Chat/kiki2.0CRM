import { Outlet } from 'react-router-dom'

import { useMe } from '../lib/useMe'
import { PaywallGlass } from './PaywallGlass'

/**
 * Route-level entitlement gate (Phase 2). Use as a layout route in App.tsx:
 *   <Route element={<FeatureRoute feature="finance" />}>…gated pages…</Route>
 * Renders the real page under a liquid-glass overlay when locked; super_admin bypasses.
 * Authoritative mutation block is backend require_entitlement (402 on POST/PATCH/…).
 */
export function FeatureRoute({ feature }: { feature: string }) {
  const { hasFeature, isLoading } = useMe()
  if (isLoading) return null
  if (hasFeature(feature)) return <Outlet />
  return (
    <PaywallGlass key={feature} feature={feature}>
      <Outlet />
    </PaywallGlass>
  )
}
