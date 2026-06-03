export const env = {
  supabaseUrl: import.meta.env.VITE_SUPABASE_URL as string | undefined,
  supabaseAnonKey: import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined,
  apiUrl: (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000',
  // Kiki copilot widget — shown only when VITE_COPILOT_ENABLED=1 (parity with
  // the backend COPILOT_ENABLED flag). Hidden by default so it ships inert.
  copilotEnabled: (import.meta.env.VITE_COPILOT_ENABLED as string | undefined) === '1',
}

export const isSupabaseConfigured = Boolean(env.supabaseUrl && env.supabaseAnonKey)
