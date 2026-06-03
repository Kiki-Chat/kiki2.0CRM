// Process-request + create-appointment modals. Behavior is unchanged from the
// original screen — same endpoints, same fields, same mutations.
import { useMutation } from '@tanstack/react-query'
import { useEffect, useState, type ReactNode } from 'react'

import { Modal } from '../../components/ui/Modal'
import { apiFetch } from '../../lib/api'
import { cn, initials } from '../../lib/utils'
import {
  type CallDetailData,
  CATEGORIES,
  COLORS,
  displayName,
  type Employee,
  type Inquiry,
  isMeaningful,
  STATUS_TAG,
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
  const [type, setType] = useState(inquiry.type ?? 'info')
  const [notes, setNotes] = useState(inquiry.notes ?? '')
  const [status, setStatus] = useState(inquiry.status)

  useEffect(() => {
    if (open) {
      setTitle(inquiry.title ?? '')
      setType(inquiry.type ?? 'info')
      setNotes(inquiry.notes ?? '')
      setStatus(inquiry.status)
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
            onClick={() => onSave({ title, type, notes, status })}
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
        <Field label="Kategorie">
          <div className="flex flex-wrap gap-2">
            {CATEGORIES.map((cat) => (
              <button
                key={cat}
                onClick={() => setType(cat)}
                className={cn(
                  'rounded-md border px-3 py-1.5 text-sm font-medium capitalize',
                  type === cat ? 'border-green-primary bg-green-primary text-white' : 'border-border bg-surface text-body hover:bg-alt',
                )}
              >
                {cat}
              </button>
            ))}
          </div>
        </Field>
        <Field label="Notiz">
          <textarea
            rows={5}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-body outline-none focus:border-green-primary"
          />
        </Field>
        <Field label="Status">
          <div className="flex gap-2">
            {(['open', 'in_progress', 'completed'] as const).map((s) => (
              <button
                key={s}
                onClick={() => setStatus(s)}
                className={cn(
                  'rounded-full px-3 py-1.5 text-sm font-semibold',
                  status === s
                    ? STATUS_TAG[s].variant === 'success'
                      ? 'bg-success text-white'
                      : STATUS_TAG[s].variant === 'warning'
                        ? 'bg-warning text-white'
                        : 'bg-info text-white'
                    : 'bg-alt text-muted',
                )}
              >
                {STATUS_TAG[s].label}
              </button>
            ))}
          </div>
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
      setApptType('customer')
      setPrivateTitle('')
      setLocation(dc.customer_address ?? call.customers?.phone ?? '')
      setDescription(call.summary ?? dc.ultimate_summary ?? '')
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
