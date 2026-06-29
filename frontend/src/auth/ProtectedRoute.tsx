import { useQuery } from '@tanstack/react-query'
import { ShieldAlert } from 'lucide-react'
import { lazy } from 'react'
import { Navigate, Outlet } from 'react-router-dom'

import { apiFetch } from '../lib/api'
import { useAuth } from './AuthProvider'

// Field technicians get a dedicated light portal instead of the full office CRM.
const TechnicianApp = lazy(() =>
  import('../technician/TechnicianApp').then((m) => ({ default: m.TechnicianApp })),
)

export function ProtectedRoute() {
  const { session, loading, configured, signOut } = useAuth()

  // P0.6 — fetch /api/me once per protected mount so we can detect a
  // disabled-org 403 ("Diese Organisation ist deaktiviert.") and show a full-
  // page block. Cached across the app via the ['me'] queryKey.
  const me = useQuery({
    queryKey: ['me'],
    queryFn: () => apiFetch<{ id: string; email: string; org_id: string | null; role: string | null }>('/api/me'),
    enabled: !!session,
    retry: false,
    staleTime: 5 * 60 * 1000,
  })

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-muted">Wird geladen…</div>
    )
  }

  // When Supabase isn't configured yet, let the app render so the shell and the
  // setup notice are visible during early development.
  if (!configured) return <Outlet />

  if (!session) return <Navigate to="/login" replace />

  // Disabled-org block: backend require_org throws 403 with German message
  // "Diese Organisation ist deaktiviert." — apiFetch surfaces it as the error
  // message. Show a full-screen alert + sign-out button.
  if (me.error) {
    const msg = (me.error as Error).message || ''
    if (msg.includes('deaktiviert')) {
      return (
        <div className="flex h-screen items-center justify-center bg-bg p-6">
          <div className="max-w-md space-y-4 rounded-xl border border-error/30 bg-error-bg/40 p-6 text-center">
            <div className="flex justify-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-full bg-error/20">
                <ShieldAlert size={28} className="text-error" />
              </div>
            </div>
            <div>
              <h1 className="text-lg font-bold text-text">Diese Organisation ist deaktiviert</h1>
              <p className="mt-1 text-sm text-muted">
                Bitte wende dich an den HeyKiki Support, um deinen Zugang wieder freizuschalten.
              </p>
            </div>
            <button
              onClick={() => signOut()}
              className="rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-body hover:bg-alt"
            >
              Abmelden
            </button>
          </div>
        </div>
      )
    }
    // Other errors (token expired, backend down, etc.) — fall through and let
    // the app surface them naturally.
  }

  // Technicians get the toned-down portal, never the office CRM shell.
  if (me.data?.role === 'technician') return <TechnicianApp />

  return <Outlet />
}
