import { useQuery } from '@tanstack/react-query'
import {
  Calendar,
  ClipboardList,
  FileText,
  FolderOpen,
  Phone,
  Receipt,
  Search,
  Users,
} from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { apiFetch } from '../lib/api'
import { cn } from '../lib/utils'

interface ProjectStats {
  calls: number
  inquiries: number
  open_inquiries: number
  appointments: number
  appointments_done: number
  cost_estimates: number
  invoices: number
  employees: number
}
interface Project {
  id: string
  number: string | null
  title: string
  status: string
  customer_id: string | null
  customer_name: string | null
  start_date: string | null
  end_date: string | null
  planned_budget: number | null
  actual_budget: number
  open_amount: number
  progress: number
  stats: ProjectStats
}
interface CustomerOption { id: string; full_name: string | null }

const STATUS_META: Record<string, { label: string; cls: string }> = {
  planning: { label: 'In Planung', cls: 'bg-warning-bg text-warning' },
  active: { label: 'In Bearbeitung', cls: 'bg-success-bg text-success' },
  completed: { label: 'Abgeschlossen', cls: 'bg-info-bg text-info' },
  archived: { label: 'Archiviert', cls: 'bg-alt text-muted' },
}

const money = (n: number | null) =>
  '€' + (n ?? 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const fmtDate = (d: string | null) =>
  d ? new Date(d).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'Europe/Berlin' }) : '—'

export function ProjectsPage() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('all')
  const [customer, setCustomer] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiFetch<Project[]>('/api/projects'),
  })
  const { data: customerData } = useQuery({
    queryKey: ['customers-options'],
    queryFn: () => apiFetch<{ customers: CustomerOption[] }>('/api/customers?limit=500'),
  })
  const customers = customerData?.customers ?? []

  const overlaps = (p: Project) => {
    if (from && p.end_date && p.end_date < from) return false
    if (to && p.start_date && p.start_date > to) return false
    return true
  }
  const filtered = projects.filter(
    (p) =>
      (!search ||
        p.title.toLowerCase().includes(search.toLowerCase()) ||
        (p.customer_name ?? '').toLowerCase().includes(search.toLowerCase())) &&
      (status === 'all' || p.status === status) &&
      (!customer || p.customer_id === customer) &&
      overlaps(p),
  )

  const activeProjects = projects.filter((p) => p.status === 'active' || p.status === 'planning')
  const totalBudget = activeProjects.reduce((s, p) => s + (p.planned_budget ?? 0), 0)
  const openItems = projects.reduce((s, p) => s + (p.open_amount ?? 0), 0)

  return (
    <div className="p-8">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <FolderOpen size={26} className="text-green-primary" />
          <div>
            <h1 className="text-2xl font-bold text-text">Projekte</h1>
            <p className="mt-0.5 text-sm text-muted">{projects.length} Projekte</p>
          </div>
        </div>
        <button
          onClick={() => navigate('/projects/new')}
          className="inline-flex items-center gap-2 rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110"
        >
          + Neues Projekt
        </button>
      </div>

      {/* Filter */}
      <div className="mb-4 rounded-xl border border-border bg-surface p-4">
        <div className="grid gap-3 md:grid-cols-4">
          <div>
            <div className="mb-1 text-xs font-medium text-muted">Suche</div>
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
              <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Titel oder Kunde…" className="w-full rounded-md border border-border bg-alt py-2 pl-9 pr-3 text-sm text-text outline-none focus:border-green-primary" />
            </div>
          </div>
          <div>
            <div className="mb-1 text-xs font-medium text-muted">Status</div>
            <select value={status} onChange={(e) => setStatus(e.target.value)} className={selectCls}>
              <option value="all">Alle</option>
              <option value="planning">In Planung</option>
              <option value="active">In Bearbeitung</option>
              <option value="completed">Abgeschlossen</option>
              <option value="archived">Archiviert</option>
            </select>
          </div>
          <div>
            <div className="mb-1 text-xs font-medium text-muted">Kontakt</div>
            <select value={customer} onChange={(e) => setCustomer(e.target.value)} className={selectCls}>
              <option value="">Alle Kontakte</option>
              {customers.map((c) => <option key={c.id} value={c.id}>{c.full_name ?? 'Unbenannt'}</option>)}
            </select>
          </div>
          <div>
            <div className="mb-1 text-xs font-medium text-muted">Zeitraum</div>
            <div className="flex items-center gap-2">
              <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className={cn(selectCls, 'px-2')} />
              <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className={cn(selectCls, 'px-2')} />
            </div>
          </div>
        </div>
      </div>

      {/* Summary */}
      <div className="mb-5 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <SummaryCard label="Aktive Projekte" value={String(activeProjects.length)} cls="text-success" />
        <SummaryCard label="Gesamtbudget" value={money(totalBudget)} cls="text-info" />
        <SummaryCard label="Offene Posten" value={money(openItems)} cls="text-warning" />
      </div>

      {/* Cards */}
      <div className="space-y-3">
        {filtered.map((p) => {
          const sm = STATUS_META[p.status] ?? STATUS_META.planning
          return (
            <button
              key={p.id}
              onClick={() => navigate(`/projects/${p.id}`)}
              className="block w-full rounded-xl border border-border bg-surface p-5 text-left transition hover:border-green-primary/50 hover:shadow-e1"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="truncate text-base font-bold text-text">{p.title}</h3>
                    <span className={cn('shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium', sm.cls)}>{sm.label}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                    {p.customer_id ? (
                      <span
                        onClick={(ev) => { ev.stopPropagation(); navigate(`/customers/${p.customer_id}`) }}
                        className="text-green-deep hover:underline"
                      >
                        {p.customer_name ?? '—'}
                      </span>
                    ) : <span className="text-muted">Kein Kunde</span>}
                    <span className="text-muted">{p.number}</span>
                    <span className="text-muted">{fmtDate(p.start_date)} – {fmtDate(p.end_date)}</span>
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  <div className="text-xs text-muted">Budget</div>
                  <div className="text-sm font-semibold text-text">
                    Geplant {money(p.planned_budget)}
                  </div>
                  <div className={cn('text-xs', (p.planned_budget && p.actual_budget > p.planned_budget) ? 'text-warning' : 'text-muted')}>
                    Ist {money(p.actual_budget)}
                  </div>
                </div>
              </div>

              {/* Progress */}
              <div className="mt-3">
                <div className="mb-1 flex items-center justify-between text-xs text-muted">
                  <span>Fortschritt ({p.stats.appointments_done}/{p.stats.appointments} Termine)</span>
                  <span>{p.progress}%</span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-alt">
                  <div className="h-full rounded-full bg-green-primary" style={{ width: `${p.progress}%` }} />
                </div>
              </div>

              {/* Stats */}
              <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-muted">
                <Stat icon={<Phone size={14} />} n={p.stats.calls} />
                <Stat icon={<ClipboardList size={14} />} n={p.stats.inquiries} />
                <Stat icon={<Calendar size={14} />} n={p.stats.appointments} />
                <Stat icon={<FileText size={14} />} n={p.stats.cost_estimates} />
                <Stat icon={<Receipt size={14} />} n={p.stats.invoices} />
                <Stat icon={<Users size={14} />} n={p.stats.employees} />
              </div>
            </button>
          )
        })}
        {!filtered.length && (
          <div className="rounded-xl border border-border bg-surface px-4 py-12 text-center text-muted">Keine Projekte.</div>
        )}
      </div>
    </div>
  )
}

const selectCls = 'w-full rounded-md border border-border bg-alt px-3 py-2 text-sm text-text outline-none focus:border-green-primary'

function SummaryCard({ label, value, cls }: { label: string; value: string; cls: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-5">
      <div className="text-xs text-muted">{label}</div>
      <div className={cn('mt-1 text-2xl font-bold', cls)}>{value}</div>
    </div>
  )
}

function Stat({ icon, n }: { icon: React.ReactNode; n: number }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {icon}
      <span className="font-medium text-body">{n}</span>
    </span>
  )
}
