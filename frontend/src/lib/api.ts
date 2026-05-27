import type { SupabaseClient } from '@supabase/supabase-js'

import { env } from './env'
import { adminSupabase, customerSupabase } from './supabase'

/**
 * HTTP helpers that attach the matching surface's Bearer token.
 *
 * The customer portal and the standalone super-admin surface use separate
 * Supabase clients (distinct `auth.storageKey`s) so they can hold independent
 * sessions in the same Chrome profile. As a result, each surface needs its
 * own `apiFetch` that reads from the right client.
 *
 * Factory pattern below: `createApiFetch(client)` returns the four functions
 * (apiFetch / apiBlobUrl / apiPostBlob / apiUpload) bound to that client.
 *
 * Default exports (`apiFetch`, `apiBlobUrl`, `apiPostBlob`, `apiUpload`) are
 * the **customer** surface — every existing import keeps working unchanged.
 * Admin pages must import from `lib/adminApi.ts` (which re-exports the
 * admin-bound versions). Do NOT import the default exports from admin code.
 */

interface ApiBundle {
  authToken: () => Promise<string | null>
  apiFetch: <T>(path: string, init?: RequestInit) => Promise<T>
  apiBlobUrl: (path: string) => Promise<string>
  apiPostBlob: (path: string, body: unknown) => Promise<string>
  apiUpload: <T>(path: string, formData: FormData) => Promise<T>
}

export function createApiFetch(client: SupabaseClient | null): ApiBundle {
  const authToken = async (): Promise<string | null> => {
    if (!client) return null
    const { data } = await client.auth.getSession()
    return data.session?.access_token ?? null
  }

  const apiBlobUrl = async (path: string): Promise<string> => {
    const headers = new Headers()
    const token = await authToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const res = await fetch(`${env.apiUrl}${path}`, { headers })
    if (!res.ok) throw new Error(`Failed to load (${res.status})`)
    return URL.createObjectURL(await res.blob())
  }

  const apiPostBlob = async (path: string, body: unknown): Promise<string> => {
    const headers = new Headers({ 'Content-Type': 'application/json' })
    const token = await authToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const res = await fetch(`${env.apiUrl}${path}`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    })
    if (!res.ok) throw new Error(`Request failed (${res.status})`)
    return URL.createObjectURL(await res.blob())
  }

  const apiUpload = async <T>(path: string, formData: FormData): Promise<T> => {
    const headers = new Headers()
    const token = await authToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const res = await fetch(`${env.apiUrl}${path}`, { method: 'POST', headers, body: formData })
    if (!res.ok) throw new Error(`Upload failed (${res.status})`)
    return res.json() as Promise<T>
  }

  const apiFetch = async <T>(path: string, init: RequestInit = {}): Promise<T> => {
    const headers = new Headers(init.headers)
    headers.set('Content-Type', 'application/json')

    const token = await authToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)

    const res = await fetch(`${env.apiUrl}${path}`, { ...init, headers })
    if (!res.ok) {
      let detail = res.statusText
      try {
        const body = await res.json()
        detail = body.detail ?? detail
      } catch {
        /* ignore */
      }
      throw new Error(detail)
    }
    return res.json() as Promise<T>
  }

  return { authToken, apiFetch, apiBlobUrl, apiPostBlob, apiUpload }
}

// Customer-surface bundle — what every page outside frontend/src/admin/ uses.
const customer = createApiFetch(customerSupabase)
export const authToken = customer.authToken
export const apiFetch = customer.apiFetch
export const apiBlobUrl = customer.apiBlobUrl
export const apiPostBlob = customer.apiPostBlob
export const apiUpload = customer.apiUpload

// Admin-surface bundle — re-exported from lib/adminApi.ts; do NOT import these
// names directly from feature code (it's clearer at the call site to import
// from `lib/adminApi`).
export const _admin: ApiBundle = createApiFetch(adminSupabase)
