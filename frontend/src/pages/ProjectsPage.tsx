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

export function ProjectsPage() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('all')
  const [customer, setCustomer] = useState('')

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiFetch<Project[]>('/api/projects'),
  })
  const { data: customerData } = useQuery({
    queryKey: ['customers-options'],
    queryFn: () => apiFetch<{ customers: CustomerOption[] }>('/api/customers?limit=500'),
  })
  const customers = customerData?.customers ?? []

  const filtered = projects.filter(
    (p) =>
      (!search ||
        p.title.toLowerCase().includes(search.toLowerCase()) ||
        (p.customer_name ?? '').toLowerCase().includes(search.toLowerCase())) &&
      (status === 'all' || p.status === status) &&
      (!customer || p.customer_id === customer),
  )

  const activeProjects = projects.filter((p) => p.status === 'active' || p.status === 'planning')

  return (
    <div className="p-8">
      <div className="mb-6 flex items-center gap-3">
        <FolderOpen size={26} className="text-green-primary" />
        <div>
          <h1 className="text-2xl font-bold text-text">Fälle</h1>
          <p className="mt-0.5 text-sm text-muted">{projects.length} Fälle · {activeProjects.length} offen — Tickets, die Kiki aus den Anrufen gebündelt hat</p>
        </div>
      </div>

      {/* Filter */}
      <div className="mb-4 rounded-xl border border-border bg-surface p-4">
        <div className="grid gap-3 md:grid-cols-3">
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
        </div>
      </div>

      {/* Cards — a lean Fall is a ticket: customer + the call(s) and the five things
          (Anfragen/Anrufe · Termine · KVA · Rechnungen · Mitarbeiter). No budget/dates. */}
      <div className="space-y-3">
        {filtered.map((p) => {
          const sm = STATUS_META[p.status] ?? STATUS_META.planning
          return (
            <button
              key={p.id}
              onClick={() => navigate(`/fall/${p.id}`)}
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
                    {p.number && <span className="font-mono text-xs text-muted">{p.number}</span>}
                  </div>
                </div>
              </div>

              {/* The five linked things */}
              <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-muted">
                <Stat icon={<Phone size={14} />} n={p.stats.calls} title="Anrufe" />
                <Stat icon={<ClipboardList size={14} />} n={p.stats.inquiries} title="Anfragen" />
                <Stat icon={<Calendar size={14} />} n={p.stats.appointments} title="Termine" />
                <Stat icon={<FileText size={14} />} n={p.stats.cost_estimates} title="KVA" />
                <Stat icon={<Receipt size={14} />} n={p.stats.invoices} title="Rechnungen" />
                <Stat icon={<Users size={14} />} n={p.stats.employees} title="Mitarbeiter" />
              </div>
            </button>
          )
        })}
        {!filtered.length && (
          <div className="rounded-xl border border-border bg-surface px-4 py-12 text-center text-muted">Keine Fälle.</div>
        )}
      </div>
    </div>
  )
}

const selectCls = 'w-full rounded-md border border-border bg-alt px-3 py-2 text-sm text-text outline-none focus:border-green-primary'

function Stat({ icon, n, title }: { icon: React.ReactNode; n: number; title: string }) {
  return (
    <span className="inline-flex items-center gap-1.5" title={title}>
      {icon}
      <span className="font-medium text-body">{n}</span>
    </span>
  )
}
