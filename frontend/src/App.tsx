import { useQuery } from '@tanstack/react-query'
import { Navigate, Outlet, Route, Routes } from 'react-router-dom'

import { ProtectedRoute } from './auth/ProtectedRoute'
import { AppLayout } from './components/layout/AppLayout'
import { apiFetch } from './lib/api'
import { BusinessHoursPage } from './pages/BusinessHoursPage'
import { CalendarPage } from './pages/CalendarPage'
import { CallLogsPage } from './pages/CallLogsPage'
import { CatalogPage } from './pages/CatalogPage'
import { CostEstimateFormPage } from './pages/CostEstimateFormPage'
import { CostEstimatesPage } from './pages/CostEstimatesPage'
import { CustomerDetailPage } from './pages/CustomerDetailPage'
import { CustomersPage } from './pages/CustomersPage'
import { DashboardPage } from './pages/DashboardPage'
import { EmployeesPage } from './pages/EmployeesPage'
import { InvoiceFormPage } from './pages/InvoiceFormPage'
import { InvoicesPage } from './pages/InvoicesPage'
import { KikiZentralePage } from './pages/KikiZentralePage'
import { LoginPage } from './pages/LoginPage'
import { PlanningBoardPage } from './pages/PlanningBoardPage'
import { Placeholder } from './pages/Placeholder'
import { ProjectFormPage } from './pages/ProjectFormPage'
import { ProjectsPage } from './pages/ProjectsPage'
import { ProjectWorkspacePage } from './pages/ProjectWorkspacePage'
import { SettingsPage } from './pages/SettingsPage'
import { SuperAdminOrgFormPage } from './pages/SuperAdminOrgFormPage'
import { SuperAdminOrgsPage } from './pages/SuperAdminOrgsPage'

// Route gate for /super-admin/* — renders the placeholder ("Not found") for
// anyone whose role !== 'super_admin'. Reuses the shared ['me'] query cache.
function SuperAdminRoute() {
  const me = useQuery({
    queryKey: ['me'],
    queryFn: () => apiFetch<{ role: string | null }>('/api/me'),
    staleTime: 5 * 60 * 1000,
  })
  if (me.isLoading) return <div className="p-12 text-center text-muted">Lädt…</div>
  if (me.data?.role !== 'super_admin') return <Placeholder title="Not found" />
  return <Outlet />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppLayout />}>
          <Route index element={<DashboardPage />} />
          <Route path="calls" element={<CallLogsPage />} />
          <Route path="customers" element={<CustomersPage />} />
          <Route path="customers/:id" element={<CustomerDetailPage />} />
          <Route path="calendar" element={<CalendarPage />} />
          <Route path="calendar/business-hours" element={<BusinessHoursPage />} />
          <Route path="projects" element={<ProjectsPage />} />
          <Route path="projects/new" element={<ProjectFormPage />} />
          <Route path="projects/:id" element={<ProjectWorkspacePage />} />
          <Route path="projects/:id/edit" element={<ProjectFormPage />} />
          <Route path="planning-board" element={<PlanningBoardPage />} />
          <Route path="cost-estimates" element={<CostEstimatesPage />} />
          <Route path="cost-estimates/new" element={<CostEstimateFormPage />} />
          <Route path="cost-estimates/:id" element={<CostEstimateFormPage />} />
          <Route path="invoices" element={<InvoicesPage />} />
          <Route path="invoices/new" element={<InvoiceFormPage />} />
          <Route path="invoices/:id" element={<InvoiceFormPage />} />
          <Route path="catalog" element={<CatalogPage />} />
          <Route path="employees" element={<EmployeesPage />} />
          <Route path="kiki" element={<Navigate to="/kiki-zentrale/verhalten" replace />} />
          <Route path="kiki-zentrale" element={<Navigate to="/kiki-zentrale/verhalten" replace />} />
          <Route path="kiki-zentrale/:section" element={<KikiZentralePage />} />
          <Route path="settings" element={<Navigate to="/settings/stammdaten" replace />} />
          <Route path="settings/:section" element={<SettingsPage />} />
          <Route path="settings/personal" element={<Placeholder title="Personal Settings" />} />
          <Route element={<SuperAdminRoute />}>
            <Route path="super-admin" element={<Navigate to="/super-admin/orgs" replace />} />
            <Route path="super-admin/orgs" element={<SuperAdminOrgsPage />} />
            <Route path="super-admin/orgs/new" element={<SuperAdminOrgFormPage />} />
            <Route path="super-admin/orgs/:id" element={<SuperAdminOrgFormPage />} />
          </Route>
        </Route>
      </Route>
      <Route path="*" element={<Placeholder title="Not found" />} />
    </Routes>
  )
}
