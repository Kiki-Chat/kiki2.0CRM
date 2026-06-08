import { useMutation } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import { apiFetch } from '../lib/api'
import { cn } from '../lib/utils'
import { Modal } from './ui/Modal'

export interface CustomerFormValues {
  id?: string
  full_name?: string | null
  email?: string | null
  phone?: string | null
  phone2?: string | null
  address?: { raw?: string } | string | null
  vat_id?: string | null
  customer_number?: string | null
  customer_type?: string | null
  notes?: string | null
}

const TYPES: { value: string; label: string; cls: string }[] = [
  { value: 'new', label: 'Neukunde', cls: 'bg-info text-white' },
  { value: 'regular', label: 'Stammkunde', cls: 'bg-success text-white' },
  { value: 'supplier', label: 'Lieferant', cls: 'bg-warning text-white' },
  { value: 'property_management', label: 'Hausverwaltung', cls: 'bg-ai text-white' },
]

function addrToString(a: CustomerFormValues['address']): string {
  if (!a) return ''
  if (typeof a === 'string') return a
  return a.raw ?? ''
}

export function CustomerFormModal({
  open,
  onClose,
  mode,
  customer,
  onSaved,
  onDeleted,
}: {
  open: boolean
  onClose: () => void
  mode: 'create' | 'edit'
  customer?: CustomerFormValues
  onSaved: (c: CustomerFormValues) => void
  onDeleted?: () => void
}) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [phone2, setPhone2] = useState('')
  const [address, setAddress] = useState('')
  const [vat, setVat] = useState('')
  const [number, setNumber] = useState('')
  const [type, setType] = useState('new')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setName(customer?.full_name ?? '')
    setEmail(customer?.email ?? '')
    setPhone(customer?.phone ?? '')
    setPhone2(customer?.phone2 ?? '')
    setAddress(addrToString(customer?.address))
    setVat(customer?.vat_id ?? '')
    setNumber(customer?.customer_number ?? '')
    setType(customer?.customer_type ?? 'new')
    setNotes(customer?.notes ?? '')
    setError(null)
  }, [open, customer])

  const save = useMutation({
    mutationFn: () => {
      const body = {
        full_name: name,
        email,
        phone,
        phone2,
        address,
        vat_id: vat,
        customer_type: type,
        notes,
        customer_number: number || undefined,
      }
      return mode === 'create'
        ? apiFetch<CustomerFormValues>('/api/customers', {
            method: 'POST',
            body: JSON.stringify(body),
          })
        : apiFetch<CustomerFormValues>(`/api/customers/${customer!.id}`, {
            method: 'PATCH',
            body: JSON.stringify(body),
          })
    },
    onSuccess: onSaved,
    onError: () => setError('Speichern fehlgeschlagen.'),
  })

  const del = useMutation({
    mutationFn: () =>
      apiFetch(`/api/customers/${customer!.id}`, { method: 'DELETE' }),
    onSuccess: () => onDeleted?.(),
  })

  return (
    <Modal
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title={mode === 'create' ? 'Neuer Kunde' : 'Kundendaten bearbeiten'}
      footer={
        <div className="space-y-3">
          <div className="flex gap-3">
            <button
              disabled={!name || save.isPending}
              onClick={() => save.mutate()}
              className="flex-1 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
            >
              {save.isPending ? 'Speichert…' : 'Aktualisieren'}
            </button>
            <button
              onClick={onClose}
              className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body"
            >
              Abbrechen
            </button>
          </div>
          {mode === 'edit' && (
            <button
              onClick={() => del.mutate()}
              className="flex w-full items-center justify-center gap-2 rounded-md bg-error-bg py-2.5 text-sm font-medium text-error hover:brightness-105"
            >
              <Trash2 size={15} /> Kunde löschen
            </button>
          )}
        </div>
      }
    >
      <div className="space-y-4">
        <Field label="Name *">
          <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} />
        </Field>
        <Field label="E-Mail">
          <input value={email} onChange={(e) => setEmail(e.target.value)} className={inputCls} />
        </Field>
        <Field label="Telefon">
          <input value={phone} onChange={(e) => setPhone(e.target.value)} className={inputCls} />
        </Field>
        <Field label="Telefon 2 (Mobil)">
          <input
            value={phone2}
            onChange={(e) => setPhone2(e.target.value)}
            placeholder="Zweite Rufnummer (optional)"
            className={inputCls}
          />
        </Field>
        <Field label="Adresse">
          <input value={address} onChange={(e) => setAddress(e.target.value)} className={inputCls} />
        </Field>
        <Field label="USt-IdNr. (nur Gewerbe)">
          <input
            value={vat}
            onChange={(e) => setVat(e.target.value)}
            placeholder="DE123456789 (optional)"
            className={inputCls}
          />
        </Field>
        <Field label="Kundennummer">
          <input
            value={number}
            onChange={(e) => setNumber(e.target.value)}
            placeholder="Automatisch (z. B. KI-000001)"
            className={inputCls}
          />
          <p className="mt-1 text-xs text-faint">
            Wird automatisch mit „KI-"-Präfix vergeben (eindeutig system­generiert, kollidiert
            nie mit Ihren eigenen Nummern). Manuelles Überschreiben nur bei Datenübernahme.
          </p>
        </Field>
        <Field label="Kundentyp">
          <div className="flex flex-wrap gap-2">
            {TYPES.map((t) => (
              <button
                key={t.value}
                onClick={() => setType(t.value)}
                className={cn(
                  'rounded-md px-3 py-2 text-sm font-semibold transition-colors',
                  type === t.value ? t.cls : 'bg-alt text-muted',
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        </Field>
        <Field label="Notizen">
          <textarea
            rows={3}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className={inputCls}
          />
        </Field>
        {error && <div className="text-sm text-error">{error}</div>}
      </div>
    </Modal>
  )
}

const inputCls =
  'w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 text-xs font-semibold text-body">{label}</div>
      {children}
    </div>
  )
}
