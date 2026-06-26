import { Navigate, Route, Routes } from 'react-router-dom'

import { AdminAuthProvider } from './AdminAuthProvider'
import { AdminBillingPage } from './AdminBillingPage'
import { AdminLoginPage } from './AdminLoginPage'
import { AdminMigrationPage } from './AdminMigrationPage'
import { AdminOrgsPage } from './AdminOrgsPage'
import { AdminOrgFormPage } from './AdminOrgFormPage'
import { AdminRoleGate } from './AdminRoleGate'
import { AdminShellRoute } from './AdminShellRoute'

/**
 * Super-admin surface. Completely separate from the customer-facing app —
 * NO `AppLayout`, NO customer sidebar, NO shared chrome. Mounted at /admin/*
 * by the top-level Router. Visually distinct (slate/dark + amber) so it's
 * obvious at a glance that you're not in customer space.
 *
 * Migration is a standalone full-page route (no Organisationen/Abrechnung nav)
 * so it never shares a split view with list/billing screens.
 */
export function AdminApp() {
  return (
    <AdminAuthProvider>
      <Routes>
        <Route path="login" element={<AdminLoginPage />} />
        <Route element={<AdminRoleGate />}>
          {/* Standalone — own shell inside AdminMigrationPage */}
          <Route path="orgs/:id/migration" element={<AdminMigrationPage />} />
          <Route element={<AdminShellRoute />}>
            <Route index element={<Navigate to="/admin/orgs" replace />} />
            <Route path="orgs" element={<AdminOrgsPage />} />
            <Route path="orgs/new" element={<AdminOrgFormPage />} />
            <Route path="orgs/:id" element={<AdminOrgFormPage />} />
            <Route path="billing" element={<AdminBillingPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/admin/orgs" replace />} />
      </Routes>
    </AdminAuthProvider>
  )
}
