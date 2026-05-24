import { Navigate, Outlet } from 'react-router-dom'

import { useAuth } from './AuthProvider'

export function ProtectedRoute() {
  const { session, loading, configured } = useAuth()

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-muted">Loading…</div>
    )
  }

  // When Supabase isn't configured yet, let the app render so the shell and the
  // setup notice are visible during early development.
  if (!configured) return <Outlet />

  if (!session) return <Navigate to="/login" replace />

  return <Outlet />
}
