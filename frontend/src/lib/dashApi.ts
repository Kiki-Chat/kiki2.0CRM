// Types + formatters for the Dashboard tabs.

export interface AnrufeData {
  kpis: {
    total_calls: number; answered: number; answer_rate: number
    avg_duration_seconds: number; outbound: number
    prev_total_calls: number; prev_answered: number
    prev_avg_duration_seconds: number; prev_outbound: number
  }
  period: KiPeriod
  period_label: string
  series: { label: string; count: number }[]
  series_x_label: string
  breakdown: { inbound: number; outbound: number; missed: number }
  recent_calls: {
    id: string; customer_name: string | null; started_at: string | null
    duration_seconds: number; direction: string | null; status: string | null
  }[]
}

export interface FinanzenData {
  kpis: {
    umsatz_month: number; prev_umsatz: number; open_invoices_count: number; open_invoices_sum: number
    kvas_pending_count: number; kvas_pending_sum: number; paid_month: number; prev_paid: number
  }
  period: KiPeriod
  period_label: string
  revenue_series: { month: string; label: string; revenue: number }[]
  top_customers: { customer_id: string; customer_name: string | null; amount: number }[]
  recent_invoices: {
    id: string; number: string | null; customer_name: string | null
    status: string | null; total: number; due_date: string | null
  }[]
}

export type KiPeriod = 'day' | 'week' | 'month' | 'range'
export interface KiNutzungData {
  kpis: {
    minutes_used: number; minutes_quota: number; month_minutes_used: number; calls_count: number
    avg_duration_seconds: number; estimated_days_remaining: number | null; over_quota: boolean
    previous_minutes: number; previous_calls: number; previous_avg_duration: number
  }
  period: KiPeriod
  period_label: string
  series: { label: string; minutes: number; calls: number }[]
  series_x_label: string
  top_callers: { customer_id: string; customer_name: string | null; total_minutes: number; call_count: number }[]
  calls_by_hour: { hour: number; count: number; minutes: number }[]
}

export interface AiInsightsData {
  enabled: boolean
  kpis: { open_count: number; kva_followup_count: number; overdue_invoices_count: number; inactive_customers_count: number }
  suggestions: {
    id: string; category: 'kva_followup' | 'invoice_overdue' | 'inactive_customer'
    title: string; subtitle: string; customer_id: string | null; created_at: string | null
  }[]
}

// ─── Stripe billing (Phase 1) ────────────────────────────────────────────────
export interface BillingSummary {
  configured: boolean
  plan_title: string | null
  status: string | null
  period_start: string | null
  period_end: string | null
  quota_minutes: number
  used_minutes: number
  used_percent: number
  over_quota: boolean
  next_invoice_amount_cents: number | null
  currency: string
}
export interface BillingInvoice {
  id: string; number: string | null; status: string | null
  amount_due_cents: number | null; amount_paid_cents: number | null; currency: string | null
  created: number | null; period_start: number | null; period_end: number | null
  hosted_invoice_url: string | null; invoice_pdf: string | null
}
export interface PlanOption {
  plan_title: string
  included_minutes: number
  monthly_cents: number
  annual_cents: number
  overage_cents_per_min: number
}
export const fmtCents = (c: number | null | undefined, cur = 'EUR') =>
  c == null ? '—' : new Intl.NumberFormat('de-DE', { style: 'currency', currency: (cur || 'EUR').toUpperCase() }).format(c / 100)

const BILLING_STATUS_LABELS: Record<string, string> = {
  active: 'Aktiv', trialing: 'Testphase', past_due: 'Zahlung überfällig', unpaid: 'Unbezahlt',
  canceled: 'Gekündigt', incomplete: 'Unvollständig', incomplete_expired: 'Abgelaufen',
  paused: 'Pausiert', legacy: 'Altvertrag', none: 'Kein Abo',
}
export const billingStatusLabel = (s: string | null) => (s ? BILLING_STATUS_LABELS[s] ?? s : '—')

const STRIPE_INVOICE_STATUS_LABELS: Record<string, string> = {
  draft: 'Entwurf', open: 'Offen', paid: 'Bezahlt', uncollectible: 'Uneinbringlich', void: 'Storniert',
}
export const stripeInvoiceStatusLabel = (s: string | null) => (s ? STRIPE_INVOICE_STATUS_LABELS[s] ?? s : '—')

export const fmtDur = (s: number) => `${Math.floor((s || 0) / 60)}:${String(Math.round((s || 0) % 60)).padStart(2, '0')}`
export const fmtEur = (n: number) => new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(n || 0)
export const fmtNum = (n: number) => new Intl.NumberFormat('de-DE').format(n || 0)

const STATUS_LABELS: Record<string, string> = {
  paid: 'Bezahlt', sent: 'Versendet', overdue: 'Überfällig', draft: 'Entwurf', cancelled: 'Storniert',
}
export const invoiceStatusLabel = (s: string | null) => (s ? STATUS_LABELS[s] ?? s : '—')
export const invoiceStatusVariant = (s: string | null): 'success' | 'info' | 'error' | 'neutral' =>
  s === 'paid' ? 'success' : s === 'overdue' ? 'error' : s === 'sent' ? 'info' : 'neutral'
