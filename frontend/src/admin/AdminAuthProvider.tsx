import { createContext, useContext, type ReactNode } from 'react'
import type { Session } from '@supabase/supabase-js'

import { useSupabaseAuthBinding } from '../auth/AuthProvider'
import { adminSupabase } from '../lib/supabase'

interface AdminAuthContextValue {
  session: Session | null
  loading: boolean
  configured: boolean
  signInWithPassword: (email: string, password: string) => Promise<void>
  signOut: () => Promise<void>
}

const AdminAuthContext = createContext<AdminAuthContextValue | null>(null)

/**
 * Admin-surface auth provider. Bound to `adminSupabase` (storageKey
 * `heykiki-admin-auth`) so the admin session lives in its own browser-storage
 * slot independent of any customer session. Signing in here does NOT clobber
 * a customer session in the same Chrome profile (and vice versa).
 *
 * Same shape as `useAuth()` minus the magic-link helper (admin login is
 * password-only by design — see AdminLoginPage).
 */
export function AdminAuthProvider({ children }: { children: ReactNode }) {
  const binding = useSupabaseAuthBinding(adminSupabase)
  const value: AdminAuthContextValue = {
    session: binding.session,
    loading: binding.loading,
    configured: binding.configured,
    signInWithPassword: binding.signInWithPassword,
    signOut: binding.signOut,
  }
  return <AdminAuthContext.Provider value={value}>{children}</AdminAuthContext.Provider>
}

export function useAdminAuth(): AdminAuthContextValue {
  const ctx = useContext(AdminAuthContext)
  if (!ctx) throw new Error('useAdminAuth must be used within AdminAuthProvider')
  return ctx
}
