import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DraggableSyntheticListeners,
} from '@dnd-kit/core'
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Copy, GripVertical, Loader2, Mail, Trash2, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { apiFetch, apiPostBlob } from '../lib/api'
import {
  consumeLiveFill,
  emitLiveFillStatus,
  sleep,
  type LiveFillPayload,
} from '../lib/liveFill'
import { useMe } from '../lib/useMe'
import { cn } from '../lib/utils'

interface Position {
  _id: string
  kind: string
  description: string
  quantity: number
  unit: string
  price: number
  vat: number
  discount_pct: number
  is_labor: boolean
}
interface CustomerOption { id: string; full_name: string | null }
interface CustomerDetail { id: string; full_name: string | null; customer_number: string | null; vat_id: string | null; address?: { street?: string | null; city?: string | null; zip?: string | null } | null }
interface CatalogItem { id: string; name: string; description: string | null; unit_price: number; unit: string | null }
interface Estimate { id: string; number: string | null; subject: string | null; status: string; customer_id: string | null; total: number | null }

const UNITS = ['Stk', 'm', 'm²', 'h', 'Std', 'pauschal', 'kg', 'l', 'Tag']
const VATS = [19, 7, 0]
const PAYMENT_TERMS = [7, 14, 21, 30, 45, 60]
const INVOICE_INTRO = 'Vielen Dank für Ihren Auftrag. Wir berechnen Ihnen wie folgt:'
const INVOICE_CLOSING = 'Bitte überweisen Sie den Betrag innerhalb der Zahlungsfrist auf unser Konto. Vielen Dank!'
const inputCls = 'w-full rounded-md border border-border bg-alt px-3 py-2 text-sm text-text outline-none focus:border-green-primary'
const labelCls = 'mb-1 block text-xs font-semibold text-body'
const uid = () => Math.random().toString(36).slice(2)
const todayIso = () => new Date().toISOString().slice(0, 10)

const newPos = (over: Partial<Position> = {}): Position => ({
  _id: uid(), kind: 'item', description: '', quantity: 1, unit: 'Stk', price: 0, vat: 19, discount_pct: 0, is_labor: false, ...over,
})
const money = (n: number) => '€' + (n || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const lineNet = (p: Position) => (p.quantity || 0) * (p.price || 0) * (1 - (p.discount_pct || 0) / 100)

function calcTotals(positions: Position[], surcharge: number, discountPct: number) {
  const factor = 1 - (discountPct || 0) / 100
  let net = 0, vat = 0
  for (const p of positions) {
    if ((p.kind || 'item') !== 'item') continue
    const ln = lineNet(p)
    net += ln
    vat += ln * (p.vat || 0) / 100
  }
  const N = net * factor + (surcharge || 0)
  const V = vat * factor + (surcharge || 0) * 0.19
  return { net: N, vat: V, gross: N + V }
}

export function InvoiceFormPage() {
  const { isAdmin } = useMe()
  const { id } = useParams()
  const isEdit = !!id
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const qc = useQueryClient()

  const [customerId, setCustomerId] = useState(params.get('customer_id') || '')
  const [kvaId, setKvaId] = useState('')
  const [caseId, setCaseId] = useState(params.get('case_id') || '')
  const [subject, setSubject] = useState('')
  const [reference, setReference] = useState('')
  const [invoiceDate, setInvoiceDate] = useState(todayIso())
  const [performanceDate, setPerformanceDate] = useState(todayIso())
  const [paymentTermsDays, setPaymentTermsDays] = useState(14)
  const [skontoPct, setSkontoPct] = useState(0)
  const [skontoDays, setSkontoDays] = useState(0)
  const [positions, setPositions] = useState<Position[]>([newPos()])
  const [introText, setIntroText] = useState(INVOICE_INTRO)
  const [closingText, setClosingText] = useState(INVOICE_CLOSING)
  const [paymentTermsText, setPaymentTermsText] = useState('')
  const [surcharge, setSurcharge] = useState(0)
  const [surchargeDesc, setSurchargeDesc] = useState('')
  const [discountPct, setDiscountPct] = useState(0)
  const [loadedNumber, setLoadedNumber] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Hydrated customer info shown as read-only block under the customer select
  const [hydratedCustomer, setHydratedCustomer] = useState<CustomerDetail | null>(null)

  const { data: customerData } = useQuery({
    queryKey: ['customers-options'],
    queryFn: () => apiFetch<{ customers: CustomerOption[] }>('/api/customers?limit=500'),
  })
  const customers = customerData?.customers ?? []
  const { data: catalog = [] } = useQuery({ queryKey: ['catalog-active'], queryFn: () => apiFetch<CatalogItem[]>('/api/catalog?status=active') })
  const { data: estimates = [] } = useQuery({ queryKey: ['cost-estimates'], queryFn: () => apiFetch<Estimate[]>('/api/cost-estimates') })
  // KVAs you can turn into an invoice: any of this customer's that aren't rejected
  // (draft/sent/accepted) — not only 'accepted', so the dropdown isn't empty.
  const KVA_STATUS_DE: Record<string, string> = { draft: 'Entwurf', sent: 'Gesendet', accepted: 'Angenommen' }
  const selectableKvas = estimates.filter((e) => e.customer_id === customerId && e.status !== 'rejected')

  // Import positions/subject/customer from a cost estimate (KVA → Rechnung).
  // Copies every field shared with invoices; does NOT overwrite fields the user already edited.
  const importKva = useCallback(async (estimateId: string) => {
    try {
      const ce = await apiFetch<Record<string, unknown>>(`/api/cost-estimates/${estimateId}`)
      setKvaId(estimateId)
      if (ce.customer_id) setCustomerId(ce.customer_id as string)
      if (ce.subject) setSubject(ce.subject as string)
      // reference_number → reference (only if user hasn't typed one yet)
      if (ce.reference_number) setReference((prev) => prev || (ce.reference_number as string))
      // payment_terms → payment_terms_text
      if (ce.payment_terms) setPaymentTermsText((prev) => prev || (ce.payment_terms as string))
      // surcharge
      if (ce.surcharge != null) setSurcharge((prev) => prev || (ce.surcharge as number))
      if (ce.surcharge_description) setSurchargeDesc((prev) => prev || (ce.surcharge_description as string))
      // total_discount_pct (Gesamtrabatt — distinct from skonto)
      if (ce.total_discount_pct != null) setDiscountPct((prev) => prev || (ce.total_discount_pct as number))
      const li = (ce.line_items as Position[]) || []
      setPositions(li.length ? li.map((p) => ({ ...newPos(), ...p, _id: uid() })) : [newPos()])
    } catch {
      setError('KVA konnte nicht übernommen werden.')
    }
  }, [])

  // On mount: if arriving from a KVA ("In Rechnung umwandeln"), import it.
  const kvaParamHandled = useRef(false)
  useEffect(() => {
    if (isEdit || kvaParamHandled.current) return
    const kp = params.get('kva_id')
    if (kp) {
      kvaParamHandled.current = true
      importKva(kp)
    }
  }, [isEdit, params, importKva])

  // ── One-shot query-string hydration (new invoice only, no kva_id, no live-fill) ──
  // Reads customer_id, case_id, kva_id, project_id from query string.
  // Fetches customer detail for the read-only Kunde block.
  // Derives subject from case if no explicit subject.
  // If project_id is present without customer_id, resolves project's customer.
  const hydrationHandled = useRef(false)
  useEffect(() => {
    if (isEdit || hydrationHandled.current || liveFillRef.current) return
    const kp = params.get('kva_id')
    if (kp) return // importKva handles this path
    hydrationHandled.current = true

    const qCustomerId = params.get('customer_id') || ''
    const qCaseId = params.get('case_id') || ''
    const qProjectId = params.get('project_id') || ''

    const run = async () => {
      try {
        // Resolve customer_id from project if not given directly
        let resolvedCustomerId = qCustomerId
        if (!resolvedCustomerId && qProjectId) {
          const proj = await apiFetch<{ customer_id?: string | null }>(`/api/projects/${qProjectId}`)
          if (proj.customer_id) {
            resolvedCustomerId = proj.customer_id
            setCustomerId(resolvedCustomerId)
          }
        }

        // Fetch full customer detail for the read-only block
        if (resolvedCustomerId) {
          const cust = await apiFetch<CustomerDetail>(`/api/customers/${resolvedCustomerId}`)
          setHydratedCustomer(cust)
        }

        // Derive subject from case (only if no explicit subject yet)
        if (qCaseId) {
          const cs = await apiFetch<{ title?: string | null; number?: string | null }>(`/api/cases/${qCaseId}`)
          const derived = [cs.number, cs.title].filter(Boolean).join(' – ')
          if (derived) setSubject((prev) => prev || derived)
        }
      } catch {
        // Non-fatal: form still usable without prefill
      }
    }
    void run()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isEdit, params])

  // ── Hey-Kiki live fill ("takeover"): a confirmed copilot create_invoice lands
  // here via lib/liveFill — Kiki visibly fills the real form (customer →
  // subject typed char-by-char → positions one by one), then saves and opens
  // the finished invoice. The data is also assembled deterministically for the
  // save, so the animation can never diverge from what is persisted.
  const [kikiFilling, setKikiFilling] = useState(false)
  // undefined = not yet checked; null = no live-fill requested.
  const liveFillRef = useRef<LiveFillPayload | null | undefined>(undefined)
  if (liveFillRef.current === undefined) {
    // One-shot consume on first render (cleared from sessionStorage immediately).
    liveFillRef.current = isEdit ? null : consumeLiveFill('create_invoice')
  }
  const liveFillStarted = useRef(false)
  useEffect(() => {
    const lf = liveFillRef.current
    // Wait until the customer options are loaded (needed for name → id matching).
    if (!lf || liveFillStarted.current || isEdit || !customerData) return
    liveFillStarted.current = true

    const run = async () => {
      setKikiFilling(true)
      // Tell the panel the takeover is live — it cancels its 60s fallback so
      // the write can never execute twice (panel + script).
      emitLiveFillStatus({ tool: 'create_invoice', status: 'started' })
      try {
        const args = lf.args || {}
        await sleep(700)

        // 1) Customer: UUID directly, otherwise EXACT unique name match — a
        // first-substring hit could attach the invoice to the wrong customer;
        // ambiguous/no match fails over to the API path, which resolves
        // server-side and refuses ambiguity properly.
        const ref = String(args.customer_id || args.customer || '').trim()
        let cid = ''
        if (/^[0-9a-f-]{36}$/i.test(ref)) {
          cid = ref
        } else if (ref) {
          const needle = ref.toLowerCase()
          const hits = (customerData.customers ?? []).filter(
            (c) => (c.full_name || '').trim().toLowerCase() === needle,
          )
          if (hits.length !== 1) {
            throw new Error(
              hits.length === 0
                ? `Kunde „${ref}“ nicht eindeutig gefunden`
                : `Mehrere Kunden namens „${ref}“ — bitte eindeutig wählen`,
            )
          }
          cid = hits[0].id
        }
        if (cid) {
          setCustomerId(cid)
          await sleep(600)
        }

        // 2) Subject — typed character by character.
        const subj = String(args.subject || '').trim()
        for (let i = 1; i <= subj.length; i++) {
          setSubject(subj.slice(0, i))
          await sleep(18)
        }
        if (subj) await sleep(400)

        // 3) Positions — appear one by one; descriptions typed.
        const wanted = (args.positions ?? []).filter((p) => p && (p.description || p.price != null))
        const rows = wanted.map((p) => ({
          ...newPos(),
          description: '',
          quantity: Number(p.quantity ?? 1),
          unit: p.unit || 'Stk',
          price: Number(p.price ?? 0),
          vat: Number(p.vat ?? 19),
        }))
        for (let r = 0; r < rows.length; r++) {
          const visible = rows.slice(0, r + 1)
          setPositions(visible.map((row) => ({ ...row })))
          const desc = String(wanted[r].description || '')
          for (let i = 1; i <= desc.length; i++) {
            rows[r].description = desc.slice(0, i)
            setPositions(rows.slice(0, r + 1).map((row) => ({ ...row })))
            await sleep(14)
          }
          await sleep(350)
        }

        // 4) Optional texts.
        if (args.intro_text) setIntroText(String(args.intro_text))
        if (args.closing_text) setClosingText(String(args.closing_text))
        await sleep(900)

        // 5) Save — payload built HERE (state closures would be stale inside
        // this async script) and identical to what was animated.
        const inv = await apiFetch<{ id: string; number?: string }>('/api/invoices', {
          method: 'POST',
          body: JSON.stringify({
            customer_id: cid || null,
            kva_id: null,
            case_id: null,
            subject: subj,
            reference_number: '',
            invoice_date: todayIso(),
            performance_date: todayIso(),
            payment_terms_days: 14,
            discount_pct: null,
            discount_days: null,
            positions: rows.map(({ _id, ...p }, r) => ({ ...p, description: String(wanted[r].description || '') })),
            intro_text: args.intro_text ? String(args.intro_text) : INVOICE_INTRO,
            closing_text: args.closing_text ? String(args.closing_text) : INVOICE_CLOSING,
            payment_terms_text: '',
            surcharge: 0,
            surcharge_description: '',
            total_discount_pct: 0,
          }),
        })
        qc.invalidateQueries({ queryKey: ['invoices'] })
        emitLiveFillStatus({
          tool: 'create_invoice',
          status: 'done',
          note: `Rechnung${inv.number ? ' ' + inv.number : ''} live ausgefüllt & gespeichert`,
          route: `/invoices/${inv.id}`,
        })
        navigate(`/invoices/${inv.id}`)
      } catch (e) {
        emitLiveFillStatus({
          tool: 'create_invoice',
          status: 'failed',
          note: e instanceof Error ? e.message : 'Formular-Ausfüllen fehlgeschlagen',
        })
      } finally {
        setKikiFilling(false)
      }
    }
    void run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerData, isEdit])

  // Edit mode: load existing invoice.
  const { data: existing } = useQuery({
    queryKey: ['invoice', id],
    queryFn: () => apiFetch<Record<string, unknown>>(`/api/invoices/${id}`),
    enabled: isEdit,
  })
  useEffect(() => {
    if (!existing) return
    setCustomerId((existing.customer_id as string) || '')
    setKvaId((existing.kva_id as string) || (existing.cost_estimate_id as string) || '')
    setCaseId((existing.case_id as string) || '')
    setSubject((existing.subject as string) || '')
    setReference((existing.reference_number as string) || '')
    setInvoiceDate(((existing.invoice_date as string) || '').slice(0, 10) || todayIso())
    setPerformanceDate(((existing.performance_date as string) || '').slice(0, 10) || todayIso())
    setPaymentTermsDays((existing.payment_terms_days as number) ?? 14)
    setSkontoPct((existing.discount_pct as number) || 0)
    setSkontoDays((existing.discount_days as number) || 0)
    setIntroText((existing.intro_text as string) ?? INVOICE_INTRO)
    setClosingText((existing.closing_text as string) ?? INVOICE_CLOSING)
    setPaymentTermsText((existing.payment_terms_text as string) || '')
    setSurcharge((existing.surcharge as number) || 0)
    setSurchargeDesc((existing.surcharge_description as string) || '')
    setDiscountPct((existing.total_discount_pct as number) || 0)
    setLoadedNumber((existing.number as string) || null)
    const li = (existing.line_items as Position[]) || []
    setPositions(li.length ? li.map((p) => ({ ...newPos(), ...p, _id: uid() })) : [newPos()])
  }, [existing])

  const totals = useMemo(() => calcTotals(positions, surcharge, discountPct), [positions, surcharge, discountPct])

  const payload = useMemo(() => ({
    customer_id: customerId || null,
    kva_id: kvaId || null,
    case_id: caseId || null,
    subject, reference_number: reference,
    invoice_date: invoiceDate, performance_date: performanceDate || null,
    payment_terms_days: paymentTermsDays,
    discount_pct: skontoPct || null, discount_days: skontoDays || null,
    positions: positions.map(({ _id, ...p }) => p),
    intro_text: introText, closing_text: closingText, payment_terms_text: paymentTermsText,
    surcharge, surcharge_description: surchargeDesc, total_discount_pct: discountPct,
  }), [customerId, kvaId, caseId, subject, reference, invoiceDate, performanceDate, paymentTermsDays, skontoPct, skontoDays, positions, introText, closingText, paymentTermsText, surcharge, surchargeDesc, discountPct])

  // ── Live PDF preview (debounced) ──
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  useEffect(() => {
    let cancelled = false
    setPreviewLoading(true)
    const handle = setTimeout(async () => {
      try {
        const url = await apiPostBlob('/api/invoices/preview', payload)
        if (cancelled) { URL.revokeObjectURL(url); return }
        setPreviewUrl((prev) => { if (prev) URL.revokeObjectURL(prev); return url })
      } catch { /* ignore preview errors */ } finally {
        if (!cancelled) setPreviewLoading(false)
      }
    }, 800)
    return () => { cancelled = true; clearTimeout(handle) }
  }, [payload])

  // ── Positions ──
  const update = (id_: string, patch: Partial<Position>) =>
    setPositions((ps) => ps.map((p) => (p._id === id_ ? { ...p, ...patch } : p)))
  const remove = (id_: string) => setPositions((ps) => ps.filter((p) => p._id !== id_))
  const duplicate = (id_: string) =>
    setPositions((ps) => { const i = ps.findIndex((p) => p._id === id_); const copy = { ...ps[i], _id: uid() }; const out = [...ps]; out.splice(i + 1, 0, copy); return out })
  const addCatalog = (catId: string) => {
    const c = catalog.find((x) => x.id === catId)
    if (!c) return
    setPositions((ps) => {
      const filled = newPos({ description: c.name, price: c.unit_price, unit: c.unit || 'Stk' })
      const emptyIdx = ps.findIndex((p) => p.kind === 'item' && !p.description && !p.price)
      if (emptyIdx >= 0) { const out = [...ps]; out[emptyIdx] = { ...filled, _id: ps[emptyIdx]._id }; return out }
      return [...ps, filled]
    })
  }

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))
  const onDragEnd = (e: DragEndEvent) => {
    const { active, over } = e
    if (!over || active.id === over.id) return
    setPositions((ps) => {
      const from = ps.findIndex((p) => p._id === active.id)
      const to = ps.findIndex((p) => p._id === over.id)
      const out = [...ps]
      const [moved] = out.splice(from, 1)
      out.splice(to, 0, moved)
      return out
    })
  }

  const persist = () =>
    apiFetch<{ id: string }>(isEdit ? `/api/invoices/${id}` : '/api/invoices', {
      method: isEdit ? 'PATCH' : 'POST',
      body: JSON.stringify(payload),
    })

  const save = useMutation({
    mutationFn: persist,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['invoices'] }); navigate('/invoices') },
    onError: () => setError('Speichern fehlgeschlagen.'),
  })

  const createSend = useMutation({
    mutationFn: async () => {
      const inv = await persist()
      await apiFetch(`/api/invoices/${inv.id}/send`, {
        method: 'POST',
        body: JSON.stringify({ to: null, subject: null, message: null, copy_to_me: true }),
      })
      return inv
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['invoices'] }); navigate('/invoices') },
    onError: () => setError('Erstellen & Senden fehlgeschlagen.'),
  })

  const busy = save.isPending || createSend.isPending

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 px-8 pt-8">
        <button onClick={() => navigate('/invoices')} className="rounded-md p-1.5 text-muted hover:bg-alt"><ArrowLeft size={20} /></button>
        <div>
          <h1 className="text-2xl font-bold text-text">{isEdit ? `${loadedNumber ?? 'Rechnung'} bearbeiten` : 'Neue Rechnung'}</h1>
          <p className="mt-0.5 text-sm text-muted">{isEdit ? 'Rechnung bearbeiten' : 'Erstellen Sie eine neue Rechnung'}</p>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-6 p-8 lg:grid-cols-[3fr_2fr]">
        {/* LEFT: form */}
        <div className="min-h-0 space-y-5 overflow-y-auto pb-24">
          {kikiFilling && (
            <div className="sticky top-0 z-10 flex items-center gap-2 rounded-lg border border-ai/30 bg-ai-bg px-4 py-2.5 text-sm font-semibold text-ai shadow-e1">
              <Loader2 size={15} className="animate-spin" />
              Kiki füllt die Rechnung aus … bitte kurz zusehen, gespeichert wird automatisch.
            </div>
          )}
          {error && <div className="rounded-md bg-error-bg px-3 py-2 text-sm text-error">{error}</div>}

          {/* Section 1 */}
          <Card title="Kunde">
            <div><div className={labelCls}>Kunde *</div>
              <select value={customerId} onChange={(e) => setCustomerId(e.target.value)} className={inputCls}>
                <option value="">Kunde auswählen…</option>
                {customers.map((c) => <option key={c.id} value={c.id}>{c.full_name ?? 'Unbenannt'}</option>)}
              </select>
            </div>
            {hydratedCustomer && hydratedCustomer.id === customerId && (
              <div className="mt-2 rounded-md border border-border bg-alt px-3 py-2 text-xs text-body space-y-0.5">
                <div className="font-semibold text-text">{hydratedCustomer.full_name ?? '—'}</div>
                {hydratedCustomer.customer_number && <div className="text-muted">Kundennr.: {hydratedCustomer.customer_number}</div>}
                {hydratedCustomer.vat_id && <div className="text-muted">USt-IdNr.: {hydratedCustomer.vat_id}</div>}
                {hydratedCustomer.address && (
                  <div className="text-muted">
                    {[hydratedCustomer.address.street, [hydratedCustomer.address.zip, hydratedCustomer.address.city].filter(Boolean).join(' ')].filter(Boolean).join(', ')}
                  </div>
                )}
              </div>
            )}
            {!!customerId && (
              <div className="mt-3"><div className={labelCls}>Aus KVA übernehmen (optional)</div>
                <select value="" onChange={(e) => { if (e.target.value) importKva(e.target.value); e.currentTarget.value = '' }} className={inputCls}>
                  <option value="">KVA übernehmen…</option>
                  {selectableKvas.map((k) => <option key={k.id} value={k.id}>{k.number} — {k.subject || 'KVA'} ({money(k.total ?? 0)}) · {KVA_STATUS_DE[k.status] ?? k.status}</option>)}
                </select>
                {kvaId && <p className="mt-1 text-xs text-green-deep">Positionen aus {estimates.find((e) => e.id === kvaId)?.number ?? 'KVA'} übernommen.</p>}
              </div>
            )}
          </Card>

          {/* Section 2 */}
          <Card title="Dokument-Kopf & Details">
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2"><div className={labelCls}>Betreff / Titel</div>
                <div className="relative">
                  <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="z. B. Rechnung für Fenstereinbau" className={cn(inputCls, subject && 'pr-10')} />
                  {subject && <button title="Leeren" onClick={() => setSubject('')} className="absolute right-2 top-1/2 -translate-y-1/2 rounded bg-error p-1 text-white hover:brightness-110"><X size={12} /></button>}
                </div>
              </div>
              <div><div className={labelCls}>Leistungsdatum</div>
                <input type="date" value={performanceDate} onChange={(e) => setPerformanceDate(e.target.value)} className={inputCls} /></div>
              <div><div className={labelCls}>Zahlungsbedingungen</div>
                <select value={paymentTermsDays} onChange={(e) => setPaymentTermsDays(Number(e.target.value))} className={inputCls}>
                  {PAYMENT_TERMS.map((d) => <option key={d} value={d}>{d} Tage</option>)}
                  <option value={0}>Sofort</option>
                </select></div>
              <div className="col-span-2"><div className={labelCls}>Ihre Referenz / Auftragsnummer</div>
                <input value={reference} onChange={(e) => setReference(e.target.value)} placeholder="optional" className={inputCls} /></div>
              <div><div className={labelCls}>Skonto (%)</div>
                <input type="number" value={skontoPct || ''} onChange={(e) => setSkontoPct(Number(e.target.value))} placeholder="z. B. 2" className={inputCls} /></div>
              <div><div className={labelCls}>Skonto-Tage</div>
                <input type="number" value={skontoDays || ''} onChange={(e) => setSkontoDays(Number(e.target.value))} placeholder="z. B. 10" className={inputCls} /></div>
            </div>
            <p className="mt-1 text-xs text-muted">{skontoPct ? `${skontoPct}% Skonto bei Zahlung innerhalb von ${skontoDays || 0} Tagen.` : 'z. B. 2% Skonto bei Zahlung innerhalb von 10 Tagen.'}</p>
          </Card>

          {/* Section 3 */}
          <Card title="Positionen" actions={
            <div className="flex flex-wrap gap-2 text-xs font-medium">
              <button onClick={() => setPositions((p) => [...p, newPos()])} className="text-green-deep hover:underline">+ Position</button>
              <button onClick={() => setPositions((p) => [...p, newPos({ kind: 'optional' })])} className="text-warning hover:underline">◯ Optional</button>
              <button onClick={() => setPositions((p) => [...p, newPos({ kind: 'subtotal', description: 'Zwischensumme' })])} className="text-info hover:underline">Σ Zwischensumme</button>
              <button onClick={() => setPositions((p) => [...p, newPos({ kind: 'text' })])} className="text-muted hover:underline">T Textposition</button>
            </div>
          }>
            <div className="mb-3"><div className={labelCls}>Schnellauswahl aus Artikeln</div>
              <select value="" onChange={(e) => { if (e.target.value) addCatalog(e.target.value); e.currentTarget.value = '' }} className={inputCls}>
                <option value="">Artikel wählen…</option>
                {catalog.map((c) => <option key={c.id} value={c.id}>{c.name} — {money(c.unit_price)}</option>)}
              </select>
            </div>
            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
              <SortableContext items={positions.map((p) => p._id)} strategy={verticalListSortingStrategy}>
                <div className="space-y-3">
                  {positions.map((p, i) => (
                    <PositionCard key={p._id} pos={p} index={i} onChange={(patch) => update(p._id, patch)} onRemove={() => remove(p._id)} onDuplicate={() => duplicate(p._id)} />
                  ))}
                </div>
              </SortableContext>
            </DndContext>
          </Card>

          {/* Section 4 */}
          <Card title="Text (optional)">
            <div className="space-y-3">
              <div><div className={labelCls}>Einleitungstext</div><textarea value={introText} onChange={(e) => setIntroText(e.target.value)} rows={2} className={inputCls} /></div>
              <div><div className={labelCls}>Schlusstext</div><textarea value={closingText} onChange={(e) => setClosingText(e.target.value)} rows={2} className={inputCls} /></div>
              <div><div className={labelCls}>Zahlungsbedingungen</div><textarea value={paymentTermsText} onChange={(e) => setPaymentTermsText(e.target.value)} rows={2} placeholder="z. B. Zahlbar innerhalb 14 Tagen ohne Abzug" className={inputCls} /></div>
            </div>
          </Card>

          {/* Section 5 */}
          <Card title="Summen">
            <div className="grid grid-cols-3 gap-3">
              <div><div className={labelCls}>Aufschlag (€)</div><input type="number" value={surcharge || ''} onChange={(e) => setSurcharge(Number(e.target.value))} className={inputCls} /></div>
              <div><div className={labelCls}>Beschreibung</div><input value={surchargeDesc} onChange={(e) => setSurchargeDesc(e.target.value)} placeholder="z. B. Anfahrt" className={inputCls} /></div>
              <div><div className={labelCls}>Gesamtrabatt (%)</div><input type="number" value={discountPct || ''} onChange={(e) => setDiscountPct(Number(e.target.value))} className={inputCls} /></div>
            </div>
            <div className="mt-4 space-y-1 border-t border-border pt-3 text-sm">
              <div className="flex justify-between"><span className="text-muted">Netto</span><span className="text-text">{money(totals.net)}</span></div>
              <div className="flex justify-between"><span className="text-muted">MwSt</span><span className="text-text">{money(totals.vat)}</span></div>
              <div className="flex justify-between text-base font-bold"><span className="text-text">Brutto</span><span className="text-green-deep">{money(totals.gross)}</span></div>
              {skontoPct > 0 && (() => {
                const skontoAmt = Math.round(totals.gross * skontoPct / 100 * 100) / 100
                const zahlbetrag = Math.round((totals.gross - skontoAmt) * 100) / 100
                return (
                  <div className="mt-2 space-y-0.5 border-t border-border pt-2 text-xs text-muted">
                    <div className="flex justify-between"><span>- {skontoPct}% Skonto</span><span>{money(skontoAmt)}</span></div>
                    <div className="flex justify-between font-medium text-body"><span>Zahlbetrag bei Skonto ({skontoDays} Tage)</span><span>{money(zahlbetrag)}</span></div>
                  </div>
                )
              })()}
            </div>
          </Card>
        </div>

        {/* RIGHT: live PDF preview */}
        <div className="hidden min-h-0 flex-col lg:flex">
          <div className="mb-2 flex items-center gap-2 text-sm font-medium text-muted">
            PDF-Vorschau {previewLoading && <Loader2 size={14} className="animate-spin" />}
          </div>
          <div className="relative min-h-0 flex-1 overflow-hidden rounded-xl border border-border bg-alt">
            {previewUrl ? (
              <iframe title="PDF-Vorschau" src={previewUrl} className="h-full w-full" />
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-muted">Vorschau wird erstellt…</div>
            )}
          </div>
        </div>
      </div>

      {/* Sticky bottom bar */}
      <div className="sticky bottom-0 flex items-center justify-end gap-4 border-t border-border bg-surface px-8 py-3">
        <button onClick={() => navigate('/invoices')} className="rounded-md border border-border bg-alt px-5 py-2 text-sm font-medium text-body">{isAdmin ? 'Abbrechen' : 'Zurück'}</button>
        {/* Saving invoices is admin-only; employees can still view (PDF preview). */}
        {isAdmin && (
          <>
            <button disabled={!customerId || busy} onClick={() => save.mutate()} className="text-sm font-medium text-body hover:text-text disabled:opacity-50">
              {save.isPending ? 'Speichert…' : isEdit ? 'Speichern' : 'Nur erstellen'}
            </button>
            <button disabled={!customerId || busy} onClick={() => createSend.mutate()} className="inline-flex items-center gap-2 rounded-md bg-green-primary px-6 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">
              <Mail size={15} /> {createSend.isPending ? 'Sendet…' : isEdit ? 'Speichern & senden' : 'Erstellen & Rechnung senden'}
            </button>
          </>
        )}
      </div>
    </div>
  )
}

function Card({ title, actions, children }: { title: string; actions?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-5">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-bold text-text">{title}</h2>
        {actions}
      </div>
      {children}
    </div>
  )
}

function PositionCard({ pos, index, onChange, onRemove, onDuplicate }: { pos: Position; index: number; onChange: (p: Partial<Position>) => void; onRemove: () => void; onDuplicate: () => void }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: pos._id })
  const style = { transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.5 : 1 }

  if (pos.kind === 'text') {
    return (
      <div ref={setNodeRef} style={style} className="rounded-lg border border-border bg-alt p-3">
        <Head label="Textposition" listeners={listeners} attributes={attributes} onRemove={onRemove} onDuplicate={onDuplicate} />
        <input value={pos.description} onChange={(e) => onChange({ description: e.target.value })} placeholder="Freitext…" className={inputCls} />
      </div>
    )
  }
  if (pos.kind === 'subtotal') {
    return (
      <div ref={setNodeRef} style={style} className="rounded-lg border border-info/30 bg-info-bg/40 p-3">
        <Head label="Zwischensumme" listeners={listeners} attributes={attributes} onRemove={onRemove} onDuplicate={onDuplicate} />
        <input value={pos.description} onChange={(e) => onChange({ description: e.target.value })} className={inputCls} />
      </div>
    )
  }
  return (
    <div ref={setNodeRef} style={style} className={cn('rounded-lg border bg-alt p-3', pos.kind === 'optional' ? 'border-warning/40' : 'border-border')}>
      <Head label={pos.kind === 'optional' ? 'Optionale Position' : `Position ${index + 1}`} listeners={listeners} attributes={attributes} onRemove={onRemove} onDuplicate={onDuplicate} />
      <input value={pos.description} onChange={(e) => onChange({ description: e.target.value })} placeholder="Beschreibung" className={cn(inputCls, 'mb-2')} />
      <div className="grid grid-cols-4 gap-2">
        <div><div className={labelCls}>Menge</div><input type="number" value={pos.quantity} onChange={(e) => onChange({ quantity: Number(e.target.value) })} className={inputCls} /></div>
        <div><div className={labelCls}>Einheit</div><select value={pos.unit} onChange={(e) => onChange({ unit: e.target.value })} className={inputCls}>{UNITS.map((u) => <option key={u} value={u}>{u}</option>)}</select></div>
        <div><div className={labelCls}>Preis (€)</div><input type="number" value={pos.price} onChange={(e) => onChange({ price: Number(e.target.value) })} className={inputCls} /></div>
        <div><div className={labelCls}>MwSt</div><select value={pos.vat} onChange={(e) => onChange({ vat: Number(e.target.value) })} className={inputCls}>{VATS.map((v) => <option key={v} value={v}>{v}%</option>)}</select></div>
      </div>
      <div className="mt-2 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1"><span className="text-xs text-muted">Rabatt %</span>
            <input type="number" value={pos.discount_pct} onChange={(e) => onChange({ discount_pct: Number(e.target.value) })} className="w-16 rounded-md border border-border bg-surface px-2 py-1 text-sm text-text outline-none focus:border-green-primary" /></div>
          <label className="flex items-center gap-1.5 text-xs text-body"><input type="checkbox" checked={pos.is_labor} onChange={(e) => onChange({ is_labor: e.target.checked })} className="h-3.5 w-3.5 accent-green-primary" /> Lohnanteil</label>
        </div>
        <div className="text-sm font-medium text-text">Netto: {pos.kind === 'optional' ? '—' : money(lineNet(pos))}</div>
      </div>
    </div>
  )
}

function Head({ label, listeners, attributes, onRemove, onDuplicate }: { label: string; listeners: DraggableSyntheticListeners; attributes: object; onRemove: () => void; onDuplicate: () => void }) {
  return (
    <div className="mb-2 flex items-center justify-between">
      <div className="flex items-center gap-2">
        <button {...listeners} {...attributes} className="cursor-grab touch-none text-muted hover:text-body"><GripVertical size={15} /></button>
        <span className="text-xs font-semibold text-body">{label}</span>
      </div>
      <div className="flex items-center gap-1">
        <button onClick={onDuplicate} title="Duplizieren" className="rounded p-1 text-ai hover:bg-surface"><Copy size={14} /></button>
        <button onClick={onRemove} title="Löschen" className="rounded p-1 text-error hover:bg-surface"><Trash2 size={14} /></button>
      </div>
    </div>
  )
}
