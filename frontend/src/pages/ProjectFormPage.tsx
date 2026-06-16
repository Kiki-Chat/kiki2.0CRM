import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, FolderOpen, Link2, Save, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { apiFetch } from '../lib/api'
import { cn } from '../lib/utils'

interface CustomerOption { id: string; full_name: string | null }

const inputCls = 'w-full rounded-md border border-border bg-alt px-3 py-2 text-sm text-text outline-none focus:border-green-primary'
const labelCls = 'mb-1 block text-sm font-semibold text-body'

/** Best-effort split of a free-text German address into street / PLZ / Ort.
 * Customers store the address as a single `{ raw }` blob, so to copy it into the
 * project's separate fields we locate the 5-digit PLZ: everything before it is the
 * street, the rest is the city. Falls back to street-only when no PLZ is found.
 * Handles "Straße 12, 12345 Stadt", "Straße 12\n12345 Stadt", "Straße 12 12345 Stadt". */
function parseGermanAddress(raw: string): { street: string; postcode: string; city: string } {
  const text = raw.trim().replace(/\s+/g, ' ')
  const m = text.match(/^(.*?)[,;\s]+(\d{5})\s+(.+)$/)
  if (m) {
    return { street: m[1].replace(/[,;]\s*$/, '').trim(), postcode: m[2], city: m[3].trim() }
  }
  return { street: text, postcode: '', city: '' }
}

export function ProjectFormPage() {
  const { id } = useParams()
  const isEdit = !!id
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [params] = useSearchParams()

  // Project-from-case context: when launched from a Fall ("Neues Projekt erstellen"),
  // the customer is pre-filled + locked, the address auto-pulled, and on save the
  // case is attached to the new project (POST /api/projects/{id}/cases).
  const fromCustomerId = !isEdit ? params.get('customer_id') || '' : ''
  const attachCaseId = !isEdit ? params.get('case_id') || '' : ''
  const attachCaseNumber = params.get('case_number') || ''

  const [title, setTitle] = useState('')
  const [customerId, setCustomerId] = useState(fromCustomerId)
  const [description, setDescription] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [budget, setBudget] = useState('')
  const [street, setStreet] = useState('')
  const [postcode, setPostcode] = useState('')
  const [city, setCity] = useState('')
  const [useCustomerAddr, setUseCustomerAddr] = useState(!!fromCustomerId)
  const [notes, setNotes] = useState('')
  const [error, setError] = useState<string | null>(null)

  const { data: customerData } = useQuery({
    queryKey: ['customers-options'],
    queryFn: () => apiFetch<{ customers: CustomerOption[] }>('/api/customers?limit=500'),
  })
  const customers = customerData?.customers ?? []

  const { data: existing } = useQuery({
    queryKey: ['project', id],
    queryFn: () => apiFetch<Record<string, unknown>>(`/api/projects/${id}`),
    enabled: isEdit,
  })
  useEffect(() => {
    if (!existing) return
    setTitle((existing.title as string) || '')
    setCustomerId((existing.customer_id as string) || '')
    setDescription((existing.description as string) || '')
    setStartDate(((existing.start_date as string) || '').slice(0, 10))
    setEndDate(((existing.end_date as string) || '').slice(0, 10))
    setBudget(existing.planned_budget != null ? String(existing.planned_budget) : '')
    const addr = (existing.project_address as Record<string, string>) || {}
    setStreet(addr.street || '')
    setPostcode(addr.postcode || '')
    setCity(addr.city || '')
    setNotes((existing.internal_notes as string) || '')
  }, [existing])

  // "Kundenadresse übernehmen": pull the selected customer's address.
  useEffect(() => {
    if (!useCustomerAddr || !customerId) return
    let cancelled = false
    apiFetch<{ address: unknown }>(`/api/customers/${customerId}`)
      .then((c) => {
        if (cancelled) return
        const a = c.address
        if (a && typeof a === 'object') {
          const o = a as Record<string, string>
          // Prefer structured sub-fields if a customer ever has them; otherwise
          // parse the free-text `raw` blob (how every customer is stored today).
          if (o.street || o.postcode || o.postal_code || o.zip || o.city) {
            setStreet(o.street || '')
            setPostcode(o.postcode || o.postal_code || o.zip || '')
            setCity(o.city || '')
          } else if (o.raw) {
            const p = parseGermanAddress(o.raw)
            setStreet(p.street)
            setPostcode(p.postcode)
            setCity(p.city)
          }
        } else if (typeof a === 'string') {
          const p = parseGermanAddress(a)
          setStreet(p.street)
          setPostcode(p.postcode)
          setCity(p.city)
        }
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [useCustomerAddr, customerId])

  const save = useMutation({
    mutationFn: async () => {
      const hasAddr = street || postcode || city
      const payload = {
        title: title.trim(),
        customer_id: customerId || null,
        description: description || null,
        start_date: startDate || null,
        end_date: endDate || null,
        planned_budget: budget ? Number(budget) : null,
        project_address: hasAddr ? { street, postcode, city } : null,
        internal_notes: notes || null,
      }
      const res = await apiFetch<{ id: string }>(isEdit ? `/api/projects/${id}` : '/api/projects', {
        method: isEdit ? 'PATCH' : 'POST',
        body: JSON.stringify(payload),
      })
      // Attach the originating Fall to the freshly-created Projekt.
      if (attachCaseId && res.id) {
        await apiFetch(`/api/projects/${res.id}/cases`, { method: 'POST', body: JSON.stringify({ case_id: attachCaseId }) })
      }
      return res
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      if (isEdit) qc.invalidateQueries({ queryKey: ['project', id] })
      if (attachCaseId) {
        // Back to the case — it now shows the project attachment.
        qc.invalidateQueries({ queryKey: ['cases'] })
        qc.invalidateQueries({ queryKey: ['caseDetail', attachCaseId] })
        navigate(`/cases?case=${attachCaseId}`)
        return
      }
      navigate(`/projects/${isEdit ? id : data.id}`)
    },
    onError: () => setError('Speichern fehlgeschlagen.'),
  })

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 px-8 pt-8">
        <button onClick={() => navigate('/projects')} className="rounded-md p-1.5 text-muted hover:bg-alt"><ArrowLeft size={20} /></button>
        <FolderOpen size={24} className="text-green-primary" />
        <h1 className="text-2xl font-bold text-text">{isEdit ? 'Projekt bearbeiten' : 'Neues Projekt'}</h1>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-8 py-6">
        <div className="mx-auto max-w-3xl space-y-5 pb-24">
          {error && <div className="rounded-md bg-error-bg px-3 py-2 text-sm text-error">{error}</div>}

          {attachCaseId && (
            <div className="flex items-center gap-2.5 rounded-lg border border-green-tint-200 bg-green-tint-50 px-3.5 py-2.5 text-sm text-green-deep">
              <Link2 size={16} className="flex-shrink-0" />
              <span>
                Der Fall <span className="font-bold">{attachCaseNumber || 'FL-…'}</span> wird diesem Projekt zugeordnet — Kunde &amp; Adresse sind bereits übernommen.
              </span>
            </div>
          )}

          {/* Grunddaten */}
          <Card title="Grunddaten">
            <div className="space-y-4">
              <div>
                <div className={labelCls}>Titel *</div>
                <div className="relative">
                  <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="z. B. Fassadenrenovierung Müller" className={cn(inputCls, title && 'pr-10')} />
                  {title && <button title="Leeren" onClick={() => setTitle('')} className="absolute right-2 top-1/2 -translate-y-1/2 rounded bg-error p-1 text-white hover:brightness-110"><X size={12} /></button>}
                </div>
              </div>
              <div>
                <div className={labelCls}>Kunde *</div>
                <select value={customerId} onChange={(e) => setCustomerId(e.target.value)} disabled={!!attachCaseId} className={cn(inputCls, attachCaseId && 'cursor-not-allowed opacity-70')}>
                  <option value="">Kunde suchen…</option>
                  {customers.map((c) => <option key={c.id} value={c.id}>{c.full_name ?? 'Unbenannt'}</option>)}
                </select>
                {attachCaseId && <p className="mt-1 text-xs text-muted">Aus dem Fall übernommen — nicht änderbar.</p>}
              </div>
              <div>
                <div className={labelCls}>Beschreibung</div>
                <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} placeholder="Projektbeschreibung…" className={inputCls} />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div><div className={labelCls}>Startdatum</div><input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className={inputCls} /></div>
                <div><div className={labelCls}>Enddatum</div><input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className={inputCls} /></div>
              </div>
            </div>
          </Card>

          {/* Budget */}
          <Card title="Budget" icon={<span className="text-green-primary">€</span>}>
            <p className="mb-3 text-sm text-muted">Legen Sie ein geplantes Budget für das Projekt fest. Das hilft bei der Kostenkontrolle und ermöglicht Vergleiche zwischen geplanten und tatsächlichen Kosten.</p>
            <div>
              <div className={labelCls}>Geplantes Budget (netto)</div>
              <div className="relative">
                <input type="number" value={budget} onChange={(e) => setBudget(e.target.value)} placeholder="0,00" className={cn(inputCls, 'pr-8')} />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted">€</span>
              </div>
              <p className="mt-1 text-xs text-muted">Nettobetrag ohne MwSt. Leer lassen, wenn kein Budget gesetzt werden soll.</p>
            </div>
          </Card>

          {/* Projektadresse */}
          <Card title="Projektadresse">
            <p className="mb-3 text-sm text-muted">Die Projektadresse kann von der Kundenadresse abweichen (z. B. bei Baustellen).</p>
            <div className="space-y-4">
              <div><div className={labelCls}>Straße</div><input value={street} onChange={(e) => setStreet(e.target.value)} placeholder="Musterstraße 123" className={inputCls} /></div>
              <div className="grid grid-cols-2 gap-4">
                <div><div className={labelCls}>PLZ</div><input value={postcode} onChange={(e) => setPostcode(e.target.value)} placeholder="12345" className={inputCls} /></div>
                <div><div className={labelCls}>Ort</div><input value={city} onChange={(e) => setCity(e.target.value)} placeholder="Musterstadt" className={inputCls} /></div>
              </div>
              <label className="flex items-center gap-2 text-sm text-text">
                <input type="checkbox" checked={useCustomerAddr} onChange={(e) => setUseCustomerAddr(e.target.checked)} disabled={!customerId} className="h-4 w-4 accent-green-primary" />
                Kundenadresse übernehmen
              </label>
            </div>
          </Card>

          {/* Interne Notizen */}
          <Card title="Interne Notizen">
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={4} placeholder="Interne Projektnotizen (nicht für den Kunden sichtbar)…" className={inputCls} />
          </Card>
        </div>
      </div>

      {/* Sticky bottom bar */}
      <div className="sticky bottom-0 flex items-center justify-end gap-3 border-t border-border bg-surface px-8 py-3">
        <button onClick={() => navigate('/projects')} className="rounded-md border border-border bg-alt px-5 py-2 text-sm font-medium text-body">Abbrechen</button>
        <button disabled={!title.trim() || !customerId || save.isPending} onClick={() => save.mutate()} className="inline-flex items-center gap-2 rounded-md bg-green-primary px-6 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">
          <Save size={15} /> {save.isPending ? 'Speichert…' : 'Speichern'}
        </button>
      </div>
    </div>
  )
}

function Card({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-5">
      <h2 className="mb-3 flex items-center gap-2 text-base font-bold text-text">{icon}{title}</h2>
      {children}
    </div>
  )
}
