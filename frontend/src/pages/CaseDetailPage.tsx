import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  CalendarClock,
  CalendarPlus,
  CheckCircle2,
  ChevronRight,
  Clock,
  FileText,
  FolderPlus,
  HardHat,
  History,
  Layers,
  MessageSquare,
  Pencil,
  Phone,
  Receipt,
  User,
  UserPlus,
  X,
  type LucideIcon,
} from 'lucide-react'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { CustomerFormModal, type CustomerFormValues } from '../components/CustomerFormModal'
import { MoveMenu, type MoveTarget } from '../components/cases/grouping'
import { Tag } from '../components/ui/Tag'
import { apiFetch } from '../lib/api'
import { fmtDate, fmtDateTime } from '../lib/datetime'
import { cn } from '../lib/utils'
import { CreateAppointmentModal } from './calls/Modals'

interface CaseInquiry {
  id: string
  number: string | null
  subject: string | null
  title: string | null
  status: string
}
interface TLEvent {
  id: string
  kind: string
  timestamp: string
  actor_name: string
  description: string
  extras: Record<string, unknown>
}
interface Appt { id: string; title: string | null; scheduled_at: string | null; status: string }
interface Kva { id: string; number: string | null; total: number | null; status: string }
interface Invoice { id: string; number: string | null; total: number | null; status: string }
interface CaseEmp { id: string; display_name: string | null; is_technician?: boolean }
interface CaseBundle {
  case: {
    id: string
    number: string | null
    label: string | null
    status: string
    customer: { id: string; full_name: string | null; phone: string | null } | null
    created_at: string | null
    project_id?: string | null
  }
  inquiries: CaseInquiry[]
  timeline: TLEvent[]
  appointments: Appt[]
  cost_estimates: Kva[]
  invoices: Invoice[]
  employees: CaseEmp[]
  open_count: number
}
interface Emp { id: string; display_name: string | null; is_active?: boolean; is_absent?: boolean; is_technician?: boolean }
interface ProjRow { id: string; number: string | null; title: string; status: string; customer_id: string | null }
interface CaseRow { id: string; number: string | null; title: string; customer_id: string | null }
interface CasePatchResp { status?: string; project_id?: string | null; title?: string }

// Case status → the user-facing Offen / In Bearbeitung / Abgeschlossen control.
const CASE_STATUS = [
  { value: 'planning', label: 'Offen', Icon: Clock, on: 'bg-info-bg text-info', chip: 'bg-info text-white' },
  { value: 'active', label: 'In Bearbeitung', Icon: CalendarClock, on: 'bg-warning-bg text-warning', chip: 'bg-warning text-white' },
  { value: 'completed', label: 'Abgeschlossen', Icon: CheckCircle2, on: 'bg-success-bg text-success', chip: 'bg-success text-white' },
] as const
const INQ_STATUS: Record<string, { label: string; variant: 'info' | 'warning' | 'success' | 'neutral' }> = {
  open: { label: 'Neu', variant: 'info' },
  in_progress: { label: 'In Bearbeitung', variant: 'warning' },
  completed: { label: 'Erledigt', variant: 'success' },
}
const TL: Record<string, { Icon: LucideIcon; cls: string }> = {
  call_created: { Icon: Phone, cls: 'bg-success-bg text-success' },
  inquiry_status_changed: { Icon: MessageSquare, cls: 'bg-info-bg text-info' },
  assignment_changed: { Icon: UserPlus, cls: 'bg-info-bg text-info' },
  appointment_created: { Icon: CalendarPlus, cls: 'bg-green-tint-100 text-green-deep' },
  appointment_rescheduled: { Icon: CalendarClock, cls: 'bg-warning-bg text-warning' },
  appointment_confirmed: { Icon: CalendarClock, cls: 'bg-success-bg text-success' },
  appointment_rejected: { Icon: CalendarClock, cls: 'bg-error-bg text-error' },
  appointment_cancelled: { Icon: CalendarClock, cls: 'bg-error-bg text-error' },
  alternative_proposed: { Icon: CalendarClock, cls: 'bg-warning-bg text-warning' },
  kva_sent: { Icon: Receipt, cls: 'bg-ai-bg text-ai' },
  kva_accepted: { Icon: Receipt, cls: 'bg-ai-bg text-ai' },
  kva_rejected: { Icon: Receipt, cls: 'bg-ai-bg text-ai' },
  invoice_created: { Icon: FileText, cls: 'bg-ai-bg text-ai' },
}
const euro = (n: number | null) => (n != null ? `${n.toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €` : '—')

export function CaseDetailPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [apptOpen, setApptOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [empOpen, setEmpOpen] = useState(false)
  const [projOpen, setProjOpen] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['caseDetail', id],
    queryFn: () => apiFetch<CaseBundle>(`/api/cases/${id}`),
    enabled: !!id,
  })
  const { data: allCases } = useQuery({
    queryKey: ['cases'],
    queryFn: () => apiFetch<CaseRow[]>('/api/cases'),
    enabled: !!id,
    staleTime: 60_000,
  })
  const { data: employees = [] } = useQuery({ queryKey: ['pe', 'employees'], queryFn: () => apiFetch<Emp[]>('/api/employees'), staleTime: 60_000 })
  const { data: projects = [] } = useQuery({ queryKey: ['projects'], queryFn: () => apiFetch<ProjRow[]>('/api/projects'), staleTime: 60_000 })

  const customerId = data?.case.customer?.id ?? null
  const { data: fullCustomer } = useQuery({
    queryKey: ['customerDetail', customerId],
    queryFn: () => apiFetch<CustomerFormValues>(`/api/customers/${customerId}`),
    enabled: !!customerId,
  })

  const setCase = (mut: (c: CaseBundle['case']) => Partial<CaseBundle['case']>) =>
    qc.setQueryData<CaseBundle>(['caseDetail', id], (old) => (old ? { ...old, case: { ...old.case, ...mut(old.case) } } : old))
  const setEmployees = (mut: (e: CaseEmp[]) => CaseEmp[]) =>
    qc.setQueryData<CaseBundle>(['caseDetail', id], (old) => (old ? { ...old, employees: mut(old.employees) } : old))

  // Status + project PATCH — OPTIMISTIC + authoritative response, so the pill flips
  // instantly and never lags behind a refetch.
  const patchCase = useMutation({
    mutationFn: (body: Record<string, unknown>) => apiFetch<CasePatchResp>(`/api/cases/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
    onMutate: (body) =>
      setCase(() => ({
        ...('status' in body ? { status: body.status as string } : {}),
        ...('project_id' in body ? { project_id: (body.project_id || null) as string | null } : {}),
      })),
    onSuccess: (resp) => {
      setCase((c) => ({ status: resp.status ?? c.status, project_id: resp.project_id ?? null, label: resp.title ?? c.label }))
      qc.invalidateQueries({ queryKey: ['cases'] })
    },
  })
  const assignEmp = useMutation({
    mutationFn: (emp: Emp) => apiFetch(`/api/cases/${id}/employees`, { method: 'POST', body: JSON.stringify({ employee_id: emp.id }) }),
    onMutate: (emp) => setEmployees((es) => (es.some((e) => e.id === emp.id) ? es : [...es, { id: emp.id, display_name: emp.display_name, is_technician: emp.is_technician }])),
    onSettled: () => qc.invalidateQueries({ queryKey: ['caseDetail', id] }),
  })
  const removeEmp = useMutation({
    mutationFn: (employeeId: string) => apiFetch(`/api/cases/${id}/employees/${employeeId}`, { method: 'DELETE' }),
    onMutate: (employeeId) => setEmployees((es) => es.filter((e) => e.id !== employeeId)),
    onSettled: () => qc.invalidateQueries({ queryKey: ['caseDetail', id] }),
  })

  if (isLoading || !data) {
    return <div className="flex h-full items-center justify-center text-muted">Lädt…</div>
  }
  const cs = data.case
  const moveTargets: MoveTarget[] = (allCases ?? [])
    .filter((c) => customerId && c.customer_id === customerId)
    .map((c) => ({ id: c.id, label: c.title, number: c.number }))
  const firstInq = data.inquiries[0]?.id
  const assignedIds = new Set(data.employees.map((e) => e.id))
  const freeEmployees = employees.filter((e) => !assignedIds.has(e.id) && e.is_active !== false)
  const currentProject = projects.find((p) => p.id === cs.project_id) ?? null
  const customerProjects = projects.filter((p) => !customerId || p.customer_id === customerId)
  const technicians = data.employees.filter((e) => e.is_technician)

  // Pass case_id so the KVA/invoice links straight back to this Fall (+ a member
  // inquiry on the KVA for the inquiry-level chain).
  const goKva = () => navigate(`/cost-estimates/new?customer_id=${customerId ?? ''}&case_id=${cs.id}${firstInq ? `&inquiry_id=${firstInq}` : ''}`)
  const goInvoice = () => navigate(`/invoices/new?customer_id=${customerId ?? ''}&case_id=${cs.id}`)

  // Synthetic "call" so the shared CreateAppointmentModal can pre-fill from the case.
  const apptCall = {
    customer_id: cs.customer?.id ?? null,
    summary_title: cs.label ?? 'Fall',
    summary: '',
    customers: cs.customer ? { full_name: cs.customer.full_name, phone: cs.customer.phone } : null,
    data_collection: {},
  } as unknown as Parameters<typeof CreateAppointmentModal>[0]['call']

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 md:p-6 lg:p-8">
      <button
        onClick={() => (cs.customer ? navigate(`/customers/${cs.customer.id}`) : navigate('/customers'))}
        className="flex items-center gap-1.5 text-sm text-muted hover:text-body"
      >
        <ArrowLeft size={15} /> {cs.customer ? `Zurück zu ${cs.customer.full_name ?? 'Kunde'}` : 'Zurück'}
      </button>

      {/* HEADER — gradient banner. overflow-visible so the action dropdowns aren't clipped. */}
      <div className="overflow-visible rounded-2xl border border-border bg-gradient-to-br from-green-tint-50 via-surface to-surface shadow-e1">
        <div className="p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <span className="inline-flex items-center gap-1 rounded-md bg-ai-bg px-2 py-0.5 font-mono text-xs font-semibold text-ai">
                <Layers size={12} /> Fall {cs.number ?? '—'}
              </span>
              <h1 className="mt-2 truncate text-2xl font-extrabold tracking-tight text-text">{cs.label || 'Fall'}</h1>
              {cs.customer && (
                <button
                  onClick={() => navigate(`/customers/${cs.customer!.id}`)}
                  className="mt-1 flex items-center gap-1.5 text-sm text-muted hover:text-green-deep"
                >
                  <User size={14} /> {cs.customer.full_name ?? 'Kunde'}
                  {cs.customer.phone ? ` · ${cs.customer.phone}` : ''}
                </button>
              )}
              {currentProject && (
                <button
                  onClick={() => navigate(`/projects/${currentProject.id}`)}
                  className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-border bg-alt px-2 py-1 text-xs font-semibold text-muted hover:text-green-deep"
                >
                  <FolderPlus size={12} /> Projekt {currentProject.number ?? ''} · {currentProject.title}
                </button>
              )}
            </div>
            {/* STATUS SWITCHER */}
            <div className="flex shrink-0 gap-1.5">
              {CASE_STATUS.map((o) => {
                const active = o.value === cs.status
                return (
                  <button
                    key={o.value}
                    disabled={patchCase.isPending}
                    onClick={() => patchCase.mutate({ status: o.value })}
                    className={cn(
                      'flex flex-col items-center gap-1 rounded-xl border px-3 py-2 text-[11px] font-bold transition disabled:opacity-50',
                      active ? cn('border-transparent', o.on, 'shadow-e1') : 'border-border bg-surface text-muted hover:bg-alt',
                    )}
                  >
                    <span className={cn('grid h-6 w-6 place-items-center rounded-full', active ? o.chip : 'bg-alt text-faint')}>
                      <o.Icon size={13} />
                    </span>
                    {o.label}
                  </button>
                )
              })}
            </div>
          </div>

          {/* ACTION BAR */}
          <div className="mt-5 flex flex-wrap gap-2 border-t border-border pt-4">
            <ActionBtn icon={CalendarPlus} label="Termin" tone="green" onClick={() => setApptOpen(true)} />
            <ActionBtn icon={Receipt} label="KVA" tone="ai" onClick={goKva} disabled={!customerId} />
            <ActionBtn icon={FileText} label="Rechnung" tone="ai" onClick={goInvoice} disabled={!customerId} />
            <div className="relative">
              <ActionBtn icon={UserPlus} label="Mitarbeiter" tone="steel" onClick={() => setEmpOpen((o) => !o)} />
              {empOpen && (
                <Dropdown onClose={() => setEmpOpen(false)} empty={!freeEmployees.length} emptyLabel="Alle zugewiesen">
                  {freeEmployees.map((e) => (
                    <button key={e.id} onClick={() => { assignEmp.mutate(e); setEmpOpen(false) }} className="block w-full truncate rounded px-2.5 py-1.5 text-left text-sm text-body hover:bg-alt">
                      {e.display_name ?? 'Mitarbeiter'}{e.is_technician ? ' · Techniker' : ''}
                    </button>
                  ))}
                </Dropdown>
              )}
            </div>
            <div className="relative">
              <ActionBtn icon={FolderPlus} label={currentProject ? 'Projekt ändern' : 'Zu Projekt'} tone="steel" onClick={() => setProjOpen((o) => !o)} />
              {projOpen && (
                <Dropdown onClose={() => setProjOpen(false)} empty={!customerProjects.length} emptyLabel="Kein Projekt — erst anlegen">
                  {currentProject && (
                    <button onClick={() => { patchCase.mutate({ project_id: '' }); setProjOpen(false) }} className="block w-full rounded px-2.5 py-1.5 text-left text-sm text-body hover:bg-alt">
                      Aus Projekt lösen
                    </button>
                  )}
                  {customerProjects.map((p) => (
                    <button key={p.id} onClick={() => { patchCase.mutate({ project_id: p.id }); setProjOpen(false) }} className="block w-full truncate rounded px-2.5 py-1.5 text-left text-sm text-body hover:bg-alt">
                      → {p.title}
                    </button>
                  ))}
                </Dropdown>
              )}
            </div>
            <ActionBtn icon={Pencil} label="Kunde bearbeiten" tone="steel" onClick={() => setEditOpen(true)} disabled={!customerId} />
          </div>
        </div>
      </div>

      {/* STATS */}
      <div className="flex flex-wrap gap-2">
        <Stat label="Anfragen" value={data.inquiries.length} />
        <Stat label="Termine" value={data.appointments.length} />
        <Stat label="KVA" value={data.cost_estimates.length} />
        <Stat label="Rechnungen" value={data.invoices.length} />
        <Stat label="Mitarbeiter" value={data.employees.length} />
        <Stat label="offene Punkte" value={data.open_count} highlight={data.open_count > 0} />
      </div>

      {/* MITARBEITER */}
      <Section icon={UserPlus} title="Mitarbeiter" count={data.employees.length}>
        {data.employees.length === 0 ? (
          <p className="text-sm text-muted">Niemand zugewiesen — über „Mitarbeiter" oben zuweisen.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {data.employees.map((e) => (
              <span key={e.id} className="inline-flex items-center gap-1.5 rounded-full border border-border bg-alt py-1 pl-3 pr-1.5 text-sm font-medium text-body">
                {e.display_name ?? 'Mitarbeiter'}
                {e.is_technician && <span className="rounded bg-green-tint-100 px-1 text-[10px] font-bold text-green-deep">Techniker</span>}
                <button onClick={() => removeEmp.mutate(e.id)} className="grid h-5 w-5 place-items-center rounded-full text-faint hover:bg-border hover:text-error" title="Entfernen">
                  <X size={13} />
                </button>
              </span>
            ))}
          </div>
        )}
      </Section>

      {/* ANFRAGEN — with per-inquiry move */}
      <Section icon={MessageSquare} title="Anfragen in diesem Fall" count={data.inquiries.length}>
        <div className="space-y-2">
          {data.inquiries.map((i) => {
            const ist = INQ_STATUS[i.status] ?? { label: i.status, variant: 'neutral' as const }
            return (
              <div key={i.id} className="group relative rounded-lg border border-border transition hover:border-green-primary hover:bg-alt">
                <div onClick={() => navigate(`/vorgang/${i.id}`)} className="cursor-pointer p-3 pr-9">
                  <div className="flex items-center gap-2">
                    <Tag variant={ist.variant}>{ist.label}</Tag>
                    <span className="flex-1 truncate text-sm font-semibold text-text">{i.subject || i.title || 'Anfrage'}</span>
                    <span className="font-mono text-xs text-muted">{i.number}</span>
                  </div>
                </div>
                <MoveMenu inquiryId={i.id} currentCaseId={cs.id} cases={moveTargets} onMoved={() => qc.invalidateQueries({ queryKey: ['caseDetail', id] })} />
              </div>
            )
          })}
          {data.inquiries.length === 0 && <p className="text-sm text-muted">Keine Anfragen in diesem Fall.</p>}
        </div>
      </Section>

      {/* TERMINE */}
      <Section icon={CalendarClock} title="Termine" count={data.appointments.length} action={<MiniBtn onClick={() => setApptOpen(true)} label="+ Termin" />}>
        {data.appointments.length === 0 ? (
          <p className="text-sm text-muted">Keine Termine.</p>
        ) : (
          <div className="space-y-2">
            {data.appointments.map((a) => (
              <button key={a.id} onClick={() => navigate('/calendar')} className="flex w-full items-center gap-2 rounded-lg border border-border p-3 text-left transition hover:border-green-primary hover:bg-alt">
                <CalendarClock size={15} className="text-green-deep" />
                <span className="flex-1 truncate text-sm font-semibold text-text">{a.title ?? 'Termin'}</span>
                <span className="text-xs text-muted">{a.scheduled_at ? fmtDateTime(a.scheduled_at) : 'offen'}</span>
                <Tag variant={a.status === 'confirmed' ? 'success' : a.status === 'cancelled' || a.status === 'rejected' ? 'neutral' : 'warning'}>{a.status}</Tag>
              </button>
            ))}
          </div>
        )}
      </Section>

      {/* TECHNIKER */}
      <Section icon={HardHat} title="Techniker" count={technicians.length}>
        {technicians.length === 0 ? (
          <p className="text-sm text-muted">Kein Techniker zugewiesen. Weisen Sie über „Mitarbeiter" einen Techniker zu — der Techniker-Einsatz wird dann am bestätigten Termin ausgelöst.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {technicians.map((t) => (
              <span key={t.id} className="inline-flex items-center gap-1.5 rounded-full border border-green-tint-200 bg-green-tint-50 px-3 py-1 text-sm font-medium text-green-deep">
                <HardHat size={13} /> {t.display_name ?? 'Techniker'}
              </span>
            ))}
          </div>
        )}
      </Section>

      {/* KVA */}
      <Section icon={Receipt} title="Kostenvoranschläge" count={data.cost_estimates.length} action={<MiniBtn onClick={goKva} label="+ KVA" />}>
        {data.cost_estimates.length === 0 ? (
          <p className="text-sm text-muted">Keine Kostenvoranschläge.</p>
        ) : (
          <div className="space-y-2">
            {data.cost_estimates.map((k) => (
              <button key={k.id} onClick={() => navigate(`/cost-estimates/${k.id}`)} className="flex w-full items-center gap-2 rounded-lg border border-border p-3 text-left transition hover:border-green-primary hover:bg-alt">
                <Receipt size={15} className="text-ai" />
                <span className="flex-1 truncate font-mono text-xs text-muted">{k.number ?? 'KVA'}</span>
                <span className="text-sm font-semibold text-text">{euro(k.total)}</span>
                <Tag variant={k.status === 'accepted' ? 'success' : k.status === 'rejected' ? 'neutral' : 'info'}>{k.status}</Tag>
                <ChevronRight size={14} className="text-faint" />
              </button>
            ))}
          </div>
        )}
      </Section>

      {/* RECHNUNGEN */}
      <Section icon={FileText} title="Rechnungen" count={data.invoices.length} action={<MiniBtn onClick={goInvoice} label="+ Rechnung" />}>
        {data.invoices.length === 0 ? (
          <p className="text-sm text-muted">Keine Rechnungen.</p>
        ) : (
          <div className="space-y-2">
            {data.invoices.map((inv) => (
              <button key={inv.id} onClick={() => navigate(`/invoices/${inv.id}`)} className="flex w-full items-center gap-2 rounded-lg border border-border p-3 text-left transition hover:border-green-primary hover:bg-alt">
                <FileText size={15} className="text-ai" />
                <span className="flex-1 truncate font-mono text-xs text-muted">{inv.number ?? 'RE'}</span>
                <span className="text-sm font-semibold text-text">{euro(inv.total)}</span>
                <Tag variant={inv.status === 'paid' ? 'success' : 'info'}>{inv.status}</Tag>
                <ChevronRight size={14} className="text-faint" />
              </button>
            ))}
          </div>
        )}
      </Section>

      {/* VERLAUF */}
      <Section icon={History} title="Gesamter Verlauf" count={data.timeline.length}>
        {data.timeline.length === 0 ? (
          <p className="text-sm text-muted">Noch keine Aktivitäten.</p>
        ) : (
          <div className="flex flex-col">
            {data.timeline.map((ev, idx) => {
              const k = TL[ev.kind] ?? { Icon: History, cls: 'bg-alt text-muted' }
              const last = idx === data.timeline.length - 1
              return (
                <div key={ev.id} className={cn('relative flex items-start gap-3.5', !last && 'pb-5')}>
                  {!last && <span className="absolute bottom-0 left-[19px] top-[42px] w-0.5 bg-border" aria-hidden />}
                  <span className={cn('z-[1] flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full', k.cls)}>
                    <k.Icon size={18} />
                  </span>
                  <div className="min-w-0 flex-1 pt-1.5">
                    <div className="text-sm font-semibold text-text">{ev.description}</div>
                    <div className="mt-0.5 text-xs text-muted">{fmtDateTime(ev.timestamp)} · {ev.actor_name}</div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </Section>

      <div className="rounded-lg border border-border bg-surface px-5 py-3 text-xs text-muted">Eröffnet: {fmtDate(cs.created_at)}</div>

      <CreateAppointmentModal
        open={apptOpen}
        onClose={() => setApptOpen(false)}
        call={apptCall}
        inquiryId={firstInq}
        employees={employees}
        onCreated={() => { setApptOpen(false); qc.invalidateQueries({ queryKey: ['caseDetail', id] }) }}
      />
      {editOpen && (
        <CustomerFormModal
          open
          mode="edit"
          customer={fullCustomer}
          onClose={() => setEditOpen(false)}
          onSaved={() => {
            setEditOpen(false)
            qc.invalidateQueries({ queryKey: ['caseDetail', id] })
            if (customerId) qc.invalidateQueries({ queryKey: ['customerDetail', customerId] })
          }}
        />
      )}
    </div>
  )
}

const TONE: Record<string, string> = {
  green: 'border-green-tint-200 bg-green-tint-50 text-green-deep hover:bg-green-tint-100',
  ai: 'border-ai-bg bg-ai-bg text-ai hover:brightness-95',
  steel: 'border-border bg-surface text-body hover:bg-alt',
}
function ActionBtn({ icon: Icon, label, tone, onClick, disabled }: { icon: LucideIcon; label: string; tone: 'green' | 'ai' | 'steel'; onClick: () => void; disabled?: boolean }) {
  return (
    <button onClick={onClick} disabled={disabled} className={cn('inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-bold transition disabled:opacity-40', TONE[tone])}>
      <Icon size={15} /> {label}
    </button>
  )
}
function Dropdown({ children, onClose, empty, emptyLabel }: { children: React.ReactNode; onClose: () => void; empty: boolean; emptyLabel: string }) {
  return (
    <>
      <div className="fixed inset-0 z-30" onClick={onClose} />
      <div className="absolute left-0 z-40 mt-1 max-h-64 w-60 overflow-auto rounded-lg border border-border bg-surface p-1 shadow-e3">
        {empty ? <p className="px-2.5 py-2 text-xs text-muted">{emptyLabel}</p> : children}
      </div>
    </>
  )
}
function MiniBtn({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button onClick={onClick} className="rounded-md border border-border bg-surface px-2.5 py-1 text-xs font-semibold text-body hover:bg-alt">{label}</button>
  )
}
function Stat({ label, value, highlight }: { label: string; value: number; highlight?: boolean }) {
  return (
    <div className={cn('rounded-lg border px-3.5 py-2 text-sm', highlight ? 'border-warning-bg bg-warning-bg' : 'border-border bg-surface')}>
      <span className={cn('font-bold', highlight ? 'text-warning' : 'text-text')}>{value}</span> <span className="text-muted">{label}</span>
    </div>
  )
}
function Section({ icon: Icon, title, count, action, children }: { icon: LucideIcon; title: string; count?: number; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-5 shadow-e1">
      <div className="mb-4 flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-bold text-text">
          <Icon size={16} className="text-green-deep" /> {title}
          {count != null && <span className="rounded-full bg-alt px-2 py-0.5 text-xs font-semibold text-muted">{count}</span>}
        </h2>
        {action}
      </div>
      {children}
    </div>
  )
}
