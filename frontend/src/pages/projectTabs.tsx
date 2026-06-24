import deLocale from '@fullcalendar/core/locales/de'
import dayGridPlugin from '@fullcalendar/daygrid'
import FullCalendar from '@fullcalendar/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CheckCircle2,
  Download,
  Eye,
  FileText,
  Link2,
  PhoneIncoming,
  PhoneOutgoing,
  Plus,
  Upload,
  X,
} from 'lucide-react'
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Modal } from '../components/ui/Modal'
import { apiBlobUrl, apiFetch, apiUpload } from '../lib/api'
import { cn } from '../lib/utils'
import type { CaseListRow } from './cases/types'

const STALE = 5 * 60 * 1000

export interface ProjectLite {
  id: string
  customer_id: string | null
  customer_name: string | null
  internal_notes: string | null
  notes_updated_at: string | null
}

const money = (n: number | null) =>
  '€' + (n ?? 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const fmtDate = (d: string | null) =>
  d ? new Date(d).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'Europe/Berlin' }) : '—'
const fmtDateTime = (d: string | null) =>
  d ? new Date(d).toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Berlin' }) : '—'
const inputCls = 'w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary'

const KVA_STATUS: Record<string, { label: string; cls: string }> = {
  draft: { label: 'Entwurf', cls: 'bg-alt text-muted' },
  sent: { label: 'Gesendet', cls: 'bg-info-bg text-info' },
  accepted: { label: 'Akzeptiert', cls: 'bg-success-bg text-success' },
  rejected: { label: 'Abgelehnt', cls: 'bg-error-bg text-error' },
  invoiced: { label: 'Abgerechnet', cls: 'bg-ai-bg text-ai' },
}
const INV_STATUS: Record<string, { label: string; cls: string }> = {
  draft: { label: 'Entwurf', cls: 'bg-alt text-muted' },
  sent: { label: 'Gesendet', cls: 'bg-info-bg text-info' },
  paid: { label: 'Bezahlt', cls: 'bg-success-bg text-success' },
  overdue: { label: 'Überfällig', cls: 'bg-warning-bg text-warning' },
  cancelled: { label: 'Storniert', cls: 'bg-error-bg text-error' },
}

function Pill({ map, status }: { map: Record<string, { label: string; cls: string }>; status: string }) {
  const m = map[status] ?? { label: status, cls: 'bg-alt text-muted' }
  return <span className={cn('rounded-full px-2.5 py-0.5 text-xs font-medium', m.cls)}>{m.label}</span>
}

function EmptyState({ children }: { children: React.ReactNode }) {
  return <div className="rounded-xl border border-dashed border-border px-6 py-12 text-center text-sm text-muted">{children}</div>
}

async function openPdf(kind: 'cost-estimates' | 'invoices', id: string, download: boolean) {
  try {
    const url = await apiBlobUrl(`/api/${kind}/${id}/pdf${download ? '' : '?preview=true'}`)
    if (download) {
      const a = document.createElement('a')
      a.href = url
      a.download = `${id}.pdf`
      a.click()
    } else window.open(url, '_blank')
  } catch { /* ignore */ }
}

function IconBtn({ title, onClick, cls, children }: { title: string; onClick: () => void; cls?: string; children: React.ReactNode }) {
  return <button title={title} onClick={onClick} className={cn('rounded-md p-1.5 text-muted hover:bg-alt', cls)}>{children}</button>
}

// ─── ANRUFE ───────────────────────────────────────────────────────────────────
interface Call { id: string; started_at: string | null; duration_seconds: number | null; direction: string | null; summary: string | null; summary_title: string | null }
export function CallsTab({ project }: { project: ProjectLite }) {
  const navigate = useNavigate()
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [dir, setDir] = useState('all')
  const { data: calls = [] } = useQuery({
    queryKey: ['project-calls', project.id],
    queryFn: () => apiFetch<Call[]>(`/api/projects/${project.id}/calls`),
    staleTime: STALE,
  })
  const filtered = calls.filter((c) => {
    const d = c.started_at?.slice(0, 10) ?? ''
    if (from && d && d < from) return false
    if (to && d && d > to) return false
    if (dir !== 'all' && c.direction !== dir) return false
    return true
  })
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div><div className="mb-1 text-xs text-muted">Von</div><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className={inputCls} /></div>
        <div><div className="mb-1 text-xs text-muted">Bis</div><input type="date" value={to} onChange={(e) => setTo(e.target.value)} className={inputCls} /></div>
        <div className="flex gap-1 rounded-md border border-border bg-alt p-1">
          {[['all', 'Alle'], ['inbound', 'Eingehend'], ['outbound', 'Ausgehend']].map(([v, l]) => (
            <button key={v} onClick={() => setDir(v)} className={cn('rounded px-3 py-1 text-sm', dir === v ? 'bg-surface font-medium text-text shadow-e1' : 'text-muted')}>{l}</button>
          ))}
        </div>
      </div>
      {filtered.length ? (
        <div className="divide-y divide-border-faint rounded-xl border border-border bg-surface">
          {filtered.map((c) => (
            <div key={c.id} className="flex items-center gap-3 px-4 py-3">
              {c.direction === 'outbound' ? <PhoneOutgoing size={16} className="text-info" /> : <PhoneIncoming size={16} className="text-success" />}
              <div className="w-36 shrink-0 text-sm text-muted">{fmtDateTime(c.started_at)}</div>
              <div className="w-16 shrink-0 text-sm text-muted">{Math.round((c.duration_seconds ?? 0) / 60)} min</div>
              <div className="min-w-0 flex-1 truncate text-sm text-body">{c.summary_title || c.summary || '—'}</div>
              <button onClick={() => navigate(`/calls?call_id=${c.id}`)} className="shrink-0 text-sm font-medium text-green-deep hover:underline">Zum Transkript</button>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState>Noch keine Anrufe für dieses Projekt.</EmptyState>
      )}
    </div>
  )
}

// ─── ANFRAGEN ─────────────────────────────────────────────────────────────────
interface Inquiry { id: string; number: string | null; title: string | null; type: string | null; status: string; notes?: string | null; created_at: string; employee_name?: string | null; project_id?: string | null }
const INQ_STATUS: Record<string, { label: string; cls: string }> = {
  open: { label: 'Offen', cls: 'bg-info-bg text-info' },
  in_progress: { label: 'In Bearbeitung', cls: 'bg-warning-bg text-warning' },
  completed: { label: 'Erledigt', cls: 'bg-success-bg text-success' },
}
export function InquiriesTab({ project }: { project: ProjectLite }) {
  const qc = useQueryClient()
  const [statusF, setStatusF] = useState('all')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [newOpen, setNewOpen] = useState(false)
  const [linkOpen, setLinkOpen] = useState(false)
  const { data: inquiries = [] } = useQuery({
    queryKey: ['project-inquiries', project.id],
    queryFn: () => apiFetch<Inquiry[]>(`/api/projects/${project.id}/inquiries`),
    staleTime: STALE,
  })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['project-inquiries', project.id] })
    qc.invalidateQueries({ queryKey: ['project', project.id] })
  }
  const filtered = inquiries.filter((i) => statusF === 'all' || i.status === statusF)
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <select value={statusF} onChange={(e) => setStatusF(e.target.value)} className="rounded-md border border-border bg-alt px-3 py-2 text-sm text-text outline-none">
          <option value="all">Alle Status</option>
          <option value="open">Offen</option>
          <option value="in_progress">In Bearbeitung</option>
          <option value="completed">Erledigt</option>
        </select>
        <div className="flex gap-2">
          <button onClick={() => setLinkOpen(true)} className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-3 py-2 text-sm font-medium text-body hover:bg-alt"><Link2 size={14} /> Bestehende verknüpfen</button>
          <button onClick={() => setNewOpen(true)} className="inline-flex items-center gap-1.5 rounded-md bg-green-primary px-3 py-2 text-sm font-semibold text-white hover:brightness-110"><Plus size={14} /> Neue Anfrage</button>
        </div>
      </div>
      {filtered.length ? (
        <div className="space-y-2">
          {filtered.map((i) => {
            const isOpen = expanded === i.id
            return (
              <div key={i.id} className="rounded-lg border border-border bg-surface">
                <button onClick={() => setExpanded(isOpen ? null : i.id)} className="flex w-full items-center gap-3 p-3 text-left">
                  <Pill map={INQ_STATUS} status={i.status} />
                  <span className="flex-1 truncate text-sm font-medium text-text">{i.title ?? 'Anfrage'}</span>
                  {i.employee_name && <span className="text-xs text-muted">{i.employee_name}</span>}
                  <span className="text-xs text-faint">{fmtDate(i.created_at)}</span>
                </button>
                {isOpen && (
                  <div className="space-y-1 border-t border-border px-3 py-3 text-sm text-muted">
                    {i.number && <div className="font-mono text-xs">{i.number}</div>}
                    {i.type && <div>Kategorie: <span className="capitalize text-body">{i.type}</span></div>}
                    <div className="whitespace-pre-wrap text-body">{i.notes ?? 'Keine Notizen.'}</div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        <EmptyState>Noch keine Anfragen für dieses Projekt.</EmptyState>
      )}
      {newOpen && <NewInquiryModal project={project} onClose={() => setNewOpen(false)} onSaved={() => { setNewOpen(false); refresh() }} />}
      {linkOpen && <LinkInquiryModal project={project} onClose={() => setLinkOpen(false)} onSaved={() => { setLinkOpen(false); refresh() }} />}
    </div>
  )
}

function NewInquiryModal({ project, onClose, onSaved }: { project: ProjectLite; onClose: () => void; onSaved: () => void }) {
  const [title, setTitle] = useState('')
  const [type, setType] = useState('info')
  const [notes, setNotes] = useState('')
  const save = useMutation({
    mutationFn: () => apiFetch('/api/inquiries', { method: 'POST', body: JSON.stringify({ customer_id: project.customer_id, project_id: project.id, title, type, notes }) }),
    onSuccess: onSaved,
  })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Neue Anfrage" footer={
      <button disabled={!title || save.isPending} onClick={() => save.mutate()} className="w-full rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">Anfrage erstellen</button>
    }>
      <div className="space-y-4">
        <div><div className="mb-1.5 text-xs font-semibold text-body">Titel *</div><input value={title} onChange={(e) => setTitle(e.target.value)} className={inputCls} /></div>
        <div>
          <div className="mb-1.5 text-xs font-semibold text-body">Kategorie</div>
          <div className="flex flex-wrap gap-2">
            {['appointment', 'offer', 'info', 'recall'].map((c) => (
              <button key={c} onClick={() => setType(c)} className={cn('rounded-md border px-3 py-1.5 text-sm font-medium capitalize', type === c ? 'border-green-primary bg-green-primary text-white' : 'border-border text-body hover:bg-alt')}>{c}</button>
            ))}
          </div>
        </div>
        <div><div className="mb-1.5 text-xs font-semibold text-body">Notiz</div><textarea rows={4} value={notes} onChange={(e) => setNotes(e.target.value)} className={inputCls} /></div>
      </div>
    </Modal>
  )
}

function LinkInquiryModal({ project, onClose, onSaved }: { project: ProjectLite; onClose: () => void; onSaved: () => void }) {
  const [picked, setPicked] = useState('')
  const { data: customer } = useQuery({
    queryKey: ['customerDetail', project.customer_id],
    queryFn: () => apiFetch<{ inquiries: Inquiry[] }>(`/api/customers/${project.customer_id}`),
    enabled: !!project.customer_id,
  })
  const candidates = (customer?.inquiries ?? []).filter((i) => !i.project_id && i.status !== 'deleted')
  const link = useMutation({
    mutationFn: () => apiFetch(`/api/inquiries/${picked}`, { method: 'PATCH', body: JSON.stringify({ project_id: project.id }) }),
    onSuccess: onSaved,
  })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Bestehende Anfrage verknüpfen" footer={
      <button disabled={!picked || link.isPending} onClick={() => link.mutate()} className="w-full rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">Verknüpfen</button>
    }>
      {candidates.length ? (
        <div className="space-y-2">
          {candidates.map((i) => (
            <label key={i.id} className={cn('flex cursor-pointer items-center gap-3 rounded-lg border p-3', picked === i.id ? 'border-green-primary bg-green-tint-50' : 'border-border')}>
              <input type="radio" name="inq" checked={picked === i.id} onChange={() => setPicked(i.id)} className="accent-green-primary" />
              <span className="flex-1 text-sm text-text">{i.title ?? 'Anfrage'}</span>
              <span className="text-xs text-muted">{fmtDate(i.created_at)}</span>
            </label>
          ))}
        </div>
      ) : (
        <p className="py-6 text-center text-sm text-muted">Keine unverknüpften Anfragen für diesen Kunden.</p>
      )}
    </Modal>
  )
}

// ─── TERMINE ──────────────────────────────────────────────────────────────────
interface Appt { id: string; title: string | null; scheduled_at: string | null; duration_minutes: number | null; status: string; color: string | null; employee_name?: string | null }
const dotFor = (s: string) => (s === 'confirmed' || s === 'completed' ? 'bg-success' : s === 'cancelled' ? 'bg-error' : 'bg-warning')
export function AppointmentsTab({ project }: { project: ProjectLite }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [newOpen, setNewOpen] = useState(false)
  const { data: appts = [] } = useQuery({
    queryKey: ['project-appointments', project.id],
    queryFn: () => apiFetch<Appt[]>(`/api/projects/${project.id}/appointments`),
    staleTime: STALE,
  })
  const events = appts.filter((a) => a.scheduled_at && a.status !== 'cancelled').map((a) => ({
    id: a.id, title: a.title ?? 'Termin', start: a.scheduled_at!,
    backgroundColor: a.color || '#2D6B3D', borderColor: a.color || '#2D6B3D',
  }))
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button onClick={() => navigate('/calendar')} className="text-sm font-medium text-green-deep hover:underline">Im Kalender öffnen →</button>
        <button onClick={() => setNewOpen(true)} className="inline-flex items-center gap-1.5 rounded-md bg-green-primary px-3 py-2 text-sm font-semibold text-white hover:brightness-110"><Plus size={14} /> Neuer Termin</button>
      </div>
      <div className="rounded-xl border border-border bg-surface p-3 [&_.fc-toolbar-title]:text-sm [&_.fc]:text-xs">
        <FullCalendar plugins={[dayGridPlugin]} initialView="dayGridMonth" locale={deLocale} firstDay={1} height={240} headerToolbar={{ left: 'prev,next', center: 'title', right: 'today' }} events={events} dayMaxEvents={2} />
      </div>
      {appts.length ? (
        <div className="divide-y divide-border-faint rounded-xl border border-border bg-surface">
          {appts.map((a) => (
            <div key={a.id} className="flex items-center gap-3 px-4 py-3">
              <span className={cn('h-2 w-2 shrink-0 rounded-full', dotFor(a.status))} />
              <div className="w-36 shrink-0 text-sm text-muted">{fmtDateTime(a.scheduled_at)}</div>
              <div className="min-w-0 flex-1 truncate text-sm font-medium text-text">{a.title ?? 'Termin'}</div>
              {a.employee_name && <span className="shrink-0 text-xs text-muted">{a.employee_name}</span>}
              <span className="shrink-0 text-xs text-muted">{a.duration_minutes ?? 60} Min</span>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState>Noch keine Termine für dieses Projekt.</EmptyState>
      )}
      {newOpen && <NewAppointmentModal project={project} onClose={() => setNewOpen(false)} onSaved={() => {
        setNewOpen(false)
        qc.invalidateQueries({ queryKey: ['project-appointments', project.id] })
        qc.invalidateQueries({ queryKey: ['project', project.id] })
      }} />}
    </div>
  )
}

function NewAppointmentModal({ project, onClose, onSaved }: { project: ProjectLite; onClose: () => void; onSaved: () => void }) {
  const [title, setTitle] = useState('')
  const [date, setDate] = useState('')
  const [time, setTime] = useState('09:00')
  const [duration, setDuration] = useState(60)
  const [assigned, setAssigned] = useState('')
  const { data: employees = [] } = useQuery({ queryKey: ['employees'], queryFn: () => apiFetch<{ id: string; display_name: string }[]>('/api/employees') })
  const save = useMutation({
    mutationFn: () => apiFetch('/api/appointments', {
      method: 'POST',
      body: JSON.stringify({ customer_id: project.customer_id, project_id: project.id, title: title || 'Termin', scheduled_at: new Date(`${date}T${time}`).toISOString(), duration_minutes: duration, assigned_employee_id: assigned || null }),
    }),
    onSuccess: onSaved,
  })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Neuer Termin" footer={
      <button disabled={!date || save.isPending} onClick={() => save.mutate()} className="w-full rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">Termin speichern</button>
    }>
      <div className="space-y-4">
        <div><div className="mb-1.5 text-xs font-semibold text-body">Titel</div><input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="z. B. Vor-Ort-Termin" className={inputCls} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><div className="mb-1.5 text-xs font-semibold text-body">Datum *</div><input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={inputCls} /></div>
          <div><div className="mb-1.5 text-xs font-semibold text-body">Uhrzeit *</div><input type="time" value={time} onChange={(e) => setTime(e.target.value)} className={inputCls} /></div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div><div className="mb-1.5 text-xs font-semibold text-body">Dauer</div><select value={duration} onChange={(e) => setDuration(Number(e.target.value))} className={inputCls}>{[30, 60, 90, 120, 180].map((m) => <option key={m} value={m}>{m} Min</option>)}</select></div>
          <div><div className="mb-1.5 text-xs font-semibold text-body">Mitarbeiter</div><select value={assigned} onChange={(e) => setAssigned(e.target.value)} className={inputCls}><option value="">Nicht zugewiesen</option>{employees.map((e) => <option key={e.id} value={e.id}>{e.display_name}</option>)}</select></div>
        </div>
      </div>
    </Modal>
  )
}

// ─── KOSTENVORANSCHLÄGE ───────────────────────────────────────────────────────
interface Kva { id: string; number: string | null; status: string; subject: string | null; total: number | null; created_at: string }
export function CostEstimatesTab({ project }: { project: ProjectLite }) {
  const navigate = useNavigate()
  const { data: kvas = [] } = useQuery({
    queryKey: ['project-cost-estimates', project.id],
    queryFn: () => apiFetch<Kva[]>(`/api/projects/${project.id}/cost-estimates`),
    staleTime: STALE,
  })
  const total = kvas.reduce((s, k) => s + (k.total ?? 0), 0)
  const accepted = kvas.filter((k) => k.status === 'accepted').reduce((s, k) => s + (k.total ?? 0), 0)
  const newUrl = `/cost-estimates/new?project_id=${project.id}${project.customer_id ? `&customer_id=${project.customer_id}` : ''}`
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button onClick={() => navigate(newUrl)} className="inline-flex items-center gap-1.5 rounded-md bg-green-primary px-3 py-2 text-sm font-semibold text-white hover:brightness-110"><Plus size={14} /> Neuer Angebot</button>
      </div>
      {kvas.length ? (
        <div className="overflow-x-auto rounded-xl border border-border bg-surface">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-border text-left text-xs font-semibold uppercase tracking-wide text-muted">
              <th className="px-4 py-3">Angebot-Nr.</th><th className="px-4 py-3">Datum</th><th className="px-4 py-3">Betreff</th><th className="px-4 py-3 text-right">Betrag</th><th className="px-4 py-3">Status</th><th className="px-4 py-3 text-right">Aktionen</th>
            </tr></thead>
            <tbody>
              {kvas.map((k) => (
                <tr key={k.id} className="border-b border-border-faint last:border-0 hover:bg-alt/40">
                  <td className="px-4 py-3 font-semibold text-text">{k.number}</td>
                  <td className="px-4 py-3 text-muted">{fmtDate(k.created_at)}</td>
                  <td className="max-w-[220px] truncate px-4 py-3 text-body">{k.subject || '—'}</td>
                  <td className="px-4 py-3 text-right font-semibold text-text">{money(k.total)}</td>
                  <td className="px-4 py-3"><Pill map={KVA_STATUS} status={k.status} /></td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-0.5">
                      <IconBtn title="Vorschau" onClick={() => openPdf('cost-estimates', k.id, false)}><Eye size={15} /></IconBtn>
                      <IconBtn title="PDF herunterladen" onClick={() => openPdf('cost-estimates', k.id, true)}><Download size={15} /></IconBtn>
                      <IconBtn title="In Rechnung umwandeln" cls="text-green-deep" onClick={() => navigate(`/invoices/new?kva_id=${k.id}&project_id=${project.id}`)}><FileText size={15} /></IconBtn>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot><tr className="border-t border-border text-sm">
              <td colSpan={3} className="px-4 py-3 text-right font-medium text-muted">Akzeptiert: <span className="text-success">{money(accepted)}</span></td>
              <td className="px-4 py-3 text-right font-bold text-text">{money(total)}</td>
              <td colSpan={2} className="px-4 py-3 text-left text-xs text-muted">Gesamt</td>
            </tr></tfoot>
          </table>
        </div>
      ) : (
        <EmptyState>Noch keine Angebote für dieses Projekt.</EmptyState>
      )}
    </div>
  )
}

// ─── RECHNUNGEN ───────────────────────────────────────────────────────────────
interface Inv { id: string; number: string | null; status: string; invoice_date: string | null; due_date: string | null; total: number | null }
export function InvoicesTab({ project }: { project: ProjectLite }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [toast, setToast] = useState<string | null>(null)
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(null), 3000) }
  const { data: invoices = [] } = useQuery({
    queryKey: ['project-invoices', project.id],
    queryFn: () => apiFetch<Inv[]>(`/api/projects/${project.id}/invoices`),
    staleTime: STALE,
  })
  const markPaid = useMutation({
    mutationFn: (id: string) => apiFetch(`/api/invoices/${id}/status`, { method: 'PATCH', body: JSON.stringify({ status: 'paid' }) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['project-invoices', project.id] })
      qc.invalidateQueries({ queryKey: ['project', project.id] })
      flash('Als bezahlt markiert.')
    },
  })
  const total = invoices.reduce((s, i) => s + (i.status !== 'cancelled' ? (i.total ?? 0) : 0), 0)
  const paid = invoices.filter((i) => i.status === 'paid').reduce((s, i) => s + (i.total ?? 0), 0)
  const open = invoices.filter((i) => i.status === 'sent' || i.status === 'overdue').reduce((s, i) => s + (i.total ?? 0), 0)
  const newUrl = `/invoices/new?project_id=${project.id}${project.customer_id ? `&customer_id=${project.customer_id}` : ''}`
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-5 text-sm">
          <span className="text-muted">Gesamt <span className="font-semibold text-text">{money(total)}</span></span>
          <span className="text-muted">Bezahlt <span className="font-semibold text-success">{money(paid)}</span></span>
          <span className="text-muted">Offen <span className="font-semibold text-warning">{money(open)}</span></span>
        </div>
        <button onClick={() => navigate(newUrl)} className="inline-flex items-center gap-1.5 rounded-md bg-green-primary px-3 py-2 text-sm font-semibold text-white hover:brightness-110"><Plus size={14} /> Neue Rechnung</button>
      </div>
      {toast && <div className="rounded-md bg-green-tint-50 px-3 py-2 text-sm font-medium text-green-deep">{toast}</div>}
      {invoices.length ? (
        <div className="overflow-x-auto rounded-xl border border-border bg-surface">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-border text-left text-xs font-semibold uppercase tracking-wide text-muted">
              <th className="px-4 py-3">RE-Nr.</th><th className="px-4 py-3">Datum</th><th className="px-4 py-3">Fällig am</th><th className="px-4 py-3 text-right">Betrag</th><th className="px-4 py-3">Status</th><th className="px-4 py-3 text-right">Aktionen</th>
            </tr></thead>
            <tbody>
              {invoices.map((inv) => {
                const overdue = inv.status === 'overdue'
                return (
                  <tr key={inv.id} className="border-b border-border-faint last:border-0 hover:bg-alt/40">
                    <td className="px-4 py-3 font-semibold text-text">{inv.number}</td>
                    <td className="px-4 py-3 text-muted">{fmtDate(inv.invoice_date)}</td>
                    <td className={cn('px-4 py-3', overdue ? 'font-semibold text-error' : 'text-muted')}>{fmtDate(inv.due_date)}</td>
                    <td className="px-4 py-3 text-right font-semibold text-text">{money(inv.total)}</td>
                    <td className="px-4 py-3"><Pill map={INV_STATUS} status={inv.status} /></td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-0.5">
                        <IconBtn title="Vorschau" onClick={() => openPdf('invoices', inv.id, false)}><Eye size={15} /></IconBtn>
                        <IconBtn title="PDF herunterladen" onClick={() => openPdf('invoices', inv.id, true)}><Download size={15} /></IconBtn>
                        {(inv.status === 'sent' || overdue) && <IconBtn title="Als bezahlt markieren" cls="text-success" onClick={() => markPaid.mutate(inv.id)}><CheckCircle2 size={15} /></IconBtn>}
                        {overdue && <button onClick={() => flash('Erinnerung vermerkt.')} className="rounded-md px-2 py-1 text-xs font-medium text-warning hover:bg-alt">Zahlungserinnerung</button>}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState>Noch keine Rechnungen für dieses Projekt.</EmptyState>
      )}
    </div>
  )
}

// ─── TEAM ─────────────────────────────────────────────────────────────────────
interface TeamMember { id: string; name: string | null; role: string | null; color: string | null; appointments_handled: number }
const initials = (name: string | null) => (name ?? '?').split(' ').map((p) => p[0]).slice(0, 2).join('').toUpperCase()
export function TeamTab({ project }: { project: ProjectLite }) {
  const qc = useQueryClient()
  const [addOpen, setAddOpen] = useState(false)
  // Read from the shared cases cache (populated by CasesTab or DashboardPage).
  // staleTime matches STALE so no extra request is fired if data is fresh.
  const { data: allCases = [] } = useQuery({
    queryKey: ['cases'],
    queryFn: () => apiFetch<CaseListRow[]>('/api/cases'),
    staleTime: STALE,
  })
  const hasNoCases = allCases.filter((c) => c.project_id === project.id).length === 0
  const { data: team = [] } = useQuery({
    queryKey: ['project-employees', project.id],
    queryFn: () => apiFetch<TeamMember[]>(`/api/projects/${project.id}/employees`),
    staleTime: STALE,
  })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['project-employees', project.id] })
    qc.invalidateQueries({ queryKey: ['project', project.id] })
  }
  const remove = useMutation({
    mutationFn: (empId: string) => apiFetch(`/api/projects/${project.id}/employees/${empId}`, { method: 'DELETE' }),
    onSuccess: refresh,
  })
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button
          onClick={() => { if (!hasNoCases) setAddOpen(true) }}
          disabled={hasNoCases}
          title={hasNoCases ? 'Zuerst einen Vorgang zum Projekt hinzufügen' : undefined}
          className="inline-flex items-center gap-1.5 rounded-md bg-green-primary px-3 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Plus size={14} /> Mitarbeiter hinzufügen
        </button>
      </div>
      {hasNoCases && (
        <div className="rounded-xl border border-border bg-alt px-4 py-3 text-sm text-muted">
          Fügen Sie dem Projekt zuerst einen Vorgang hinzu, um Mitarbeiter zuzuweisen.
        </div>
      )}
      {team.length ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {team.map((m) => (
            <div key={m.id} className="flex items-center gap-3 rounded-xl border border-border bg-surface p-4">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-sm font-bold text-white" style={{ background: m.color || '#2D6B3D' }}>{initials(m.name)}</div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold text-text">{m.name ?? '—'}</div>
                <div className="text-xs text-muted">{m.role || 'Mitarbeiter'} · {m.appointments_handled} Termine übernommen</div>
              </div>
              <button title="Entfernen" onClick={() => { if (confirm('Mitarbeiter aus Projekt entfernen?')) remove.mutate(m.id) }} className="rounded-md p-1.5 text-muted hover:bg-alt hover:text-error"><X size={15} /></button>
            </div>
          ))}
        </div>
      ) : (
        !hasNoCases && <EmptyState>Noch keine Mitarbeiter zugewiesen.</EmptyState>
      )}
      {addOpen && <AddEmployeeModal project={project} existing={team.map((t) => t.id)} onClose={() => setAddOpen(false)} onSaved={() => { setAddOpen(false); refresh() }} />}
    </div>
  )
}

function AddEmployeeModal({ project, existing, onClose, onSaved }: { project: ProjectLite; existing: string[]; onClose: () => void; onSaved: () => void }) {
  const [q, setQ] = useState('')
  const { data: employees = [] } = useQuery({ queryKey: ['employees'], queryFn: () => apiFetch<{ id: string; display_name: string }[]>('/api/employees') })
  const add = useMutation({
    mutationFn: (empId: string) => apiFetch(`/api/projects/${project.id}/employees`, { method: 'POST', body: JSON.stringify({ employee_id: empId }) }),
    onSuccess: onSaved,
  })
  const available = employees.filter((e) => !existing.includes(e.id) && (e.display_name ?? '').toLowerCase().includes(q.toLowerCase()))
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Mitarbeiter hinzufügen">
      <input type="search" name="project-employee-search" autoComplete="off" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Mitarbeiter suchen…" className={cn(inputCls, 'mb-3')} />
      <div className="space-y-2">
        {available.map((e) => (
          <button key={e.id} onClick={() => add.mutate(e.id)} className="flex w-full items-center gap-3 rounded-lg border border-border p-3 text-left hover:bg-alt">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-green-primary text-xs font-bold text-white">{initials(e.display_name)}</div>
            <span className="flex-1 text-sm text-text">{e.display_name}</span>
            <Plus size={15} className="text-green-deep" />
          </button>
        ))}
        {!available.length && <p className="py-6 text-center text-sm text-muted">Keine Mitarbeiter verfügbar.</p>}
      </div>
    </Modal>
  )
}

// ─── DOKUMENTE ────────────────────────────────────────────────────────────────
interface Doc { id: string; name: string | null; category: string | null; is_image: boolean; uploaded_at: string; size_bytes: number | null; url: string | null; uploaded_by_name?: string | null }
const fmtSize = (b: number | null) => (b == null ? '' : b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.round(b / 1024)} KB`)
export function DocumentsTab({ project }: { project: ProjectLite }) {
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const { data: docs = [] } = useQuery({
    queryKey: ['project-documents', project.id],
    queryFn: () => apiFetch<Doc[]>(`/api/projects/${project.id}/documents`),
    staleTime: STALE,
  })
  async function upload(files: FileList | null) {
    if (!files?.length) return
    setUploading(true)
    try {
      for (const f of Array.from(files)) {
        const fd = new FormData()
        fd.append('file', f)
        fd.append('category', f.type.startsWith('image/') ? 'Foto' : 'Dokument')
        await apiUpload(`/api/projects/${project.id}/documents`, fd)
      }
      qc.invalidateQueries({ queryKey: ['project-documents', project.id] })
      qc.invalidateQueries({ queryKey: ['project', project.id] })
    } finally { setUploading(false) }
  }
  const photos = docs.filter((d) => d.is_image)
  const files = docs.filter((d) => !d.is_image)
  const groups = files.reduce<Record<string, Doc[]>>((acc, d) => { (acc[d.category || 'Sonstige'] ??= []).push(d); return acc }, {})
  return (
    <div className="space-y-5">
      <div
        onClick={() => fileRef.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); upload(e.dataTransfer.files) }}
        className="cursor-pointer rounded-xl border-2 border-dashed border-border p-8 text-center hover:bg-alt"
      >
        <Upload size={24} className="mx-auto mb-2 text-faint" />
        <div className="text-sm text-body">{uploading ? 'Lädt hoch…' : 'Datei hierher ziehen oder klicken.'}</div>
        <div className="text-xs text-faint">JPG, PNG, GIF oder PDF (max. 10MB)</div>
        <input ref={fileRef} type="file" multiple accept="image/*,application/pdf" className="hidden" onChange={(e) => upload(e.target.files)} />
      </div>

      {Object.entries(groups).map(([cat, list]) => (
        <div key={cat}>
          <div className="mb-2 text-xs font-bold uppercase tracking-wide text-muted">{cat}</div>
          <div className="divide-y divide-border-faint rounded-xl border border-border bg-surface">
            {list.map((d) => (
              <div key={d.id} className="flex items-center gap-3 px-4 py-3">
                <FileText size={16} className="text-warning" />
                <div className="min-w-0 flex-1"><div className="truncate text-sm font-medium text-text">{d.name}</div><div className="text-xs text-muted">{fmtSize(d.size_bytes)} · {fmtDate(d.uploaded_at)}{d.uploaded_by_name ? ` · ${d.uploaded_by_name}` : ''}</div></div>
                {d.url && <a href={d.url} target="_blank" rel="noreferrer" className="rounded-md p-1.5 text-muted hover:bg-alt"><Download size={15} /></a>}
              </div>
            ))}
          </div>
        </div>
      ))}

      {photos.length > 0 && (
        <div>
          <div className="mb-2 text-xs font-bold uppercase tracking-wide text-muted">Fotos</div>
          <div className="grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-6">
            {photos.map((p) => (
              <a key={p.id} href={p.url ?? '#'} target="_blank" rel="noreferrer" title={p.uploaded_by_name ?? p.name ?? ''}>
                <img src={p.url ?? ''} alt={p.name ?? ''} className="aspect-square w-full rounded-lg border border-border object-cover" />
                {/* Who fed this photo in (e.g. "Techniker: Tobi") — item 6 polish. */}
                {p.uploaded_by_name && (
                  <div className="mt-0.5 truncate text-[10px] font-medium text-muted">{p.uploaded_by_name}</div>
                )}
              </a>
            ))}
          </div>
        </div>
      )}

      {!docs.length && <EmptyState>Noch keine Dokumente — zieh Dateien in das Feld oben.</EmptyState>}
    </div>
  )
}

// ─── NOTIZEN ──────────────────────────────────────────────────────────────────
export function NotesTab({ project }: { project: ProjectLite }) {
  const qc = useQueryClient()
  const [notes, setNotes] = useState(project.internal_notes ?? '')
  const [lastSaved, setLastSaved] = useState<Date | null>(project.notes_updated_at ? new Date(project.notes_updated_at) : null)
  const [history, setHistory] = useState<{ at: Date; text: string }[]>([])
  const [showHistory, setShowHistory] = useState(false)
  const savedRef = useRef(project.internal_notes ?? '')

  const save = useMutation({
    mutationFn: () => apiFetch(`/api/projects/${project.id}`, { method: 'PATCH', body: JSON.stringify({ internal_notes: notes }) }),
    onSuccess: () => {
      const now = new Date()
      setLastSaved(now)
      setHistory((h) => [{ at: now, text: notes }, ...h].slice(0, 5))
      savedRef.current = notes
      qc.invalidateQueries({ queryKey: ['project', project.id] })
    },
  })
  const onBlur = () => { if (notes !== savedRef.current) save.mutate() }
  const agoMin = lastSaved ? Math.round((Date.now() - lastSaved.getTime()) / 60000) : null

  return (
    <div className="mx-auto max-w-3xl space-y-2">
      <textarea
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        onBlur={onBlur}
        placeholder="Interne Projektnotizen (nicht für den Kunden sichtbar)…"
        className="min-h-[400px] w-full rounded-xl border border-border bg-surface p-4 text-sm text-text outline-none focus:border-green-primary"
      />
      <div className="flex items-center justify-between text-xs text-muted">
        <span>{save.isPending ? 'Speichert…' : lastSaved ? `Zuletzt gespeichert: ${agoMin === 0 ? 'gerade eben' : `vor ${agoMin} Min`}` : 'Noch nicht gespeichert'}</span>
        <span>{notes.length} Zeichen</span>
      </div>
      {history.length > 0 && (
        <div>
          <button onClick={() => setShowHistory((s) => !s)} className="text-xs font-medium text-green-deep hover:underline">Verlauf {showHistory ? 'ausblenden' : 'anzeigen'} ({history.length})</button>
          {showHistory && (
            <div className="mt-2 space-y-2">
              {history.map((h, i) => (
                <div key={i} className="rounded-lg border border-border bg-alt p-3 text-xs">
                  <div className="mb-1 font-medium text-muted">{fmtDateTime(h.at.toISOString())}</div>
                  <div className="line-clamp-2 text-body">{h.text.slice(0, 100) || '(leer)'}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
