import { ShieldAlert, LogOut } from 'lucide-react'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthProvider'

/**
 * Standalone admin shell. Slate/dark palette + amber accent — deliberately
 * contrasting with the green-on-light customer portal. No sidebar, no CRM
 * affordances; just a top bar with the role badge + sign-out.
 */
export function AdminLayout({ children }: { children: ReactNode }) {
  const { session, signOut } = useAuth()
  const navigate = useNavigate()
  const email = session?.user.email ?? ''

  async function handleSignOut() {
    await signOut()
    navigate('/admin/login', { replace: true })
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 bg-slate-900">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-6 py-3">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-md bg-amber-500/15 text-amber-400">
              <ShieldAlert size={16} />
            </div>
            <div>
              <div className="text-xs font-bold uppercase tracking-widest text-amber-400">
                HeyKiki · Super-Admin
              </div>
              <div className="text-[11px] text-slate-400">Interne Verwaltung — kein Kundenbereich</div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="hidden text-right sm:block">
              <div className="text-xs text-slate-400">Angemeldet als</div>
              <div className="text-sm font-medium text-slate-200">{email}</div>
            </div>
            <button
              onClick={handleSignOut}
              className="flex items-center gap-1.5 rounded-md border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-700"
            >
              <LogOut size={13} /> Abmelden
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-6 py-8">{children}</main>
    </div>
  )
}
