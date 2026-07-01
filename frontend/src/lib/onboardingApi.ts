import { apiFetch } from './api'

// Mirrors backend app/schemas/billing.py PlanOption.
export interface PlanOption {
  plan_title: string
  included_minutes: number
  monthly_cents: number
  annual_cents: number
  overage_cents_per_min: number
  seats: number
}

export interface OnboardingStartPayload {
  trade: string
  contact_name: string
  company_name: string
  email: string
  phone: string
  password: string
  // Resume the SAME lead (the funnel carries this in the URL as ?s=<token>) so
  // back/abort/refresh never spawns a duplicate. Omitted on a first submit.
  token?: string
  utm?: Record<string, string> | null
  referral_code?: string | null
}

// Safe resume payload — mirrors backend OnboardingSessionResponse (no password).
export interface OnboardingSession {
  token: string
  status: string
  company_name: string | null
  contact_name: string | null
  email: string | null
  phone: string | null
  trade: string | null
  plan_title: string | null
  interval: string | null
}

// Public funnel endpoints (no auth). apiFetch omits the bearer when there's no
// session, so these work for an anonymous visitor.
export const getOnboardingPlans = () => apiFetch<PlanOption[]>('/api/onboarding/plans')

export const checkOnboardingEmail = (email: string) =>
  apiFetch<{ available: boolean }>('/api/onboarding/check-email', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })

export const startOnboarding = (payload: OnboardingStartPayload) =>
  apiFetch<{ token: string }>('/api/onboarding/start', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

// Resume a funnel session from the URL token (?s=<token>). 404 → the session is gone
// and the funnel restarts from signup.
export const getOnboardingSession = (token: string) =>
  apiFetch<OnboardingSession>(`/api/onboarding/session/${encodeURIComponent(token)}`)

export const createOnboardingCheckout = (payload: {
  token: string
  plan_title: string
  interval: 'month' | 'year'
  return_origin: string
}) =>
  apiFetch<{ url: string; session_id: string }>('/api/onboarding/checkout', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
