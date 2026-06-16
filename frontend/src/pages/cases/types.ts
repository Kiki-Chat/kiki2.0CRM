// Shared types for the Cases (Fälle) split-view redesign. Mirrors the backend
// /api/cases (list) + /api/cases/{id} (umbrella) shapes. The dirC "Karteikarte"
// design renders entirely from these.

export interface CaseStats {
  calls: number
  inquiries: number
  open_inquiries: number
  appointments: number
  appointments_done: number
  cost_estimates: number
  invoices: number
  employees: number
}

export interface CaseListRow {
  id: string
  number: string | null
  title: string | null
  status: string
  customer_id: string | null
  customer_name: string | null
  created_at: string | null
  updated_at: string | null
  project_id: string | null
  emergency: boolean
  stats: CaseStats
}

export interface UmbrellaInquiry {
  id: string
  number: string | null
  subject: string | null
  title: string | null
  type: string | null
  status: string
  created_at?: string | null
  // Originating call — the row opens this call's transcript/audio drawer.
  call_id: string | null
  emergency_flag?: boolean
}
export interface UmbrellaAppt { id: string; title: string | null; scheduled_at: string | null; status: string; created_at?: string | null }
export interface UmbrellaKva { id: string; number: string | null; total: number | null; status: string }
export interface UmbrellaInvoice { id: string; number: string | null; total: number | null; status: string }
export interface UmbrellaEmp { id: string; display_name: string | null; is_technician?: boolean }

export interface CaseUmbrella {
  case: {
    id: string
    number: string | null
    label: string | null
    status: string
    customer: { id: string; full_name: string | null; phone: string | null; email?: string | null } | null
    created_at: string | null
    project_id: string | null
    emergency: boolean
  }
  inquiries: UmbrellaInquiry[]
  appointments: UmbrellaAppt[]
  cost_estimates: UmbrellaKva[]
  invoices: UmbrellaInvoice[]
  employees: UmbrellaEmp[]
  open_count: number
}

export interface CaseJob {
  id: string
  token: string
  url: string
  employee_id: string | null
  employee_name: string | null
  appointment_id: string | null
  appointment_title: string | null
  scheduled_at: string | null
  status: 'offen' | 'läuft' | 'abgeschlossen'
  started_at: string | null
  finished_at: string | null
  submitted_at: string | null
  photo_count: number
  report: { description?: string; needs?: string[]; job_finished?: boolean; site_visit_notes?: string; extra_demands?: string } | null
  created_at: string | null
}

export interface Employee {
  id: string
  display_name: string | null
  is_active?: boolean
  is_absent?: boolean
  is_technician?: boolean
}
export interface ProjectRow { id: string; number: string | null; title: string; status: string; customer_id: string | null }

// The three case statuses, with the plain-language labels + tones from the design.
export const CASE_STATUS = [
  { value: 'planning', label: 'Offen', tone: 'info' as const },
  { value: 'active', label: 'In Arbeit', tone: 'warning' as const },
  { value: 'completed', label: 'Fertig', tone: 'success' as const },
]

// A case's single "next action" signal, resolved from /api/actions/pending.
export interface NextAction {
  label: string
  urgent: boolean
}
