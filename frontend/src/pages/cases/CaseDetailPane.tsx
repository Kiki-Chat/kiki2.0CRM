// Right pane of the Cases split-view — the dirC "Karteikarte". Header (customer +
// status switch) · a FOCUSED "Was ist zu tun?" panel (the compact version of the
// Call-Log Aktionen — the detailed version lives in the call drawer) · quick-action
// tiles · record TABLES (Anfragen / Termine / Kostenvoranschläge / Rechnungen /
// Techniker), each always shown, grouped by date, with empty states + add actions.
// Clicking an Anfrage opens that call's transcript drawer.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CalendarCheck,
  CalendarClock,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock,
  Copy,
  FileText,
  FolderPlus,
  HardHat,
  Inbox,
  MapPin,
  Phone,
  Plus,
  Receipt,
  Send,
  Sparkles,
  Users,
  Wrench,
  X,
  type LucideIcon,
} from 'lucide-react'
import { Fragment, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { CustomerFormModal, type CustomerFormValues } from '../../components/CustomerFormModal'
import { MoveMenu, type MoveTarget } from '../../components/cases/grouping'
import { Tag } from '../../components/ui/Tag'
import { apiFetch } from '../../lib/api'
import { fmtDateTime } from '../../lib/datetime'
import { cn, initials } from '../../lib/utils'
import { dayDividerLabel, dayKeyOf } from '../calls/log/util'
import { CreateAppointmentModal } from '../calls/Modals'
import { buildDecisions, usePosteingangActions, type DecisionVM, type Employee as PEEmp, type RawAction } from '../posteingang/api'
import {
  CASE_STATUS,
  type CaseJob,
  type CaseListRow,
  type CaseUmbrella,
  type Employee,
  type ProjectRow,
  type UmbrellaInquiry,
} from './types'

const euro = (n: number | null) =>
  n != null ? `${n.toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €` : '—'

function fmtAddress(a: CustomerFormValues['address']): string {
  if (!a) return ''
  if (typeof a === 'string') return a
  if (a.raw) return a.raw
  return ''
}

const NOW = Date.now()
// Group rows under date dividers (Heute / Gestern / "Montag, 16. Juni"), newest first.
function groupByDay<T>(items: T[], getIso: (t: T) => string | null): { key: string; label: string; items: T[] }[] {
  const sorted = [...items].sort((a, b) => (Date.parse(getIso(b) || '') || 0) - (Date.parse(getIso(a) || '') || 0))
  const out: { key: string; label: string; items: T[] }[] = []
  for (const it of sorted) {
    const iso = getIso(it)
    const key = dayKeyOf(iso)
    const last = out[out.length - 1]
    if (last && last.key === key) last.items.push(it)
    else out.push({ key, label: dayDividerLabel(iso, NOW), items: [it] })
  }
  return out
}

const INQ_STATUS: Record<string, { label: string; variant: 'info' | 'warning' | 'success' | 'neutral' }> = {
  open: { label: 'Neu', variant: 'info' },
  in_progress: { label: 'In Arbeit', variant: 'warning' },
  completed: { label: 'Erledigt', variant: 'success' },
}
const APPT_STATUS: Record<string, { label: string; variant: 'info' | 'warning' | 'success' | 'neutral' }> = {
  pending: { label: 'Offen', variant: 'warning' },
  confirmed: { label: 'Bestätigt', variant: 'info' },
  completed: { label: 'Erledigt', variant: 'success' },
  cancelled: { label: 'Storniert', variant: 'neutral' },
  rejected: { label: 'Abgelehnt', variant: 'neutral' },
}
const JOB_STATUS: Record<string, { label: string; variant: 'info' | 'warning' | 'success' }> = {
  offen: { label: 'Offen', variant: 'warning' },
  'läuft': { label: 'Läuft', variant: 'info' },
  abgeschlossen: { label: 'Abgeschlossen', variant: 'success' },
}

// ─── Header status switch (Offen / In Arbeit / Fertig) ──────────────────────
const STATUS_ICON: Record<string, LucideIcon> = { planning: Clock, active: Wrench, completed: CheckCircle2 }
const STATUS_ON: Record<string, string> = {
  info: 'border-info bg-info-bg text-info',
  warning: 'border-warning bg-warning-bg text-warning',
  success: 'border-success bg-success-bg text-success',
}
function StatusSwitch({ status, onChange, disabled }: { status: string; onChange: (v: string) => void; disabled?: boolean }) {
  return (
    <div className="flex w-full gap-2.5">
      {CASE_STATUS.map((o) => {
        const on = o.value === status
        const Icon = STATUS_ICON[o.value]
        return (
          <button
            key={o.value}
            disabled={disabled}
            onClick={() => onChange(o.value)}
            className={cn(
              'flex flex-1 items-center justify-center gap-2 rounded-2xl border-2 px-3 py-3.5 text-[15px] font-extrabold transition disabled:opacity-60',
              on ? STATUS_ON[o.tone] : 'border-border bg-surface text-muted hover:bg-alt',
            )}
          >
            <Icon size={19} /> {o.label}
          </button>
        )
      })}
    </div>
  )
}

// ─── Focused action card (compact Aktion) ───────────────────────────────────
function FocusedActionCard({ d, urgent, onResolve, onDismiss }: {
  d: DecisionVM
  urgent: boolean
  onResolve: (d: DecisionVM, choice: 'primary' | 'secondary' | 'tertiary') => void
  onDismiss: (d: DecisionVM) => void
}) {
  const [busy, setBusy] = useState(false)
  const run = async (choice: 'primary' | 'secondary' | 'tertiary') => {
    setBusy(true)
    try { await onResolve(d, choice) } finally { setBusy(false) }
  }
  return (
    <div className={cn('rounded-2xl bg-surface p-4 ring-1 ring-inset', urgent ? 'ring-[1.5px] ring-warning' : 'ring-border')}>
      <div className="flex items-start gap-2.5">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Tag variant={d.typeVariant}>{d.typeLabel}</Tag>
            {urgent && <span className="text-[10.5px] font-extrabold uppercase tracking-wide text-error">Dringend</span>}
          </div>
          <div className="mt-1.5 text-[15.5px] font-bold text-text">{d.title}</div>
          <div className="mt-0.5 line-clamp-2 text-[13.5px] text-muted">{d.snippet}</div>
        </div>
        <button onClick={() => onDismiss(d)} title="Ausblenden" className="grid h-7 w-7 flex-shrink-0 place-items-center rounded-lg text-faint hover:bg-alt hover:text-error">
          <X size={15} />
        </button>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3">
        <button disabled={busy} onClick={() => run('primary')} className="inline-flex items-center gap-1.5 rounded-xl bg-green-primary px-3.5 py-2 text-sm font-bold text-white transition hover:brightness-105 disabled:opacity-50">
          <Check size={15} /> {d.primary}
        </button>
        {d.secondary && <button disabled={busy} onClick={() => run('secondary')} className="rounded-xl border border-border bg-surface px-3 py-2 text-sm font-bold text-body transition hover:bg-alt disabled:opacity-50">{d.secondary}</button>}
        {d.tertiary && <button disabled={busy} onClick={() => run('tertiary')} className="rounded-xl border border-border bg-surface px-3 py-2 text-sm font-bold text-body transition hover:bg-alt disabled:opacity-50">{d.tertiary}</button>}
      </div>
    </div>
  )
}

// ─── Card shell + grouped table ─────────────────────────────────────────────
function BigCard({ title, icon: Icon, accent, count, action, children }: {
  title: string
  icon: LucideIcon
  accent?: 'green' | 'ai'
  count?: number
  action?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="rounded-3xl bg-surface p-6 shadow-e1">
      <div className="mb-4 flex items-center gap-3">
        <span className={cn('grid h-10 w-10 flex-shrink-0 place-items-center rounded-xl', accent === 'ai' ? 'bg-ai-bg text-ai' : 'bg-green-tint-100 text-green-deep')}><Icon size={20} /></span>
        <h2 className="font-poster text-[19px] font-extrabold text-text">{title}</h2>
        {count != null && count > 0 && <span className="rounded-full bg-alt px-2 py-0.5 text-xs font-bold text-muted">{count}</span>}
        {action && <div className="ml-auto">{action}</div>}
      </div>
      {children}
    </div>
  )
}

function AddBtn({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button onClick={onClick} className="inline-flex items-center gap-1 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-xs font-bold text-body transition hover:bg-alt">
      <Plus size={13} /> {label}
    </button>
  )
}

function EmptyHint({ text }: { text: string }) {
  return <p className="rounded-xl border border-dashed border-border px-3 py-5 text-center text-sm text-muted">{text}</p>
}

function GroupedTable({ columns, children }: { columns: string[]; children: React.ReactNode }) {
  return (
    <div className="scroll overflow-x-auto rounded-xl border border-border">
      <table className="w-full min-w-[420px] border-collapse text-left text-sm">
        <thead className="bg-alt">
          <tr>{columns.map((c, i) => <th key={i} className="px-3 py-2 text-[11px] font-extrabold uppercase tracking-wide text-muted">{c}</th>)}</tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  )
}
function DayDivider({ label, span }: { label: string; span: number }) {
  return (
    <tr className="bg-bg">
      <td colSpan={span} className="border-y border-border-faint px-3 py-1.5 text-[11.5px] font-extrabold capitalize tracking-wide text-muted">{label}</td>
    </tr>
  )
}

function QuickTile({ label, icon: Icon, tone, onClick, disabled }: { label: string; icon: LucideIcon; tone: 'green' | 'ai' | 'steel'; onClick: () => void; disabled?: boolean }) {
  const cls = tone === 'green' ? 'border-green-tint-200 bg-green-tint-50 text-green-deep' : tone === 'ai' ? 'border-ai-bg bg-ai-bg text-ai' : 'border-border bg-surface text-body'
  return (
    <button onClick={onClick} disabled={disabled} className={cn('flex items-center gap-3 rounded-2xl border px-4 py-4 text-base font-extrabold transition hover:brightness-[.97] disabled:opacity-40', cls)}>
      <span className="grid h-10 w-10 place-items-center rounded-xl" style={{ background: 'color-mix(in srgb, currentColor 12%, transparent)' }}><Icon size={21} /></span>
      {label}
      <Plus size={18} className="ml-auto" />
    </button>
  )
}

export function CaseDetailPane({ caseId, employees, projects, allCases, pendingActions, onOpenCall, flash }: {
  caseId: string | null
  employees: Employee[]
  projects: ProjectRow[]
  allCases: CaseListRow[]
  pendingActions: RawAction[]
  onOpenCall: (callId: string) => void
  flash: (m: string) => void
}) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { resolve } = usePosteingangActions()
  const [apptOpen, setApptOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [empOpen, setEmpOpen] = useState(false)
  const [projOpen, setProjOpen] = useState(false)
  const [techForm, setTechForm] = useState(false)
  const [techAppt, setTechAppt] = useState('')
  const [techEmp, setTechEmp] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['caseDetail', caseId],
    queryFn: () => apiFetch<CaseUmbrella>(`/api/cases/${caseId}`),
    enabled: !!caseId,
  })
  const customerId = data?.case.customer?.id ?? null
  const { data: fullCustomer } = useQuery({
    queryKey: ['customerDetail', customerId],
    queryFn: () => apiFetch<CustomerFormValues>(`/api/customers/${customerId}`),
    enabled: !!customerId,
  })
  const { data: jobs = [] } = useQuery({
    queryKey: ['caseJobs', caseId],
    queryFn: () => apiFetch<CaseJob[]>(`/api/cases/${caseId}/jobs`),
    enabled: !!caseId,
  })

  const patchCase = useMutation({
    mutationFn: (body: Record<string, unknown>) => apiFetch(`/api/cases/${caseId}`, { method: 'PATCH', body: JSON.stringify(body) }),
    onMutate: (body) =>
      qc.setQueryData<CaseUmbrella>(['caseDetail', caseId], (old) =>
        old ? { ...old, case: { ...old.case, ...('status' in body ? { status: body.status as string } : {}), ...('project_id' in body ? { project_id: (body.project_id || null) as string | null } : {}) } } : old),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['cases'] }),
  })
  const assignEmp = useMutation({
    mutationFn: (emp: Employee) => apiFetch(`/api/cases/${caseId}/employees`, { method: 'POST', body: JSON.stringify({ employee_id: emp.id }) }),
    onSettled: () => qc.invalidateQueries({ queryKey: ['caseDetail', caseId] }),
  })
  const removeEmp = useMutation({
    mutationFn: (employeeId: string) => apiFetch(`/api/cases/${caseId}/employees/${employeeId}`, { method: 'DELETE' }),
    onSettled: () => qc.invalidateQueries({ queryKey: ['caseDetail', caseId] }),
  })
  const dismissAction = useMutation({
    mutationFn: (d: DecisionVM) => apiFetch('/api/actions/state', { method: 'POST', body: JSON.stringify({ action_key: d.actionKey, status: 'dismissed' }) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['pe'] }); flash('Aktion entfernt') },
  })
  const dispatchTech = useMutation({
    mutationFn: () => apiFetch(`/api/appointments/${techAppt}/dispatch-technician`, { method: 'POST', body: JSON.stringify({ employee_id: techEmp }) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['caseJobs', caseId] })
      setTechForm(false); setTechAppt(''); setTechEmp('')
      flash('Techniker beauftragt – Link gesendet ✓')
    },
    onError: () => flash('Beauftragung fehlgeschlagen.'),
  })

  if (!caseId) return <div className="grid flex-1 place-items-center bg-bg text-[17px] text-muted">Tippen Sie links auf einen Fall.</div>
  if (isLoading || !data) return <div className="grid flex-1 place-items-center bg-bg text-muted">Lädt…</div>

  const cs = data.case
  const firstInq = data.inquiries[0]?.id
  const assignedIds = new Set(data.employees.map((e) => e.id))
  const freeEmployees = employees.filter((e) => !assignedIds.has(e.id) && e.is_active !== false)
  const technicians = employees.filter((e) => e.is_technician && e.is_active !== false)
  const currentProject = projects.find((p) => p.id === cs.project_id) ?? null
  const customerProjects = projects.filter((p) => !customerId || p.customer_id === customerId)
  const moveTargets: MoveTarget[] = allCases.filter((c) => customerId && c.customer_id === customerId).map((c) => ({ id: c.id, label: c.title, number: c.number }))
  const address = fmtAddress(fullCustomer?.address)

  const inqIds = new Set(data.inquiries.map((i) => i.id))
  const caseActions = pendingActions.filter((a) => a.inquiry_id && inqIds.has(a.inquiry_id))
  const urgentKeys = new Set(caseActions.filter((a) => a.priority === 'high').map((a) => a.action_key))
  const decisions = buildDecisions(caseActions, employees as PEEmp[], new Map())

  const onResolve = async (d: DecisionVM, choice: 'primary' | 'secondary' | 'tertiary') => {
    await resolve(d, choice)
    qc.invalidateQueries({ queryKey: ['caseDetail', caseId] })
  }

  const goKva = () => navigate(`/cost-estimates/new?customer_id=${customerId ?? ''}&case_id=${cs.id}${firstInq ? `&inquiry_id=${firstInq}` : ''}`)
  const goInvoice = () => navigate(`/invoices/new?customer_id=${customerId ?? ''}&case_id=${cs.id}`)
  const goNewProject = () => navigate(`/projects/new?customer_id=${customerId ?? ''}&case_id=${cs.id}&case_number=${encodeURIComponent(cs.number ?? '')}`)

  const apptCall = {
    customer_id: customerId,
    summary_title: cs.label ?? 'Fall',
    summary: '',
    customers: cs.customer ? { full_name: cs.customer.full_name, phone: cs.customer.phone } : null,
    data_collection: {},
  } as unknown as Parameters<typeof CreateAppointmentModal>[0]['call']

  const openInquiry = (i: UmbrellaInquiry) => {
    if (i.call_id) onOpenCall(i.call_id)
    else flash('Für diese Anfrage ist kein Anruf hinterlegt.')
  }
  const copyLink = (url: string) => { navigator.clipboard?.writeText(url); flash('Link kopiert') }

  const rowCls = 'cursor-pointer border-t border-border-faint transition hover:bg-alt'

  return (
    <div className="scroll flex-1 overflow-y-auto bg-bg">
      <div key={cs.id} className="case-fade-up mx-auto flex max-w-[760px] flex-col gap-[18px] px-7 py-8">
        {/* HEADER CARD */}
        <div className="rounded-3xl bg-surface p-6 shadow-e1">
          {cs.emergency && (
            <span className="mb-3 inline-flex items-center gap-1.5 rounded-full bg-error-bg px-2.5 py-1 text-[12px] font-extrabold uppercase tracking-wide text-error">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-error" /> Notdienst
            </span>
          )}
          <div className="flex items-center gap-4">
            <span className="grid h-[58px] w-[58px] flex-shrink-0 place-items-center rounded-full bg-alt text-xl font-extrabold text-body ring-1 ring-inset ring-border">{initials(cs.customer?.full_name ?? '?')}</span>
            <div className="min-w-0 flex-1">
              <h1 className="font-poster text-[26px] font-extrabold leading-tight text-text">{cs.customer?.full_name ?? 'Kunde'}</h1>
              <div className="mt-0.5 text-[16px] text-body">{cs.label ?? 'Fall'} · <span className="font-mono text-sm text-muted">{cs.number ?? '—'}</span></div>
            </div>
          </div>
          <div className="mt-4 flex flex-col gap-2.5">
            {cs.customer?.phone && <a href={`tel:${cs.customer.phone.replace(/\s/g, '')}`} className="inline-flex items-center gap-2.5 text-[16px] font-bold text-green-deep"><Phone size={18} /> {cs.customer.phone}</a>}
            {address && <div className="inline-flex items-center gap-2.5 text-[15px] text-muted"><MapPin size={17} /> {address}</div>}
            {customerId && <button onClick={() => setEditOpen(true)} className="self-start text-[13px] font-bold text-muted hover:text-green-deep">Kundendaten bearbeiten</button>}
          </div>

          {/* Project link */}
          <div className="relative mt-4">
            {currentProject ? (
              <div className="flex flex-wrap items-center gap-2">
                <button onClick={() => navigate(`/projects/${currentProject.id}`)} className="inline-flex items-center gap-1.5 rounded-lg border border-ai-bg bg-ai-bg px-2.5 py-1 text-xs font-bold text-ai hover:brightness-95"><FolderPlus size={13} /> Projekt {currentProject.number ?? ''} · {currentProject.title}</button>
                <button onClick={() => setProjOpen((o) => !o)} className="text-xs font-bold text-muted hover:text-body">ändern</button>
              </div>
            ) : (
              <button onClick={() => setProjOpen((o) => !o)} className="inline-flex items-center gap-1.5 text-xs font-bold text-green-deep hover:underline"><FolderPlus size={14} /> Zu Projekt hinzufügen</button>
            )}
            {projOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setProjOpen(false)} />
                <div className="absolute left-0 z-50 mt-1 max-h-64 w-64 overflow-auto rounded-xl border border-border bg-surface p-1.5 shadow-e3">
                  {currentProject && <button onClick={() => { patchCase.mutate({ project_id: '' }); setProjOpen(false) }} className="block w-full rounded-lg px-2.5 py-1.5 text-left text-sm text-body hover:bg-alt">Aus Projekt lösen</button>}
                  {customerProjects.map((p) => <button key={p.id} onClick={() => { patchCase.mutate({ project_id: p.id }); setProjOpen(false) }} className="block w-full truncate rounded-lg px-2.5 py-1.5 text-left text-sm text-body hover:bg-alt">→ {p.title}</button>)}
                  <button onClick={goNewProject} className="mt-0.5 flex w-full items-center gap-1.5 rounded-lg border-t border-border px-2.5 py-1.5 text-left text-sm font-bold text-green-deep hover:bg-alt"><FolderPlus size={14} /> Neues Projekt erstellen</button>
                </div>
              </>
            )}
          </div>

          <div className="mt-[18px] border-t border-border pt-[18px]">
            <div className="mb-2.5 text-[13px] font-bold text-muted">Wie ist der Stand?</div>
            <StatusSwitch status={cs.status} onChange={(v) => patchCase.mutate({ status: v })} disabled={patchCase.isPending} />
          </div>
        </div>

        {/* WAS IST ZU TUN? */}
        <div className={cn('rounded-3xl bg-surface p-6', decisions.length ? 'ring-2 ring-inset ring-warning' : 'shadow-e1')}>
          <div className={cn('flex items-center gap-3', decisions.length > 0 && 'mb-4')}>
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-warning-bg text-warning"><Sparkles size={21} /></span>
            <div>
              <h2 className="font-poster text-[20px] font-extrabold text-text">Was ist zu tun?</h2>
              <div className="text-[13.5px] text-muted">Kiki hat das für Sie vorbereitet</div>
            </div>
          </div>
          {decisions.length ? (
            <div className="flex flex-col gap-3">
              {decisions.map((d) => <FocusedActionCard key={d.actionKey} d={d} urgent={urgentKeys.has(d.actionKey)} onResolve={onResolve} onDismiss={(x) => dismissAction.mutate(x)} />)}
            </div>
          ) : (
            <div className="py-2 text-center">
              <span className="mx-auto grid h-16 w-16 place-items-center rounded-full bg-green-tint-100 text-green-deep"><CheckCircle2 size={30} /></span>
              <div className="mt-3 text-[17px] font-extrabold text-text">Keine offenen Aktionen</div>
              <div className="mt-1 text-[13px] text-muted">Kiki hat alles im Griff.</div>
            </div>
          )}
        </div>

        {/* QUICK ACTIONS */}
        <div className="grid grid-cols-2 gap-3">
          <QuickTile label="Termin" icon={CalendarCheck} tone="green" onClick={() => setApptOpen(true)} />
          <QuickTile label="Kostenvoranschlag" icon={Receipt} tone="ai" onClick={goKva} disabled={!customerId} />
          <QuickTile label="Rechnung" icon={FileText} tone="ai" onClick={goInvoice} disabled={!customerId} />
          <div className="relative">
            <QuickTile label="Mitarbeiter" icon={Users} tone="steel" onClick={() => setEmpOpen((o) => !o)} />
            {empOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setEmpOpen(false)} />
                <div className="absolute right-0 z-50 mt-1 max-h-64 w-60 overflow-auto rounded-xl border border-border bg-surface p-1.5 shadow-e3">
                  {freeEmployees.length ? freeEmployees.map((e) => <button key={e.id} onClick={() => { assignEmp.mutate(e); setEmpOpen(false) }} className="block w-full truncate rounded-lg px-2.5 py-1.5 text-left text-sm text-body hover:bg-alt">{e.display_name ?? 'Mitarbeiter'}{e.is_technician ? ' · Techniker' : ''}</button>) : <p className="px-2.5 py-2 text-xs text-muted">Alle zugewiesen.</p>}
                </div>
              </>
            )}
          </div>
        </div>

        {/* ANFRAGEN */}
        <BigCard title="Anfragen" icon={Inbox} count={data.inquiries.length}>
          {data.inquiries.length ? (
            <GroupedTable columns={['Status', 'Betreff', 'Nummer', '']}>
              {groupByDay(data.inquiries, (i) => i.created_at ?? null).map((g) => (
                <Fragment key={g.key}>
                  <DayDivider label={g.label} span={4} />
                  {g.items.map((i) => {
                    const st = INQ_STATUS[i.status] ?? { label: i.status, variant: 'neutral' as const }
                    return (
                      <tr key={i.id} className={cn(rowCls, 'group relative')}>
                        <td className="px-3 py-2.5" onClick={() => openInquiry(i)}><Tag variant={st.variant}>{st.label}</Tag></td>
                        <td className="px-3 py-2.5 font-semibold text-text" onClick={() => openInquiry(i)}><span className="line-clamp-1">{i.subject || i.title || 'Anfrage'}</span></td>
                        <td className="px-3 py-2.5 font-mono text-xs text-muted" onClick={() => openInquiry(i)}>
                          <span className="inline-flex items-center gap-1.5">{i.call_id && <Phone size={12} className="text-green-deep" />}{i.number}</span>
                        </td>
                        <td className="relative w-10 px-3 py-2.5"><MoveMenu inquiryId={i.id} currentCaseId={cs.id} cases={moveTargets} onMoved={() => { qc.invalidateQueries({ queryKey: ['caseDetail', caseId] }); qc.invalidateQueries({ queryKey: ['cases'] }) }} /></td>
                      </tr>
                    )
                  })}
                </Fragment>
              ))}
            </GroupedTable>
          ) : <EmptyHint text="Noch keine Anfragen in diesem Fall." />}
        </BigCard>

        {/* TERMINE */}
        <BigCard title="Termine" icon={CalendarClock} count={data.appointments.length} action={<AddBtn label="Termin" onClick={() => setApptOpen(true)} />}>
          {data.appointments.length ? (
            <GroupedTable columns={['Termin', 'Datum', 'Status', '']}>
              {groupByDay(data.appointments, (a) => a.scheduled_at ?? a.created_at ?? null).map((g) => (
                <Fragment key={g.key}>
                  <DayDivider label={g.label} span={4} />
                  {g.items.map((a) => {
                    const st = APPT_STATUS[a.status] ?? { label: a.status, variant: 'neutral' as const }
                    return (
                      <tr key={a.id} className={rowCls} onClick={() => navigate(`/calendar?appointment=${a.id}${a.scheduled_at ? `&date=${a.scheduled_at.slice(0, 10)}` : ''}`)}>
                        <td className="px-3 py-2.5 font-semibold text-text"><span className="line-clamp-1">{a.title ?? 'Termin'}</span></td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-xs text-muted">{a.scheduled_at ? fmtDateTime(a.scheduled_at) : 'offen'}</td>
                        <td className="px-3 py-2.5"><Tag variant={st.variant}>{st.label}</Tag></td>
                        <td className="px-3 py-2.5 text-right"><ChevronRight size={15} className="inline text-faint" /></td>
                      </tr>
                    )
                  })}
                </Fragment>
              ))}
            </GroupedTable>
          ) : <EmptyHint text={'Noch keine Termine — über „Termin" oben anlegen.'} />}
        </BigCard>

        {/* KOSTENVORANSCHLÄGE */}
        <BigCard title="Kostenvoranschläge" icon={Receipt} accent="ai" count={data.cost_estimates.length} action={<AddBtn label="KVA" onClick={goKva} />}>
          {data.cost_estimates.length ? (
            <GroupedTable columns={['Nummer', 'Betrag', 'Status']}>
              {groupByDay(data.cost_estimates, () => null).map((g) => (
                <Fragment key={g.key}>
                  {g.items.map((k) => (
                    <tr key={k.id} className={rowCls} onClick={() => navigate(`/cost-estimates/${k.id}`)}>
                      <td className="px-3 py-2.5 font-mono text-xs text-muted">{k.number ?? 'KVA'}</td>
                      <td className="px-3 py-2.5 font-bold text-text">{euro(k.total)}</td>
                      <td className="px-3 py-2.5"><Tag variant={k.status === 'accepted' ? 'success' : k.status === 'rejected' ? 'neutral' : 'info'}>{k.status}</Tag></td>
                    </tr>
                  ))}
                </Fragment>
              ))}
            </GroupedTable>
          ) : <EmptyHint text="Noch keine Kostenvoranschläge." />}
        </BigCard>

        {/* RECHNUNGEN */}
        <BigCard title="Rechnungen" icon={FileText} accent="ai" count={data.invoices.length} action={<AddBtn label="Rechnung" onClick={goInvoice} />}>
          {data.invoices.length ? (
            <GroupedTable columns={['Nummer', 'Betrag', 'Status']}>
              {data.invoices.map((inv) => (
                <tr key={inv.id} className={rowCls} onClick={() => navigate(`/invoices/${inv.id}`)}>
                  <td className="px-3 py-2.5 font-mono text-xs text-muted">{inv.number ?? 'RE'}</td>
                  <td className="px-3 py-2.5 font-bold text-text">{euro(inv.total)}</td>
                  <td className="px-3 py-2.5"><Tag variant={inv.status === 'paid' ? 'success' : 'info'}>{inv.status}</Tag></td>
                </tr>
              ))}
            </GroupedTable>
          ) : <EmptyHint text="Noch keine Rechnungen." />}
        </BigCard>

        {/* TECHNIKER */}
        <BigCard title="Techniker" icon={HardHat} count={jobs.length} action={<AddBtn label="Beauftragen" onClick={() => setTechForm((o) => !o)} />}>
          {techForm && (
            <div className="mb-3 rounded-xl border border-border bg-alt p-3">
              {data.appointments.length === 0 ? (
                <p className="text-sm text-muted">Erst einen Termin anlegen — der Techniker-Link gehört zu einem Termin.</p>
              ) : technicians.length === 0 ? (
                <p className="text-sm text-muted">Keine Techniker hinterlegt (Mitarbeiter mit Technikerrolle).</p>
              ) : (
                <div className="flex flex-wrap items-end gap-2">
                  <label className="flex flex-col gap-1 text-xs font-bold text-muted">Termin
                    <select value={techAppt} onChange={(e) => setTechAppt(e.target.value)} className="rounded-lg border border-border bg-surface px-2 py-1.5 text-sm text-text">
                      <option value="">wählen…</option>
                      {data.appointments.map((a) => <option key={a.id} value={a.id}>{(a.title ?? 'Termin') + (a.scheduled_at ? ` · ${fmtDateTime(a.scheduled_at)}` : '')}</option>)}
                    </select>
                  </label>
                  <label className="flex flex-col gap-1 text-xs font-bold text-muted">Techniker
                    <select value={techEmp} onChange={(e) => setTechEmp(e.target.value)} className="rounded-lg border border-border bg-surface px-2 py-1.5 text-sm text-text">
                      <option value="">wählen…</option>
                      {technicians.map((e) => <option key={e.id} value={e.id}>{e.display_name ?? 'Techniker'}</option>)}
                    </select>
                  </label>
                  <button disabled={!techAppt || !techEmp || dispatchTech.isPending} onClick={() => dispatchTech.mutate()} className="inline-flex items-center gap-1.5 rounded-lg bg-green-primary px-3 py-2 text-sm font-bold text-white transition hover:brightness-105 disabled:opacity-50">
                    <Send size={14} /> Link senden
                  </button>
                </div>
              )}
            </div>
          )}
          {jobs.length ? (
            <GroupedTable columns={['Techniker', 'Termin', 'Status', 'Bericht', '']}>
              {groupByDay(jobs, (j) => j.scheduled_at ?? j.created_at ?? null).map((g) => (
                <Fragment key={g.key}>
                  <DayDivider label={g.label} span={5} />
                  {g.items.map((j) => {
                    const st = JOB_STATUS[j.status] ?? { label: j.status, variant: 'warning' as const }
                    return (
                      <tr key={j.id} className="border-t border-border-faint">
                        <td className="whitespace-nowrap px-3 py-2.5 font-semibold text-text"><span className="inline-flex items-center gap-1.5"><Wrench size={13} className="text-green-deep" />{j.employee_name ?? 'Techniker'}</span></td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-xs text-muted">{j.appointment_title ?? 'Termin'}{j.scheduled_at ? ` · ${fmtDateTime(j.scheduled_at)}` : ''}</td>
                        <td className="px-3 py-2.5"><Tag variant={st.variant}>{st.label}</Tag></td>
                        <td className="px-3 py-2.5 text-xs text-body">
                          {j.report?.description ? (
                            <span className="line-clamp-2">{j.report.description}{j.photo_count ? ` · 📷 ${j.photo_count}` : ''}</span>
                          ) : <span className="text-faint">noch offen</span>}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-right">
                          <button onClick={() => copyLink(j.url)} title="Techniker-Link kopieren" className="inline-flex items-center gap-1 rounded-lg border border-border px-2 py-1 text-xs font-bold text-body hover:bg-alt"><Copy size={12} /> Link</button>
                        </td>
                      </tr>
                    )
                  })}
                </Fragment>
              ))}
            </GroupedTable>
          ) : <EmptyHint text={'Noch kein Techniker beauftragt — über „Beauftragen" einen Termin-Link senden.'} />}
        </BigCard>

        {/* WER IST DABEI */}
        <BigCard title="Wer ist dabei" icon={Users} count={data.employees.length}>
          {data.employees.length === 0 ? (
            <EmptyHint text={'Niemand zugewiesen — über „Mitarbeiter" oben zuweisen.'} />
          ) : (
            <div className="flex flex-wrap gap-2">
              {data.employees.map((e) => (
                <span key={e.id} className={cn('inline-flex items-center gap-1.5 rounded-full border py-1 pl-3 pr-1.5 text-sm font-semibold', e.is_technician ? 'border-green-tint-200 bg-green-tint-50 text-green-deep' : 'border-border bg-alt text-body')}>
                  {e.is_technician && <Wrench size={13} />}
                  {e.display_name ?? 'Mitarbeiter'}
                  <button onClick={() => removeEmp.mutate(e.id)} className="grid h-5 w-5 place-items-center rounded-full text-faint hover:bg-border hover:text-error" title="Entfernen"><X size={13} /></button>
                </span>
              ))}
            </div>
          )}
        </BigCard>
      </div>

      <CreateAppointmentModal
        open={apptOpen}
        onClose={() => setApptOpen(false)}
        call={apptCall}
        inquiryId={firstInq}
        employees={employees}
        onCreated={() => { setApptOpen(false); qc.invalidateQueries({ queryKey: ['caseDetail', caseId] }); flash('Termin erstellt ✓') }}
      />
      {editOpen && <CustomerFormModal open mode="edit" customer={fullCustomer} onClose={() => setEditOpen(false)} onSaved={() => { setEditOpen(false); qc.invalidateQueries({ queryKey: ['caseDetail', caseId] }) }} />}
    </div>
  )
}
