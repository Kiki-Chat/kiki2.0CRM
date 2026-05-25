import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  Banknote,
  Calendar,
  CheckCircle2,
  ClipboardList,
  FileText,
  FolderOpen,
  LayoutDashboard,
  Loader2,
  MoreHorizontal,
  Pencil,
  Phone,
  Receipt,
  StickyNote,
  Users,
  type LucideIcon,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { apiFetch } from '../lib/api'
import { cn } from '../lib/utils'
import {
  AppointmentsTab,
  CallsTab,
  CostEstimatesTab,
  DocumentsTab,
  InquiriesTab,
  InvoicesTab,
  NotesTab,
  TeamTab,
} from './projectTabs'

const STALE = 5 * 60 * 1000

interface ProjectStats {
  calls: number
  inquiries: number
  open_inquiries: number
  appointments: number
  appointments_done: number
  cost_estimates: number
  invoices: number
  documents: number
  employees: number
  next_appointment: string | null
  open_invoices_amount: number
}
interface Employee { id: string; name: string | null; role: string | null; color: string | null }
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
  internal_notes: string | null
  stats: ProjectStats
  employees: Employee[]
}

const STATUS_META: Record<string, { label: string; cls: string }> = {
  planning: { label: 'In Planung', cls: 'bg-warning-bg text-warning' },
  active: { label: 'In Bearbeitung', cls: 'bg-success-bg text-success' },
  completed: { label: 'Abgeschlossen', cls: 'bg-info-bg text-info' },
  archived: { label: 'Archiviert', cls: 'bg-alt text-muted' },
}

const TABS: { key: string; label: string; icon: LucideIcon }[] = [
  { key: 'overview', label: 'Übersicht', icon: LayoutDashboard },
  { key: 'calls', label: 'Anrufe', icon: Phone },
  { key: 'inquiries', label: 'Anfragen', icon: ClipboardList },
  { key: 'appointments', label: 'Termine', icon: Calendar },
  { key: 'cost_estimates', label: 'Kostenvoranschläge', icon: FileText },
  { key: 'invoices', label: 'Rechnungen', icon: Receipt },
  { key: 'team', label: 'Team', icon: Users },
  { key: 'documents', label: 'Dokumente', icon: FolderOpen },
  { key: 'notes', label: 'Notizen', icon: StickyNote },
]

const money = (n: number | null) =>
  '€' + (n ?? 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const fmtDate = (d: string | null) =>
  d ? new Date(d).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' }) : '—'
const fmtDateTime = (d: string | null) =>
  d ? new Date(d).toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'

export function ProjectWorkspacePage() {
  const { id } = useParams()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [tab, setTab] = useState(params.get('tab') || 'overview')

  // Header data — loaded ONCE; stays cached across tab switches.
  const { data: project, isLoading } = useQuery({
    queryKey: ['project', id],
    queryFn: () => apiFetch<Project>(`/api/projects/${id}`),
    staleTime: STALE,
  })

  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      apiFetch(`/api/projects/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['project', id] })
      qc.invalidateQueries({ queryKey: ['projects'] })
    },
  })
  const del = useMutation({
    mutationFn: () => apiFetch(`/api/projects/${id}`, { method: 'DELETE' }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['projects'] }); navigate('/projects') },
  })

  if (isLoading || !project) {
    return <div className="flex h-full items-center justify-center text-muted"><Loader2 className="animate-spin" /></div>
  }

  return (
    <div className="flex h-full min-h-0">
      {/* Persistent left sidebar */}
      <aside className="flex w-52 shrink-0 flex-col border-r border-border bg-surface">
        <div className="border-b border-border p-4">
          <button onClick={() => navigate('/projects')} className="mb-2 inline-flex items-center gap-1 text-xs text-muted hover:text-text"><ArrowLeft size={13} /> Projekte</button>
          <div className="text-sm font-bold leading-snug text-text">{project.title}</div>
          <span className={cn('mt-2 inline-block rounded-full px-2 py-0.5 text-xs font-medium', (STATUS_META[project.status] ?? STATUS_META.planning).cls)}>
            {(STATUS_META[project.status] ?? STATUS_META.planning).label}
          </span>
        </div>
        <nav className="flex-1 overflow-y-auto p-2">
          {TABS.map((t) => {
            const Icon = t.icon
            const active = tab === t.key
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={cn(
                  'mb-0.5 flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm transition',
                  active ? 'bg-green-tint-50 font-semibold text-green-deep' : 'text-body hover:bg-alt',
                )}
              >
                <Icon size={16} /> {t.label}
              </button>
            )
          })}
        </nav>
      </aside>

      {/* Main */}
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar project={project} onPatch={(b) => patch.mutate(b)} onDelete={() => del.mutate()} />
        <div className="min-h-0 flex-1 overflow-y-auto p-6">
          {tab === 'overview' && <OverviewTab project={project} />}
          {tab === 'calls' && <CallsTab project={project} />}
          {tab === 'inquiries' && <InquiriesTab project={project} />}
          {tab === 'appointments' && <AppointmentsTab project={project} />}
          {tab === 'cost_estimates' && <CostEstimatesTab project={project} />}
          {tab === 'invoices' && <InvoicesTab project={project} />}
          {tab === 'team' && <TeamTab project={project} />}
          {tab === 'documents' && <DocumentsTab project={project} />}
          {tab === 'notes' && <NotesTab project={project} />}
        </div>
      </div>
    </div>
  )
}

function TopBar({ project, onPatch, onDelete }: { project: Project; onPatch: (b: Record<string, unknown>) => void; onDelete: () => void }) {
  const navigate = useNavigate()
  const [titleDraft, setTitleDraft] = useState(project.title)
  const [menu, setMenu] = useState(false)
  const savedTitle = useRef(project.title)
  useEffect(() => { setTitleDraft(project.title); savedTitle.current = project.title }, [project.title])

  const commitTitle = () => {
    const t = titleDraft.trim()
    if (t && t !== savedTitle.current) { savedTitle.current = t; onPatch({ title: t }) }
    else setTitleDraft(savedTitle.current)
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-surface px-6 py-3">
      <div className="min-w-0">
        <input
          value={titleDraft}
          onChange={(e) => setTitleDraft(e.target.value)}
          onBlur={commitTitle}
          onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
          className="w-full max-w-md truncate rounded bg-transparent px-1 text-xl font-bold text-text outline-none hover:bg-alt focus:bg-alt"
        />
        <div className="mt-0.5 flex flex-wrap items-center gap-x-3 px-1 text-sm text-muted">
          {project.customer_id && (
            <button onClick={() => navigate(`/customers/${project.customer_id}`)} className="text-green-deep hover:underline">{project.customer_name ?? '—'}</button>
          )}
          <span>{project.number}</span>
          <span>{fmtDate(project.start_date)} – {fmtDate(project.end_date)}</span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <select
          value={project.status}
          onChange={(e) => onPatch({ status: e.target.value })}
          className={cn('cursor-pointer rounded-md border border-border bg-alt px-3 py-1.5 text-sm font-medium outline-none', (STATUS_META[project.status] ?? STATUS_META.planning).cls)}
        >
          <option value="planning">In Planung</option>
          <option value="active">In Bearbeitung</option>
          <option value="completed">Abgeschlossen</option>
          <option value="archived">Archiviert</option>
        </select>
        <button title="Bearbeiten" onClick={() => navigate(`/projects/${project.id}/edit`)} className="rounded-md border border-border p-2 text-body hover:bg-alt"><Pencil size={15} /></button>
        <div className="relative">
          <button title="Mehr" onClick={() => setMenu((m) => !m)} className="rounded-md border border-border p-2 text-body hover:bg-alt"><MoreHorizontal size={15} /></button>
          {menu && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setMenu(false)} />
              <div className="absolute right-0 z-20 mt-1 w-44 rounded-md border border-border bg-surface py-1 shadow-e2">
                <button onClick={() => { setMenu(false); onPatch({ status: 'archived' }) }} className="block w-full px-3 py-2 text-left text-sm text-body hover:bg-alt">Archivieren</button>
                <button onClick={() => { if (confirm('Projekt löschen?')) { setMenu(false); onDelete() } }} className="block w-full px-3 py-2 text-left text-sm text-error hover:bg-alt">Projekt löschen</button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function OverviewTab({ project }: { project: Project }) {
  const { data: activity = [] } = useQuery({
    queryKey: ['project-activity', project.id],
    queryFn: () => apiFetch<ActivityItem[]>(`/api/projects/${project.id}/activity?limit=10`),
    staleTime: STALE,
  })
  const s = project.stats
  const planned = project.planned_budget ?? 0
  const ist = project.actual_budget ?? 0
  const pct = planned ? Math.round((ist / planned) * 100) : 0
  const over = planned > 0 && ist > planned

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Anrufe" value={String(s.calls)} />
        <StatCard label="Offene Anfragen" value={String(s.open_inquiries)} />
        <StatCard label="Nächster Termin" value={s.next_appointment ? fmtDate(s.next_appointment) : '–'} />
        <StatCard label="Offene Rechnungen" value={money(s.open_invoices_amount)} cls={s.open_invoices_amount > 0 ? 'text-warning' : 'text-text'} />
      </div>

      {/* Budget */}
      {planned > 0 && (
        <div className="rounded-xl border border-border bg-surface p-5">
          <div className="mb-2 flex items-center justify-between text-sm">
            <span className="font-bold text-text">Budget</span>
            <span className={cn('font-medium', over ? 'text-warning' : 'text-muted')}>{pct}%</span>
          </div>
          <div className="mb-2 flex items-center justify-between text-sm">
            <span className="text-muted">Geplant: <span className="font-semibold text-text">{money(planned)}</span></span>
            <span className="text-muted">Ist: <span className={cn('font-semibold', over ? 'text-warning' : 'text-text')}>{money(ist)}</span></span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-alt">
            <div className={cn('h-full rounded-full', over ? 'bg-warning' : 'bg-green-primary')} style={{ width: `${Math.min(pct, 100)}%` }} />
          </div>
          {over && <p className="mt-2 text-xs text-warning">Das Ist-Budget überschreitet das geplante Budget.</p>}
        </div>
      )}

      {/* Activity feed */}
      <div className="rounded-xl border border-border bg-surface p-5">
        <h3 className="mb-3 text-sm font-bold text-text">Letzte Aktivitäten</h3>
        {activity.length ? (
          <div className="space-y-3">
            {activity.map((a, i) => {
              const Icon = ACTIVITY_ICON[a.type] ?? LayoutDashboard
              return (
                <div key={i} className="flex items-start gap-3">
                  <div className="mt-0.5 rounded-md bg-alt p-1.5 text-muted"><Icon size={14} /></div>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm text-text">{a.label}{a.amount != null ? ` · ${money(a.amount)}` : ''}</div>
                    <div className="text-xs text-muted">{fmtDateTime(a.date)}</div>
                  </div>
                </div>
              )
            })}
          </div>
        ) : (
          <p className="py-6 text-center text-sm text-muted">Noch keine Aktivitäten.</p>
        )}
      </div>
    </div>
  )
}

interface ActivityItem { type: string; date: string; label: string; amount?: number | null }
const ACTIVITY_ICON: Record<string, LucideIcon> = {
  call: Phone,
  inquiry: ClipboardList,
  appointment: Calendar,
  appointment_done: CheckCircle2,
  cost_estimate: FileText,
  invoice: Receipt,
  payment: Banknote,
}

function StatCard({ label, value, cls }: { label: string; value: string; cls?: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="text-xs text-muted">{label}</div>
      <div className={cn('mt-1 text-xl font-bold', cls ?? 'text-text')}>{value}</div>
    </div>
  )
}

