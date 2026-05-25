import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Ban,
  CheckCircle2,
  ChevronDown,
  Copy,
  Download,
  Eye,
  Mail,
  Pencil,
  Receipt,
  Search,
  Trash2,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Modal } from '../components/ui/Modal'
import { apiBlobUrl, apiFetch } from '../lib/api'
import { cn } from '../lib/utils'

interface Invoice {
  id: string
  number: string | null
  status: string
  subject: string | null
  customer_id: string | null
  customer_name: string | null
  customer_email: string | null
  invoice_date: string | null
  due_date: string | null
  total: number | null
  sent_at: string | null
  paid_at: string | null
  created_at: string
}
interface CustomerOption {
  id: string
  full_name: string | null
}

const STATUS_META: Record<string, { label: string; cls: string }> = {
  draft: { label: 'Entwurf', cls: 'bg-alt text-muted' },
  sent: { label: 'Gesendet', cls: 'bg-info-bg text-info' },
  paid: { label: 'Bezahlt', cls: 'bg-success-bg text-success' },
  overdue: { label: 'Überfällig', cls: 'bg-warning-bg text-warning' },
  cancelled: { label: 'Storniert', cls: 'bg-error-bg text-error' },
}

const money = (n: number | null) =>
  '€' + (n ?? 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const fmtDate = (d: string | null) =>
  d ? new Date(d).toLocaleDateString('de-DE', { day: 'numeric', month: 'short', year: 'numeric' }) : '—'

export function InvoicesPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [num, setNum] = useState('')
  const [customer, setCustomer] = useState('')
  const [status, setStatus] = useState('all')
  const [year, setYear] = useState(String(new Date().getFullYear()))
  const [sendFor, setSendFor] = useState<Invoice | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const flash = (m: string) => {
    setToast(m)
    setTimeout(() => setToast(null), 4000)
  }

  const { data: invoices = [] } = useQuery({
    queryKey: ['invoices'],
    queryFn: () => apiFetch<Invoice[]>('/api/invoices'),
  })
  const { data: customerData } = useQuery({
    queryKey: ['customers-options'],
    queryFn: () => apiFetch<{ customers: CustomerOption[] }>('/api/customers?limit=500'),
  })
  const customers = customerData?.customers ?? []

  const yearOf = (inv: Invoice) => new Date(inv.invoice_date || inv.created_at).getFullYear()
  const years = Array.from(new Set([new Date().getFullYear(), ...invoices.map(yearOf)])).sort((a, b) => b - a)

  // Base set = everything except the status filter (so the Overview by-status is stable).
  const base = invoices.filter(
    (inv) =>
      (!num || inv.number?.toLowerCase().includes(num.toLowerCase())) &&
      (!customer || inv.customer_id === customer) &&
      (year === 'all' || yearOf(inv) === Number(year)),
  )
  const filtered = base.filter((inv) => status === 'all' || inv.status === status)
  const sum = (pred: (i: Invoice) => boolean) =>
    base.filter(pred).reduce((s, i) => s + (i.total ?? 0), 0)

  const openPdf = async (id: string, download: boolean) => {
    try {
      const url = await apiBlobUrl(`/api/invoices/${id}/pdf${download ? '' : '?preview=true'}`)
      if (download) {
        const a = document.createElement('a')
        a.href = url
        a.download = `${id}.pdf`
        a.click()
      } else {
        window.open(url, '_blank')
      }
    } catch {
      flash('PDF konnte nicht geladen werden.')
    }
  }

  const act = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) => {
      if (action === 'duplicate') return apiFetch(`/api/invoices/${id}/duplicate`, { method: 'POST' })
      if (action === 'delete') return apiFetch(`/api/invoices/${id}`, { method: 'DELETE' })
      return apiFetch(`/api/invoices/${id}/status`, {
        method: 'PATCH',
        body: JSON.stringify({ status: action }),
      })
    },
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: ['invoices'] })
      flash(
        {
          duplicate: 'Dupliziert.',
          delete: 'Gelöscht.',
          paid: 'Als bezahlt markiert.',
          cancelled: 'Storniert.',
          sent: 'Als gesendet markiert.',
          draft: 'Auf Entwurf gesetzt.',
        }[v.action] ?? 'Aktualisiert.',
      )
    },
    onError: (e: Error) => flash(e.message),
  })

  return (
    <div className="p-8">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <Receipt size={26} className="text-green-primary" />
          <div>
            <h1 className="text-2xl font-bold text-text">Rechnungen</h1>
            <p className="mt-0.5 text-sm text-muted">{invoices.length} Rechnungen</p>
          </div>
        </div>
        <button
          onClick={() => navigate('/invoices/new')}
          className="inline-flex items-center gap-2 rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110"
        >
          + Neue Rechnung
        </button>
      </div>

      {/* Filter */}
      <div className="mb-4 rounded-xl border border-border bg-surface p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-body">Filter</div>
        <div className="grid gap-3 md:grid-cols-4">
          <div>
            <div className="mb-1 text-xs font-medium text-muted">Rechnungsnummer</div>
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
              <input
                value={num}
                onChange={(e) => setNum(e.target.value)}
                placeholder="z.B. RE-2026-00001"
                className="w-full rounded-md border border-border bg-alt py-2 pl-9 pr-10 text-sm text-text outline-none focus:border-green-primary"
              />
              {num && (
                <button
                  title="Zurücksetzen"
                  onClick={() => setNum('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded bg-error p-1 text-white hover:brightness-110"
                >
                  <X size={12} />
                </button>
              )}
            </div>
          </div>
          <div>
            <div className="mb-1 text-xs font-medium text-muted">Kunde</div>
            <select value={customer} onChange={(e) => setCustomer(e.target.value)} className={selectCls}>
              <option value="">Alle Kunden</option>
              {customers.map((c) => <option key={c.id} value={c.id}>{c.full_name ?? 'Unbenannt'}</option>)}
            </select>
          </div>
          <div>
            <div className="mb-1 text-xs font-medium text-muted">Status</div>
            <select value={status} onChange={(e) => setStatus(e.target.value)} className={selectCls}>
              <option value="all">Alle Status</option>
              <option value="draft">Entwurf</option>
              <option value="sent">Gesendet</option>
              <option value="paid">Bezahlt</option>
              <option value="overdue">Überfällig</option>
              <option value="cancelled">Storniert</option>
            </select>
          </div>
          <div>
            <div className="mb-1 text-xs font-medium text-muted">Jahr</div>
            <select value={year} onChange={(e) => setYear(e.target.value)} className={selectCls}>
              <option value="all">Alle Jahre</option>
              {years.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>
        </div>
      </div>

      {/* Overview */}
      <div className="mb-4 rounded-xl border border-border bg-surface p-5">
        <div className="mb-3 text-sm font-bold text-text">Übersicht</div>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <Stat label="Entwürfe" value={money(sum((i) => i.status === 'draft'))} cls="text-text" />
          <Stat label="Offen" value={money(sum((i) => i.status === 'sent' || i.status === 'overdue'))} cls="text-info" />
          <Stat label="Bezahlt" value={money(sum((i) => i.status === 'paid'))} cls="text-success" />
          <Stat label="Storniert" value={money(sum((i) => i.status === 'cancelled'))} cls="text-error" />
        </div>
      </div>

      {toast && <div className="mb-3 rounded-md bg-green-tint-50 px-3 py-2 text-sm font-medium text-green-deep">{toast}</div>}

      {/* Table */}
      <div className="overflow-x-auto rounded-xl border border-border bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs font-semibold uppercase tracking-wide text-muted">
              <th className="px-4 py-3">Rechnungs-Nr.</th>
              <th className="px-4 py-3">Kunde</th>
              <th className="px-4 py-3">Datum</th>
              <th className="px-4 py-3">Fällig am</th>
              <th className="px-4 py-3 text-right">Betrag</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Aktionen</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((inv) => {
              const isDraft = inv.status === 'draft'
              const isOverdue = inv.status === 'overdue'
              const canSend = inv.status === 'draft' || inv.status === 'sent'
              const canPay = inv.status === 'sent' || inv.status === 'overdue'
              const canCancel = inv.status !== 'paid' && inv.status !== 'cancelled'
              return (
                <tr
                  key={inv.id}
                  className="cursor-pointer border-b border-border-faint last:border-0 hover:bg-alt/40"
                  onClick={() => navigate(`/invoices/${inv.id}`)}
                >
                  <td className="px-4 py-3 font-semibold text-text">{inv.number}</td>
                  <td className="px-4 py-3">
                    {inv.customer_id ? (
                      <button
                        onClick={(ev) => { ev.stopPropagation(); navigate(`/customers/${inv.customer_id}`) }}
                        className="text-green-deep hover:underline"
                      >
                        {inv.customer_name ?? '—'}
                      </button>
                    ) : <span className="text-muted">—</span>}
                  </td>
                  <td className="px-4 py-3 text-muted">{fmtDate(inv.invoice_date)}</td>
                  <td className={cn('px-4 py-3', isOverdue ? 'font-semibold text-error' : 'text-muted')}>{fmtDate(inv.due_date)}</td>
                  <td className="px-4 py-3 text-right font-semibold text-text">{money(inv.total)}</td>
                  <td className="px-4 py-3" onClick={(ev) => ev.stopPropagation()}>
                    <StatusSelect inv={inv} onChange={(s) => act.mutate({ id: inv.id, action: s })} />
                  </td>
                  <td className="px-4 py-3" onClick={(ev) => ev.stopPropagation()}>
                    <div className="flex items-center justify-end gap-0.5 text-muted">
                      <Icon title="Vorschau" onClick={() => openPdf(inv.id, false)}><Eye size={15} /></Icon>
                      <Icon title="PDF herunterladen" onClick={() => openPdf(inv.id, true)}><Download size={15} /></Icon>
                      {canSend && <Icon title="Per E-Mail senden" cls="text-info" onClick={() => setSendFor(inv)}><Mail size={15} /></Icon>}
                      <Icon title="Duplizieren" cls="text-ai" onClick={() => act.mutate({ id: inv.id, action: 'duplicate' })}><Copy size={15} /></Icon>
                      {canPay && <Icon title="Als bezahlt markieren" cls="text-success" onClick={() => act.mutate({ id: inv.id, action: 'paid' })}><CheckCircle2 size={15} /></Icon>}
                      {canCancel && <Icon title="Stornieren" cls="text-error" onClick={() => confirm(`${inv.number} stornieren?`) && act.mutate({ id: inv.id, action: 'cancelled' })}><Ban size={15} /></Icon>}
                      {isDraft && <Icon title="Bearbeiten" cls="text-warning" onClick={() => navigate(`/invoices/${inv.id}`)}><Pencil size={15} /></Icon>}
                      {isDraft && <Icon title="Löschen" cls="text-error" onClick={() => confirm(`${inv.number} löschen?`) && act.mutate({ id: inv.id, action: 'delete' })}><Trash2 size={15} /></Icon>}
                    </div>
                  </td>
                </tr>
              )
            })}
            {!filtered.length && (
              <tr><td colSpan={7} className="px-4 py-12 text-center text-muted">Keine Rechnungen.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {sendFor && (
        <SendModal
          invoice={sendFor}
          onClose={() => setSendFor(null)}
          onSent={() => {
            qc.invalidateQueries({ queryKey: ['invoices'] })
            flash(`${sendFor.number} als gesendet markiert.`)
            setSendFor(null)
          }}
        />
      )}
    </div>
  )
}

function StatusSelect({ inv, onChange }: { inv: Invoice; onChange: (s: string) => void }) {
  const sm = STATUS_META[inv.status] ?? STATUS_META.draft
  return (
    <div className="relative inline-block">
      <select
        value={inv.status}
        onChange={(e) => onChange(e.target.value)}
        className={cn('cursor-pointer appearance-none rounded-full py-1 pl-2.5 pr-6 text-xs font-medium outline-none', sm.cls)}
      >
        {inv.status === 'overdue' && <option value="overdue">Überfällig</option>}
        <option value="draft">Entwurf</option>
        <option value="sent">Gesendet</option>
        <option value="paid">Bezahlt</option>
        <option value="cancelled">Storniert</option>
      </select>
      <ChevronDown size={12} className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 opacity-60" />
    </div>
  )
}

function SendModal({ invoice, onClose, onSent }: { invoice: Invoice; onClose: () => void; onSent: () => void }) {
  const [to, setTo] = useState(invoice.customer_email ?? '')
  const [subject, setSubject] = useState(`Ihre Rechnung ${invoice.number ?? ''}`)
  const [message, setMessage] = useState(
    `Sehr geehrte/r ${invoice.customer_name ?? 'Damen und Herren'},\n\n` +
      `anbei erhalten Sie Ihre Rechnung ${invoice.number ?? ''} über ${money(invoice.total)}, ` +
      `fällig am ${fmtDate(invoice.due_date)}.\n\nMit freundlichen Grüßen`,
  )
  const [copyToMe, setCopyToMe] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const send = useMutation({
    mutationFn: () =>
      apiFetch(`/api/invoices/${invoice.id}/send`, {
        method: 'POST',
        body: JSON.stringify({ to, subject, message, copy_to_me: copyToMe }),
      }),
    onSuccess: onSent,
    onError: () => setError('Senden fehlgeschlagen.'),
  })

  const ta = 'w-full rounded-md border border-border bg-alt px-3 py-2 text-sm text-text outline-none focus:border-green-primary'
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title="Rechnung senden"
      widthClass="max-w-lg"
      footer={
        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body">Abbrechen</button>
          <button disabled={!to || send.isPending} onClick={() => send.mutate()} className="inline-flex flex-1 items-center justify-center gap-2 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">
            <Mail size={15} /> {send.isPending ? 'Sendet…' : 'Senden'}
          </button>
        </div>
      }
    >
      <div className="space-y-3">
        {error && <div className="rounded-md bg-error-bg px-3 py-2 text-sm text-error">{error}</div>}
        <div><div className="mb-1 text-xs font-semibold text-body">An</div><input value={to} onChange={(e) => setTo(e.target.value)} placeholder="kunde@example.de" className={ta} /></div>
        <div><div className="mb-1 text-xs font-semibold text-body">Betreff</div><input value={subject} onChange={(e) => setSubject(e.target.value)} className={ta} /></div>
        <div><div className="mb-1 text-xs font-semibold text-body">Nachricht</div><textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={6} className={ta} /></div>
        <label className="flex items-center gap-2 text-sm text-muted"><input type="checkbox" checked disabled className="h-4 w-4 accent-green-primary" /> PDF anhängen</label>
        <label className="flex items-center gap-2 text-sm text-text"><input type="checkbox" checked={copyToMe} onChange={(e) => setCopyToMe(e.target.checked)} className="h-4 w-4 accent-green-primary" /> Kopie an mich senden</label>
        <p className="rounded-md bg-info-bg px-3 py-2 text-xs text-info">Hinweis: E-Mail-Versand (SMTP) ist noch nicht konfiguriert — die Rechnung wird als „Gesendet" markiert.</p>
      </div>
    </Modal>
  )
}

const selectCls = 'w-full rounded-md border border-border bg-alt px-3 py-2 text-sm text-text outline-none focus:border-green-primary'

function Stat({ label, value, cls }: { label: string; value: string; cls: string }) {
  return (
    <div>
      <div className="text-xs text-muted">{label}</div>
      <div className={cn('mt-1 text-xl font-bold', cls)}>{value}</div>
    </div>
  )
}

function Icon({ children, title, onClick, cls }: { children: React.ReactNode; title: string; onClick: () => void; cls?: string }) {
  return (
    <button title={title} onClick={onClick} className={cn('rounded-md p-1.5 hover:bg-alt', cls)}>
      {children}
    </button>
  )
}
