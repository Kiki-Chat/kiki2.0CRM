import {
  AtSign,
  FileText,
  MapPin,
  MoreHorizontal,
  Paperclip,
  Pencil,
  Phone,
  RefreshCw,
  Sparkles,
  StickyNote,
  Trash2,
} from 'lucide-react'
import { useState } from 'react'

import { cn } from '../../lib/utils'
import type { CustomerDetail } from './types'
import { addrStr } from './useCustomerVorgaenge'

const TYPE_META: Record<string, { label: string; badge: string }> = {
  new: { label: 'Neukunde', badge: 'bg-info-bg text-info' },
  regular: { label: 'Stammkunde', badge: 'bg-success-bg text-success' },
  supplier: { label: 'Lieferant', badge: 'bg-warning-bg text-warning' },
  property_management: { label: 'Hausverwaltung', badge: 'bg-ai-bg text-ai' },
}

interface Props {
  customer: CustomerDetail
  onEdit: () => void
  onCreateOffer: () => void
  onOpenDocuments: () => void
  onKiGrouping: () => void
  onDelete: () => void
}

export function CustomerHeader({ customer, onEdit, onCreateOffer, onOpenDocuments, onKiGrouping, onDelete }: Props) {
  const [overflow, setOverflow] = useState(false)
  const meta = TYPE_META[customer.customer_type ?? 'new'] ?? TYPE_META.new
  const phones: { label: string; value: string }[] = []
  if (customer.phone) phones.push({ label: 'Mobil', value: customer.phone })
  if (customer.phone2) phones.push({ label: 'Festnetz', value: customer.phone2 })

  return (
    <div className="rounded-2xl border border-border bg-surface p-6 shadow-e1">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-bold text-text">{customer.full_name ?? 'Unbekannt'}</h1>
          {customer.customer_number && (
            <span className="rounded-md bg-alt px-2 py-0.5 font-mono text-xs text-muted">#{customer.customer_number}</span>
          )}
          <span className={cn('rounded-full px-2.5 py-0.5 text-xs font-bold', meta.badge)}>{meta.label}</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onCreateOffer}
            className="flex items-center gap-1.5 rounded-md px-3 py-2 text-sm font-semibold text-green-deep hover:bg-green-tint-50"
          >
            <FileText size={15} /> Angebot erstellen
          </button>
          <button
            onClick={onOpenDocuments}
            className="flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-2 text-sm font-medium text-body hover:bg-alt"
          >
            <Paperclip size={15} /> Dokument
          </button>
          <button
            onClick={onEdit}
            className="flex items-center gap-2 rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110"
          >
            <Pencil size={15} /> Bearbeiten
          </button>
          <div className="relative">
            <button
              onClick={() => setOverflow((o) => !o)}
              className="flex h-9 w-9 items-center justify-center rounded-md border border-border bg-surface text-body hover:bg-alt"
              title="Weitere Aktionen"
            >
              <MoreHorizontal size={16} />
            </button>
            {overflow && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setOverflow(false)} />
                <div className="absolute right-0 top-full z-50 mt-1.5 w-64 rounded-xl border border-border bg-surface p-1.5 shadow-e3">
                  <div className="px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-faint">KI-Werkzeuge</div>
                  <button
                    onClick={() => {
                      setOverflow(false)
                      onKiGrouping()
                    }}
                    className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm text-body hover:bg-alt"
                  >
                    <Sparkles size={16} className="text-ai" />
                    <span className="flex-1">KI-Gruppierung vorschlagen</span>
                  </button>
                  <button
                    onClick={() => {
                      setOverflow(false)
                      onKiGrouping()
                    }}
                    className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm text-body hover:bg-alt"
                  >
                    <RefreshCw size={16} className="text-muted" />
                    <span className="flex-1">Alles neu gruppieren</span>
                  </button>
                  <div className="my-1 h-px bg-border-faint" />
                  <button
                    onClick={() => {
                      setOverflow(false)
                      onDelete()
                    }}
                    className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm text-error hover:bg-error-bg"
                  >
                    <Trash2 size={16} />
                    <span className="flex-1">Kunde löschen</span>
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-x-7 gap-y-2.5 border-t border-border pt-5 text-sm text-muted">
        <div className="flex items-center gap-2">
          <AtSign size={14} className="text-faint" />
          <span className="truncate">{customer.email ?? '—'}</span>
        </div>
        {phones.map((p) => (
          <div key={p.value} className="flex items-center gap-2">
            <Phone size={14} className="text-faint" />
            <span className="text-[11px] font-semibold uppercase tracking-wide text-faint">{p.label}</span>
            <span className="font-mono text-body">{p.value}</span>
          </div>
        ))}
        <div className="flex items-center gap-2">
          <MapPin size={14} className="text-faint" />
          <span className="truncate">{addrStr(customer.address)}</span>
        </div>
      </div>

      {customer.notes && (
        <div className="mt-3 flex items-start gap-2 rounded-lg bg-alt px-3 py-2 text-xs text-body">
          <StickyNote size={14} className="mt-px flex-shrink-0 text-faint" />
          <span className="whitespace-pre-wrap">{customer.notes}</span>
        </div>
      )}
    </div>
  )
}
