import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, Plus } from 'lucide-react'
import { useState } from 'react'

import { Modal } from '../components/ui/Modal'
import { apiFetch } from '../lib/api'
import { useToast } from '../lib/useToast'
import { cn } from '../lib/utils'

// Employee-facing absence self-service. Employees apply for their OWN absence
// (lands as 'pending') and see their own requests + status. The backend resolves
// the employee from the caller (POST/GET /api/employees/me/absences), so this
// page exposes no other employee's data and no HR fields.

interface MyAbsence {
  id: string
  type: string
  starts_at: string
  ends_at: string
  all_day: boolean
  reason: string | null
  status: string
  internal_note: string | null
}

const TYPE_LABEL: Record<string, string> = {
  vacation: 'Urlaub',
  illness: 'Krankheit',
  training: 'Weiterbildung',
  home_office: 'Homeoffice',
  other: 'Sonstiges',
}
const TYPE_OPTIONS = Object.entries(TYPE_LABEL).map(([key, label]) => ({ key, label }))

const STATUS_META: Record<string, { label: string; cls: string }> = {
  pending: { label: 'Ausstehend', cls: 'bg-warning-bg text-warning' },
  approved: { label: 'Genehmigt', cls: 'bg-success-bg text-success' },
  rejected: { label: 'Abgelehnt', cls: 'bg-error-bg text-error' },
}

const inputCls =
  'w-full rounded-md border border-border bg-surface px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary'
const todayYmd = () => new Date().toISOString().slice(0, 10)
const fmtDate = (s: string) =>
  new Date(s).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'Europe/Berlin' })

export function MyAbsencePage() {
  const [open, setOpen] = useState(false)
  const { toast, flash } = useToast()
  const qc = useQueryClient()

  const { data: absences = [], isLoading } = useQuery({
    queryKey: ['my-absences'],
    queryFn: () => apiFetch<MyAbsence[]>('/api/employees/me/absences'),
  })

  return (
    <div className="p-8">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <CalendarClock size={26} className="text-green-primary" />
          <div>
            <h1 className="text-2xl font-bold text-text">Meine Abwesenheit</h1>
            <p className="mt-0.5 text-sm text-muted">Urlaub & Abwesenheiten beantragen</p>
          </div>
        </div>
        <button
          onClick={() => setOpen(true)}
          className="inline-flex items-center gap-2 rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110"
        >
          <Plus size={16} /> Abwesenheit beantragen
        </button>
      </div>

      {toast && (
        <div className="mb-3 rounded-md bg-green-tint-50 px-3 py-2 text-sm font-medium text-green-deep">
          {toast}
        </div>
      )}

      <div className="overflow-x-auto rounded-xl border border-border bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs font-semibold uppercase tracking-wide text-muted">
              <th className="px-4 py-3">Art</th>
              <th className="px-4 py-3">Von</th>
              <th className="px-4 py-3">Bis</th>
              <th className="px-4 py-3">Grund</th>
              <th className="px-4 py-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {absences.map((a) => {
              const sm = STATUS_META[a.status] ?? STATUS_META.pending
              return (
                <tr key={a.id} className="border-b border-border-faint last:border-0">
                  <td className="px-4 py-3 font-medium text-text">{TYPE_LABEL[a.type] ?? a.type}</td>
                  <td className="px-4 py-3 text-body">{fmtDate(a.starts_at)}</td>
                  <td className="px-4 py-3 text-body">{fmtDate(a.ends_at)}</td>
                  <td className="max-w-[260px] truncate px-4 py-3 text-muted">{a.reason || '—'}</td>
                  <td className="px-4 py-3">
                    <span className={cn('rounded-full px-2.5 py-0.5 text-xs font-medium', sm.cls)}>{sm.label}</span>
                    {a.status === 'rejected' && a.internal_note && (
                      <div className="mt-0.5 text-[11px] text-muted">{a.internal_note}</div>
                    )}
                  </td>
                </tr>
              )
            })}
            {!isLoading && !absences.length && (
              <tr>
                <td colSpan={5} className="px-4 py-12 text-center text-muted">
                  Noch keine Abwesenheiten beantragt.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {open && (
        <ApplyModal
          onClose={() => setOpen(false)}
          onSaved={() => {
            qc.invalidateQueries({ queryKey: ['my-absences'] })
            setOpen(false)
            flash('Antrag eingereicht – wartet auf Genehmigung.')
          }}
        />
      )}
    </div>
  )
}

interface EmpLite {
  id: string
  display_name: string
  is_active?: boolean
  open_tickets?: number
}

function ApplyModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [type, setType] = useState('vacation')
  const [from, setFrom] = useState(todayYmd())
  const [until, setUntil] = useState(todayYmd())
  const [reason, setReason] = useState('')
  const [substitute, setSubstitute] = useState('')
  const [error, setError] = useState<string | null>(null)

  // Colleagues who could stand in — each shown with their current open-ticket
  // load so the requester picks someone who isn't already overloaded.
  const { data: employees = [] } = useQuery({
    queryKey: ['absence-substitute-candidates'],
    queryFn: () => apiFetch<EmpLite[]>('/api/employees'),
  })
  const candidates = employees.filter((e) => e.is_active !== false)
  // A substitute is mandatory for planned vacation; illness can be unplanned.
  const substituteRequired = type === 'vacation'

  const save = useMutation({
    mutationFn: () =>
      apiFetch('/api/employees/me/absences', {
        method: 'POST',
        body: JSON.stringify({
          type,
          starts_at: new Date(`${from}T00:00:00`).toISOString(),
          ends_at: new Date(`${until}T23:59:59`).toISOString(),
          all_day: true,
          reason: reason || null,
          substitute_employee_id: substitute || null,
        }),
      }),
    onSuccess: onSaved,
    onError: (e: Error) => setError(e.message),
  })

  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title="Abwesenheit beantragen"
      widthClass="max-w-lg"
      footer={
        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body">
            Abbrechen
          </button>
          <button
            disabled={!from || !until || (substituteRequired && !substitute) || save.isPending}
            onClick={() => save.mutate()}
            className="flex-1 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
          >
            {save.isPending ? 'Wird eingereicht…' : 'Antrag einreichen'}
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        {error && <div className="rounded-md bg-error-bg px-3 py-2 text-sm text-error">{error}</div>}
        <div>
          <label className="mb-1 block text-sm font-medium text-body">Art</label>
          <select value={type} onChange={(e) => setType(e.target.value)} className={inputCls}>
            {TYPE_OPTIONS.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block text-sm font-medium text-body">Von</label>
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className={inputCls} />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-body">Bis</label>
            <input type="date" value={until} min={from} onChange={(e) => setUntil(e.target.value)} className={inputCls} />
          </div>
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-body">
            Vertretung{substituteRequired ? '' : ' (optional)'}
          </label>
          <select value={substitute} onChange={(e) => setSubstitute(e.target.value)} className={inputCls}>
            <option value="">Vertretung wählen…</option>
            {candidates.map((e) => (
              <option key={e.id} value={e.id}>
                {e.display_name} · {e.open_tickets ?? 0} offene Tickets
              </option>
            ))}
          </select>
          <p className="mt-1 text-[11px] text-muted">
            {substituteRequired
              ? 'Für Urlaub erforderlich. Die offenen Tickets je Person helfen bei der Auswahl.'
              : 'Optional – wer übernimmt während der Abwesenheit?'}
          </p>
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-body">Grund (optional)</label>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            className={cn(inputCls, 'resize-none')}
            placeholder="z. B. Familienurlaub"
          />
        </div>
      </div>
    </Modal>
  )
}
