export interface PrimaryCall {
  id: string
  summary_title: string | null
  direction: string | null
  duration_seconds: number | null
  started_at: string | null
}

export interface InquiryRow {
  id: string
  number: string | null
  subject?: string | null
  title: string | null
  type: string | null
  status: string
  notes?: string | null
  created_at: string
  call_count?: number
  open_count?: number
  last_activity_at?: string | null
  case_id?: string | null
  case_confidence?: number | null
  case_reason?: string | null
  primary_call?: PrimaryCall | null
}

export interface CaseCardRow {
  id: string
  number: string | null
  label: string | null
  status: string
  created_at: string | null
  project_id: string | null
  ai_summary?: string | null
  call_count?: number
  entry_count?: number
  last_activity_at?: string | null
}

export interface CustomerDetail {
  id: string
  full_name: string | null
  email: string | null
  phone: string | null
  phone2?: string | null
  address: { raw?: string; street?: string; postal_code?: string; city?: string } | string | null
  customer_number: string | null
  customer_type: string | null
  vat_id: string | null
  notes: string | null
  created_at: string
  updated_at: string
  inquiries: InquiryRow[]
  appointments: unknown[]
  cost_estimates: unknown[]
  calls: { id: string; inquiry_id: string | null; summary_title: string | null; direction: string | null; duration_seconds: number | null; started_at: string | null }[]
  cases?: CaseCardRow[]
}

export interface DocRow {
  id: string
  name: string | null
  category: string | null
  is_image: boolean
  uploaded_at: string
  url: string | null
}

export type StatusFilter = 'all' | 'open' | 'in_progress' | 'completed'
export type MasterTab = 'vorgaenge' | 'lone'

export interface ModalTarget {
  kind: 'vorgang' | 'call'
  id: string
}

export interface PickerState {
  mode: 'assign' | 'transfer'
  inquiryId: string
  fromCaseId?: string
}

export interface Proposal {
  model: string
  n_inquiries: number
  cost: number
  cases: { label: string; members: string[]; confidence: number; reason: string; tier: string }[]
}
