import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, MinusCircle, Pencil, Plus, ShieldAlert, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Modal } from '../components/ui/Modal'
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

const fmtDate = (s: string | null) =>
  s ? new Date(s).toLocaleDateString('de-DE', { year: 'numeric', month: '2-digit', day: '2-digit' }) : '—'

export function SuperAdminOrgsPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [toast, setToast] = useState<string | null>(null)
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(null), 3500) }

  const [deleteTarget, setDeleteTarget] = useState<OrgRow | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState('')

  const { data, isLoading, error } = useQuery({
    queryKey: ['super-admin', 'orgs'],
    queryFn: () => apiFetch<{ orgs: OrgRow[] }>('/api/super-admin/orgs'),
  })

  const setDisabled = useMutation({
    mutationFn: ({ id, disabled }: { id: string; disabled: boolean }) =>
      apiFetch<OrgRow>(`/api/super-admin/orgs/${id}/${disabled ? 'disable' : 'enable'}`, {
        method: 'POST',
      }),
    onSuccess: (_r, { disabled }) => {
      qc.invalidateQueries({ queryKey: ['super-admin', 'orgs'] })
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
      qc.invalidateQueries({ queryKey: ['super-admin', 'orgs'] })
      flash('Organisation gelöscht.')
      setDeleteTarget(null)
      setDeleteConfirm('')
    },
    onError: (e: Error) => flash(e.message),
  })

  return (
    <div className="space-y-5 p-6">
      <header className="flex items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide text-ai">
            <ShieldAlert size={13} /> Super-Admin
          </div>
          <h1 className="mt-1 text-xl font-bold text-text">Alle Organisationen</h1>
          <p className="mt-0.5 text-sm text-muted">
            Verwalten Sie HeyKiki-Organisationen: anlegen, bearbeiten, deaktivieren, löschen.
          </p>
        </div>
        <button
          onClick={() => navigate('/super-admin/orgs/new')}
          className="flex items-center gap-2 rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110"
        >
          <Plus size={15} /> Neue Organisation
        </button>
      </header>

      {toast && (
        <div className="rounded-md bg-green-tint-50 px-3 py-2 text-sm font-medium text-green-deep">
          {toast}
        </div>
      )}

      {isLoading && <div className="rounded-xl border border-border bg-surface p-12 text-center text-muted">Lädt…</div>}
      {error && (
        <div className="rounded-xl border border-error/30 bg-error-bg/40 p-4 text-sm text-error">
          {(error as Error).message}
        </div>
      )}

      {data && (
        <div className="overflow-hidden rounded-xl border border-border bg-surface">
          <table className="w-full text-sm">
            <thead className="bg-alt text-left text-xs font-semibold uppercase tracking-wide text-muted">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">heykiki_org_id</th>
                <th className="px-4 py-3">Agent ID</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Erstellt</th>
                <th className="px-4 py-3 text-right">Aktionen</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.orgs.map((o) => {
                const disabled = o.disabled_at !== null
                return (
                  <tr key={o.id} className="hover:bg-alt/40">
                    <td className="px-4 py-3 font-semibold text-text">{o.name ?? '—'}</td>
                    <td className="px-4 py-3 font-mono text-xs text-muted">{o.heykiki_org_id ?? '—'}</td>
                    <td className="px-4 py-3 font-mono text-xs text-muted">{o.elevenlabs_agent_id ?? '—'}</td>
                    <td className="px-4 py-3">
                      <span
                        className={cn(
                          'rounded-full px-2 py-0.5 text-xs font-semibold',
                          disabled ? 'bg-error-bg text-error' : 'bg-success-bg text-success',
                        )}
                      >
                        {disabled ? 'Deaktiviert' : 'Aktiv'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-muted">{fmtDate(o.created_at)}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => navigate(`/super-admin/orgs/${o.id}`)}
                          className="flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-body hover:bg-alt"
                          title="Bearbeiten"
                        >
                          <Pencil size={13} /> Bearbeiten
                        </button>
                        <button
                          onClick={() => setDisabled.mutate({ id: o.id, disabled: !disabled })}
                          disabled={setDisabled.isPending}
                          className={cn(
                            'flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium hover:bg-alt disabled:opacity-50',
                            disabled ? 'text-success' : 'text-warning',
                          )}
                          title={disabled ? 'Reaktivieren' : 'Deaktivieren'}
                        >
                          {disabled ? <CheckCircle2 size={13} /> : <MinusCircle size={13} />}
                          {disabled ? 'Reaktivieren' : 'Deaktivieren'}
                        </button>
                        <button
                          onClick={() => { setDeleteTarget(o); setDeleteConfirm('') }}
                          className="flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-error hover:bg-error-bg/40"
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
                  <td colSpan={6} className="px-4 py-12 text-center text-muted">
                    Keine Organisationen — legen Sie die erste an.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Hard-delete confirmation modal */}
      {deleteTarget && (
        <Modal
          open
          onOpenChange={(v) => !v && setDeleteTarget(null)}
          title="Organisation löschen?"
        >
          <div className="space-y-3 text-sm">
            <div className="rounded-md border border-error/30 bg-error-bg/40 p-3 text-error">
              <div className="font-bold">Diese Aktion ist unwiderruflich.</div>
              <div className="mt-1 text-xs">
                Alle Kunden, Anrufe, Anfragen, Termine, KVAs, Rechnungen und Benutzer dieser Organisation werden gelöscht.
              </div>
            </div>
            <p>
              Zur Bestätigung tippen Sie bitte den Namen der Organisation exakt ein:
            </p>
            <p className="font-mono text-sm font-semibold text-text">{deleteTarget.name}</p>
            <input
              autoFocus
              value={deleteConfirm}
              onChange={(e) => setDeleteConfirm(e.target.value)}
              placeholder="Name eingeben…"
              className="w-full rounded-md border border-border bg-alt px-3 py-2 text-sm outline-none focus:border-error"
            />
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setDeleteTarget(null)}
                className="rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-body hover:bg-alt"
              >
                Abbrechen
              </button>
              <button
                disabled={deleteConfirm !== deleteTarget.name || delMut.isPending}
                onClick={() => delMut.mutate({ id: deleteTarget.id, name: deleteTarget.name! })}
                className="rounded-md bg-error px-4 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
              >
                Endgültig löschen
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
