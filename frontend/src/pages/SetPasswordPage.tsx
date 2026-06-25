import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthProvider'
import { Button } from '../components/ui/Button'
import { customerSupabase } from '../lib/supabase'

/**
 * Landing page for the employee invite / password-recovery link (Wave 2).
 *
 * The Supabase action link redirects here with a recovery/invite token in the
 * URL hash. The customer Supabase client (detectSessionInUrl: true) parses it
 * and establishes a short-lived session — `useAuth().session` then becomes
 * non-null. With that session the user sets their OWN password via
 * `auth.updateUser({ password })`; no password is ever transmitted by email.
 */
export function SetPasswordPage() {
  const { session, loading } = useAuth()
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)
  // detectSessionInUrl is async; give it a moment before declaring the link bad.
  const [waited, setWaited] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setWaited(true), 2500)
    return () => clearTimeout(t)
  }, [])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (password.length < 8) {
      setError('Das Passwort muss mindestens 8 Zeichen lang sein.')
      return
    }
    if (password !== confirm) {
      setError('Die Passwörter stimmen nicht überein.')
      return
    }
    if (!customerSupabase) {
      setError('Supabase ist nicht konfiguriert.')
      return
    }
    setBusy(true)
    try {
      const { error: updErr } = await customerSupabase.auth.updateUser({ password })
      if (updErr) throw updErr
      setDone(true)
      setTimeout(() => navigate('/', { replace: true }), 1400)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Passwort konnte nicht gesetzt werden.')
    } finally {
      setBusy(false)
    }
  }

  if (done) {
    return (
      <Shell>
        <div className="rounded-lg border border-border bg-surface p-6 text-center shadow-e1">
          <p className="text-sm font-medium text-success">
            Passwort gesetzt. Sie werden angemeldet…
          </p>
        </div>
      </Shell>
    )
  }

  // Waiting for the recovery/invite token to establish a session.
  if (!session) {
    return (
      <Shell>
        <div className="rounded-lg border border-border bg-surface p-6 text-center shadow-e1">
          {loading || !waited ? (
            <p className="text-sm text-muted">Link wird überprüft…</p>
          ) : (
            <p className="text-sm text-error">
              Dieser Link ist ungültig oder abgelaufen. Bitte fordere bei deinem
              Administrator eine neue Einladung an.
            </p>
          )}
        </div>
      </Shell>
    )
  }

  return (
    <Shell>
      <form onSubmit={handleSubmit} className="space-y-4 rounded-lg border border-border bg-surface p-6 shadow-e1">
        <p className="text-sm text-muted">
          Bitte vergib ein persönliches Passwort für deinen Zugang.
        </p>
        <div>
          <label className="mb-1.5 block text-sm font-medium text-body">Neues Passwort</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoFocus
            className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary"
          />
        </div>
        <div>
          <label className="mb-1.5 block text-sm font-medium text-body">Passwort bestätigen</label>
          <input
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
            className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary"
          />
        </div>

        {error && <div className="text-sm text-error">{error}</div>}

        <Button type="submit" variant="primary" disabled={busy} className="w-full">
          {busy ? 'Wird gespeichert…' : 'Passwort festlegen'}
        </Button>
      </form>
    </Shell>
  )
}

// Module-scope so it keeps a stable identity across re-renders — defining it
// inside SetPasswordPage remounted the inputs on every keystroke (focus loss).
function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen items-center justify-center bg-bg px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3">
          <img src="/kiki-logo.jpg" alt="HeyKiki" className="h-12 w-12 rounded-xl object-cover" />
          <div className="text-center">
            <h1 className="text-xl font-bold text-text">HeyKiki-Portal</h1>
            <p className="text-sm text-muted">Passwort festlegen</p>
          </div>
        </div>
        {children}
      </div>
    </div>
  )
}
