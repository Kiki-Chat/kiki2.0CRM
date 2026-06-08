import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Box, Download, FileText, Pencil, Search, Trash2, Upload, Wrench } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'

import { Modal } from '../components/ui/Modal'
import { apiBlobUrl, apiFetch, apiUpload } from '../lib/api'
import { useMe } from '../lib/useMe'
import { useToast } from '../lib/useToast'
import { cn } from '../lib/utils'

// ─── Types ───────────────────────────────────────────────────────────────────
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
interface TextModule {
  id: string
  name: string
  category: string
  content: string
  sort_order: number
  is_default: boolean
}
interface Vehicle {
  id: string
  name: string
  model: string | null
  license_plate: string | null
  vehicle_type: string | null
  brand: string | null
  status: string | null
  tuev_until: string | null
  insurance_until: string | null
  next_maintenance: string | null
  max_weight_kg: number | null
  cargo_space_m3: number | null
  notes: string | null
  next_appointment: string | null
  in_use_today: boolean
  tuev_expired?: boolean
  insurance_expired?: boolean
  maintenance_overdue?: boolean
  service_alert?: boolean
}
interface Tool {
  id: string
  name: string
  category: string | null
  serial_number: string | null
  condition: string | null
  next_maintenance: string | null
  purchase_date: string | null
  purchase_price: number | null
  notes: string | null
  maintenance_overdue?: boolean
  service_alert?: boolean
}
interface CustomerOption { id: string; full_name: string | null }

const CATEGORIES = ['Montage', 'Glas', 'Material', 'Elektro', 'Sanitär', 'Heizung', 'Sonstiges']
const UNITS = ['Stk', 'm', 'm²', 'm³', 'h', 'kg', 'l', 'pauschal']
const VATS = [19, 7, 0]
const TEXT_CATEGORIES = [
  { v: 'einleitung', l: 'Einleitung' },
  { v: 'schlusstext', l: 'Schlusstext' },
  { v: 'zahlungsbedingungen', l: 'Zahlungsbedingungen' },
  { v: 'anmerkungen', l: 'Anmerkungen' },
  { v: 'sonstiges', l: 'Sonstiges' },
]
const VEHICLE_STATUS: Record<string, { l: string; cls: string }> = {
  available: { l: 'Verfügbar', cls: 'bg-success-bg text-success' },
  in_use: { l: 'Im Einsatz', cls: 'bg-info-bg text-info' },
  maintenance: { l: 'In Wartung', cls: 'bg-warning-bg text-warning' },
  inactive: { l: 'Inaktiv', cls: 'bg-alt text-muted' },
}
const TOOL_CONDITION: Record<string, { l: string; cls: string }> = {
  new: { l: 'Neu', cls: 'bg-success-bg text-success' },
  good: { l: 'Gut', cls: 'bg-info-bg text-info' },
  worn: { l: 'Abgenutzt', cls: 'bg-warning-bg text-warning' },
  defective: { l: 'Defekt', cls: 'bg-error-bg text-error' },
}
const money = (n: number | null) => '€' + (n ?? 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const margin = (s: number | null, b: number | null) => (s && b ? `${(((s - b) / s) * 100).toFixed(0)} %` : '–')
const fmtDate = (d: string | null) => (d ? new Date(d).toLocaleDateString('de-DE', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Europe/Berlin' }) : '–')
const inputCls = 'w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary'
const labelCls = 'mb-1.5 block text-xs font-semibold text-body'

type Tab = 'positions' | 'text' | 'vehicles' | 'tools'

export function CatalogPage() {
  const { isAdmin } = useMe()
  const [tab, setTab] = useState<Tab>('positions')
  const [creating, setCreating] = useState<Tab | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const qc = useQueryClient()
  const { toast, flash } = useToast()

  const { data: items = [] } = useQuery({ queryKey: ['catalog'], queryFn: () => apiFetch<CatalogItem[]>('/api/catalog') })
  const { data: textModules = [] } = useQuery({ queryKey: ['text-modules'], queryFn: () => apiFetch<TextModule[]>('/api/text-modules') })
  const { data: vehicles = [] } = useQuery({ queryKey: ['vehicles'], queryFn: () => apiFetch<Vehicle[]>('/api/vehicles') })
  const { data: tools = [] } = useQuery({ queryKey: ['tools'], queryFn: () => apiFetch<Tool[]>('/api/tools') })

  const tabs: { id: Tab; label: string; icon: typeof Box; count?: number }[] = [
    { id: 'positions', label: 'Positionen', icon: Box, count: items.length },
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

  const newBtn = (label: string) => (
    <button onClick={() => setCreating(tab)} className="inline-flex items-center gap-2 rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110">+ {label}</button>
  )

  return (
    <div className="p-8">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <Box size={26} className="text-green-primary" />
          <div>
            <h1 className="text-2xl font-bold text-text">Katalog & Vorlagen</h1>
            <p className="mt-0.5 text-sm text-muted">Positionen und Textbausteine verwalten</p>
          </div>
        </div>
        {/* Create / import are admin-only (mutations 403 an employee); CSV
            export stays available as a read action. */}
        <div className="flex items-center gap-2">
          {tab === 'positions' && (
            <>
              <button onClick={exportCsv} className="inline-flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-2 text-sm font-medium text-body hover:bg-alt"><Download size={15} /> CSV Export</button>
              {isAdmin && (
                <>
                  <button onClick={() => fileRef.current?.click()} className="inline-flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-2 text-sm font-medium text-body hover:bg-alt"><Upload size={15} /> CSV Import</button>
                  {newBtn('Neue Position')}
                  <input ref={fileRef} type="file" accept=".csv,text/csv" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f && confirm(`CSV "${f.name}" importieren?`)) importCsv.mutate(f); e.target.value = '' }} />
                </>
              )}
            </>
          )}
          {isAdmin && tab === 'text' && newBtn('Neuer Textbaustein')}
          {isAdmin && tab === 'vehicles' && newBtn('Neues Fahrzeug')}
          {isAdmin && tab === 'tools' && newBtn('Neues Werkzeug')}
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

      {tab === 'positions' && <PositionsTab items={items} flash={flash} />}
      {tab === 'text' && <TextModulesTab modules={textModules} flash={flash} onCreate={() => setCreating('text')} />}
      {tab === 'vehicles' && <VehiclesTab vehicles={vehicles} flash={flash} />}
      {tab === 'tools' && <ToolsTab tools={tools} flash={flash} />}

      {creating === 'positions' && <PositionModal onClose={() => setCreating(null)} onSaved={() => { qc.invalidateQueries({ queryKey: ['catalog'] }); setCreating(null) }} />}
      {creating === 'text' && <TextModuleModal onClose={() => setCreating(null)} onSaved={() => { qc.invalidateQueries({ queryKey: ['text-modules'] }); setCreating(null) }} />}
      {creating === 'vehicles' && <VehicleModal onClose={() => setCreating(null)} onSaved={() => { qc.invalidateQueries({ queryKey: ['vehicles'] }); setCreating(null) }} />}
      {creating === 'tools' && <ToolModal onClose={() => setCreating(null)} onSaved={() => { qc.invalidateQueries({ queryKey: ['tools'] }); setCreating(null) }} />}
    </div>
  )
}

// ─── Positionen tab ──────────────────────────────────────────────────────────
function PositionsTab({ items, flash }: { items: CatalogItem[]; flash: (m: string) => void }) {
  const qc = useQueryClient()
  const { isAdmin } = useMe()
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
        <SummaryCard color="bg-info-bg text-info" label="Gesamt" value={String(items.length)} />
        <SummaryCard color="bg-success-bg text-success" label="Aktiv" value={String(items.filter((i) => i.is_active).length)} />
        <SummaryCard color="bg-ai-bg text-ai" label="Durchschnittspreis" value={money(avgPrice)} />
      </div>
      <div className="mb-4 grid gap-3 md:grid-cols-[1fr_220px_180px]">
        <div className="relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input type="search" name="catalog-search" autoComplete="off" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Suchen…" className="w-full rounded-md border border-border bg-surface py-2.5 pl-9 pr-3 text-sm text-text outline-none focus:border-green-primary" />
        </div>
        <select value={cat} onChange={(e) => setCat(e.target.value)} className={inputCls}><option value="all">Kategorie</option>{categories.map((c) => <option key={c} value={c}>{c}</option>)}</select>
        <select value={status} onChange={(e) => setStatus(e.target.value)} className={inputCls}><option value="active">Aktiv</option><option value="inactive">Inaktiv</option><option value="all">Alle</option></select>
      </div>
      <div className="overflow-x-auto rounded-xl border border-border bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs font-semibold uppercase tracking-wide text-muted">
              <th className="px-4 py-3"><input type="checkbox" checked={!!filtered.length && filtered.every((i) => selected.has(i.id))} onChange={(e) => setSelected(e.target.checked ? new Set(filtered.map((i) => i.id)) : new Set())} className="h-4 w-4 accent-green-primary" /></th>
              <th className="px-4 py-3">Artikel-Nr.</th><th className="px-4 py-3">Bezeichnung</th><th className="px-4 py-3">Kategorie</th><th className="px-4 py-3">Einheit</th>
              <th className="px-4 py-3 text-right">Verkaufspreis</th><th className="px-4 py-3 text-right">Einkaufspreis</th><th className="px-4 py-3 text-right">Marge</th><th className="px-4 py-3">Status</th><th className="px-4 py-3 text-right">Aktionen</th>
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
                <td className="px-4 py-3"><div className="flex items-center justify-end gap-1">{isAdmin && <><button title="Bearbeiten" onClick={() => setEditing(i)} className="rounded-md p-1.5 text-warning hover:bg-alt"><Pencil size={15} /></button><button title="Löschen" onClick={() => confirm(`${i.name} löschen?`) && del.mutate(i.id)} className="rounded-md p-1.5 text-error hover:bg-alt"><Trash2 size={15} /></button></>}</div></td>
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

function SummaryCard({ color, label, value }: { color: string; label: string; value: string }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-border bg-surface p-5">
      <span className={cn('flex h-11 w-11 items-center justify-center rounded-lg', color)}><Box size={18} /></span>
      <div><div className="text-xs text-muted">{label}</div><div className="mt-0.5 text-xl font-bold text-text">{value}</div></div>
    </div>
  )
}

// ─── Textbausteine tab ───────────────────────────────────────────────────────
function TextModulesTab({ modules, flash, onCreate }: { modules: TextModule[]; flash: (m: string) => void; onCreate: () => void }) {
  const qc = useQueryClient()
  const { isAdmin } = useMe()
  const [cat, setCat] = useState('all')
  const [editing, setEditing] = useState<TextModule | null>(null)
  const filtered = modules.filter((m) => cat === 'all' || m.category === cat)
  const del = useMutation({
    mutationFn: (id: string) => apiFetch(`/api/text-modules/${id}`, { method: 'DELETE' }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['text-modules'] }); flash('Textbaustein gelöscht.') },
  })
  const catLabel = (v: string) => TEXT_CATEGORIES.find((c) => c.v === v)?.l ?? v

  return (
    <div>
      <div className="mb-4 flex items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3">
        <FileText size={16} className="text-muted" />
        <select value={cat} onChange={(e) => setCat(e.target.value)} className="rounded-md border border-border bg-alt px-3 py-1.5 text-sm text-text outline-none focus:border-green-primary"><option value="all">Alle Kategorien</option>{TEXT_CATEGORIES.map((c) => <option key={c.v} value={c.v}>{c.l}</option>)}</select>
        <span className="text-sm text-muted">{filtered.length} Einträge</span>
      </div>
      {filtered.length ? (
        <div className="overflow-hidden rounded-xl border border-border bg-surface">
          {filtered.map((m) => (
            <div key={m.id} className="flex items-center gap-4 border-b border-border-faint px-5 py-3.5 last:border-0">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-text">{m.name}</span>
                  <span className="rounded-full bg-alt px-2 py-0.5 text-xs text-muted">{catLabel(m.category)}</span>
                  {m.is_default && <span className="rounded-full bg-green-tint-100 px-2 py-0.5 text-xs font-medium text-green-deep">Als Standard</span>}
                </div>
                <div className="mt-0.5 truncate text-sm text-muted">{m.content}</div>
              </div>
              {isAdmin && (
                <div className="flex items-center gap-1">
                  <button title="Bearbeiten" onClick={() => setEditing(m)} className="rounded-md p-1.5 text-warning hover:bg-alt"><Pencil size={15} /></button>
                  <button title="Löschen" onClick={() => confirm(`${m.name} löschen?`) && del.mutate(m.id)} className="rounded-md p-1.5 text-error hover:bg-alt"><Trash2 size={15} /></button>
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-surface py-20 text-center">
          <FileText size={44} className="mx-auto mb-4 text-faint" strokeWidth={1.5} />
          <div className="text-lg font-bold text-text">Keine Textbausteine vorhanden</div>
          <p className="mt-1 text-sm text-muted">Erstellen Sie Ihren ersten Textbaustein.</p>
          {isAdmin && <button onClick={onCreate} className="mt-4 inline-flex items-center gap-2 rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110">+ Textbaustein erstellen</button>}
        </div>
      )}
      {editing && <TextModuleModal module={editing} onClose={() => setEditing(null)} onSaved={() => { qc.invalidateQueries({ queryKey: ['text-modules'] }); setEditing(null) }} />}
    </div>
  )
}

// ─── Fahrzeuge tab ───────────────────────────────────────────────────────────
function VehiclesTab({ vehicles, flash }: { vehicles: Vehicle[]; flash: (m: string) => void }) {
  const { isAdmin } = useMe()
  const qc = useQueryClient()
  const [status, setStatus] = useState('all')
  const [editing, setEditing] = useState<Vehicle | null>(null)
  // An expired TÜV / insurance or overdue maintenance overrides the stored status
  // so the vehicle reads as needing attention (and is filterable under "In Wartung").
  const effStatus = (v: Vehicle) => (v.service_alert ? 'maintenance' : v.in_use_today ? 'in_use' : v.status || 'available')
  const alertLabel = (v: Vehicle) =>
    [v.tuev_expired && 'TÜV', v.insurance_expired && 'Versicherung', v.maintenance_overdue && 'Wartung']
      .filter(Boolean)
      .join(' · ')
  const filtered = vehicles.filter((v) => status === 'all' || effStatus(v) === status)
  const del = useMutation({
    mutationFn: (id: string) => apiFetch(`/api/vehicles/${id}`, { method: 'DELETE' }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['vehicles'] }); flash('Fahrzeug deaktiviert.') },
  })
  return (
    <div>
      <div className="mb-4"><select value={status} onChange={(e) => setStatus(e.target.value)} className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-green-primary"><option value="all">Alle Status</option>{Object.entries(VEHICLE_STATUS).map(([v, m]) => <option key={v} value={v}>{m.l}</option>)}</select></div>
      <div className="overflow-x-auto rounded-xl border border-border bg-surface">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left text-xs font-semibold uppercase tracking-wide text-muted">
            <th className="px-5 py-3">Kennzeichen</th><th className="px-5 py-3">Bezeichnung</th><th className="px-5 py-3">Typ</th><th className="px-5 py-3">Status</th><th className="px-5 py-3">Nächste Termine</th><th className="px-5 py-3 text-right">Aktionen</th>
          </tr></thead>
          <tbody>
            {filtered.map((v) => { const s = VEHICLE_STATUS[effStatus(v)] ?? VEHICLE_STATUS.available; return (
              <tr key={v.id} className="border-b border-border-faint last:border-0">
                <td className="px-5 py-3.5 font-semibold text-text">{v.license_plate || v.name}</td>
                <td className="px-5 py-3.5 text-body">{v.model || v.name}</td>
                <td className="px-5 py-3.5 text-body">{v.vehicle_type || '–'}</td>
                <td className="px-5 py-3.5">
                  <div className="flex flex-col items-start gap-1">
                    <span className={cn('rounded-full px-2.5 py-0.5 text-xs font-medium', s.cls)}>{s.l}</span>
                    {v.service_alert && (
                      <span
                        title={`Nicht einsatzbereit: ${alertLabel(v)} abgelaufen/fällig`}
                        className="rounded-full bg-error-bg px-2.5 py-0.5 text-xs font-semibold text-error"
                      >
                        ⚠ {alertLabel(v)} fällig
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-5 py-3.5 text-body">{fmtDate(v.next_appointment)}</td>
                <td className="px-5 py-3.5"><div className="flex items-center justify-end gap-1">{isAdmin && <><button title="Bearbeiten" onClick={() => setEditing(v)} className="rounded-md p-1.5 text-warning hover:bg-alt"><Pencil size={15} /></button><button title="Deaktivieren" onClick={() => confirm(`${v.name} deaktivieren?`) && del.mutate(v.id)} className="rounded-md p-1.5 text-error hover:bg-alt"><Trash2 size={15} /></button></>}</div></td>
              </tr>
            )})}
            {!filtered.length && <tr><td colSpan={6} className="px-5 py-12 text-center text-muted">Keine Fahrzeuge.</td></tr>}
          </tbody>
        </table>
      </div>
      {editing && <VehicleModal vehicle={editing} onClose={() => setEditing(null)} onSaved={() => { qc.invalidateQueries({ queryKey: ['vehicles'] }); setEditing(null) }} />}
    </div>
  )
}

// ─── Werkzeug tab ────────────────────────────────────────────────────────────
function ToolsTab({ tools, flash }: { tools: Tool[]; flash: (m: string) => void }) {
  const { isAdmin } = useMe()
  const qc = useQueryClient()
  const [cond, setCond] = useState('all')
  const [editing, setEditing] = useState<Tool | null>(null)
  const filtered = tools.filter((t) => cond === 'all' || (t.condition || 'new') === cond)
  const del = useMutation({
    mutationFn: (id: string) => apiFetch(`/api/tools/${id}`, { method: 'DELETE' }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['tools'] }); flash('Werkzeug deaktiviert.') },
  })
  return (
    <div>
      <div className="mb-4"><select value={cond} onChange={(e) => setCond(e.target.value)} className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-green-primary"><option value="all">Alle Zustände</option>{Object.entries(TOOL_CONDITION).map(([v, m]) => <option key={v} value={v}>{m.l}</option>)}</select></div>
      <div className="overflow-x-auto rounded-xl border border-border bg-surface">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left text-xs font-semibold uppercase tracking-wide text-muted">
            <th className="px-5 py-3">Bezeichnung</th><th className="px-5 py-3">Kategorie</th><th className="px-5 py-3">Seriennummer</th><th className="px-5 py-3">Zustand</th><th className="px-5 py-3">Wartung</th><th className="px-5 py-3 text-right">Aktionen</th>
          </tr></thead>
          <tbody>
            {filtered.map((t) => { const c = TOOL_CONDITION[t.condition || 'new'] ?? TOOL_CONDITION.new; return (
              <tr key={t.id} className="border-b border-border-faint last:border-0">
                <td className="px-5 py-3.5 font-semibold text-text">{t.name}</td>
                <td className="px-5 py-3.5 text-body">{t.category || '–'}</td>
                <td className="px-5 py-3.5 text-body">{t.serial_number || '–'}</td>
                <td className="px-5 py-3.5"><span className={cn('rounded-full px-2.5 py-0.5 text-xs font-medium', c.cls)}>{c.l}</span></td>
                <td className="px-5 py-3.5">
                  {t.maintenance_overdue ? (
                    <span
                      title="Wartung überfällig — nicht einsatzbereit"
                      className="rounded-full bg-error-bg px-2.5 py-0.5 text-xs font-semibold text-error"
                    >
                      ⚠ {fmtDate(t.next_maintenance)}
                    </span>
                  ) : (
                    <span className="text-body">{fmtDate(t.next_maintenance)}</span>
                  )}
                </td>
                <td className="px-5 py-3.5"><div className="flex items-center justify-end gap-1">{isAdmin && <><button title="Bearbeiten" onClick={() => setEditing(t)} className="rounded-md p-1.5 text-warning hover:bg-alt"><Pencil size={15} /></button><button title="Deaktivieren" onClick={() => confirm(`${t.name} deaktivieren?`) && del.mutate(t.id)} className="rounded-md p-1.5 text-error hover:bg-alt"><Trash2 size={15} /></button></>}</div></td>
              </tr>
            )})}
            {!filtered.length && <tr><td colSpan={6} className="px-5 py-12 text-center text-muted">Keine Werkzeuge.</td></tr>}
          </tbody>
        </table>
      </div>
      {editing && <ToolModal tool={editing} onClose={() => setEditing(null)} onSaved={() => { qc.invalidateQueries({ queryKey: ['tools'] }); setEditing(null) }} />}
    </div>
  )
}

// ─── Position modal ──────────────────────────────────────────────────────────
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
    mutationFn: () => apiFetch(item ? `/api/catalog/${item.id}` : '/api/catalog', { method: item ? 'PATCH' : 'POST', body: JSON.stringify({ article_number: articleNumber || null, category, name, description: description || null, unit, vat_rate: vat, is_wage: isWage, unit_price: sell, purchase_price: buy === '' ? null : buy, supplier_id: supplier || null, is_active: active }) }),
    onSuccess: onSaved, onError: () => setError('Speichern fehlgeschlagen.'),
  })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={item ? 'Position bearbeiten' : 'Neue Position'} widthClass="max-w-lg"
      footer={<ModalFooter onClose={onClose} disabled={!name.trim() || save.isPending} pending={save.isPending} edit={!!item} onSave={() => save.mutate()} />}>
      <div className="space-y-4">
        {error && <ErrBox msg={error} />}
        <div className="grid grid-cols-2 gap-3">
          <div><div className={labelCls}>Artikelnummer (optional)</div><input value={articleNumber} onChange={(e) => setArticleNumber(e.target.value)} placeholder="z. B. GLX-001" className={inputCls} /></div>
          <div><div className={labelCls}>Kategorie *</div><input list="cat-list" value={category} onChange={(e) => setCategory(e.target.value)} className={inputCls} /><datalist id="cat-list">{CATEGORIES.map((c) => <option key={c} value={c} />)}</datalist></div>
        </div>
        <div><div className={labelCls}>Bezeichnung *</div><input value={name} onChange={(e) => setName(e.target.value)} placeholder="z. B. 4mm Isolierglas" className={inputCls} /></div>
        <div><div className={labelCls}>Beschreibung (optional)</div><textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} className={inputCls} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><div className={labelCls}>Einheit *</div><select value={unit} onChange={(e) => setUnit(e.target.value)} className={inputCls}>{UNITS.map((u) => <option key={u} value={u}>{u}</option>)}</select></div>
          <div><div className={labelCls}>MwSt-Satz *</div><select value={vat} onChange={(e) => setVat(Number(e.target.value))} className={inputCls}>{VATS.map((v) => <option key={v} value={v}>{v}%</option>)}</select></div>
        </div>
        <label className="flex cursor-pointer items-start gap-2"><input type="checkbox" checked={isWage} onChange={(e) => setIsWage(e.target.checked)} className="mt-0.5 h-4 w-4 accent-green-primary" /><span><span className="text-sm font-medium text-text">Lohnanteil</span><span className="block text-xs text-muted">Position wird als Arbeitsleistung markiert</span></span></label>
        <div className="grid grid-cols-2 gap-3">
          <div><div className={labelCls}>Verkaufspreis netto *</div><EuroInput value={sell} onChange={setSell} /></div>
          <div><div className={labelCls}>Einkaufspreis (optional)</div><div className="relative"><input type="number" value={buy} onChange={(e) => setBuy(e.target.value === '' ? '' : Number(e.target.value))} className={cn(inputCls, 'pr-7')} /><span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted">€</span></div></div>
        </div>
        <div><div className={labelCls}>Standardlieferant (optional)</div><select value={supplier} onChange={(e) => setSupplier(e.target.value)} className={inputCls}><option value="">– Kein Lieferant –</option>{suppliers.map((s) => <option key={s.id} value={s.id}>{s.full_name ?? 'Unbenannt'}</option>)}</select></div>
        <label className="flex items-center justify-between"><span className="text-sm font-medium text-text">Position aktiv</span><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} className="h-4 w-4 accent-green-primary" /></label>
      </div>
    </Modal>
  )
}

// ─── Text module modal ───────────────────────────────────────────────────────
function TextModuleModal({ module, onClose, onSaved }: { module?: TextModule; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(module?.name ?? '')
  const [category, setCategory] = useState(module?.category ?? 'einleitung')
  const [sortOrder, setSortOrder] = useState(module?.sort_order ?? 0)
  const [content, setContent] = useState(module?.content ?? '')
  const [isDefault, setIsDefault] = useState(module?.is_default ?? false)
  const [error, setError] = useState<string | null>(null)
  const save = useMutation({
    mutationFn: () => apiFetch(module ? `/api/text-modules/${module.id}` : '/api/text-modules', { method: module ? 'PATCH' : 'POST', body: JSON.stringify({ name, category, sort_order: sortOrder, content, is_default: isDefault }) }),
    onSuccess: onSaved, onError: () => setError('Speichern fehlgeschlagen.'),
  })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={module ? 'Textbaustein bearbeiten' : 'Neuer Textbaustein'} widthClass="max-w-lg"
      footer={<ModalFooter onClose={onClose} disabled={!name.trim() || !content.trim() || save.isPending} pending={save.isPending} edit={!!module} onSave={() => save.mutate()} />}>
      <div className="space-y-4">
        {error && <ErrBox msg={error} />}
        <div><div className={labelCls}>Name *</div><input value={name} onChange={(e) => setName(e.target.value)} placeholder="z. B. Standard-Einleitung Rechnung" className={inputCls} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><div className={labelCls}>Kategorie *</div><select value={category} onChange={(e) => setCategory(e.target.value)} className={inputCls}>{TEXT_CATEGORIES.map((c) => <option key={c.v} value={c.v}>{c.l}</option>)}</select></div>
          <div><div className={labelCls}>Sortierung</div><input type="number" value={sortOrder} onChange={(e) => setSortOrder(Number(e.target.value))} className={inputCls} /></div>
        </div>
        <div><div className={labelCls}>Inhalt *</div><textarea value={content} onChange={(e) => setContent(e.target.value)} rows={5} placeholder="Text eingeben…" className={inputCls} /></div>
        <label className="flex cursor-pointer items-start gap-2"><input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} className="mt-0.5 h-4 w-4 accent-green-primary" /><span><span className="text-sm font-medium text-text">Als Standard verwenden</span><span className="block text-xs text-muted">Wird automatisch in neue Dokumente eingefügt</span></span></label>
      </div>
    </Modal>
  )
}

// ─── Vehicle modal ───────────────────────────────────────────────────────────
function VehicleModal({ vehicle, onClose, onSaved }: { vehicle?: Vehicle; onClose: () => void; onSaved: () => void }) {
  const [plate, setPlate] = useState(vehicle?.license_plate ?? '')
  const [name, setName] = useState(vehicle?.name ?? '')
  const [vtype, setVtype] = useState(vehicle?.vehicle_type ?? '')
  const [status, setStatus] = useState(vehicle?.status ?? 'available')
  const [brand, setBrand] = useState(vehicle?.brand ?? '')
  const [model, setModel] = useState(vehicle?.model ?? '')
  const [tuev, setTuev] = useState(vehicle?.tuev_until ?? '')
  const [insurance, setInsurance] = useState(vehicle?.insurance_until ?? '')
  const [maint, setMaint] = useState(vehicle?.next_maintenance ?? '')
  const [weight, setWeight] = useState<number | ''>(vehicle?.max_weight_kg ?? '')
  const [cargo, setCargo] = useState<number | ''>(vehicle?.cargo_space_m3 ?? '')
  const [notes, setNotes] = useState(vehicle?.notes ?? '')
  const [error, setError] = useState<string | null>(null)
  const save = useMutation({
    mutationFn: () => apiFetch(vehicle ? `/api/vehicles/${vehicle.id}` : '/api/vehicles', { method: vehicle ? 'PATCH' : 'POST', body: JSON.stringify({ license_plate: plate || null, name: name || plate, vehicle_type: vtype || null, status, brand: brand || null, model: model || null, tuev_until: tuev || null, insurance_until: insurance || null, next_maintenance: maint || null, max_weight_kg: weight === '' ? null : weight, cargo_space_m3: cargo === '' ? null : cargo, notes: notes || null }) }),
    onSuccess: onSaved, onError: () => setError('Speichern fehlgeschlagen.'),
  })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={vehicle ? 'Fahrzeug bearbeiten' : 'Neues Fahrzeug'} widthClass="max-w-xl"
      footer={<ModalFooter onClose={onClose} disabled={!plate.trim() || !name.trim() || save.isPending} pending={save.isPending} edit={!!vehicle} onSave={() => save.mutate()} saveLabel="Speichern" />}>
      <div className="grid grid-cols-2 gap-3">
        {error && <div className="col-span-2"><ErrBox msg={error} /></div>}
        <div><div className={labelCls}>Kennzeichen *</div><input value={plate} onChange={(e) => setPlate(e.target.value)} placeholder="B-MD-2023" className={inputCls} /></div>
        <div><div className={labelCls}>Bezeichnung *</div><input value={name} onChange={(e) => setName(e.target.value)} placeholder="Sprinter Sanitär 1" className={inputCls} /></div>
        <div><div className={labelCls}>Typ</div><input value={vtype} onChange={(e) => setVtype(e.target.value)} placeholder="Transporter, PKW, Anhänger" className={inputCls} /></div>
        <div><div className={labelCls}>Status</div><select value={status} onChange={(e) => setStatus(e.target.value)} className={inputCls}>{Object.entries(VEHICLE_STATUS).map(([v, m]) => <option key={v} value={v}>{m.l}</option>)}</select></div>
        <div><div className={labelCls}>Marke</div><input value={brand} onChange={(e) => setBrand(e.target.value)} placeholder="Mercedes" className={inputCls} /></div>
        <div><div className={labelCls}>Modell</div><input value={model} onChange={(e) => setModel(e.target.value)} placeholder="Sprinter 316" className={inputCls} /></div>
        <div><div className={labelCls}>TÜV bis</div><input type="date" value={tuev} onChange={(e) => setTuev(e.target.value)} className={inputCls} /></div>
        <div><div className={labelCls}>Versicherung bis</div><input type="date" value={insurance} onChange={(e) => setInsurance(e.target.value)} className={inputCls} /></div>
        <div><div className={labelCls}>Nächste Wartung</div><input type="date" value={maint} onChange={(e) => setMaint(e.target.value)} className={inputCls} /></div>
        <div><div className={labelCls}>Max. Gewicht (kg)</div><input type="number" value={weight} onChange={(e) => setWeight(e.target.value === '' ? '' : Number(e.target.value))} className={inputCls} /></div>
        <div className="col-span-2"><div className={labelCls}>Laderaum (m³)</div><input type="number" value={cargo} onChange={(e) => setCargo(e.target.value === '' ? '' : Number(e.target.value))} className={inputCls} /></div>
        <div className="col-span-2"><div className={labelCls}>Bemerkung</div><textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className={inputCls} /></div>
      </div>
    </Modal>
  )
}

// ─── Tool modal ──────────────────────────────────────────────────────────────
function ToolModal({ tool, onClose, onSaved }: { tool?: Tool; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(tool?.name ?? '')
  const [category, setCategory] = useState(tool?.category ?? '')
  const [condition, setCondition] = useState(tool?.condition ?? 'new')
  const [serial, setSerial] = useState(tool?.serial_number ?? '')
  const [maint, setMaint] = useState(tool?.next_maintenance ?? '')
  const [purchaseDate, setPurchaseDate] = useState(tool?.purchase_date ?? '')
  const [price, setPrice] = useState<number | ''>(tool?.purchase_price ?? '')
  const [notes, setNotes] = useState(tool?.notes ?? '')
  const [error, setError] = useState<string | null>(null)
  const save = useMutation({
    mutationFn: () => apiFetch(tool ? `/api/tools/${tool.id}` : '/api/tools', { method: tool ? 'PATCH' : 'POST', body: JSON.stringify({ name, category: category || null, condition, serial_number: serial || null, next_maintenance: maint || null, purchase_date: purchaseDate || null, purchase_price: price === '' ? null : price, notes: notes || null }) }),
    onSuccess: onSaved, onError: () => setError('Speichern fehlgeschlagen.'),
  })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={tool ? 'Werkzeug bearbeiten' : 'Neues Werkzeug'} widthClass="max-w-lg"
      footer={<ModalFooter onClose={onClose} disabled={!name.trim() || save.isPending} pending={save.isPending} edit={!!tool} onSave={() => save.mutate()} saveLabel="Speichern" />}>
      <div className="space-y-4">
        {error && <ErrBox msg={error} />}
        <div><div className={labelCls}>Bezeichnung *</div><input value={name} onChange={(e) => setName(e.target.value)} placeholder="Hilti TE 30 Bohrhammer" className={inputCls} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><div className={labelCls}>Kategorie</div><input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Elektro, Hand, Schutz" className={inputCls} /></div>
          <div><div className={labelCls}>Zustand</div><select value={condition} onChange={(e) => setCondition(e.target.value)} className={inputCls}>{Object.entries(TOOL_CONDITION).map(([v, m]) => <option key={v} value={v}>{m.l}</option>)}</select></div>
        </div>
        <div><div className={labelCls}>Seriennummer</div><input value={serial} onChange={(e) => setSerial(e.target.value)} className={inputCls} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><div className={labelCls}>Nächste Wartung</div><input type="date" value={maint} onChange={(e) => setMaint(e.target.value)} className={inputCls} /></div>
          <div><div className={labelCls}>Kaufdatum</div><input type="date" value={purchaseDate} onChange={(e) => setPurchaseDate(e.target.value)} className={inputCls} /></div>
        </div>
        <div><div className={labelCls}>Kaufpreis (€)</div><div className="relative"><input type="number" value={price} onChange={(e) => setPrice(e.target.value === '' ? '' : Number(e.target.value))} className={cn(inputCls, 'pr-7')} /><span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted">€</span></div></div>
        <div><div className={labelCls}>Bemerkung</div><textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className={inputCls} /></div>
      </div>
    </Modal>
  )
}

// ─── Shared modal bits ───────────────────────────────────────────────────────
function ErrBox({ msg }: { msg: string }) { return <div className="rounded-md bg-error-bg px-3 py-2 text-sm text-error">{msg}</div> }
function EuroInput({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  return <div className="relative"><input type="number" value={value} onChange={(e) => onChange(Number(e.target.value))} className={cn(inputCls, 'pr-7')} /><span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted">€</span></div>
}
function ModalFooter({ onClose, onSave, disabled, pending, edit, saveLabel }: { onClose: () => void; onSave: () => void; disabled: boolean; pending: boolean; edit: boolean; saveLabel?: string }) {
  return (
    <div className="flex gap-3">
      <button onClick={onClose} className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body">Abbrechen</button>
      <button disabled={disabled} onClick={onSave} className="flex-1 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">{pending ? 'Speichert…' : saveLabel ?? (edit ? 'Aktualisieren' : 'Erstellen')}</button>
    </div>
  )
}
