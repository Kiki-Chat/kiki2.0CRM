import { ShieldAlert, LogOut } from 'lucide-react'
import type { ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'

import { useAdminAuth } from './AdminAuthProvider'

const NAV = [
  { to: '/admin/orgs', label: 'Organisationen' },
  { to: '/admin/billing', label: 'Abrechnung' },
]

/**
 * Standalone admin shell. Slate/dark palette + amber accent — deliberately
 * contrasting with the green-on-light customer portal. No sidebar, no CRM
 * affordances; just a top bar with the role badge + sign-out.
 */
export function AdminLayout({ children }: { children: ReactNode }) {
  const { session, signOut } = useAdminAuth()
  const navigate = useNavigate()
  const email = session?.user.email ?? ''

  async function handleSignOut() {
    await signOut()
    navigate('/admin/login', { replace: true })
  }

  return (
    <div className="flex min-h-screen min-w-0 flex-col bg-slate-950 text-slate-100">
      <header className="shrink-0 border-b border-slate-800 bg-slate-900">
        <div className="mx-auto flex w-full max-w-7xl min-w-0 items-center justify-between gap-4 px-4 py-3 sm:px-6">
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
      <nav className="shrink-0 border-b border-slate-800 bg-slate-900/60">
        <div className="mx-auto flex w-full max-w-7xl min-w-0 items-center gap-1 overflow-x-auto px-4 sm:px-6">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                `border-b-2 px-3 py-2.5 text-sm font-medium transition ${
                  isActive
                    ? 'border-amber-400 text-amber-300'
                    : 'border-transparent text-slate-400 hover:text-slate-200'
                }`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </div>
      </nav>
      <main className="mx-auto w-full min-w-0 max-w-7xl flex-1 overflow-x-auto px-4 py-6 sm:px-6 sm:py-8">
        {children}
      </main>
    </div>
  )
}
