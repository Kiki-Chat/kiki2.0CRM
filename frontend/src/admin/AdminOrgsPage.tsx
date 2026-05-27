import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, MinusCircle, Pencil, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { apiFetch } from '../lib/api'
import { cn } from '../lib/utils'

interface OrgRow {
  id: string
  heykiki_org_id: string | null
  name: string | null
  email: string | null
  phone_number: string | null
  elevenlabs_agent_id: string | null
  disabled_at: string | null
  created_at: string
  updated_at: string | null
}

interface OrgStats {
  calls: number
  kvas_sent: number
  employees: number
  appointments: number
  last_activity: string | null
}

const fmtDate = (s: string | null) =>
  s ? new Date(s).toLocaleDateString('de-DE', { year: 'numeric', month: '2-digit', day: '2-digit' }) : '—'

export function AdminOrgsPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [toast, setToast] = useState<string | null>(null)
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(null), 3500) }

  const [deleteTarget, setDeleteTarget] = useState<OrgRow | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState('')

  const { data, isLoading, error } = useQuery({
    queryKey: ['admin', 'orgs'],
    queryFn: () => apiFetch<{ orgs: OrgRow[] }>('/api/super-admin/orgs'),
  })

  const statsQuery = useQuery({
    queryKey: ['admin', 'orgs-stats'],
    queryFn: () => apiFetch<{ stats: Record<string, OrgStats> }>('/api/super-admin/orgs-stats'),
    staleTime: 60 * 1000,
  })

  const setDisabled = useMutation({
    mutationFn: ({ id, disabled }: { id: string; disabled: boolean }) =>
      apiFetch<OrgRow>(`/api/super-admin/orgs/${id}/${disabled ? 'disable' : 'enable'}`, {
        method: 'POST',
      }),
    onSuccess: (_r, { disabled }) => {
      qc.invalidateQueries({ queryKey: ['admin', 'orgs'] })
      flash(disabled ? 'Organisation deaktiviert.' : 'Organisation reaktiviert.')
    },
    onError: (e: Error) => flash(e.message),
  })

  const delMut = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      apiFetch(`/api/super-admin/orgs/${id}`, {
        method: 'DELETE',
        headers: { 'X-Confirm-Delete': name },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'orgs'] })
      qc.invalidateQueries({ queryKey: ['admin', 'orgs-stats'] })
      flash('Organisation gelöscht.')
      setDeleteTarget(null)
      setDeleteConfirm('')
    },
    onError: (e: Error) => flash(e.message),
  })

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Organisationen</h1>
          <p className="mt-0.5 text-sm text-slate-400">
            {data ? `${data.orgs.length} Organisation${data.orgs.length === 1 ? '' : 'en'}` : '—'} — anlegen, bearbeiten, deaktivieren, löschen.
          </p>
        </div>
        <button
          onClick={() => navigate('/admin/orgs/new')}
          className="flex items-center gap-2 rounded-md bg-amber-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-amber-400"
        >
          <Plus size={15} /> Neue Organisation
        </button>
      </header>

      {toast && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm font-medium text-amber-300">
          {toast}
        </div>
      )}

      {isLoading && (
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-12 text-center text-slate-400">
          Lädt…
        </div>
      )}
      {error && (
        <div className="rounded-xl border border-red-900/60 bg-red-950/40 p-4 text-sm text-red-300">
          {(error as Error).message}
        </div>
      )}

      {data && (
        <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900">
          <table className="w-full text-sm">
            <thead className="bg-slate-900/60 text-left text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-4 py-3">Org</th>
                <th className="px-4 py-3">Kontakt</th>
                <th className="px-4 py-3">Agent</th>
                <th className="px-4 py-3 text-right">Nutzung</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Erstellt</th>
                <th className="px-4 py-3">Aktivität</th>
                <th className="px-4 py-3 text-right">Aktionen</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {data.orgs.map((o) => {
                const disabled = o.disabled_at !== null
                const s = statsQuery.data?.stats[o.id]
                return (
                  <tr key={o.id} className="hover:bg-slate-800/40">
                    <td className="px-4 py-3">
                      <div className="font-semibold text-slate-100">{o.name ?? '—'}</div>
                      <div className="font-mono text-[11px] text-slate-500">{o.heykiki_org_id ?? '—'}</div>
                    </td>
                    <td className="px-4 py-3 text-xs">
                      <div className="text-slate-300">{o.email ?? '—'}</div>
                      <div className="text-slate-500">{o.phone_number ?? '—'}</div>
                    </td>
                    <td className="px-4 py-3 font-mono text-[11px] text-slate-400">{o.elevenlabs_agent_id ?? '—'}</td>
                    <td className="px-4 py-3 text-right text-xs">
                      {s ? (
                        <div className="space-y-0.5 text-slate-300">
                          <div><span className="text-slate-500">Anrufe:</span> <span className="font-mono">{s.calls}</span></div>
                          <div><span className="text-slate-500">KVAs:</span> <span className="font-mono">{s.kvas_sent}</span></div>
                          <div><span className="text-slate-500">MA:</span> <span className="font-mono">{s.employees}</span> · <span className="text-slate-500">Termine:</span> <span className="font-mono">{s.appointments}</span></div>
                        </div>
                      ) : (
                        <span className="text-slate-600">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={cn(
                          'rounded-full px-2 py-0.5 text-xs font-semibold',
                          disabled
                            ? 'bg-red-950/60 text-red-300 ring-1 ring-red-900/60'
                            : 'bg-emerald-950/60 text-emerald-300 ring-1 ring-emerald-900/60',
                        )}
                      >
                        {disabled ? 'Deaktiviert' : 'Aktiv'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-400">{fmtDate(o.created_at)}</td>
                    <td className="px-4 py-3 text-xs text-slate-400">{fmtDate(s?.last_activity ?? null)}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => navigate(`/admin/orgs/${o.id}`)}
                          className="flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-slate-300 hover:bg-slate-800"
                          title="Bearbeiten"
                        >
                          <Pencil size={13} /> Bearbeiten
                        </button>
                        <button
                          onClick={() => setDisabled.mutate({ id: o.id, disabled: !disabled })}
                          disabled={setDisabled.isPending}
                          className={cn(
                            'flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium hover:bg-slate-800 disabled:opacity-50',
                            disabled ? 'text-emerald-400' : 'text-amber-400',
                          )}
                          title={disabled ? 'Reaktivieren' : 'Deaktivieren'}
                        >
                          {disabled ? <CheckCircle2 size={13} /> : <MinusCircle size={13} />}
                          {disabled ? 'Reaktivieren' : 'Deaktivieren'}
                        </button>
                        <button
                          onClick={() => { setDeleteTarget(o); setDeleteConfirm('') }}
                          className="flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-red-400 hover:bg-red-950/40"
                          title="Löschen"
                        >
                          <Trash2 size={13} /> Löschen
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
              {data.orgs.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-12 text-center text-slate-500">
                    Keine Organisationen — legen Sie die erste an.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Hard-delete confirmation — slate/dark modal (no shared Modal component to keep the surface visually distinct). */}
      {deleteTarget && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onClick={() => setDeleteTarget(null)}
        >
          <div
            className="w-full max-w-md space-y-4 rounded-xl border border-red-900/60 bg-slate-900 p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div>
              <h2 className="text-lg font-bold text-slate-100">Organisation löschen?</h2>
              <p className="mt-1 text-xs text-slate-400">
                Diese Aktion ist <span className="font-semibold text-red-400">unwiderruflich</span>.
                Alle Kunden, Anrufe, Anfragen, Termine, KVAs, Rechnungen und Benutzer dieser
                Organisation werden gelöscht.
              </p>
            </div>
            <div className="space-y-2 text-sm">
              <p className="text-slate-300">Zur Bestätigung den Namen exakt eintippen:</p>
              <p className="font-mono text-sm font-semibold text-amber-300">{deleteTarget.name}</p>
              <input
                autoFocus
                value={deleteConfirm}
                onChange={(e) => setDeleteConfirm(e.target.value)}
                placeholder="Name eingeben…"
                className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-red-500"
              />
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <button
                onClick={() => setDeleteTarget(null)}
                className="rounded-md border border-slate-700 bg-slate-800 px-4 py-2 text-sm font-medium text-slate-200 hover:bg-slate-700"
              >
                Abbrechen
              </button>
              <button
                disabled={deleteConfirm !== deleteTarget.name || delMut.isPending}
                onClick={() => delMut.mutate({ id: deleteTarget.id, name: deleteTarget.name! })}
                className="rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-500 disabled:opacity-50"
              >
                Endgültig löschen
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
