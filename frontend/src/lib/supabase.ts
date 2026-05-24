import { createClient, type SupabaseClient } from '@supabase/supabase-js'

import { env, isSupabaseConfigured } from './env'

// Single browser client. Null when env is not yet configured so the app can
// still boot (e.g. before Amber provides credentials) and show a clear notice.
export const supabase: SupabaseClient | null = isSupabaseConfigured
  ? createClient(env.supabaseUrl as string, env.supabaseAnonKey as string)
  : null
