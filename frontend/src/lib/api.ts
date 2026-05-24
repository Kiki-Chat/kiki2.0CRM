import { env } from './env'
import { supabase } from './supabase'

export async function authToken(): Promise<string | null> {
  if (!supabase) return null
  const { data } = await supabase.auth.getSession()
  return data.session?.access_token ?? null
}

/** Fetch a binary resource (e.g. call audio) with auth and return an object URL. */
export async function apiBlobUrl(path: string): Promise<string> {
  const headers = new Headers()
  const token = await authToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const res = await fetch(`${env.apiUrl}${path}`, { headers })
  if (!res.ok) throw new Error(`Failed to load (${res.status})`)
  return URL.createObjectURL(await res.blob())
}

/** POST a JSON body and return the response as an object URL (e.g. a generated PDF). */
export async function apiPostBlob(path: string, body: unknown): Promise<string> {
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

/** Multipart upload with auth (browser sets the multipart boundary). */
export async function apiUpload<T>(path: string, formData: FormData): Promise<T> {
  const headers = new Headers()
  const token = await authToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const res = await fetch(`${env.apiUrl}${path}`, { method: 'POST', headers, body: formData })
  if (!res.ok) throw new Error(`Upload failed (${res.status})`)
  return res.json() as Promise<T>
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Content-Type', 'application/json')

  if (supabase) {
    const { data } = await supabase.auth.getSession()
    const token = data.session?.access_token
    if (token) headers.set('Authorization', `Bearer ${token}`)
  }

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
