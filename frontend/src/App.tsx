import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { ProtectedRoute } from './auth/ProtectedRoute'
import { AppLayout } from './components/layout/AppLayout'
import { LoginPage } from './pages/LoginPage'
import { Placeholder } from './pages/Placeholder'

// Route pages are code-split (React.lazy) so the initial JS bundle stays small and
// first paint is fast — each page's chunk is fetched on first navigation, then
// cached. Structural/entry components (layout, auth gate, login, not-found) stay
// eager since they're needed immediately. (Pages use named exports → unwrap to the
// default React.lazy expects.)
const AdminApp = lazy(() => import('./admin/AdminApp').then((m) => ({ default: m.AdminApp })))
const SetPasswordPage = lazy(() => import('./pages/SetPasswordPage').then((m) => ({ default: m.SetPasswordPage })))
const DashboardPage = lazy(() => import('./pages/DashboardPage').then((m) => ({ default: m.DashboardPage })))
const CallLogsPage = lazy(() => import('./pages/CallLogsPage').then((m) => ({ default: m.CallLogsPage })))
const CustomersPage = lazy(() => import('./pages/CustomersPage').then((m) => ({ default: m.CustomersPage })))
const CustomerDetailPage = lazy(() => import('./pages/CustomerDetailPage').then((m) => ({ default: m.CustomerDetailPage })))
const CalendarPage = lazy(() => import('./pages/CalendarPage').then((m) => ({ default: m.CalendarPage })))
const MyAbsencePage = lazy(() => import('./pages/MyAbsencePage').then((m) => ({ default: m.MyAbsencePage })))
const ProjectsPage = lazy(() => import('./pages/ProjectsPage').then((m) => ({ default: m.ProjectsPage })))
const ProjectFormPage = lazy(() => import('./pages/ProjectFormPage').then((m) => ({ default: m.ProjectFormPage })))
const ProjectWorkspacePage = lazy(() =>
  import('./pages/ProjectWorkspacePage').then((m) => ({ default: m.ProjectWorkspacePage })),
)
const PlanningBoardPage = lazy(() => import('./pages/PlanningBoardPage').then((m) => ({ default: m.PlanningBoardPage })))
const CostEstimatesPage = lazy(() => import('./pages/CostEstimatesPage').then((m) => ({ default: m.CostEstimatesPage })))
const CostEstimateFormPage = lazy(() =>
  import('./pages/CostEstimateFormPage').then((m) => ({ default: m.CostEstimateFormPage })),
)
const InvoicesPage = lazy(() => import('./pages/InvoicesPage').then((m) => ({ default: m.InvoicesPage })))
const InvoiceFormPage = lazy(() => import('./pages/InvoiceFormPage').then((m) => ({ default: m.InvoiceFormPage })))
const CatalogPage = lazy(() => import('./pages/CatalogPage').then((m) => ({ default: m.CatalogPage })))
const EmployeesPage = lazy(() => import('./pages/EmployeesPage').then((m) => ({ default: m.EmployeesPage })))
const KikiZentralePage = lazy(() => import('./pages/KikiZentralePage').then((m) => ({ default: m.KikiZentralePage })))
const RufumleitungGuidePage = lazy(() =>
  import('./pages/RufumleitungGuidePage').then((m) => ({ default: m.RufumleitungGuidePage })),
)
const SettingsPage = lazy(() => import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })))

export default function App() {
  return (
    <Suspense fallback={<div className="flex h-screen items-center justify-center text-muted">Lädt…</div>}>
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
    </Suspense>
  )
}
