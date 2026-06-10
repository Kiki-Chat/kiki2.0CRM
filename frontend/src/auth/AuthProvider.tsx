import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import type { Session, SupabaseClient } from '@supabase/supabase-js'

import { customerSupabase } from '../lib/supabase'
import { isSupabaseConfigured } from '../lib/env'

interface AuthContextValue {
  session: Session | null
  loading: boolean
  configured: boolean
  signInWithPassword: (email: string, password: string) => Promise<void>
  signInWithMagicLink: (email: string) => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

/**
 * Internal hook — sets up a session + auth-state subscription against a
 * single Supabase client. Used by both `AuthProvider` (customer surface,
 * bound to `customerSupabase`) and the admin surface's provider (bound to
 * `adminSupabase`, distinct storageKey).
 */
export function useSupabaseAuthBinding(client: SupabaseClient | null): AuthContextValue {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!client) {
      setLoading(false)
      return
    }
    client.auth.getSession().then(({ data }) => {
      setSession(data.session)
      setLoading(false)
    })
    const { data: sub } = client.auth.onAuthStateChange((_event, s) => {
      setSession(s)
    })
    return () => sub.subscription.unsubscribe()
  }, [client])

  return useMemo<AuthContextValue>(
    () => ({
      session,
      loading,
      configured: isSupabaseConfigured,
      async signInWithPassword(email, password) {
        if (!client) throw new Error('Supabase not configured')
        const { error } = await client.auth.signInWithPassword({ email, password })
        if (error) throw error
      },
      async signInWithMagicLink(email) {
        if (!client) throw new Error('Supabase not configured')
        const { error } = await client.auth.signInWithOtp({
          email,
          // Without redirectTo, Supabase falls back to its globally-configured
          // Site URL (a localhost default), so the emailed link lands on
          // localhost. Pin it to the origin the user is actually on so prod
          // links return to prod. The origin must also be in Supabase Auth's
          // "Redirect URLs" allowlist or Supabase silently rejects it.
          options: { emailRedirectTo: window.location.origin },
        })
        if (error) throw error
      },
      async signOut() {
        if (!client) return
        await client.auth.signOut()
      },
    }),
    [client, session, loading],
  )
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const value = useSupabaseAuthBinding(customerSupabase)
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
