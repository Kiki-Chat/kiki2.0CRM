import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Copy, GripVertical, Loader2, Plus, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { apiFetch, apiPostBlob } from '../lib/api'
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
interface Inquiry { id: string; title: string | null; status: string }
interface CatalogItem { id: string; name: string; description: string | null; unit_price: number; unit: string | null }

const UNITS = ['Stk', 'm', 'm²', 'h', 'Std', 'pauschal', 'kg', 'l', 'Tag']
const VATS = [19, 7, 0]
const VALIDITY = [7, 14, 30, 60, 90]
const DOC_TYPES = [
  { v: 'kva', l: 'Kostenvoranschlag' },
  { v: 'offer', l: 'Angebot' },
  { v: 'order_confirmation', l: 'Auftragsbestätigung' },
]
const inputCls = 'w-full rounded-md border border-border bg-alt px-3 py-2 text-sm text-text outline-none focus:border-green-primary'
const labelCls = 'mb-1 block text-xs font-semibold text-body'
const uid = () => Math.random().toString(36).slice(2)

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

export function CostEstimateFormPage() {
  const { id } = useParams()
  const isEdit = !!id
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const qc = useQueryClient()

  const [customerId, setCustomerId] = useState(params.get('customer_id') || '')
  const [inquiryId, setInquiryId] = useState(params.get('inquiry_id') || '')
  const [projectId, setProjectId] = useState(params.get('project_id') || '')
  const [type, setType] = useState('kva')
  const [subject, setSubject] = useState('')
  const [reference, setReference] = useState('')
  const [isBinding, setIsBinding] = useState(false)
  const [tolerance, setTolerance] = useState(20)
  const [validity, setValidity] = useState(30)
  const [positions, setPositions] = useState<Position[]>([newPos()])
  const [introText, setIntroText] = useState('')
  const [closingText, setClosingText] = useState('')
  const [paymentTerms, setPaymentTerms] = useState('')
  const [surcharge, setSurcharge] = useState(0)
  const [surchargeDesc, setSurchargeDesc] = useState('')
  const [discountPct, setDiscountPct] = useState(0)
  const [loadedNumber, setLoadedNumber] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const inquiryAutofilled = useRef(false)

  const { data: customerData } = useQuery({
    queryKey: ['customers-options'],
    queryFn: () => apiFetch<{ customers: CustomerOption[] }>('/api/customers?limit=500'),
  })
  const customers = customerData?.customers ?? []
  const { data: catalog = [] } = useQuery({ queryKey: ['catalog-active'], queryFn: () => apiFetch<CatalogItem[]>('/api/catalog?status=active') })
  const { data: textDefaults } = useQuery({ queryKey: ['text-defaults'], queryFn: () => apiFetch<Record<string, string>>('/api/text-modules/defaults') })

  // Selected customer's inquiries (for the Anfrage dropdown).
  const { data: customerDetail } = useQuery({
    queryKey: ['customer-detail', customerId],
    queryFn: () => apiFetch<{ inquiries: Inquiry[] }>(`/api/customers/${customerId}`),
    enabled: !!customerId,
  })
  const inquiries = (customerDetail?.inquiries ?? []).filter((i) => i.status !== 'deleted')

  // Edit mode: load existing estimate.
  const { data: existing } = useQuery({
    queryKey: ['cost-estimate', id],
    queryFn: () => apiFetch<Record<string, unknown>>(`/api/cost-estimates/${id}`),
    enabled: isEdit,
  })
  useEffect(() => {
    if (!existing) return
    setCustomerId((existing.customer_id as string) || '')
    setInquiryId((existing.inquiry_id as string) || '')
    setProjectId((existing.project_id as string) || '')
    setType((existing.type as string) || 'kva')
    setSubject((existing.subject as string) || '')
    setReference((existing.reference_number as string) || '')
    setIsBinding(!!existing.is_binding)
    setTolerance((existing.tolerance_pct as number) ?? 20)
    setValidity((existing.validity_days as number) ?? 30)
    setIntroText((existing.intro_text as string) || '')
    setClosingText((existing.closing_text as string) || '')
    setPaymentTerms((existing.payment_terms as string) || '')
    setSurcharge((existing.surcharge as number) || 0)
    setSurchargeDesc((existing.surcharge_description as string) || '')
    setDiscountPct((existing.total_discount_pct as number) || 0)
    setLoadedNumber((existing.number as string) || null)
    const li = (existing.line_items as Position[]) || []
    setPositions(li.length ? li.map((p) => ({ ...newPos(), ...p, _id: uid() })) : [newPos()])
    inquiryAutofilled.current = true
  }, [existing])

  // Auto-fill subject from the selected inquiry (param-driven AI workflow).
  useEffect(() => {
    if (isEdit || inquiryAutofilled.current) return
    if (inquiryId && inquiries.length) {
      const inq = inquiries.find((i) => i.id === inquiryId)
      if (inq?.title && !subject) {
        setSubject(inq.title)
        inquiryAutofilled.current = true
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inquiryId, inquiries, isEdit])

  // Pre-fill default text modules (Einleitung/Schluss/Zahlungsbedingungen) for new docs.
  const textDefaultsApplied = useRef(false)
  useEffect(() => {
    if (isEdit || textDefaultsApplied.current || !textDefaults) return
    textDefaultsApplied.current = true
    if (textDefaults.einleitung) setIntroText((v) => v || textDefaults.einleitung)
    if (textDefaults.schlusstext) setClosingText((v) => v || textDefaults.schlusstext)
    if (textDefaults.zahlungsbedingungen) setPaymentTerms((v) => v || textDefaults.zahlungsbedingungen)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [textDefaults, isEdit])

  const totals = useMemo(() => calcTotals(positions, surcharge, discountPct), [positions, surcharge, discountPct])

  // ── Live PDF preview (debounced) ──
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const payload = useMemo(() => ({
    customer_id: customerId || null,
    inquiry_id: inquiryId || null,
    project_id: projectId || null,
    type, subject, reference_number: reference, is_binding: isBinding,
    tolerance_pct: tolerance, validity_days: validity,
    positions: positions.map(({ _id, ...p }) => p),
    intro_text: introText, closing_text: closingText, payment_terms: paymentTerms,
    surcharge, surcharge_description: surchargeDesc, total_discount_pct: discountPct,
  }), [customerId, inquiryId, projectId, type, subject, reference, isBinding, tolerance, validity, positions, introText, closingText, paymentTerms, surcharge, surchargeDesc, discountPct])

  useEffect(() => {
    let cancelled = false
    setPreviewLoading(true)
    const handle = setTimeout(async () => {
      try {
        const url = await apiPostBlob('/api/cost-estimates/preview', payload)
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

  const save = useMutation({
    mutationFn: () => apiFetch(isEdit ? `/api/cost-estimates/${id}` : '/api/cost-estimates', {
      method: isEdit ? 'PATCH' : 'POST',
      body: JSON.stringify(payload),
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cost-estimates'] })
      navigate('/cost-estimates')
    },
    onError: () => setError('Speichern fehlgeschlagen.'),
  })

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 px-8 pt-8">
        <button onClick={() => navigate('/cost-estimates')} className="rounded-md p-1.5 text-muted hover:bg-alt"><ArrowLeft size={20} /></button>
        <div>
          <h1 className="text-2xl font-bold text-text">{isEdit ? `${loadedNumber ?? 'KVA'} bearbeiten` : 'Neuer Kostenvoranschlag'}</h1>
          <p className="mt-0.5 text-sm text-muted">{isEdit ? 'Kostenvoranschlag bearbeiten' : 'Erstellen Sie einen neuen Kostenvoranschlag'}</p>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-6 p-8 lg:grid-cols-[3fr_2fr]">
        {/* LEFT: form */}
        <div className="min-h-0 space-y-5 overflow-y-auto pb-24">
          {error && <div className="rounded-md bg-error-bg px-3 py-2 text-sm text-error">{error}</div>}

          {/* Section 1 */}
          <Card title="Kunde & Anfrage">
            <div><div className={labelCls}>Kunde *</div>
              <select value={customerId} onChange={(e) => { setCustomerId(e.target.value); setInquiryId('') }} className={inputCls}>
                <option value="">Kunde auswählen…</option>
                {customers.map((c) => <option key={c.id} value={c.id}>{c.full_name ?? 'Unbenannt'}</option>)}
              </select>
            </div>
            {!!customerId && (
              <div className="mt-3"><div className={labelCls}>Anfrage (optional)</div>
                <select value={inquiryId} onChange={(e) => { setInquiryId(e.target.value); const inq = inquiries.find((i) => i.id === e.target.value); if (inq?.title) setSubject(inq.title) }} className={inputCls}>
                  <option value="">Keine Anfrage</option>
                  {inquiries.map((i) => <option key={i.id} value={i.id}>{i.title ?? 'Anfrage'}</option>)}
                </select>
              </div>
            )}
          </Card>

          {/* Section 2 */}
          <Card title="Dokument-Kopf & Details">
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2"><div className={labelCls}>Betreff / Titel</div>
                <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="z. B. Angebot für Heizungswartung" className={inputCls} /></div>
              <div><div className={labelCls}>Gültigkeitsdauer</div>
                <select value={validity} onChange={(e) => setValidity(Number(e.target.value))} className={inputCls}>{VALIDITY.map((d) => <option key={d} value={d}>{d} Tage</option>)}</select></div>
              <div><div className={labelCls}>Dokumenttyp</div>
                <select value={type} onChange={(e) => setType(e.target.value)} className={inputCls}>{DOC_TYPES.map((t) => <option key={t.v} value={t.v}>{t.l}</option>)}</select></div>
              <div><div className={labelCls}>Ihre Referenz / Auftragsnummer</div>
                <input value={reference} onChange={(e) => setReference(e.target.value)} placeholder="optional" className={inputCls} /></div>
              <div><div className={labelCls}>Toleranz (%)</div>
                <input type="number" value={tolerance} disabled={isBinding} onChange={(e) => setTolerance(Number(e.target.value))} className={cn(inputCls, isBinding && 'opacity-50')} /></div>
            </div>
            <label className="mt-3 flex items-center gap-2 text-sm text-text">
              <input type="checkbox" checked={isBinding} onChange={(e) => setIsBinding(e.target.checked)} className="h-4 w-4 accent-green-primary" />
              Verbindlich (garantiert)
            </label>
            <p className="mt-1 text-xs text-muted">{isBinding ? 'Verbindliches Angebot.' : `Unverbindlicher Kostenvoranschlag — Toleranz ±${tolerance}% (§ 650c BGB).`}</p>
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
            <div className="mb-3"><div className={labelCls}>Schnellauswahl aus Katalog</div>
              <select value="" onChange={(e) => { if (e.target.value) addCatalog(e.target.value); e.target.value = '' }} className={inputCls}>
                <option value="">Aus Katalog wählen…</option>
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
              <div><div className={labelCls}>Einleitungstext</div><textarea value={introText} onChange={(e) => setIntroText(e.target.value)} rows={2} placeholder="Text vor den Positionen…" className={inputCls} /></div>
              <div><div className={labelCls}>Schlusstext</div><textarea value={closingText} onChange={(e) => setClosingText(e.target.value)} rows={2} placeholder="Text nach den Summen…" className={inputCls} /></div>
              <div><div className={labelCls}>Zahlungsbedingungen</div><textarea value={paymentTerms} onChange={(e) => setPaymentTerms(e.target.value)} rows={2} placeholder="z. B. Zahlbar innerhalb 14 Tagen ohne Abzug" className={inputCls} /></div>
            </div>
          </Card>

          {/* Section 5 */}
          <Card title="Summen">
            <div className="grid grid-cols-3 gap-3">
              <div><div className={labelCls}>Aufschlag (€)</div><input type="number" value={surcharge} onChange={(e) => setSurcharge(Number(e.target.value))} className={inputCls} /></div>
              <div><div className={labelCls}>Beschreibung</div><input value={surchargeDesc} onChange={(e) => setSurchargeDesc(e.target.value)} placeholder="z. B. Anfahrt" className={inputCls} /></div>
              <div><div className={labelCls}>Gesamtrabatt (%)</div><input type="number" value={discountPct} onChange={(e) => setDiscountPct(Number(e.target.value))} className={inputCls} /></div>
            </div>
            <div className="mt-4 space-y-1 border-t border-border pt-3 text-sm">
              <div className="flex justify-between"><span className="text-muted">Netto</span><span className="text-text">{money(totals.net)}</span></div>
              <div className="flex justify-between"><span className="text-muted">MwSt</span><span className="text-text">{money(totals.vat)}</span></div>
              <div className="flex justify-between text-base font-bold"><span className="text-text">Brutto</span><span className="text-green-deep">{money(totals.gross)}</span></div>
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
      <div className="sticky bottom-0 flex items-center justify-end gap-3 border-t border-border bg-surface px-8 py-3">
        <button onClick={() => navigate('/cost-estimates')} className="rounded-md border border-border bg-alt px-5 py-2 text-sm font-medium text-body">Abbrechen</button>
        <button disabled={!customerId || save.isPending} onClick={() => save.mutate()} className="rounded-md bg-green-primary px-6 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">
          {save.isPending ? 'Speichert…' : isEdit ? 'Aktualisieren' : 'Erstellen'}
        </button>
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
        <Head index={index} label="Textposition" listeners={listeners} attributes={attributes} onRemove={onRemove} onDuplicate={onDuplicate} />
        <input value={pos.description} onChange={(e) => onChange({ description: e.target.value })} placeholder="Freitext…" className={inputCls} />
      </div>
    )
  }
  if (pos.kind === 'subtotal') {
    return (
      <div ref={setNodeRef} style={style} className="rounded-lg border border-info/30 bg-info-bg/40 p-3">
        <Head index={index} label="Zwischensumme" listeners={listeners} attributes={attributes} onRemove={onRemove} onDuplicate={onDuplicate} />
        <input value={pos.description} onChange={(e) => onChange({ description: e.target.value })} className={inputCls} />
      </div>
    )
  }
  return (
    <div ref={setNodeRef} style={style} className={cn('rounded-lg border bg-alt p-3', pos.kind === 'optional' ? 'border-warning/40' : 'border-border')}>
      <Head index={index} label={pos.kind === 'optional' ? 'Optionale Position' : `Position ${index + 1}`} listeners={listeners} attributes={attributes} onRemove={onRemove} onDuplicate={onDuplicate} />
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

function Head({ index, label, listeners, attributes, onRemove, onDuplicate }: { index: number; label: string; listeners: object; attributes: object; onRemove: () => void; onDuplicate: () => void }) {
  void index
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
