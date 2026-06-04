import { Navigate, Route, Routes } from 'react-router-dom'

import { AdminApp } from './admin/AdminApp'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { AppLayout } from './components/layout/AppLayout'
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
import { MyAbsencePage } from './pages/MyAbsencePage'
import { PlanningBoardPage } from './pages/PlanningBoardPage'
import { Placeholder } from './pages/Placeholder'
import { ProjectFormPage } from './pages/ProjectFormPage'
import { ProjectsPage } from './pages/ProjectsPage'
import { ProjectWorkspacePage } from './pages/ProjectWorkspacePage'
import { RufumleitungGuidePage } from './pages/RufumleitungGuidePage'
import { SetPasswordPage } from './pages/SetPasswordPage'
import { SettingsPage } from './pages/SettingsPage'

export default function App() {
  return (
    <Routes>
      {/* Super-admin: completely separate React tree (own layout, own login,
          own auth gate). Rendered before /login so /admin/login resolves first. */}
      <Route path="/admin/*" element={<AdminApp />} />

      <Route path="/login" element={<LoginPage />} />
      {/* Employee invite / password-recovery landing (Wave 2) — public: the
          recovery token in the URL establishes the session for setting a pw. */}
      <Route path="/set-password" element={<SetPasswordPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppLayout />}>
          <Route index element={<DashboardPage />} />
          <Route path="calls" element={<CallLogsPage />} />
          <Route path="customers" element={<CustomersPage />} />
          <Route path="customers/:id" element={<CustomerDetailPage />} />
          <Route path="calendar" element={<CalendarPage />} />
          {/* Business hours moved into Kiki-Zentrale (UAT); keep the old path as a redirect. */}
          <Route path="calendar/business-hours" element={<Navigate to="/kiki-zentrale/geschaeftszeiten" replace />} />
          <Route path="meine-abwesenheit" element={<MyAbsencePage />} />
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
          <Route path="docs/rufumleitung" element={<RufumleitungGuidePage />} />
          <Route path="settings" element={<Navigate to="/settings/stammdaten" replace />} />
          <Route path="settings/:section" element={<SettingsPage />} />
          <Route path="settings/personal" element={<Placeholder title="Personal Settings" />} />
        </Route>
      </Route>
      <Route path="*" element={<Placeholder title="Not found" />} />
    </Routes>
  )
}
