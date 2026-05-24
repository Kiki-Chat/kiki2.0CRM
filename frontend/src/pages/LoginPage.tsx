import { useState } from 'react'
import { Navigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthProvider'
import { Button } from '../components/ui/Button'

export function LoginPage() {
  const { session, configured, signInWithPassword, signInWithMagicLink } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (session) return <Navigate to="/" replace />

  async function handlePassword(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setNotice(null)
    setBusy(true)
    try {
      await signInWithPassword(email, password)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleMagicLink() {
    setError(null)
    setNotice(null)
    if (!email) {
      setError('Enter your email first')
      return
    }
    setBusy(true)
    try {
      await signInWithMagicLink(email)
      setNotice('Check your email for a magic link.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not send link')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-screen items-center justify-center bg-bg px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-green-brand to-green-primary text-xl font-extrabold text-white">
            K
          </div>
          <div className="text-center">
            <h1 className="text-xl font-bold text-text">HeyKiki Portal</h1>
            <p className="text-sm text-muted">Sign in to your account</p>
          </div>
        </div>

        {!configured && (
          <div className="mb-4 rounded-md border border-warning bg-warning-bg p-3 text-sm text-warning">
            Supabase is not configured yet. Set <code>VITE_SUPABASE_URL</code> and{' '}
            <code>VITE_SUPABASE_ANON_KEY</code> to enable login.
          </div>
        )}

        <form onSubmit={handlePassword} className="space-y-4 rounded-lg border border-border bg-surface p-6 shadow-e1">
          <div>
            <label className="mb-1.5 block text-sm font-medium text-body">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium text-body">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary"
            />
          </div>

          {error && <div className="text-sm text-error">{error}</div>}
          {notice && <div className="text-sm text-success">{notice}</div>}

          <Button type="submit" variant="primary" disabled={busy || !configured} className="w-full">
            {busy ? 'Signing in…' : 'Sign in'}
          </Button>
          <Button
            type="button"
            variant="tertiary"
            disabled={busy || !configured}
            className="w-full"
            onClick={handleMagicLink}
          >
            Email me a magic link
          </Button>
        </form>
      </div>
    </div>
  )
}
