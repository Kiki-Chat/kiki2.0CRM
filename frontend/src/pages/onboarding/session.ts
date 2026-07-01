// Onboarding session token = the lead token. It is the URL source of truth
// (?s=<token>) so a refresh / back / mistakenly-aborted funnel resumes the SAME lead
// instead of spawning a duplicate; sessionStorage is a fallback so an in-tab refresh
// that drops the query string still recovers it. The token is also the single binding
// key from signup → Stripe (client_reference_id) → org creation.
import { ONBOARDING_TOKEN_KEY } from './constants'

export const SESSION_PARAM = 's'

const UTM_KEYS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content'] as const
const UTM_STORAGE_KEY = 'hk_onboarding_utm'
const REF_STORAGE_KEY = 'hk_onboarding_ref'

/** Resolve the active session token: URL ?s= first, else sessionStorage. Persists a
 *  URL token so later steps recover it even if the query is dropped. */
export function resolveSessionToken(search: string): string | null {
  const fromUrl = new URLSearchParams(search).get(SESSION_PARAM)
  if (fromUrl) {
    sessionStorage.setItem(ONBOARDING_TOKEN_KEY, fromUrl)
    return fromUrl
  }
  return sessionStorage.getItem(ONBOARDING_TOKEN_KEY)
}

export function persistSessionToken(token: string): void {
  sessionStorage.setItem(ONBOARDING_TOKEN_KEY, token)
}

/** Append (or keep) the session token on a funnel path. */
export function withSession(path: string, token: string): string {
  const sep = path.includes('?') ? '&' : '?'
  return `${path}${sep}${SESSION_PARAM}=${encodeURIComponent(token)}`
}

/** Capture UTM + referral from the LANDING url and persist them so they survive the
 *  funnel even after the query is replaced by ?s=. Never wipes prior attribution when
 *  a later step's url carries none. */
export function captureAttribution(search: string): void {
  const p = new URLSearchParams(search)
  const utm: Record<string, string> = {}
  for (const k of UTM_KEYS) {
    const v = p.get(k)
    if (v) utm[k.replace('utm_', '')] = v
  }
  if (Object.keys(utm).length) sessionStorage.setItem(UTM_STORAGE_KEY, JSON.stringify(utm))
  const ref = p.get('ref')
  if (ref) sessionStorage.setItem(REF_STORAGE_KEY, ref)
}

export function readAttribution(): {
  utm: Record<string, string> | null
  referral_code: string | null
} {
  let utm: Record<string, string> | null = null
  try {
    const raw = sessionStorage.getItem(UTM_STORAGE_KEY)
    utm = raw ? (JSON.parse(raw) as Record<string, string>) : null
  } catch {
    utm = null
  }
  return { utm, referral_code: sessionStorage.getItem(REF_STORAGE_KEY) }
}
