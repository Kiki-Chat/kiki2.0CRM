import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CheckCircle2,
  ClipboardList,
  Copy,
  Download,
  Eye,
  FileText,
  Mail,
  Pencil,
  Search,
  Trash2,
} from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Modal } from '../components/ui/Modal'
import { apiBlobUrl, apiFetch } from '../lib/api'
import { useMe } from '../lib/useMe'
import { useToast } from '../lib/useToast'
import { cn } from '../lib/utils'

interface Estimate {
  id: string
  number: string | null
  type: string
  status: string
  subject: string | null
  customer_id: string | null
  customer_name: string | null
  customer_email: string | null
  inquiry_title: string | null
  is_binding: boolean
  valid_until: string | null
  total: number | null
  sent_at: string | null
  created_at: string
}
interface CustomerOption {
  id: string
  full_name: string | null
}

const STATUS_META: Record<string, { label: string; cls: string }> = {
  draft: { label: 'Entwurf', cls: 'bg-alt text-muted' },
  sent: { label: 'Gesendet', cls: 'bg-info-bg text-info' },
  accepted: { label: 'Akzeptiert', cls: 'bg-success-bg text-success' },
  rejected: { label: 'Abgelehnt', cls: 'bg-error-bg text-error' },
  invoiced: { label: 'Abgerechnet', cls: 'bg-ai-bg text-ai' },
}
const TYPE_LABEL: Record<string, string> = { kva: 'Angebot', offer: 'Angebot', order_confirmation: 'Auftragsbest.', invoice: 'Rechnung' }

const money = (n: number | null) =>
  '€' + (n ?? 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const fmtDate = (d: string | null) =>
  d ? new Date(d).toLocaleDateString('de-DE', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Europe/Berlin' }) : '—'

export function CostEstimatesPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { isAdmin } = useMe()
  const [num, setNum] = useState('')
  const [customer, setCustomer] = useState('')
  const [status, setStatus] = useState('all')
  const [type, setType] = useState('all')
  const [sendFor, setSendFor] = useState<Estimate | null>(null)
  const { toast, flash } = useToast()

  const { data: estimates = [] } = useQuery({
    queryKey: ['cost-estimates'],
    queryFn: () => apiFetch<Estimate[]>('/api/cost-estimates'),
  })
  const { data: customerData } = useQuery({
    queryKey: ['customers-options'],
    queryFn: () => apiFetch<{ customers: CustomerOption[] }>('/api/customers?limit=500'),
  })
  const customers = customerData?.customers ?? []

  const filtered = estimates.filter(
    (e) =>
      (!num || e.number?.toLowerCase().includes(num.toLowerCase())) &&
      (!customer || e.customer_id === customer) &&
      (status === 'all' || e.status === status) &&
      (type === 'all' || e.type === type),
  )

  const sum = (pred: (e: Estimate) => boolean) =>
    estimates.filter(pred).reduce((s, e) => s + (e.total ?? 0), 0)

  const openPdf = async (id: string, download: boolean) => {
    try {
      const url = await apiBlobUrl(`/api/cost-estimates/${id}/pdf${download ? '' : '?preview=true'}`)
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
      if (action === 'duplicate') return apiFetch(`/api/cost-estimates/${id}/duplicate`, { method: 'POST' })
      if (action === 'delete') return apiFetch(`/api/cost-estimates/${id}`, { method: 'DELETE' })
      return apiFetch(`/api/cost-estimates/${id}/status`, {
        method: 'PATCH',
        body: JSON.stringify({ status: action }),
      })
    },
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: ['cost-estimates'] })
      flash(
        { duplicate: 'Dupliziert.', delete: 'Gelöscht.', accepted: 'Als akzeptiert markiert.', invoiced: 'In Rechnung umgewandelt.' }[
          v.action
        ] ?? 'Aktualisiert.',
      )
    },
    onError: (e: Error) => flash(e.message),
  })

  return (
    <div className="p-8">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <ClipboardList size={26} className="text-green-primary" />
          <div>
            <h1 className="text-2xl font-bold text-text">Angebote</h1>
            <p className="mt-0.5 text-sm text-muted">{estimates.length} Angebote</p>
          </div>
        </div>
        {isAdmin && (
          <button
            onClick={() => navigate('/cost-estimates/new')}
            className="inline-flex items-center gap-2 rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110"
          >
            + Neuer Angebot
          </button>
        )}
      </div>

      {/* Filter */}
      <div className="mb-4 rounded-xl border border-border bg-surface p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-body">Filter</div>
        <div className="grid gap-3 md:grid-cols-4">
          <div>
            <div className="mb-1 text-xs font-medium text-muted">Angebotsnummer</div>
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
              <input value={num} onChange={(e) => setNum(e.target.value)} placeholder="z.B. AG-2026-00001" className="w-full rounded-md border border-border bg-alt py-2 pl-9 pr-3 text-sm text-text outline-none focus:border-green-primary" />
            </div>
          </div>
          <div>
            <div className="mb-1 text-xs font-medium text-muted">Kontakt</div>
            <select value={customer} onChange={(e) => setCustomer(e.target.value)} className={selectCls}>
              <option value="">Alle Kontakte</option>
              {customers.map((c) => <option key={c.id} value={c.id}>{c.full_name ?? 'Unbenannt'}</option>)}
            </select>
          </div>
          <div>
            <div className="mb-1 text-xs font-medium text-muted">Status</div>
            <select value={status} onChange={(e) => setStatus(e.target.value)} className={selectCls}>
              <option value="all">Alle Status</option>
              <option value="draft">Entwurf</option>
              <option value="sent">Gesendet</option>
              <option value="accepted">Akzeptiert</option>
              <option value="rejected">Abgelehnt</option>
              <option value="invoiced">Abgerechnet</option>
            </select>
          </div>
          <div>
            <div className="mb-1 text-xs font-medium text-muted">Typ</div>
            <select value={type} onChange={(e) => setType(e.target.value)} className={selectCls}>
              <option value="all">Alle Typen</option>
              <option value="kva">Angebot</option>
              <option value="offer">Angebot</option>
              <option value="invoice">Rechnung</option>
            </select>
          </div>
        </div>
      </div>

      {/* Summary */}
      <div className="mb-4 grid grid-cols-3 gap-4 rounded-xl border border-border bg-surface p-5">
        <div>
          <div className="text-xs text-muted">Gesamt</div>
          <div className="mt-1 text-xl font-bold text-text">{money(sum(() => true))}</div>
        </div>
        <div>
          <div className="text-xs text-muted">Entwürfe</div>
          <div className="mt-1 text-xl font-bold text-text">{money(sum((e) => e.status === 'draft'))}</div>
        </div>
        <div>
          <div className="text-xs text-muted">Gesendet</div>
          <div className="mt-1 text-xl font-bold text-info">{money(sum((e) => e.status === 'sent'))}</div>
        </div>
      </div>

      {toast && <div className="mb-3 rounded-md bg-green-tint-50 px-3 py-2 text-sm font-medium text-green-deep">{toast}</div>}

      {/* Table */}
      <div className="overflow-x-auto rounded-xl border border-border bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs font-semibold uppercase tracking-wide text-muted">
              <th className="px-4 py-3">Nr.</th>
              <th className="hidden px-4 py-3 md:table-cell">Typ</th>
              <th className="px-4 py-3">Kunde</th>
              <th className="hidden px-4 py-3 md:table-cell">Anfrage</th>
              <th className="hidden px-4 py-3 md:table-cell">Datum</th>
              <th className="hidden px-4 py-3 md:table-cell">Gültig bis</th>
              <th className="px-4 py-3 text-right">Betrag</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Aktionen</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((e) => {
              const sm = STATUS_META[e.status] ?? STATUS_META.draft
              const isDraft = e.status === 'draft'
              return (
                <tr key={e.id} className="cursor-pointer border-b border-border-faint last:border-0 hover:bg-alt/40" onClick={() => navigate(`/cost-estimates/${e.id}`)}>
                  <td className="px-4 py-3 font-semibold text-text">{e.number}</td>
                  <td className="hidden px-4 py-3 md:table-cell">
                    <span className="rounded bg-alt px-2 py-0.5 text-xs font-medium text-body">{TYPE_LABEL[e.type] ?? e.type}</span>
                    {e.type === 'kva' && <div className="mt-0.5 text-[10px] text-muted">{e.is_binding ? 'verbindlich' : 'unverbindlich'}</div>}
                  </td>
                  <td className="px-4 py-3">
                    {e.customer_id ? (
                      <button onClick={(ev) => { ev.stopPropagation(); navigate(`/customers/${e.customer_id}`) }} className="text-green-deep hover:underline">
                        {e.customer_name ?? '—'}
                      </button>
                    ) : <span className="text-muted">—</span>}
                  </td>
                  <td className="hidden max-w-[220px] truncate px-4 py-3 text-body md:table-cell">{e.subject || e.inquiry_title || '—'}</td>
                  <td className="hidden px-4 py-3 text-muted md:table-cell">{fmtDate(e.created_at)}</td>
                  <td className="hidden px-4 py-3 text-muted md:table-cell">{fmtDate(e.valid_until)}</td>
                  <td className="px-4 py-3 text-right font-semibold text-text">{money(e.total)}</td>
                  <td className="px-4 py-3">
                    <span className={cn('rounded-full px-2.5 py-0.5 text-xs font-medium', sm.cls)}>{sm.label}</span>
                    {e.status === 'sent' && e.sent_at && <div className="mt-0.5 text-[10px] text-muted">{fmtDate(e.sent_at)}</div>}
                  </td>
                  <td className="px-4 py-3" onClick={(ev) => ev.stopPropagation()}>
                    <div className="flex items-center justify-end gap-0.5 text-muted">
                      <Icon title="Vorschau" onClick={() => openPdf(e.id, false)}><Eye size={15} /></Icon>
                      <Icon title="PDF herunterladen" onClick={() => openPdf(e.id, true)}><Download size={15} /></Icon>
                      {/* Mutations are admin-only on the backend — hidden for employees. */}
                      {isAdmin && <>
                        {isDraft && <Icon title="Bearbeiten" cls="text-warning" onClick={() => navigate(`/cost-estimates/${e.id}`)}><Pencil size={15} /></Icon>}
                        <Icon title="Per E-Mail senden" cls="text-info" onClick={() => setSendFor(e)}><Mail size={15} /></Icon>
                        <Icon title="Duplizieren" cls="text-ai" onClick={() => act.mutate({ id: e.id, action: 'duplicate' })}><Copy size={15} /></Icon>
                        {e.status !== 'accepted' && <Icon title="Als akzeptiert markieren" cls="text-success" onClick={() => act.mutate({ id: e.id, action: 'accepted' })}><CheckCircle2 size={15} /></Icon>}
                        <Icon title="In Rechnung umwandeln" cls="text-green-deep" onClick={() => navigate(`/invoices/new?kva_id=${e.id}`)}><FileText size={15} /></Icon>
                        {isDraft && <Icon title="Löschen" cls="text-error" onClick={() => confirm(`${e.number} löschen?`) && act.mutate({ id: e.id, action: 'delete' })}><Trash2 size={15} /></Icon>}
                      </>}
                    </div>
                  </td>
                </tr>
              )
            })}
            {!filtered.length && (
              <tr><td colSpan={9} className="px-4 py-12 text-center text-muted">Keine Angebote.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {sendFor && (
        <SendModal
          estimate={sendFor}
          onClose={() => setSendFor(null)}
          onSent={() => {
            qc.invalidateQueries({ queryKey: ['cost-estimates'] })
            flash(`${sendFor.number} als gesendet markiert.`)
            setSendFor(null)
          }}
        />
      )}
    </div>
  )
}

function SendModal({ estimate, onClose, onSent }: { estimate: Estimate; onClose: () => void; onSent: () => void }) {
  const [to, setTo] = useState(estimate.customer_email ?? '')
  const [subject, setSubject] = useState(`Ihr Angebot ${estimate.number ?? ''}`)
  const [message, setMessage] = useState(
    `Sehr geehrte Damen und Herren,\n\nanbei erhältst du unser Angebot ${estimate.number ?? ''}. ` +
      `Bei Fragen stehen wir Ihnen gerne zur Verfügung.\n\nMit freundlichen Grüßen`,
  )
  const [copyToMe, setCopyToMe] = useState(false)
  const [attachPdf, setAttachPdf] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const noCustomerEmail = !estimate.customer_email

  const send = useMutation({
    mutationFn: () =>
      apiFetch(`/api/cost-estimates/${estimate.id}/send`, {
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
      title="Angebot senden"
      widthClass="max-w-lg"
      footer={
        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body">Abbrechen</button>
          <button disabled={!to || send.isPending} onClick={() => send.mutate()} className="flex-1 inline-flex items-center justify-center gap-2 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">
            <Mail size={15} /> {send.isPending ? 'Sendet…' : 'Senden'}
          </button>
        </div>
      }
    >
      <div className="space-y-3">
        {error && <div className="rounded-md bg-error-bg px-3 py-2 text-sm text-error">{error}</div>}
        {noCustomerEmail && (
          <div className="rounded-md bg-warning-bg px-3 py-2 text-xs font-medium text-warning">
            ⚠ Für diesen Kunden ist keine E-Mail hinterlegt. Bitte oben eine Empfänger-Adresse eintragen oder beim Kunden ergänzen — sonst kann nichts versendet werden.
          </div>
        )}
        <div><div className="mb-1 text-xs font-semibold text-body">An</div><input value={to} onChange={(e) => setTo(e.target.value)} placeholder="kunde@firma.de" className={ta} /></div>
        <div><div className="mb-1 text-xs font-semibold text-body">Betreff</div><input value={subject} onChange={(e) => setSubject(e.target.value)} className={ta} /></div>
        <div><div className="mb-1 text-xs font-semibold text-body">Nachricht</div><textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={5} className={ta} /></div>
        <label className="flex items-center gap-2 text-sm text-text"><input type="checkbox" checked={attachPdf} onChange={(e) => setAttachPdf(e.target.checked)} className="h-4 w-4 accent-green-primary" /> PDF anhängen</label>
        <label className="flex items-center gap-2 text-sm text-text"><input type="checkbox" checked={copyToMe} onChange={(e) => setCopyToMe(e.target.checked)} className="h-4 w-4 accent-green-primary" /> Kopie an mich senden</label>
        <p className="rounded-md bg-info-bg px-3 py-2 text-xs text-info">Hinweis: E-Mail-Versand (SMTP) ist noch nicht konfiguriert — das Angebot wird als „Gesendet“ markiert.</p>
      </div>
    </Modal>
  )
}

const selectCls = 'w-full rounded-md border border-border bg-alt px-3 py-2 text-sm text-text outline-none focus:border-green-primary'

function Icon({ children, title, onClick, cls }: { children: React.ReactNode; title: string; onClick: () => void; cls?: string }) {
  return (
    <button title={title} onClick={onClick} className={cn('rounded-md p-1.5 hover:bg-alt', cls)}>
      {children}
    </button>
  )
}
