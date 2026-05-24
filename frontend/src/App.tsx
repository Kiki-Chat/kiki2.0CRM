import { Route, Routes } from 'react-router-dom'

import { ProtectedRoute } from './auth/ProtectedRoute'
import { AppLayout } from './components/layout/AppLayout'
import { BusinessHoursPage } from './pages/BusinessHoursPage'
import { CalendarPage } from './pages/CalendarPage'
import { CallLogsPage } from './pages/CallLogsPage'
import { CustomerDetailPage } from './pages/CustomerDetailPage'
import { CustomersPage } from './pages/CustomersPage'
import { DashboardPage } from './pages/DashboardPage'
import { EmployeesPage } from './pages/EmployeesPage'
import { LoginPage } from './pages/LoginPage'
import { PlanningBoardPage } from './pages/PlanningBoardPage'
import { Placeholder } from './pages/Placeholder'

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
          <Route path="projects" element={<Placeholder title="Projekte" />} />
          <Route path="planning-board" element={<PlanningBoardPage />} />
          <Route path="cost-estimates" element={<Placeholder title="Kostenvoranschläge" />} />
          <Route path="invoices" element={<Placeholder title="Rechnungen" />} />
          <Route path="catalog" element={<Placeholder title="Katalog" />} />
          <Route path="employees" element={<EmployeesPage />} />
          <Route path="kiki" element={<Placeholder title="Kiki-Zentrale" />} />
          <Route path="settings/personal" element={<Placeholder title="Personal Settings" />} />
          <Route path="settings/company" element={<Placeholder title="Company Settings" />} />
        </Route>
      </Route>
      <Route path="*" element={<Placeholder title="Not found" />} />
    </Routes>
  )
}
