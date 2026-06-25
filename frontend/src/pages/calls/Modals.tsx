// Process-request + create-appointment modals. Behavior is unchanged from the
// original screen — same endpoints, same fields, same mutations.
import { useMutation } from '@tanstack/react-query'
import { useEffect, useState, type ReactNode } from 'react'

import { Modal } from '../../components/ui/Modal'
import { apiFetch } from '../../lib/api'
import { cn, initials } from '../../lib/utils'
import {
  absoluteTimeDe,
  type CallDetailData,
  COLORS,
  displayName,
  type Employee,
  type Inquiry,
  isMeaningful,
} from './shared'

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 text-xs font-semibold text-body">{label}</div>
      {children}
    </div>
  )
}

export function ProcessRequestModal({
  open,
  onClose,
  inquiry,
  onSave,
}: {
  open: boolean
  onClose: () => void
  inquiry: Inquiry
  onSave: (body: Partial<Inquiry>) => void
}) {
  const [title, setTitle] = useState(inquiry.title ?? '')
  const [notes, setNotes] = useState(inquiry.notes ?? '')

  useEffect(() => {
    if (open) {
      setTitle(inquiry.title ?? '')
      setNotes(inquiry.notes ?? '')
    }
  }, [open, inquiry])

  return (
    <Modal
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Anfrage bearbeiten"
      footer={
        <div className="flex gap-3">
          <button
            onClick={() => onSave({ title, notes })}
            className="flex-1 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110"
          >
            Aktualisieren
          </button>
          <button onClick={onClose} className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body">
            Abbrechen
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        <Field label="Referenz">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary"
          />
        </Field>
        <Field label="Notiz">
          <textarea
            rows={5}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-body outline-none focus:border-green-primary"
          />
        </Field>
      </div>
    </Modal>
  )
}

export function CreateAppointmentModal({
  open,
  onClose,
  call,
  inquiryId,
  employees,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  call: CallDetailData
  inquiryId: string | undefined
  employees: Employee[]
  onCreated: () => void
}) {
  const dc = call.data_collection ?? {}
  const [apptType, setApptType] = useState<'customer' | 'private'>('customer')
  const [privateTitle, setPrivateTitle] = useState('')
  const [date, setDate] = useState('')
  const [time, setTime] = useState('09:00')
  const [duration, setDuration] = useState(60)
  const [color, setColor] = useState(COLORS[0])
  const [location, setLocation] = useState('')
  const [assigned, setAssigned] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      const pf = call.enrichment?.prefill
      setApptType('customer')
      setPrivateTitle('')
      setLocation(pf?.address ?? dc.customer_address ?? call.customers?.phone ?? '')
      const baseDesc = pf?.problem ?? call.summary ?? dc.ultimate_summary ?? ''
      // Surface the caller's preferred time (the AI can't reliably set the date
      // field, but staff should see it) as the first note line.
      setDescription(
        pf?.preferred_time ? `Wunschtermin laut Anruf: ${pf.preferred_time}\n\n${baseDesc}`.trim() : baseDesc,
      )
      setError(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const create = useMutation({
    mutationFn: () => {
      const iso = new Date(`${date}T${time}`).toISOString()
      const isPrivate = apptType === 'private'
      return apiFetch('/api/appointments', {
        method: 'POST',
        body: JSON.stringify({
          customer_id: isPrivate ? null : call.customer_id,
          title: isPrivate ? privateTitle || 'Privater Termin' : call.summary_title ?? 'Termin',
          scheduled_at: iso,
          duration_minutes: duration,
          location,
          color,
          assigned_employee_id: assigned || null,
          notes: description,
          inquiry_id: isPrivate ? null : inquiryId ?? null,
        }),
      })
    },
    onSuccess: onCreated,
    onError: () => setError('Termin konnte nicht erstellt werden.'),
  })

  const customerName = isMeaningful(call.customers?.full_name) ? call.customers!.full_name : displayName(call)

  return (
    <Modal
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Termin erstellen"
      widthClass="max-w-xl"
      footer={
        <div className="flex gap-3">
          <button
            disabled={!date || create.isPending}
            onClick={() => create.mutate()}
            className="flex-1 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
          >
            {create.isPending ? 'Speichert…' : 'Termin speichern'}
          </button>
          <button onClick={onClose} className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body">
            Abbrechen
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-2 rounded-md bg-alt p-1">
          {(['customer', 'private'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setApptType(t)}
              className={cn('rounded-md py-2 text-sm font-semibold transition-colors', apptType === t ? 'bg-green-primary text-white' : 'text-muted')}
            >
              {t === 'customer' ? 'Kunde' : 'Privat'}
            </button>
          ))}
        </div>

        {apptType === 'customer' ? (
          <Field label="Kunde">
            <div className="flex items-center gap-2 rounded-md border border-border bg-green-tint-50 px-3 py-2.5">
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-green-tint-100 text-xs font-bold text-green-deep">
                {initials(customerName ?? '?')}
              </div>
              <span className="text-sm font-medium text-text">{customerName}</span>
            </div>
          </Field>
        ) : (
          <Field label="Titel *">
            <input
              value={privateTitle}
              onChange={(e) => setPrivateTitle(e.target.value)}
              placeholder="z. B. Werkstatt-Wartung"
              className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary"
            />
          </Field>
        )}

        <div className="grid grid-cols-2 gap-3">
          <Field label="Datum *">
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary" />
          </Field>
          <Field label="Uhrzeit *">
            <input type="time" value={time} onChange={(e) => setTime(e.target.value)} className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary" />
          </Field>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Dauer">
            <select value={duration} onChange={(e) => setDuration(Number(e.target.value))} className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary">
              {[30, 60, 90, 120].map((m) => (
                <option key={m} value={m}>
                  {m} Min
                </option>
              ))}
            </select>
          </Field>
          <Field label="Farbe">
            <div className="flex items-center gap-2 pt-1.5">
              {COLORS.map((c) => (
                <button
                  key={c}
                  onClick={() => setColor(c)}
                  className={cn('h-6 w-6 rounded-full transition-transform', color === c && 'ring-2 ring-offset-2 ring-offset-surface')}
                  style={{ background: c, boxShadow: color === c ? `0 0 0 2px ${c}` : undefined }}
                />
              ))}
            </div>
          </Field>
        </div>

        <Field label="Ort">
          <input value={location} onChange={(e) => setLocation(e.target.value)} className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary" />
        </Field>

        <Field label="Zugewiesen an">
          <select value={assigned} onChange={(e) => setAssigned(e.target.value)} className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary">
            <option value="">— Nicht zugewiesen —</option>
            {employees.map((e) => (
              <option key={e.id} value={e.id}>
                {e.display_name}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Fahrzeuge & Werkzeuge">
          <div className="rounded-md border border-dashed border-border px-3 py-2.5 text-xs text-faint">
            Inventar (Planungstafel) — folgt in einer späteren Phase.
          </div>
        </Field>

        <Field label="Beschreibung">
          <textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-body outline-none focus:border-green-primary" />
        </Field>

        {error && <div className="text-sm text-error">{error}</div>}
      </div>
    </Modal>
  )
}

// One-click approve/decline for a customer-proposed reschedule, openable straight from
// the Aktionen tab (no need to find the call). Pre-filled with the proposed slot.
export function RescheduleApprovalModal({
  open,
  appointmentId,
  customerName,
  proposedTime,
  originalTime,
  expiresAt,
  replaceIntent,
  onClose,
  onResolved,
}: {
  open: boolean
  appointmentId: string | null
  customerName: string | null
  proposedTime: string | null
  originalTime?: string | null
  expiresAt?: string | null
  replaceIntent?: boolean | null
  onClose: () => void
  onResolved: () => void
}) {
  const overdue = !!expiresAt && new Date(expiresAt).getTime() < Date.now()
  const [error, setError] = useState<string | null>(null)
  const done = () => {
    onResolved()
    onClose()
  }
  const approve = useMutation({
    mutationFn: () => apiFetch(`/api/appointments/${appointmentId}/approve-proposal`, { method: 'POST' }),
    onSuccess: done,
    onError: (e: Error) => setError(e.message || 'Genehmigung fehlgeschlagen.'),
  })
  const decline = useMutation({
    mutationFn: () => apiFetch(`/api/appointments/${appointmentId}/decline-proposal`, { method: 'POST' }),
    onSuccess: done,
    onError: (e: Error) => setError(e.message || 'Ablehnen fehlgeschlagen.'),
  })
  const busy = approve.isPending || decline.isPending
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Terminänderung genehmigen">
      <div className="space-y-4">
        <p className="text-sm text-body">
          <span className="font-semibold">{customerName || 'Der Kunde'}</span> möchte den Termin verschieben:
        </p>
        <div className="flex items-stretch gap-2">
          <div className="flex-1 rounded-lg border border-border bg-alt p-3 text-center">
            <div className="text-sm font-semibold text-body line-through">
              {originalTime ? absoluteTimeDe(originalTime) : '—'}
            </div>
            <div className="text-xs text-muted">Bisheriger Termin</div>
          </div>
          <div className="flex items-center text-muted">→</div>
          <div className="flex-1 rounded-lg border border-orange-200 bg-orange-50 p-3 text-center">
            <div className="text-sm font-bold text-orange-700">
              {proposedTime ? absoluteTimeDe(proposedTime) : '—'}
            </div>
            <div className="text-xs text-muted">Gewünschter neuer Termin</div>
          </div>
        </div>
        {overdue && (
          <div className="rounded-md bg-amber-50 px-3 py-2 text-xs font-medium text-amber-700">
            Diese Anfrage ist überfällig — der Kunde wartet auf deine Entscheidung.
          </div>
        )}
        <p className="text-xs text-muted">
          „Genehmigen" verschiebt den Termin auf diese Zeit, bestätigt ihn und informiert den Kunden (Anruf + E-Mail).
          {replaceIntent
            ? ' „Ablehnen" — der Kunde wollte den alten Termin nicht behalten, daher wird er storniert und der Kunde informiert.'
            : ' „Ablehnen" verwirft den Vorschlag — der bisherige Termin bleibt bestehen.'}
        </p>
        {error && <div className="rounded-md bg-error-bg px-3 py-2 text-xs text-error">{error}</div>}
        <div className="flex gap-3">
          <button
            disabled={busy}
            onClick={() => {
              setError(null)
              approve.mutate()
            }}
            className="flex-1 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
          >
            {approve.isPending ? 'Genehmigt…' : 'Genehmigen'}
          </button>
          <button
            disabled={busy}
            onClick={() => {
              setError(null)
              decline.mutate()
            }}
            className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body hover:bg-surface disabled:opacity-50"
          >
            {decline.isPending ? 'Lehnt ab…' : 'Ablehnen'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
