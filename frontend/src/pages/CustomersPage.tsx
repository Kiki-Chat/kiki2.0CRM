import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AtSign,
  ChevronLeft,
  ChevronRight,
  Download,
  LayoutGrid,
  Loader2,
  MapPin,
  Phone,
  Plus,
  Rows3,
  Search,
  Trash2,
  Upload,
  User,
  Users,
} from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import { CsvImportModal } from '../components/CsvImportModal'
import { CustomerFormModal } from '../components/CustomerFormModal'
import { apiBlobUrl, apiFetch } from '../lib/api'
import { cn } from '../lib/utils'

interface CustomerCard {
  id: string
  full_name: string | null
  email: string | null
  phone: string | null
  address: { raw?: string } | string | null
  customer_number: string | null
  customer_type: string | null
  identified_by: string | null
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
// Acquisition source (customers.identified_by) → label + badge. "phone" means the
// customer was identified during a call (AI/agent or manual phone entry).
const SOURCE_META: Record<string, { label: string; badge: string }> = {
  phone: { label: 'Anruf / KI', badge: 'bg-ai-bg text-ai' },
  manual: { label: 'Manuell', badge: 'bg-alt text-body' },
  csv_import: { label: 'Import', badge: 'bg-info-bg text-info' },
}
function sourceMeta(s: string | null): { label: string; badge: string } {
  return SOURCE_META[s ?? ''] ?? { label: 'Unbekannt', badge: 'bg-alt text-muted' }
}
const FILTERS: { key: string; label: string; type?: string }[] = [
  { key: 'all', label: 'Alle' },
  { key: 'new', label: 'Neukunden', type: 'new' },
  { key: 'regular', label: 'Stammkunden', type: 'regular' },
  { key: 'supplier', label: 'Lieferanten', type: 'supplier' },
  { key: 'property_management', label: 'Hausverwaltungen', type: 'property_management' },
]

// Records-per-page choices for the selector.
const PAGE_SIZE_OPTIONS = [24, 48, 96, 200]

// Responsive default page size: estimate the visible columns (from width) × rows
// (from height) so the first page roughly fills the viewport, then snap up to a
// page-size option. Computed once on mount; the user can override via the selector.
function defaultPageSize(): number {
  if (typeof window === 'undefined') return 48
  const cols = window.innerWidth >= 1280 ? 3 : window.innerWidth >= 768 ? 2 : 1
  const rows = Math.max(2, Math.floor((window.innerHeight - 300) / 230))
  const fit = cols * (rows + 1)
  return PAGE_SIZE_OPTIONS.find((o) => o >= fit) ?? PAGE_SIZE_OPTIONS[PAGE_SIZE_OPTIONS.length - 1]
}

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
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(() => defaultPageSize())
  const [view, setView] = useState<'cards' | 'list'>(() =>
    localStorage.getItem('kunden-view') === 'list' ? 'list' : 'cards',
  )
  const [exporting, setExporting] = useState(false)
  useEffect(() => {
    localStorage.setItem('kunden-view', view)
  }, [view])

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['customers', filter, search, page, pageSize],
    queryFn: () => {
      const params = new URLSearchParams()
      if (search.trim()) params.set('q', search.trim())
      const f = FILTERS.find((x) => x.key === filter)
      if (f?.type) params.set('customer_type', f.type)
      params.set('limit', String(pageSize))
      params.set('offset', String(page * pageSize))
      return apiFetch<CustomerListResponse>(`/api/customers?${params.toString()}`)
    },
    // Keep the previous page visible (dimmed) while the next one loads — smooth
    // buffering instead of an empty flash.
    placeholderData: keepPreviousData,
  })
  const customers = data?.customers ?? []
  const counts = data?.type_counts ?? {}
  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const startIdx = total === 0 ? 0 : page * pageSize + 1
  const endIdx = Math.min(total, (page + 1) * pageSize)
  const fmtN = (n: number) => n.toLocaleString('de-DE')

  // Selection (checkbox multi-select + bulk remove). Cleared whenever the visible
  // set changes so a hidden row can never be silently included in a delete.
  // Back to page 1 whenever the query shape changes.
  useEffect(() => {
    setPage(0)
  }, [filter, search, pageSize])
  // Clear selection whenever the visible set changes (so a hidden row can never
  // be silently included in a bulk delete).
  useEffect(() => {
    setSelected(new Set())
  }, [filter, search, page, pageSize])

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

  // Export the CURRENT view (search + active type filter) as a CSV download.
  const exportCsv = async () => {
    setExporting(true)
    try {
      const params = new URLSearchParams()
      if (search.trim()) params.set('q', search.trim())
      const f = FILTERS.find((x) => x.key === filter)
      if (f?.type) params.set('customer_type', f.type)
      const url = await apiBlobUrl(`/api/customers/export?${params.toString()}`)
      const a = document.createElement('a')
      a.href = url
      a.download = `kunden-${new Date().toISOString().slice(0, 10)}.csv`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      window.alert(e instanceof Error ? e.message : 'Export fehlgeschlagen')
    } finally {
      setExporting(false)
    }
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
          <div className="flex items-center rounded-md border border-border bg-surface p-0.5">
            <button
              onClick={() => setView('cards')}
              className={cn(
                'rounded p-1.5 transition-colors',
                view === 'cards' ? 'bg-alt text-text' : 'text-muted hover:text-body',
              )}
              title="Kachelansicht"
              aria-label="Kachelansicht"
              aria-pressed={view === 'cards'}
            >
              <LayoutGrid size={15} />
            </button>
            <button
              onClick={() => setView('list')}
              className={cn(
                'rounded p-1.5 transition-colors',
                view === 'list' ? 'bg-alt text-text' : 'text-muted hover:text-body',
              )}
              title="Listenansicht"
              aria-label="Listenansicht"
              aria-pressed={view === 'list'}
            >
              <Rows3 size={15} />
            </button>
          </div>
          <HeaderBtn
            icon={Download}
            label={exporting ? 'Export…' : 'CSV Export'}
            onClick={exportCsv}
            disabled={exporting}
          />
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
      {isLoading ? (
        <div className="flex items-center justify-center py-24 text-muted">
          <Loader2 size={22} className="mr-2 animate-spin" /> Kunden werden geladen…
        </div>
      ) : view === 'list' ? (
        <div
          aria-busy={isFetching}
          className={cn(
            'overflow-x-auto rounded-xl border border-border bg-surface transition-opacity',
            isFetching && 'pointer-events-none opacity-50',
          )}
        >
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-alt text-left text-xs uppercase tracking-wide text-muted">
                <th className="w-10 px-3 py-2.5">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={toggleAll}
                    aria-label="Alle auswählen"
                    className="h-4 w-4 cursor-pointer accent-green-primary"
                  />
                </th>
                <th className="px-3 py-2.5 font-semibold">Name</th>
                <th className="px-3 py-2.5 font-semibold">Kundennr.</th>
                <th className="px-3 py-2.5 font-semibold">Typ</th>
                <th className="px-3 py-2.5 font-semibold">Quelle</th>
                <th className="px-3 py-2.5 font-semibold">E-Mail</th>
                <th className="px-3 py-2.5 font-semibold">Telefon</th>
                <th className="px-3 py-2.5 font-semibold">Adresse</th>
                <th
                  className="px-3 py-2.5 text-right font-semibold"
                  title="Anfragen · Termine · Dokumente/Fotos"
                >
                  A · T · D
                </th>
              </tr>
            </thead>
            <tbody>
              {customers.map((c) => {
                const meta = TYPE_META[c.customer_type ?? 'new'] ?? TYPE_META.new
                const sm = sourceMeta(c.identified_by)
                const isSel = selected.has(c.id)
                return (
                  <tr
                    key={c.id}
                    onClick={() => navigate(`/customers/${c.id}`)}
                    className={cn(
                      'cursor-pointer border-b border-border transition-colors last:border-0 hover:bg-green-tint-50',
                      isSel && 'bg-green-tint-50',
                    )}
                  >
                    <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={isSel}
                        onChange={() => toggle(c.id)}
                        aria-label={`${c.full_name ?? 'Kunde'} auswählen`}
                        className="h-4 w-4 cursor-pointer accent-green-primary"
                      />
                    </td>
                    <td className="px-3 py-2.5 font-semibold text-text">{c.full_name ?? 'Unbekannt'}</td>
                    <td className="px-3 py-2.5 text-muted">{c.customer_number ?? '—'}</td>
                    <td className="px-3 py-2.5">
                      <span className={cn('rounded-full px-2 py-0.5 text-xs font-bold', meta.badge)}>
                        {meta.label}
                      </span>
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={cn('rounded-full px-2 py-0.5 text-xs font-medium', sm.badge)}>
                        {sm.label}
                      </span>
                    </td>
                    <td className="max-w-[200px] truncate px-3 py-2.5 text-muted">{c.email ?? '—'}</td>
                    <td className="px-3 py-2.5 text-muted">{c.phone ?? '—'}</td>
                    <td className="max-w-[220px] truncate px-3 py-2.5 text-muted">{addr(c.address)}</td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-right text-xs text-muted">
                      {c.inquiry_count} · {c.appointment_count} · {c.photo_count + c.document_count}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div
          aria-busy={isFetching}
          className={cn(
            'grid grid-cols-1 gap-5 transition-opacity md:grid-cols-2 xl:grid-cols-3',
            isFetching && 'pointer-events-none opacity-50',
          )}
        >
          {customers.map((c) => {
            const meta = TYPE_META[c.customer_type ?? 'new'] ?? TYPE_META.new
            const sm = sourceMeta(c.identified_by)
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
                  <div className="flex shrink-0 flex-col items-end gap-1">
                    <span className={cn('rounded-full px-2.5 py-0.5 text-xs font-bold', meta.badge)}>
                      {meta.label}
                    </span>
                    <span className={cn('rounded-full px-2 py-0.5 text-[10px] font-medium', sm.badge)}>
                      {sm.label}
                    </span>
                  </div>
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
      )}

      {!isLoading && !customers.length && (
        <div className="py-16 text-center text-muted">Keine Kunden gefunden.</div>
      )}

      {/* Pagination */}
      {total > 0 && (
        <div className="mt-6 flex flex-wrap items-center justify-between gap-4 border-t border-border pt-4">
          <div className="flex flex-wrap items-center gap-4 text-sm text-muted">
            <span>
              {fmtN(startIdx)}–{fmtN(endIdx)} von {fmtN(total)}
            </span>
            <label className="flex items-center gap-1.5">
              <span>Pro Seite</span>
              <select
                value={pageSize}
                onChange={(e) => setPageSize(Number(e.target.value))}
                className="rounded-md border border-border bg-surface px-2 py-1 text-sm text-body outline-none focus:border-green-primary"
              >
                {PAGE_SIZE_OPTIONS.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            </label>
            {isFetching && (
              <span className="flex items-center gap-1 text-faint">
                <Loader2 size={13} className="animate-spin" /> Lädt…
              </span>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            <PageBtn onClick={() => setPage(0)} disabled={page === 0}>
              Erste
            </PageBtn>
            <PageBtn onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}>
              <ChevronLeft size={15} />
            </PageBtn>
            <span className="px-2 text-sm font-medium text-body">
              Seite {page + 1} / {totalPages}
            </span>
            <PageBtn
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
            >
              <ChevronRight size={15} />
            </PageBtn>
            <PageBtn onClick={() => setPage(totalPages - 1)} disabled={page >= totalPages - 1}>
              Letzte
            </PageBtn>
          </div>
        </div>
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

function PageBtn({
  children,
  onClick,
  disabled,
}: {
  children: ReactNode
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="flex items-center gap-1 rounded-md border border-border bg-surface px-3 py-1.5 text-sm font-medium text-body transition-colors hover:bg-alt disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  )
}
