import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowLeftRight, CheckCircle2, MinusCircle, Pencil, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { apiFetch } from '../lib/adminApi'
import { cn } from '../lib/utils'
import { AgentHealthModal } from './AgentHealthModal'

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

interface AgentHealthSummary {
  org_id: string
  name: string | null
  ok: boolean
  red_checks: string[]
}

const fmtDate = (s: string | null) =>
  s ? new Date(s).toLocaleDateString('de-DE', { year: 'numeric', month: '2-digit', day: '2-digit', timeZone: 'Europe/Berlin' }) : '—'

export function AdminOrgsPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [toast, setToast] = useState<string | null>(null)
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(null), 3500) }

  const [deleteTarget, setDeleteTarget] = useState<OrgRow | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState('')
  const [healthTarget, setHealthTarget] = useState<OrgRow | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['admin', 'orgs'],
    queryFn: () => apiFetch<{ orgs: OrgRow[] }>('/api/super-admin/orgs'),
  })

  const statsQuery = useQuery({
    queryKey: ['admin', 'orgs-stats'],
    queryFn: () => apiFetch<{ stats: Record<string, OrgStats> }>('/api/super-admin/orgs-stats'),
    staleTime: 60 * 1000,
  })

  const agentHealthQuery = useQuery({
    queryKey: ['admin', 'agent-health'],
    queryFn: () => apiFetch<AgentHealthSummary[]>('/api/super-admin/agent-health'),
    staleTime: 60 * 1000,
    retry: false,
  })
  // Build a lookup map by org_id for O(1) access in the table
  const agentHealthMap = Object.fromEntries(
    (agentHealthQuery.data ?? []).map((h) => [h.org_id, h]),
  )

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
      <header className="flex flex-wrap items-center justify-between gap-3">
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
          Wird geladen…
        </div>
      )}
      {error && (
        <div className="rounded-xl border border-red-900/60 bg-red-950/40 p-4 text-sm text-red-300">
          {(error as Error).message}
        </div>
      )}

      {data && (
        <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900">
          <table className="w-full min-w-[88rem] border-collapse text-sm">
            <colgroup>
              <col className="min-w-[11rem]" />
              <col className="min-w-[10rem]" />
              <col className="min-w-[12rem]" />
              <col className="min-w-[7.5rem]" />
              <col className="w-[4.5rem]" />
              <col className="w-[5rem]" />
              <col className="w-[5.5rem]" />
              <col className="w-[5rem]" />
              <col className="min-w-[6.5rem]" />
              <col className="w-[6.5rem]" />
              <col className="w-[7rem]" />
              <col className="min-w-[18rem]" />
            </colgroup>
            <thead className="bg-slate-900/60 text-left text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-4 py-3">Organisation</th>
                <th className="px-4 py-3">Kontakt</th>
                <th className="px-4 py-3">Sprach-ID</th>
                <th className="px-4 py-3">Agent-Status</th>
                <th className="px-4 py-3 text-right">Anrufe</th>
                <th className="px-4 py-3 text-right">Angebote</th>
                <th className="px-4 py-3 text-right">Mitarbeiter</th>
                <th className="px-4 py-3 text-right">Termine</th>
                <th className="px-4 py-3">Zugang</th>
                <th className="whitespace-nowrap px-4 py-3">Angelegt am</th>
                <th className="whitespace-nowrap px-4 py-3">Letzte Aktivität</th>
                <th className="sticky right-0 z-10 bg-slate-900/95 px-4 py-3 text-right shadow-[-10px_0_16px_rgba(2,6,23,0.65)]">
                  Aktionen
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {data.orgs.map((o) => {
                const disabled = o.disabled_at !== null
                const s = statsQuery.data?.stats[o.id]
                const ah = agentHealthMap[o.id]
                return (
                  <tr key={o.id} className="group hover:bg-slate-800/40">
                    <td className="px-4 py-3 align-top">
                      <div className="font-semibold text-slate-100">{o.name ?? '—'}</div>
                      <div className="font-mono text-[11px] text-slate-500">{o.heykiki_org_id ?? '—'}</div>
                    </td>
                    <td className="px-4 py-3 align-top text-xs">
                      <div className="text-slate-300">{o.email ?? '—'}</div>
                      <div className="text-slate-500">{o.phone_number ?? '—'}</div>
                    </td>
                    <td className="max-w-[12rem] truncate px-4 py-3 align-top font-mono text-[11px] text-slate-400" title={o.elevenlabs_agent_id ?? undefined}>
                      {o.elevenlabs_agent_id ?? '—'}
                    </td>
                    <td className="px-4 py-3 align-top">
                      {agentHealthQuery.isLoading ? (
                        <span className="text-xs text-slate-600">…</span>
                      ) : !ah ? (
                        <span className="whitespace-nowrap rounded-full bg-slate-800 px-2 py-0.5 text-[11px] font-medium text-slate-500 ring-1 ring-slate-700">
                          Nicht eingerichtet
                        </span>
                      ) : ah.ok ? (
                        <button
                          onClick={() => setHealthTarget(o)}
                          className="flex items-center gap-1 whitespace-nowrap rounded-full bg-emerald-950/60 px-2 py-0.5 text-[11px] font-semibold text-emerald-300 ring-1 ring-emerald-900/60 hover:ring-emerald-500/60"
                          title="Agent-Status anzeigen"
                        >
                          <CheckCircle2 size={11} />
                          In Ordnung
                        </button>
                      ) : (
                        <button
                          onClick={() => setHealthTarget(o)}
                          className="flex items-center gap-1.5 whitespace-nowrap rounded-full bg-red-950/60 px-2 py-0.5 text-[11px] font-semibold text-red-300 ring-1 ring-red-900/60 hover:ring-red-500/60"
                          title={ah.red_checks.join(', ')}
                        >
                          <AlertTriangle size={11} />
                          <span>{ah.red_checks.length} Problem{ah.red_checks.length === 1 ? '' : 'e'}</span>
                        </button>
                      )}
                    </td>
                    <td className="px-4 py-3 align-top text-right font-mono text-xs text-slate-300">
                      {s ? s.calls : <span className="text-slate-600">—</span>}
                    </td>
                    <td className="px-4 py-3 align-top text-right font-mono text-xs text-slate-300">
                      {s ? s.kvas_sent : <span className="text-slate-600">—</span>}
                    </td>
                    <td className="px-4 py-3 align-top text-right font-mono text-xs text-slate-300">
                      {s ? s.employees : <span className="text-slate-600">—</span>}
                    </td>
                    <td className="px-4 py-3 align-top text-right font-mono text-xs text-slate-300">
                      {s ? s.appointments : <span className="text-slate-600">—</span>}
                    </td>
                    <td className="px-4 py-3 align-top">
                      <span
                        className={cn(
                          'whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold',
                          disabled
                            ? 'bg-red-950/60 text-red-300 ring-1 ring-red-900/60'
                            : 'bg-emerald-950/60 text-emerald-300 ring-1 ring-emerald-900/60',
                        )}
                      >
                        {disabled ? 'Deaktiviert' : 'Aktiv'}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 align-top text-xs text-slate-400">{fmtDate(o.created_at)}</td>
                    <td className="whitespace-nowrap px-4 py-3 align-top text-xs text-slate-400">{fmtDate(s?.last_activity ?? null)}</td>
                    <td className="sticky right-0 z-10 bg-slate-900 px-4 py-3 align-top shadow-[-10px_0_16px_rgba(2,6,23,0.65)] group-hover:bg-slate-800/40">
                      <div className="flex flex-wrap items-center justify-end gap-1 whitespace-nowrap">
                        <button
                          onClick={() => navigate(`/admin/orgs/${o.id}`)}
                          className="flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-slate-300 hover:bg-slate-800"
                          title="Bearbeiten"
                        >
                          <Pencil size={13} /> Bearbeiten
                        </button>
                        <button
                          onClick={() => navigate(`/admin/orgs/${o.id}/migration`)}
                          className="flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-slate-300 hover:bg-slate-800"
                          title="Migration (intern): übernommene Daten + Prompt-Abweichung"
                        >
                          <ArrowLeftRight size={13} /> Migration
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
                  <td colSpan={12} className="px-4 py-12 text-center text-slate-500">
                    Keine Organisationen — lege die erste an.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Agent-health detail modal */}
      {healthTarget && (
        <AgentHealthModal
          orgId={healthTarget.id}
          orgName={healthTarget.name}
          onClose={() => setHealthTarget(null)}
        />
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
                Alle Kunden, Anrufe, Anfragen, Termine, Angebote, Rechnungen und Benutzer dieser
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
