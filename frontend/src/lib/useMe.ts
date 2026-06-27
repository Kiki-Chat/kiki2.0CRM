import { useQuery } from '@tanstack/react-query'

import { apiFetch } from './api'

/** Shape of GET /api/me. The ['me'] query is primed by ProtectedRoute and shared
 * (same queryKey) across the sidebar, settings, personal-settings, etc. */
export interface Me {
  id: string
  email: string | null
  org_id: string | null
  role: string | null
  full_name: string | null
  org_name: string | null
  /** White-label company identity (from /api/me) — drives the sidebar badge +
   * footer. Available to every authenticated user, unlike admin-only /api/settings. */
  org_email: string | null
  org_logo_url: string | null
  org_address: Record<string, string> | null
  /** Phase-2 entitlements (from /api/me): the org's current plan + the gateable
   * feature keys it unlocks. Drives menu/route gating + the locked soft preview. */
  plan_title?: string | null
  features?: string[]
}

export function isAdminRole(role: string | null | undefined): boolean {
  return role === 'org_admin' || role === 'super_admin'
}

/**
 * Current-user role, derived from GET /api/me.
 *
 * Role-aware UI: the backend is the source of truth (every admin action is
 * gated by `require_org_admin` / `_require_admin` and 403s an employee). This
 * hook only drives *cosmetic* hiding/disabling so employees don't see controls
 * that would 403. `isAdmin` = org_admin OR super_admin; plain `employee` → false.
 *
 * `isLoading` lets callers avoid flashing admin controls (or a restricted
 * panel) before the role resolves.
 */
export function useMe() {
  const q = useQuery({
    queryKey: ['me'],
    queryFn: () => apiFetch<Me>('/api/me'),
    staleTime: 5 * 60 * 1000,
  })
  const features = q.data?.features ?? []
  return {
    me: q.data,
    role: q.data?.role ?? null,
    isAdmin: isAdminRole(q.data?.role),
    features,
    /** Entitlement check for menu/route gating. super_admin bypasses (platform staff
     * are never plan-gated); otherwise the feature must be in the org's granted set. */
    hasFeature: (f: string) => q.data?.role === 'super_admin' || features.includes(f),
    isLoading: q.isLoading,
  }
}
