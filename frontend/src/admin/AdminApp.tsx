import { Navigate, Route, Routes } from 'react-router-dom'

import { AdminAuthProvider } from './AdminAuthProvider'
import { AdminBillingPage } from './AdminBillingPage'
import { AdminLoginPage } from './AdminLoginPage'
import { AdminMigrationPage } from './AdminMigrationPage'
import { AdminOrgsPage } from './AdminOrgsPage'
import { AdminOrgFormPage } from './AdminOrgFormPage'
import { AdminProtectedRoute } from './AdminProtectedRoute'

/**
 * Super-admin surface. Completely separate from the customer-facing app —
 * NO `AppLayout`, NO customer sidebar, NO shared chrome. Mounted at /admin/*
 * by the top-level Router. Visually distinct (slate/dark + amber) so it's
 * obvious at a glance that you're not in customer space.
 *
 * Wraps everything in `AdminAuthProvider` so the admin tree reads/writes its
 * own Supabase session (storageKey `heykiki-admin-auth`) independently of the
 * customer surface's `AuthProvider` (storageKey `heykiki-customer-auth`).
 * Result: both surfaces can hold a live session in the same Chrome profile.
 */
export function AdminApp() {
  return (
    <AdminAuthProvider>
      <Routes>
        <Route path="login" element={<AdminLoginPage />} />
        <Route element={<AdminProtectedRoute />}>
          <Route index element={<Navigate to="orgs" replace />} />
          <Route path="orgs" element={<AdminOrgsPage />} />
          <Route path="orgs/new" element={<AdminOrgFormPage />} />
          <Route path="orgs/:id" element={<AdminOrgFormPage />} />
          <Route path="orgs/:id/migration" element={<AdminMigrationPage />} />
          <Route path="billing" element={<AdminBillingPage />} />
        </Route>
        {/* Anything else under /admin/* that doesn't match → bounce to login (or list, if signed in).
            AdminProtectedRoute does the role check; non-super-admins get 404'd there. */}
        <Route path="*" element={<Navigate to="orgs" replace />} />
      </Routes>
    </AdminAuthProvider>
  )
}
