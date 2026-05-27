import { Navigate, Route, Routes } from 'react-router-dom'

import { AdminLoginPage } from './AdminLoginPage'
import { AdminOrgsPage } from './AdminOrgsPage'
import { AdminOrgFormPage } from './AdminOrgFormPage'
import { AdminProtectedRoute } from './AdminProtectedRoute'

/**
 * Super-admin surface. Completely separate from the customer-facing app —
 * NO `AppLayout`, NO customer sidebar, NO shared chrome. Mounted at /admin/*
 * by the top-level Router. Visually distinct (slate/dark + amber) so it's
 * obvious at a glance that you're not in customer space.
 */
export function AdminApp() {
  return (
    <Routes>
      <Route path="login" element={<AdminLoginPage />} />
      <Route element={<AdminProtectedRoute />}>
        <Route index element={<Navigate to="orgs" replace />} />
        <Route path="orgs" element={<AdminOrgsPage />} />
        <Route path="orgs/new" element={<AdminOrgFormPage />} />
        <Route path="orgs/:id" element={<AdminOrgFormPage />} />
      </Route>
      {/* Anything else under /admin/* that doesn't match → bounce to login (or list, if signed in).
          AdminProtectedRoute does the role check; non-super-admins get 404'd there. */}
      <Route path="*" element={<Navigate to="orgs" replace />} />
    </Routes>
  )
}
