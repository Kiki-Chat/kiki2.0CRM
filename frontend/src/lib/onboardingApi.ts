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
