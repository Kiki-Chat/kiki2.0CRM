import { useQuery } from '@tanstack/react-query'
import { Navigate, Outlet } from 'react-router-dom'

import { apiFetch } from '../lib/adminApi'
import { AdminNotFound } from './AdminNotFound'
import { useAdminAuth } from './AdminAuthProvider'

/**
 * Super-admin auth gate for /admin/* (except /admin/login). Renders nested
 * routes via <Outlet /> without imposing a layout — callers choose whether to
 * wrap in AdminLayout (list/billing) or render a standalone page (migration).
 */
export function AdminRoleGate() {
  const { session, loading } = useAdminAuth()

  const me = useQuery({
    queryKey: ['admin-me'],
    queryFn: () => apiFetch<{ id: string; email: string; role: string | null }>('/api/me'),
    enabled: !!session,
    retry: false,
    staleTime: 5 * 60 * 1000,
  })

  if (loading) {
    return <div className="flex h-screen items-center justify-center bg-slate-950 text-slate-400">Wird geladen…</div>
  }

  if (!session) {
    return <Navigate to="/admin/login" replace />
  }

  if (me.isLoading) {
    return <div className="flex h-screen items-center justify-center bg-slate-950 text-slate-400">Wird geladen…</div>
  }

  if (me.data?.role !== 'super_admin') {
    return <AdminNotFound />
  }

  return <Outlet />
}
