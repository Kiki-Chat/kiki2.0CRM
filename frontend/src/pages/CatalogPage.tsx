import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Box, Download, FileText, Package, Pencil, Search, Trash2, Upload, Wrench } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'

import { Modal } from '../components/ui/Modal'
import { apiBlobUrl, apiFetch, apiUpload } from '../lib/api'
import { cn } from '../lib/utils'

interface CatalogItem {
  id: string
  article_number: string | null
  name: string
  description: string | null
  category: string | null
  unit: string | null
  vat_rate: number | null
  is_wage: boolean
  unit_price: number | null
  purchase_price: number | null
  supplier_id: string | null
  supplier_name: string | null
  is_active: boolean
}
interface CustomerOption { id: string; full_name: string | null }

const CATEGORIES = ['Montage', 'Glas', 'Material', 'Elektro', 'Sanitär', 'Heizung', 'Sonstiges']
const UNITS = ['Stk', 'm', 'm²', 'm³', 'h', 'kg', 'l', 'pauschal']
const VATS = [19, 7, 0]
const money = (n: number | null) => '€' + (n ?? 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const margin = (sell: number | null, buy: number | null) =>
  sell && buy ? `${(((sell - buy) / sell) * 100).toFixed(0)} %` : '–'
const inputCls = 'w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary'
const labelCls = 'mb-1.5 block text-xs font-semibold text-body'

type Tab = 'positions' | 'text' | 'vehicles' | 'tools'

export function CatalogPage() {
  const [tab, setTab] = useState<Tab>('positions')
  const fileRef = useRef<HTMLInputElement>(null)
  const qc = useQueryClient()
  const [newOpen, setNewOpen] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(null), 4000) }

  const { data: items = [] } = useQuery({ queryKey: ['catalog'], queryFn: () => apiFetch<CatalogItem[]>('/api/catalog') })
  const { data: textModules = [] } = useQuery({ queryKey: ['text-modules'], queryFn: () => apiFetch<unknown[]>('/api/text-modules') })

  const tabs: { id: Tab; label: string; icon: typeof Package; count?: number }[] = [
    { id: 'positions', label: 'Positionen', icon: Package, count: items.length },
    { id: 'text', label: 'Textbausteine', icon: FileText, count: textModules.length },
    { id: 'vehicles', label: 'Fahrzeuge', icon: Box },
    { id: 'tools', label: 'Werkzeug', icon: Wrench },
  ]

  const importCsv = useMutation({
    mutationFn: (file: File) => { const fd = new FormData(); fd.append('file', file); return apiUpload<{ created: number; skipped: number }>('/api/catalog/import', fd) },
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ['catalog'] }); flash(`${r.created} Positionen importiert${r.skipped ? `, ${r.skipped} übersprungen` : ''}.`) },
    onError: () => flash('Import fehlgeschlagen.'),
  })
  const exportCsv = async () => {
    try { const url = await apiBlobUrl('/api/catalog/export'); const a = document.createElement('a'); a.href = url; a.download = 'katalog.csv'; a.click() }
    catch { flash('Export fehlgeschlagen.') }
  }

  return (
    <div className="p-8">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <Box size={26} className="text-green-primary" />
          <div>
            <h1 className="text-2xl font-bold text-text">Katalog & Vorlagen</h1>
            <p className="mt-0.5 text-sm text-muted">Positionen und Textbausteine verwalten</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {tab === 'positions' && (
            <>
              <button onClick={exportCsv} className="inline-flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-2 text-sm font-medium text-body hover:bg-alt"><Download size={15} /> CSV Export</button>
              <button onClick={() => fileRef.current?.click()} className="inline-flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-2 text-sm font-medium text-body hover:bg-alt"><Upload size={15} /> CSV Import</button>
              <button onClick={() => setNewOpen(true)} className="inline-flex items-center gap-2 rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110">+ Neue Position</button>
              <input ref={fileRef} type="file" accept=".csv,text/csv" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f && confirm(`CSV "${f.name}" importieren?`)) importCsv.mutate(f); e.target.value = '' }} />
            </>
          )}
          {tab === 'text' && <button onClick={() => flash('Textbausteine werden als Nächstes gebaut.')} className="inline-flex items-center gap-2 rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110">+ Neuer Textbaustein</button>}
          {tab === 'vehicles' && <button onClick={() => flash('Fahrzeuge-Tab folgt als Nächstes.')} className="inline-flex items-center gap-2 rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110">+ Neues Fahrzeug</button>}
          {tab === 'tools' && <button onClick={() => flash('Werkzeug-Tab folgt als Nächstes.')} className="inline-flex items-center gap-2 rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110">+ Neues Werkzeug</button>}
        </div>
      </div>

      <div className="mb-6 flex gap-1 border-b border-border">
        {tabs.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)} className={cn('flex items-center gap-1.5 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors', tab === t.id ? 'border-green-primary text-green-deep' : 'border-transparent text-muted hover:text-body')}>
            <t.icon size={15} /> {t.label}
            {t.count !== undefined && <span className="rounded-full bg-alt px-1.5 text-xs text-muted">{t.count}</span>}
          </button>
        ))}
      </div>

      {toast && <div className="mb-3 rounded-md bg-green-tint-50 px-3 py-2 text-sm font-medium text-green-deep">{toast}</div>}

      {tab === 'positions' ? (
        <PositionsTab items={items} flash={flash} />
      ) : (
        <div className="rounded-xl border border-dashed border-border py-20 text-center text-sm text-muted">Dieser Tab wird als Nächstes gebaut.</div>
      )}

      {newOpen && <PositionModal onClose={() => setNewOpen(false)} onSaved={() => { qc.invalidateQueries({ queryKey: ['catalog'] }); setNewOpen(false) }} />}
    </div>
  )
}

function PositionsTab({ items, flash }: { items: CatalogItem[]; flash: (m: string) => void }) {
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [cat, setCat] = useState('all')
  const [status, setStatus] = useState('active')
  const [editing, setEditing] = useState<CatalogItem | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const categories = useMemo(() => [...new Set(items.map((i) => i.category).filter(Boolean))] as string[], [items])
  const filtered = items.filter(
    (i) =>
      (!q || i.name.toLowerCase().includes(q.toLowerCase()) || (i.article_number ?? '').toLowerCase().includes(q.toLowerCase())) &&
      (cat === 'all' || i.category === cat) &&
      (status === 'all' || (status === 'active' ? i.is_active : !i.is_active)),
  )
  const activeCount = items.filter((i) => i.is_active).length
  const avgPrice = items.length ? items.reduce((s, i) => s + (i.unit_price ?? 0), 0) / items.length : 0

  const del = useMutation({
    mutationFn: (id: string) => apiFetch(`/api/catalog/${id}`, { method: 'DELETE' }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['catalog'] }); flash('Position gelöscht.') },
    onError: (e: Error) => flash(e.message),
  })
  const toggle = (id: string) => setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })

  return (
    <div>
      <div className="mb-4 grid grid-cols-3 gap-4">
        <SummaryCard icon={<Box size={18} />} color="bg-info-bg text-info" label="Gesamt" value={String(items.length)} />
        <SummaryCard icon={<Box size={18} />} color="bg-success-bg text-success" label="Aktiv" value={String(activeCount)} />
        <SummaryCard icon={<Box size={18} />} color="bg-ai-bg text-ai" label="Durchschnittspreis" value={money(avgPrice)} />
      </div>

      <div className="mb-4 grid gap-3 md:grid-cols-[1fr_220px_180px]">
        <div className="relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Suchen…" className="w-full rounded-md border border-border bg-surface py-2.5 pl-9 pr-3 text-sm text-text outline-none focus:border-green-primary" />
        </div>
        <select value={cat} onChange={(e) => setCat(e.target.value)} className={inputCls}><option value="all">Kategorie</option>{categories.map((c) => <option key={c} value={c}>{c}</option>)}</select>
        <select value={status} onChange={(e) => setStatus(e.target.value)} className={inputCls}><option value="active">Aktiv</option><option value="inactive">Inaktiv</option><option value="all">Alle</option></select>
      </div>

      <div className="overflow-x-auto rounded-xl border border-border bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs font-semibold uppercase tracking-wide text-muted">
              <th className="px-4 py-3"><input type="checkbox" checked={!!filtered.length && filtered.every((i) => selected.has(i.id))} onChange={(e) => setSelected(e.target.checked ? new Set(filtered.map((i) => i.id)) : new Set())} className="h-4 w-4 accent-green-primary" /></th>
              <th className="px-4 py-3">Artikel-Nr.</th>
              <th className="px-4 py-3">Bezeichnung</th>
              <th className="px-4 py-3">Kategorie</th>
              <th className="px-4 py-3">Einheit</th>
              <th className="px-4 py-3 text-right">Verkaufspreis</th>
              <th className="px-4 py-3 text-right">Einkaufspreis</th>
              <th className="px-4 py-3 text-right">Marge</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Aktionen</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((i) => (
              <tr key={i.id} className="border-b border-border-faint last:border-0">
                <td className="px-4 py-3"><input type="checkbox" checked={selected.has(i.id)} onChange={() => toggle(i.id)} className="h-4 w-4 accent-green-primary" /></td>
                <td className="px-4 py-3 text-muted">{i.article_number || '–'}</td>
                <td className="px-4 py-3 font-semibold text-text">{i.name}</td>
                <td className="px-4 py-3">{i.category ? <span className="rounded-full bg-alt px-2.5 py-0.5 text-xs font-medium text-body">{i.category}</span> : '–'}</td>
                <td className="px-4 py-3 text-body">{i.unit || '–'}</td>
                <td className="px-4 py-3 text-right font-medium text-text">{money(i.unit_price)}</td>
                <td className="px-4 py-3 text-right text-body">{i.purchase_price != null ? money(i.purchase_price) : '–'}</td>
                <td className="px-4 py-3 text-right text-body">{margin(i.unit_price, i.purchase_price)}</td>
                <td className="px-4 py-3"><span className={cn('rounded-full px-2.5 py-0.5 text-xs font-medium', i.is_active ? 'bg-success-bg text-success' : 'bg-alt text-muted')}>{i.is_active ? 'Aktiv' : 'Inaktiv'}</span></td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-1 text-muted">
                    <button title="Bearbeiten" onClick={() => setEditing(i)} className="rounded-md p-1.5 text-warning hover:bg-alt"><Pencil size={15} /></button>
                    <button title="Löschen" onClick={() => confirm(`${i.name} löschen?`) && del.mutate(i.id)} className="rounded-md p-1.5 text-error hover:bg-alt"><Trash2 size={15} /></button>
                  </div>
                </td>
              </tr>
            ))}
            {!filtered.length && <tr><td colSpan={10} className="px-4 py-12 text-center text-muted">Keine Positionen.</td></tr>}
          </tbody>
        </table>
      </div>

      {editing && <PositionModal item={editing} onClose={() => setEditing(null)} onSaved={() => { qc.invalidateQueries({ queryKey: ['catalog'] }); setEditing(null) }} />}
    </div>
  )
}

function SummaryCard({ icon, color, label, value }: { icon: React.ReactNode; color: string; label: string; value: string }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-border bg-surface p-5">
      <span className={cn('flex h-11 w-11 items-center justify-center rounded-lg', color)}>{icon}</span>
      <div>
        <div className="text-xs text-muted">{label}</div>
        <div className="mt-0.5 text-xl font-bold text-text">{value}</div>
      </div>
    </div>
  )
}

function PositionModal({ item, onClose, onSaved }: { item?: CatalogItem; onClose: () => void; onSaved: () => void }) {
  const [articleNumber, setArticleNumber] = useState(item?.article_number ?? '')
  const [category, setCategory] = useState(item?.category ?? CATEGORIES[0])
  const [name, setName] = useState(item?.name ?? '')
  const [description, setDescription] = useState(item?.description ?? '')
  const [unit, setUnit] = useState(item?.unit ?? 'Stk')
  const [vat, setVat] = useState(item?.vat_rate ?? 19)
  const [isWage, setIsWage] = useState(item?.is_wage ?? false)
  const [sell, setSell] = useState(item?.unit_price ?? 0)
  const [buy, setBuy] = useState<number | ''>(item?.purchase_price ?? '')
  const [supplier, setSupplier] = useState(item?.supplier_id ?? '')
  const [active, setActive] = useState(item?.is_active ?? true)
  const [error, setError] = useState<string | null>(null)

  const { data: supplierData } = useQuery({ queryKey: ['suppliers'], queryFn: () => apiFetch<{ customers: CustomerOption[] }>('/api/customers?customer_type=supplier&limit=500') })
  const suppliers = supplierData?.customers ?? []

  const save = useMutation({
    mutationFn: () => apiFetch(item ? `/api/catalog/${item.id}` : '/api/catalog', {
      method: item ? 'PATCH' : 'POST',
      body: JSON.stringify({ article_number: articleNumber || null, category, name, description: description || null, unit, vat_rate: vat, is_wage: isWage, unit_price: sell, purchase_price: buy === '' ? null : buy, supplier_id: supplier || null, is_active: active }),
    }),
    onSuccess: onSaved,
    onError: () => setError('Speichern fehlgeschlagen.'),
  })

  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={item ? 'Position bearbeiten' : 'Neue Position'} widthClass="max-w-lg"
      footer={<div className="flex gap-3"><button onClick={onClose} className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body">Abbrechen</button><button disabled={!name.trim() || save.isPending} onClick={() => save.mutate()} className="flex-1 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">{save.isPending ? 'Speichert…' : item ? 'Aktualisieren' : 'Erstellen'}</button></div>}>
      <div className="space-y-4">
        {error && <div className="rounded-md bg-error-bg px-3 py-2 text-sm text-error">{error}</div>}
        <div className="grid grid-cols-2 gap-3">
          <div><div className={labelCls}>Artikelnummer (optional)</div><input value={articleNumber} onChange={(e) => setArticleNumber(e.target.value)} placeholder="z. B. GLX-001" className={inputCls} /></div>
          <div><div className={labelCls}>Kategorie *</div><input list="cat-list" value={category} onChange={(e) => setCategory(e.target.value)} className={inputCls} /><datalist id="cat-list">{CATEGORIES.map((c) => <option key={c} value={c} />)}</datalist></div>
        </div>
        <div><div className={labelCls}>Bezeichnung *</div><input value={name} onChange={(e) => setName(e.target.value)} placeholder="z. B. 4mm Isolierglas" className={inputCls} /></div>
        <div><div className={labelCls}>Beschreibung (optional)</div><textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} placeholder="Zusätzliche Details…" className={inputCls} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><div className={labelCls}>Einheit *</div><select value={unit} onChange={(e) => setUnit(e.target.value)} className={inputCls}>{UNITS.map((u) => <option key={u} value={u}>{u}</option>)}</select></div>
          <div><div className={labelCls}>MwSt-Satz *</div><select value={vat} onChange={(e) => setVat(Number(e.target.value))} className={inputCls}>{VATS.map((v) => <option key={v} value={v}>{v}%</option>)}</select></div>
        </div>
        <label className="flex cursor-pointer items-start gap-2">
          <input type="checkbox" checked={isWage} onChange={(e) => setIsWage(e.target.checked)} className="mt-0.5 h-4 w-4 accent-green-primary" />
          <span><span className="text-sm font-medium text-text">Lohnanteil</span><span className="block text-xs text-muted">Position wird als Arbeitsleistung markiert</span></span>
        </label>
        <div className="grid grid-cols-2 gap-3">
          <div><div className={labelCls}>Verkaufspreis netto *</div><div className="relative"><input type="number" value={sell} onChange={(e) => setSell(Number(e.target.value))} className={cn(inputCls, 'pr-7')} /><span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted">€</span></div></div>
          <div><div className={labelCls}>Einkaufspreis (optional)</div><div className="relative"><input type="number" value={buy} onChange={(e) => setBuy(e.target.value === '' ? '' : Number(e.target.value))} className={cn(inputCls, 'pr-7')} /><span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted">€</span></div></div>
        </div>
        <div><div className={labelCls}>Standardlieferant (optional)</div><select value={supplier} onChange={(e) => setSupplier(e.target.value)} className={inputCls}><option value="">– Kein Lieferant –</option>{suppliers.map((s) => <option key={s.id} value={s.id}>{s.full_name ?? 'Unbenannt'}</option>)}</select></div>
        <label className="flex items-center justify-between"><span className="text-sm font-medium text-text">Position aktiv</span><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} className="h-4 w-4 accent-green-primary" /></label>
      </div>
    </Modal>
  )
}
