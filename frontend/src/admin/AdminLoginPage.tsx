import { useQuery } from '@tanstack/react-query'
import { ShieldAlert } from 'lucide-react'
import { useState } from 'react'
import { Navigate } from 'react-router-dom'

import { useAdminAuth } from './AdminAuthProvider'
import { apiFetch } from '../lib/adminApi'

/**
 * /admin/login — plain email/password gate. No magic link, no signup.
 * Restricted to role='super_admin'. Anyone else lands on a clear error
 * (and is signed out so they can't accidentally hold an admin-level session).
 */
export function AdminLoginPage() {
  const { session, signInWithPassword, signOut } = useAdminAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // If already signed in, verify role and either redirect or reject.
  // Distinct queryKey from the customer-surface ['me'] so the two surfaces
  // don't share a cached identity across QueryClient.
  const me = useQuery({
    queryKey: ['admin-me'],
    queryFn: () => apiFetch<{ id: string; email: string; role: string | null }>('/api/me'),
    enabled: !!session,
    retry: false,
    staleTime: 5 * 60 * 1000,
  })

  if (session && me.data?.role === 'super_admin') {
    return <Navigate to="/admin/orgs" replace />
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await signInWithPassword(email, password)
      // After sign-in, /api/me will be refetched by the ['me'] query above.
      // We poll once more here so the error path can fire synchronously.
      const meRes = await apiFetch<{ role: string | null }>('/api/me')
      if (meRes.role !== 'super_admin') {
        await signOut()
        setError(
          'Dieser Login hat keinen Super-Admin-Zugang. Bitte verwenden Sie das Kunden-Portal.',
        )
      }
      // else: the Navigate above takes over on next render
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Anmeldung fehlgeschlagen.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4 text-slate-100">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-amber-500/15 text-amber-400">
            <ShieldAlert size={22} />
          </div>
          <div className="text-center">
            <div className="text-xs font-bold uppercase tracking-[0.2em] text-amber-400">
              Super-Admin
            </div>
            <h1 className="mt-1 text-lg font-semibold text-slate-100">Interne Verwaltung</h1>
            <p className="mt-0.5 text-xs text-slate-400">
              Kein Kunden-Login — nur HeyKiki-Personal.
            </p>
          </div>
        </div>

        <form
          onSubmit={handleSubmit}
          className="space-y-4 rounded-xl border border-slate-800 bg-slate-900 p-6 shadow-2xl"
        >
          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-slate-400">
              E-Mail
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-slate-100 outline-none focus:border-amber-500"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-slate-400">
              Passwort
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-slate-100 outline-none focus:border-amber-500"
            />
          </div>

          {error && (
            <div className="rounded-md border border-red-900/60 bg-red-950/50 px-3 py-2 text-xs text-red-300">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-md bg-amber-500 px-4 py-2.5 text-sm font-semibold text-slate-950 hover:bg-amber-400 disabled:opacity-50"
          >
            {busy ? 'Anmeldung läuft…' : 'Anmelden'}
          </button>
        </form>
      </div>
    </div>
  )
}
