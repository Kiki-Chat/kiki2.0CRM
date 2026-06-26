import { Outlet } from 'react-router-dom'

import { AdminLayout } from './AdminLayout'

/**
 * @deprecated Prefer AdminRoleGate + AdminShellRoute in AdminApp routing.
 * Kept for any external imports — wraps content in the standard admin shell.
 */
export function AdminProtectedRoute() {
  return (
    <AdminLayout>
      <Outlet />
    </AdminLayout>
  )
}
