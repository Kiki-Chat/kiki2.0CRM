import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes, useParams } from 'react-router-dom'

import { ProtectedRoute } from './auth/ProtectedRoute'
import { ChunkErrorBoundary } from './components/ChunkErrorBoundary'
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
// Rebuilt call log (feature/call-log-redesign) — runs alongside /calls during cutover.
const PosteingangPage = lazy(() => import('./pages/PosteingangPage').then((m) => ({ default: m.PosteingangPage })))
const CustomersPage = lazy(() => import('./pages/CustomersPage').then((m) => ({ default: m.CustomersPage })))
const CustomerDetailPage = lazy(() => import('./pages/CustomerDetailPage').then((m) => ({ default: m.CustomerDetailPage })))
const VorgangThreadPage = lazy(() => import('./pages/VorgangThreadPage').then((m) => ({ default: m.VorgangThreadPage })))
const CalendarPage = lazy(() => import('./pages/CalendarPage').then((m) => ({ default: m.CalendarPage })))
const MyAbsencePage = lazy(() => import('./pages/MyAbsencePage').then((m) => ({ default: m.MyAbsencePage })))
const MyCalendarPage = lazy(() => import('./pages/MyCalendarPage').then((m) => ({ default: m.MyCalendarPage })))
const CasesPage = lazy(() => import('./pages/CasesPage').then((m) => ({ default: m.CasesPage })))
const ProjectsPage = lazy(() => import('./pages/ProjectsPage').then((m) => ({ default: m.ProjectsPage })))
const ProjectWorkspacePage = lazy(() => import('./pages/ProjectWorkspacePage').then((m) => ({ default: m.ProjectWorkspacePage })))
const ProjectFormPage = lazy(() => import('./pages/ProjectFormPage').then((m) => ({ default: m.ProjectFormPage })))
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
const JobLinkPage = lazy(() => import('./pages/JobLinkPage').then((m) => ({ default: m.JobLinkPage })))
const TechnicianPortalPage = lazy(() =>
  import('./pages/TechnicianPortalPage').then((m) => ({ default: m.TechnicianPortalPage })),
)

// Legacy single-Fall route → pre-select that case in the new /cases split view.
function FallRedirect() {
  const { id } = useParams()
  return <Navigate to={`/cases?case=${id ?? ''}`} replace />
}

export default function App() {
  return (
    <ChunkErrorBoundary>
      <Suspense fallback={<div className="flex h-screen items-center justify-center text-muted">Wird geladen…</div>}>
        <Routes>
          {/* Super-admin: completely separate React tree (own layout, own login,
              own auth gate). Rendered before /login so /admin/login resolves first. */}
          <Route path="/admin/*" element={<AdminApp />} />

          <Route path="/login" element={<LoginPage />} />
          {/* Employee invite / password-recovery landing (Wave 2) — public: the
              recovery token in the URL establishes the session for setting a pw. */}
          <Route path="/set-password" element={<SetPasswordPage />} />
          {/* Techniker-Einsatzlink — public: the unguessable token in the URL is
              the credential; the technician has no portal login. */}
          <Route path="/job/:token" element={<JobLinkPage />} />
          {/* Techniker-Portal — public standing link: lists the technician's own
              jobs (past + current); no login (the token is the credential). */}
          <Route path="/techniker/:token" element={<TechnicianPortalPage />} />
          <Route element={<ProtectedRoute />}>
            <Route element={<AppLayout />}>
              <Route index element={<DashboardPage />} />
              <Route path="calls" element={<CallLogsPage />} />
              <Route path="posteingang" element={<PosteingangPage />} />
              <Route path="cases" element={<CasesPage />} />
              <Route path="customers" element={<CustomersPage />} />
              <Route path="customers/:id" element={<CustomerDetailPage />} />
              <Route path="vorgang/:id" element={<VorgangThreadPage />} />
              {/* Cases are now the split view at /cases; deep-links to a single Vorgang
                  pre-select it in that view. */}
              <Route path="fall/:id" element={<FallRedirect />} />
              <Route path="calendar" element={<CalendarPage />} />
              {/* Business hours moved into Kiki-Zentrale (UAT); keep the old path as a redirect. */}
              <Route path="calendar/business-hours" element={<Navigate to="/kiki-zentrale/geschaeftszeiten" replace />} />
              <Route path="meine-abwesenheit" element={<MyAbsencePage />} />
              <Route path="mein-kalender" element={<MyCalendarPage />} />
              <Route path="projects" element={<ProjectsPage />} />
              {/* Top-layer Projekt (restored above the Case): full workspace + create/edit form. */}
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
    </ChunkErrorBoundary>
  )
}
