import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, RotateCcw } from 'lucide-react'
import { useState } from 'react'

import { apiFetch } from '../../lib/api'
import { KZ, type KzAudit } from '../../lib/kikiApi'
import { cn } from '../../lib/utils'
import { Modal } from '../ui/Modal'
import { Tag } from '../ui/Tag'
import { Card, ConfirmDialog, inputCls } from './shared'

const LABELS: Record<string, string> = {
  verhalten: 'Verhalten',
  'prompt-editor': 'Prompt-Editor',
  rollback: 'Rückgängig',
  knowledge_resource_push: 'Wissens-Quelle',
  knowledge_resource_remove: 'Wissens-Quelle entfernt',
}
const sectionLabel = (l: string) => LABELS[l] ?? l

function fmtVal(v: unknown): string {
  if (v === null || v === undefined) return '∅'
  if (typeof v === 'string') return v.length > 400 ? v.slice(0, 400) + '…' : v
  return JSON.stringify(v)
}

export function VerlaufSection({ flash }: { flash: (m: string) => void }) {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['kiki-zentrale', 'audit'], queryFn: () => apiFetch<{ entries: KzAudit[] }>(`${KZ}/audit`) })
  const entries = data?.entries ?? []

  const [secFilter, setSecFilter] = useState<string[]>([])
  const [actorQ, setActorQ] = useState('')
  const [onlyRollbackable, setOnlyRollbackable] = useState(false)
  const [detail, setDetail] = useState<KzAudit | null>(null)
  const [restoreSnap, setRestoreSnap] = useState<string | null>(null)

  const sections = Array.from(new Set(entries.map((e) => e.endpoint_label)))
  const rollback = useMutation({
    mutationFn: (snapId: string) => apiFetch(`${KZ}/rollback/${snapId}`, { method: 'POST' }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['kiki-zentrale'] }); setRestoreSnap(null); setDetail(null); flash('Wiederhergestellt.') },
    onError: (e: Error) => { setRestoreSnap(null); flash(e.message || 'Wiederherstellen fehlgeschlagen.') },
  })

  const filtered = entries.filter((e) => {
    if (secFilter.length && !secFilter.includes(e.endpoint_label)) return false
    if (actorQ && !(e.actor_name ?? '').toLowerCase().includes(actorQ.toLowerCase())) return false
    if (onlyRollbackable && (!e.snapshot_id || e.rolled_back)) return false
    return true
  })

  return (
    <Card>
      {/* Filters */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1.5">
          {sections.map((s) => {
            const on = secFilter.includes(s)
            return (
              <button key={s} onClick={() => setSecFilter((f) => (on ? f.filter((x) => x !== s) : [...f, s]))} className={cn('rounded-full px-3 py-1 text-xs font-medium transition', on ? 'bg-green-tint-100 text-green-deep' : 'bg-alt text-muted hover:bg-border')}>
                {sectionLabel(s)}
              </button>
            )
          })}
        </div>
        <input value={actorQ} onChange={(e) => setActorQ(e.target.value)} placeholder="Nach Person filtern…" className={cn(inputCls, 'h-8 max-w-[200px] py-1')} />
        <label className="flex items-center gap-1.5 text-xs text-body"><input type="checkbox" checked={onlyRollbackable} onChange={(e) => setOnlyRollbackable(e.target.checked)} className="h-4 w-4 accent-green-primary" /> Nur wiederherstellbar</label>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-left text-sm">
          <thead className="bg-alt text-xs uppercase tracking-wide text-muted">
            <tr>
              <th className="px-3 py-2 font-semibold">Zeitpunkt</th>
              <th className="px-3 py-2 font-semibold">Sektion</th>
              <th className="px-3 py-2 font-semibold">Geändert von</th>
              <th className="px-3 py-2 font-semibold">Felder</th>
              <th className="px-3 py-2 font-semibold">Status</th>
              <th className="px-3 py-2 font-semibold">Aktion</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && <tr><td colSpan={6} className="px-3 py-8 text-center text-muted">Keine Einträge.</td></tr>}
            {filtered.map((e) => {
              const fields = Object.keys(e.fields_changed || {}).map((p) => p.split('.').pop()).join(', ')
              const ok = (e.elevenlabs_response_status ?? 200) < 300 && !e.rolled_back
              return (
                <tr key={e.id} className={cn('border-t border-border hover:bg-alt', e.rolled_back && 'opacity-50')}>
                  <td className="cursor-pointer px-3 py-2 text-body" onClick={() => setDetail(e)}>{new Date(e.created_at).toLocaleString('de-DE')}</td>
                  <td className="px-3 py-2"><Tag variant="neutral">{sectionLabel(e.endpoint_label)}</Tag></td>
                  <td className="px-3 py-2 text-body">{e.actor_name ?? '—'}</td>
                  <td className="max-w-[200px] truncate px-3 py-2 font-mono text-xs text-muted">{fields || '—'}</td>
                  <td className="px-3 py-2">{e.rolled_back ? <Tag variant="warning">Rückgängig</Tag> : ok ? <Tag variant="success">Erfolg</Tag> : <Tag variant="error">Fehler</Tag>}</td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-3">
                      <button onClick={() => setDetail(e)} className="text-xs font-medium text-green-deep hover:underline">Diff ansehen</button>
                      {e.snapshot_id && !e.rolled_back && (
                        <button onClick={() => setRestoreSnap(e.snapshot_id)} className="flex items-center gap-1 text-xs font-medium text-green-deep hover:underline"><RotateCcw size={13} /> Wiederherstellen</button>
                      )}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Diff drawer */}
      <Modal open={!!detail} onOpenChange={(v) => !v && setDetail(null)} title="Änderungsdetails" widthClass="max-w-2xl">
        {detail && (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm text-muted">
              <Tag variant="neutral">{sectionLabel(detail.endpoint_label)}</Tag>
              <span>{new Date(detail.created_at).toLocaleString('de-DE')}</span>
              <span>· {detail.actor_name ?? '—'}</span>
            </div>
            {Object.entries(detail.fields_changed || {}).map(([path, ch]) => (
              <div key={path} className="rounded-lg border border-border">
                <div className="border-b border-border bg-alt px-3 py-1.5 font-mono text-xs text-body">{path}</div>
                <div className="space-y-1 p-3 font-mono text-xs">
                  <div className="whitespace-pre-wrap rounded bg-error-bg p-2 text-error">- {fmtVal((ch as { old: unknown }).old)}</div>
                  <div className="whitespace-pre-wrap rounded bg-success-bg p-2 text-success">+ {fmtVal((ch as { new: unknown }).new)}</div>
                </div>
              </div>
            ))}
            {detail.snapshot_id && !detail.rolled_back && (
              <button onClick={() => setRestoreSnap(detail.snapshot_id)} className="flex items-center gap-1.5 rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-body hover:bg-alt"><RotateCcw size={14} /> Diese Änderung rückgängig machen</button>
            )}
            {detail.rolled_back && <div className="flex items-center gap-1.5 text-sm text-warning"><Check size={14} /> Diese Änderung wurde bereits rückgängig gemacht.</div>}
          </div>
        )}
      </Modal>

      <ConfirmDialog
        open={!!restoreSnap}
        onOpenChange={(v) => !v && setRestoreSnap(null)}
        title="Änderung rückgängig machen?"
        message="Der Agent wird auf den gespeicherten Snapshot vor dieser Änderung zurückgesetzt. Der aktuelle Stand wird zuvor gesichert."
        confirmLabel="Wiederherstellen"
        busy={rollback.isPending}
        onConfirm={() => restoreSnap && rollback.mutate(restoreSnap)}
      />
    </Card>
  )
}
