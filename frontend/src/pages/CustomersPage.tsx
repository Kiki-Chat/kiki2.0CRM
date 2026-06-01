import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AtSign,
  Download,
  MapPin,
  Phone,
  Plus,
  Search,
  Trash2,
  Upload,
  User,
  Users,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { CsvImportModal } from '../components/CsvImportModal'
import { CustomerFormModal } from '../components/CustomerFormModal'
import { apiFetch } from '../lib/api'
import { cn } from '../lib/utils'

interface CustomerCard {
  id: string
  full_name: string | null
  email: string | null
  phone: string | null
  address: { raw?: string } | string | null
  customer_number: string | null
  customer_type: string | null
  inquiry_count: number
  appointment_count: number
  photo_count: number
  document_count: number
}
interface CustomerListResponse {
  customers: CustomerCard[]
  total: number
  type_counts: Record<string, number>
}

const TYPE_META: Record<string, { label: string; badge: string }> = {
  new: { label: 'Neukunde', badge: 'bg-info-bg text-info' },
  regular: { label: 'Stammkunde', badge: 'bg-success-bg text-success' },
  supplier: { label: 'Lieferant', badge: 'bg-warning-bg text-warning' },
  property_management: { label: 'Hausverwaltung', badge: 'bg-ai-bg text-ai' },
}
const FILTERS: { key: string; label: string; type?: string }[] = [
  { key: 'all', label: 'Alle' },
  { key: 'new', label: 'Neukunden', type: 'new' },
  { key: 'regular', label: 'Stammkunden', type: 'regular' },
  { key: 'supplier', label: 'Lieferanten', type: 'supplier' },
  { key: 'property_management', label: 'Hausverwaltungen', type: 'property_management' },
]

function addr(a: CustomerCard['address']): string {
  if (!a) return '—'
  return typeof a === 'string' ? a : a.raw ?? '—'
}

export function CustomersPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('all')
  const [newOpen, setNewOpen] = useState(false)
  const [csvOpen, setCsvOpen] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const { data } = useQuery({
    queryKey: ['customers', filter, search],
    queryFn: () => {
      const params = new URLSearchParams()
      if (search.trim()) params.set('q', search.trim())
      const f = FILTERS.find((x) => x.key === filter)
      if (f?.type) params.set('customer_type', f.type)
      return apiFetch<CustomerListResponse>(`/api/customers?${params.toString()}`)
    },
  })
  const customers = data?.customers ?? []
  const counts = data?.type_counts ?? {}

  // Selection (checkbox multi-select + bulk remove). Cleared whenever the visible
  // set changes so a hidden row can never be silently included in a delete.
  useEffect(() => {
    setSelected(new Set())
  }, [filter, search])

  const allSelected = customers.length > 0 && customers.every((c) => selected.has(c.id))
  const someSelected = selected.size > 0 && !allSelected
  const selectAllRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = someSelected
  }, [someSelected])

  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  const toggleAll = () => setSelected(allSelected ? new Set() : new Set(customers.map((c) => c.id)))
  const clear = () => setSelected(new Set())

  const del = useMutation({
    mutationFn: (ids: string[]) =>
      apiFetch<{ deleted: number }>('/api/customers/bulk-delete', {
        method: 'POST',
        body: JSON.stringify({ ids }),
      }),
    onSuccess: () => {
      clear()
      qc.invalidateQueries({ queryKey: ['customers'] })
    },
  })
  const removeSelected = () => {
    const ids = [...selected]
    if (!ids.length) return
    if (window.confirm(`${ids.length} ${ids.length > 1 ? 'Kunden' : 'Kunde'} wirklich entfernen?`)) del.mutate(ids)
  }

  return (
    <div className="mx-auto max-w-[1440px] p-8">
      {/* Header */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Users size={26} className="text-green-deep" />
          <h1 className="text-2xl font-bold text-text">Kunden</h1>
        </div>
        <div className="flex items-center gap-2">
          <span className="mr-2 text-sm text-muted">
            {data?.total ?? 0} von {counts.all ?? 0} Kunden
          </span>
          <HeaderBtn icon={Download} label="CSV Export" disabled />
          <HeaderBtn icon={Upload} label="CSV Import" onClick={() => setCsvOpen(true)} />
          <button
            onClick={() => setNewOpen(true)}
            className="flex items-center gap-2 rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110"
          >
            <Plus size={16} /> Neuer Kunde
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="relative mb-4">
        <Search size={16} className="absolute left-4 top-1/2 -translate-y-1/2 text-faint" />
        <input
          type="search"
          name="customer-search"
          autoComplete="off"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Suche nach Name, E-Mail, Telefon, Adresse oder Kundennummer…"
          className="w-full rounded-lg border border-border bg-surface py-3 pl-11 pr-4 text-sm text-body shadow-e1 outline-none focus:border-green-primary"
        />
      </div>

      {/* Filter tabs */}
      <div className="mb-4 flex flex-wrap gap-2">
        {FILTERS.map((f) => {
          const active = filter === f.key
          const count = f.key === 'all' ? counts.all ?? 0 : counts[f.type!] ?? 0
          return (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={cn(
                'flex items-center gap-2 rounded-full px-4 py-1.5 text-sm font-semibold transition-colors',
                active ? 'bg-text text-white' : 'bg-surface text-body hover:bg-alt',
              )}
            >
              <span className={active ? '' : f.type ? typeText(f.type) : ''}>{f.label}</span>
              <span className={cn('text-xs', active ? 'text-white/70' : 'text-faint')}>{count}</span>
            </button>
          )
        })}
      </div>

      {/* Selection / bulk-remove bar */}
      {customers.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <label className="flex cursor-pointer items-center gap-2 text-sm font-medium text-body">
            <input
              ref={selectAllRef}
              type="checkbox"
              checked={allSelected}
              onChange={toggleAll}
              className="h-4 w-4 cursor-pointer accent-green-primary"
            />
            {selected.size > 0 ? `${selected.size} ausgewählt` : 'Alle auswählen'}
          </label>
          {selected.size > 0 && (
            <div className="flex items-center gap-2">
              <button
                onClick={clear}
                className="rounded-md border border-border bg-surface px-3 py-1.5 text-sm font-medium text-body hover:bg-alt"
              >
                Abbrechen
              </button>
              <button
                onClick={removeSelected}
                disabled={del.isPending}
                className="flex items-center gap-2 rounded-md bg-error px-4 py-1.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
              >
                <Trash2 size={15} /> {del.isPending ? 'Löscht…' : `Löschen (${selected.size})`}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Grid */}
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
        {customers.map((c) => {
          const meta = TYPE_META[c.customer_type ?? 'new'] ?? TYPE_META.new
          const isSel = selected.has(c.id)
          return (
            <div
              key={c.id}
              role="button"
              tabIndex={0}
              onClick={() => navigate(`/customers/${c.id}`)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') navigate(`/customers/${c.id}`)
              }}
              className={cn(
                'relative flex cursor-pointer flex-col rounded-lg border bg-surface p-5 text-left shadow-e1 transition hover:bg-green-tint-50 hover:shadow-e2',
                isSel ? 'border-green-primary ring-1 ring-green-primary' : 'border-border',
              )}
            >
              <div className="mb-4 flex items-start justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2.5">
                  <input
                    type="checkbox"
                    checked={isSel}
                    onClick={(e) => e.stopPropagation()}
                    onChange={() => toggle(c.id)}
                    aria-label={`${c.full_name ?? 'Kunde'} auswählen`}
                    className="h-4 w-4 shrink-0 cursor-pointer accent-green-primary"
                  />
                  <User size={18} className="shrink-0 text-green-deep" />
                  <span className="truncate text-base font-bold text-text">{c.full_name ?? 'Unbekannt'}</span>
                </div>
                <span className={cn('shrink-0 rounded-full px-2.5 py-0.5 text-xs font-bold', meta.badge)}>
                  {meta.label}
                </span>
              </div>
              <div className="space-y-1.5 text-sm text-muted">
                <div className="flex items-center gap-2">
                  <AtSign size={14} className="flex-shrink-0 text-faint" />
                  <span className="truncate">{c.email ?? '—'}</span>
                </div>
                <div className="flex items-center gap-2">
                  <Phone size={14} className="flex-shrink-0 text-faint" />
                  <span className="truncate">{c.phone ?? '—'}</span>
                </div>
                <div className="flex items-center gap-2">
                  <MapPin size={14} className="flex-shrink-0 text-faint" />
                  <span className="truncate">{addr(c.address)}</span>
                </div>
              </div>
              <div className="mt-4 border-t border-border pt-3 text-xs text-muted">
                {c.inquiry_count} Anfragen · {c.appointment_count} Termine · {c.photo_count} Fotos ·{' '}
                {c.document_count} Dokumente
              </div>
            </div>
          )
        })}
      </div>

      {!customers.length && (
        <div className="py-16 text-center text-muted">Keine Kunden gefunden.</div>
      )}

      <CustomerFormModal
        open={newOpen}
        mode="create"
        onClose={() => setNewOpen(false)}
        onSaved={(c) => {
          setNewOpen(false)
          qc.invalidateQueries({ queryKey: ['customers'] })
          if (c.id) navigate(`/customers/${c.id}`)
        }}
      />
      {csvOpen && (
        <CsvImportModal
          entity="customers"
          onClose={() => setCsvOpen(false)}
          onDone={() => qc.invalidateQueries({ queryKey: ['customers'] })}
        />
      )}
    </div>
  )
}

function typeText(type: string): string {
  return (
    { new: 'text-info', regular: 'text-success', supplier: 'text-warning', property_management: 'text-ai' }[
      type
    ] ?? ''
  )
}

function HeaderBtn({
  icon: Icon,
  label,
  disabled,
  onClick,
}: {
  icon: typeof Download
  label: string
  disabled?: boolean
  onClick?: () => void
}) {
  return (
    <button
      disabled={disabled}
      onClick={onClick}
      title={disabled ? 'Bald verfügbar' : undefined}
      className="flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-2 text-sm font-medium text-body hover:bg-alt disabled:opacity-50"
    >
      <Icon size={15} /> {label}
    </button>
  )
}
