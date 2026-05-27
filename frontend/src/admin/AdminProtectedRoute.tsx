import { useQuery } from '@tanstack/react-query'
import { Navigate, Outlet } from 'react-router-dom'

import { apiFetch } from '../lib/adminApi'
import { AdminLayout } from './AdminLayout'
import { AdminNotFound } from './AdminNotFound'
import { useAdminAuth } from './AdminAuthProvider'

/**
 * Gate for /admin/* (except /admin/login). Three outcomes:
 *  1. No Supabase session → redirect to /admin/login.
 *  2. Session present, role !== 'super_admin' → render 404 (customer-portal
 *     users must never see the admin surface).
 *  3. Role === 'super_admin' → render the admin layout + nested routes.
 */
export function AdminProtectedRoute() {
  const { session, loading } = useAdminAuth()

  // Distinct queryKey from the customer ['me'] — different surface, different
  // user identity, different cache slot.
  const me = useQuery({
    queryKey: ['admin-me'],
    queryFn: () => apiFetch<{ id: string; email: string; role: string | null }>('/api/me'),
    enabled: !!session,
    retry: false,
    staleTime: 5 * 60 * 1000,
  })

  if (loading) {
    return <div className="flex h-screen items-center justify-center bg-slate-950 text-slate-400">Lädt…</div>
  }

  if (!session) {
    return <Navigate to="/admin/login" replace />
  }

  if (me.isLoading) {
    return <div className="flex h-screen items-center justify-center bg-slate-950 text-slate-400">Lädt…</div>
  }

  if (me.data?.role !== 'super_admin') {
    // Non-super-admins (org_admin, employee) hitting /admin/* see the same
    // 404 the rest of the world sees when typing an unknown URL.
    return <AdminNotFound />
  }

  return (
    <AdminLayout>
      <Outlet />
    </AdminLayout>
  )
}
