import { createClient, type SupabaseClient } from '@supabase/supabase-js'

import { env, isSupabaseConfigured } from './env'

// Two browser clients with distinct localStorage keys so the customer portal
// and the standalone super-admin surface can coexist in the same Chrome
// profile/tab without clobbering each other's session. Without this, signing
// in on one surface would kick the other surface out (Supabase defaults to a
// single shared `sb-<project>-auth-token` key per origin).
//
// Both clients hit the same Supabase project; only the `auth.storageKey`
// differs. The HTTP layer (apiFetch) reads the matching client's session and
// attaches its access_token as the Bearer.
//
// Either client is null while env is unconfigured so the app can still boot
// and show the configuration notice.
function makeClient(storageKey: string): SupabaseClient | null {
  if (!isSupabaseConfigured) return null
  return createClient(env.supabaseUrl as string, env.supabaseAnonKey as string, {
    auth: {
      storageKey,
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
    },
  })
}

export const customerSupabase: SupabaseClient | null = makeClient('heykiki-customer-auth')
export const adminSupabase: SupabaseClient | null = makeClient('heykiki-admin-auth')

// Back-compat alias for the customer client. Existing imports of `supabase`
// continue to mean the customer client; the admin tree imports `adminSupabase`
// directly. Do NOT add any new imports of this alias from admin code.
export const supabase: SupabaseClient | null = customerSupabase
