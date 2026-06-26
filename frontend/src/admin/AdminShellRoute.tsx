import { Outlet } from 'react-router-dom'

import { AdminLayout } from './AdminLayout'

/** Standard super-admin chrome (header + Organisationen/Abrechnung nav). */
export function AdminShellRoute() {
  return (
    <AdminLayout>
      <Outlet />
    </AdminLayout>
  )
}
