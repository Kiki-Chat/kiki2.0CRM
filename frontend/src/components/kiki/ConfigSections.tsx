import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowUpDown, Clock, FileText, Globe, Info, Lock, Phone, Plus, RefreshCw,
  Siren, Trash2, X,
} from 'lucide-react'
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { apiFetch, apiUpload } from '../../lib/api'
import {
  KZ, type KzCategory, type KzOverview, type KzRequiredField, type KzResource, type KzService,
} from '../../lib/kikiApi'
import { cn } from '../../lib/utils'
import { Modal } from '../ui/Modal'
import { Tag } from '../ui/Tag'
import { Card, Field, GroupLabel, inputCls, labelCls, SaveBar, StatusBadge, Toggle } from './shared'

type Props = { data: KzOverview; flash: (m: string) => void }

const TRADES = ['Heizung & Sanitär', 'Elektro', 'Schlüsseldienst', 'Dachdecker', 'Maler & Lackierer', 'Tischler/Schreiner', 'Garten- & Landschaftsbau', 'SHK', 'Sonstiges']
const WEEKDAYS: [string, string][] = [['mon', 'Mo'], ['tue', 'Di'], ['wed', 'Mi'], ['thu', 'Do'], ['fri', 'Fr'], ['sat', 'Sa'], ['sun', 'So']]
const OCCASIONS: [string, string][] = [
  ['kva_followup', 'KVA-Nachfassen'], ['appointment_reminder', 'Terminerinnerung'],
  ['payment_reminder', 'Zahlungserinnerung'], ['maintenance_due', 'Wartung fällig'],
  ['satisfaction_survey', 'Zufriedenheitsumfrage'], ['missed_call_callback', 'Rückruf bei verpasstem Anruf'],
  ['review_request', 'Bewertungsanfrage'],
]

function useConfigPatch(path: string, flash: (m: string) => void) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => apiFetch(`${KZ}${path}`, { method: 'PATCH', body: JSON.stringify(body) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['kiki-zentrale'] }); flash('Gespeichert.') },
    onError: (e: Error) => flash(e.message || 'Speichern fehlgeschlagen.'),
  })
}

// ─── Pflichtfelder ───────────────────────────────────────────────────────────
export function PflichtfelderSection({ flash }: Props) {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['kiki-zentrale', 'required-fields'], queryFn: () => apiFetch<{ fields: KzRequiredField[] }>(`${KZ}/required-fields`) })
  const fields = data?.fields ?? []
  const [newKey, setNewKey] = useState('')
  const [newLabel, setNewLabel] = useState('')
  const dragIdx = useRef<number | null>(null)

  const create = useMutation({
    mutationFn: () => apiFetch(`${KZ}/required-fields`, { method: 'POST', body: JSON.stringify({ field_key: newKey || newLabel.toLowerCase().replace(/\s+/g, '_'), label: newLabel }) }),
    onSuccess: () => { setNewKey(''); setNewLabel(''); qc.invalidateQueries({ queryKey: ['kiki-zentrale', 'required-fields'] }) },
  })
  const del = useMutation({
    mutationFn: (id: string) => apiFetch(`${KZ}/required-fields/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['kiki-zentrale', 'required-fields'] }),
    onError: (e: Error) => flash(e.message || 'Löschen fehlgeschlagen.'),
  })
  const reorder = useMutation({
    mutationFn: (ids: string[]) => apiFetch(`${KZ}/required-fields/reorder`, { method: 'POST', body: JSON.stringify({ ordered_ids: ids }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['kiki-zentrale', 'required-fields'] }),
  })

  const onDrop = (to: number) => {
    const from = dragIdx.current
    dragIdx.current = null
    if (from === null || from === to) return
    const ids = fields.map((f) => f.id)
    const [m] = ids.splice(from, 1)
    ids.splice(to, 0, m)
    reorder.mutate(ids)
  }
  const idRoles = fields.filter((f) => f.identification_role)

  return (
    <div className="space-y-4">
      <Card>
        <GroupLabel>Kundenidentifikation</GroupLabel>
        <p className="text-sm text-muted">Kiki erkennt Anrufer automatisch anhand dieser Merkmale und ordnet sie bestehenden Kunden zu.</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {idRoles.length === 0 && <span className="text-sm text-faint">Keine Identifikationsmerkmale konfiguriert.</span>}
          {idRoles.map((f) => (
            <Tag key={f.id} variant="info">{f.label} · {f.identification_role}</Tag>
          ))}
        </div>
      </Card>

      <Card>
        <div className="mb-3 flex items-center justify-between">
          <GroupLabel>Immer abgefragte Felder</GroupLabel>
          <span className="text-xs text-muted">Ziehen zum Sortieren</span>
        </div>
        <div className="space-y-2">
          {fields.map((f, i) => (
            <div
              key={f.id}
              draggable
              onDragStart={() => (dragIdx.current = i)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => onDrop(i)}
              className="flex items-center gap-3 rounded-lg border border-border bg-alt px-3 py-2"
            >
              <ArrowUpDown size={15} className="cursor-grab text-faint" />
              <div className="flex-1">
                <div className="flex items-center gap-2 text-sm font-medium text-text">
                  {f.label}
                  {f.is_locked && <Lock size={12} className="text-faint" />}
                  {f.is_duty && <Tag variant="green">Pflicht</Tag>}
                </div>
                {f.description && <div className="text-xs text-muted">{f.description}</div>}
              </div>
              <button
                disabled={f.is_locked}
                onClick={() => del.mutate(f.id)}
                title={f.is_locked ? 'Gesperrtes Feld' : 'Entfernen'}
                className="text-muted hover:text-error disabled:opacity-30"
              >
                <Trash2 size={15} />
              </button>
            </div>
          ))}
        </div>
        <div className="mt-4 flex items-end gap-2 border-t border-border pt-4">
          <div className="flex-1">
            <Field label="Neues Feld"><input value={newLabel} onChange={(e) => setNewLabel(e.target.value)} placeholder="z. B. E-Mail-Adresse" className={inputCls} /></Field>
          </div>
          <button onClick={() => newLabel.trim() && create.mutate()} disabled={!newLabel.trim() || create.isPending} className="rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">
            Hinzufügen
          </button>
        </div>
      </Card>
    </div>
  )
}

// ─── Branche & Kontext ───────────────────────────────────────────────────────
export function BrancheKontextSection({ data, flash }: Props) {
  const qc = useQueryClient()
  const patch = useConfigPatch('/context', flash)
  const [trade, setTrade] = useState(data.config.trade ?? '')
  const [knowledge, setKnowledge] = useState(data.config.knowledge_text ?? '')
  const [urlOpen, setUrlOpen] = useState(false)
  const [url, setUrl] = useState('')
  const [urlName, setUrlName] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const { data: resData } = useQuery({ queryKey: ['kiki-zentrale', 'knowledge-resources'], queryFn: () => apiFetch<{ resources: KzResource[] }>(`${KZ}/knowledge-resources`) })
  const resources = resData?.resources ?? []
  const invRes = () => qc.invalidateQueries({ queryKey: ['kiki-zentrale', 'knowledge-resources'] })

  const addUrl = useMutation({
    mutationFn: () => apiFetch(`${KZ}/knowledge-resources/url`, { method: 'POST', body: JSON.stringify({ url, display_name: urlName || url }) }),
    onSuccess: () => { setUrlOpen(false); setUrl(''); setUrlName(''); invRes(); flash('Wissens-Quelle hinzugefügt.') },
    onError: (e: Error) => flash(e.message || 'Hinzufügen fehlgeschlagen.'),
  })
  const addPdf = useMutation({
    mutationFn: (file: File) => { const fd = new FormData(); fd.append('file', file); return apiUpload(`${KZ}/knowledge-resources/pdf`, fd) },
    onSuccess: () => { invRes(); flash('PDF hinzugefügt.') },
    onError: (e: Error) => flash(e.message || 'Upload fehlgeschlagen.'),
  })
  const delRes = useMutation({ mutationFn: (id: string) => apiFetch(`${KZ}/knowledge-resources/${id}`, { method: 'DELETE' }), onSuccess: invRes })
  const reindex = useMutation({ mutationFn: (id: string) => apiFetch(`${KZ}/knowledge-resources/${id}/reindex`, { method: 'POST' }), onSuccess: invRes })

  return (
    <div className="space-y-4">
      <Card>
        <GroupLabel>Branche</GroupLabel>
        <select
          value={trade}
          onChange={(e) => { setTrade(e.target.value); patch.mutate({ trade: e.target.value }) }}
          className={cn(inputCls, 'max-w-sm')}
        >
          <option value="">— Branche wählen —</option>
          {TRADES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </Card>

      <Card>
        <GroupLabel>Wissens-Text</GroupLabel>
        <p className="mb-2 text-sm text-muted">Kurze Anweisungen, die dem System-Prompt zur Laufzeit vorangestellt werden.</p>
        <textarea value={knowledge} maxLength={15000} onChange={(e) => setKnowledge(e.target.value)} className={cn(inputCls, 'min-h-[160px]')} />
        <div className="mt-2 flex items-center justify-between">
          <span className="text-xs text-muted">{knowledge.length}/15.000 Zeichen</span>
          <button onClick={() => patch.mutate({ knowledge_text: knowledge })} disabled={patch.isPending} className="rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-body hover:bg-alt disabled:opacity-50">
            Text speichern
          </button>
        </div>
      </Card>

      <Card>
        <div className="mb-3 flex items-center justify-between">
          <GroupLabel>Wissens-Quellen (ElevenLabs Wissensdatenbank)</GroupLabel>
          <div className="flex items-center gap-2">
            <button onClick={() => setUrlOpen(true)} className="flex items-center gap-1.5 rounded-md border border-border bg-surface px-3 py-1.5 text-sm font-medium text-body hover:bg-alt"><Globe size={14} /> URL</button>
            <button onClick={() => fileRef.current?.click()} className="flex items-center gap-1.5 rounded-md bg-green-primary px-3 py-1.5 text-sm font-semibold text-white hover:brightness-110"><Plus size={14} /> PDF</button>
            <input ref={fileRef} type="file" accept="application/pdf" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) addPdf.mutate(f); e.target.value = '' }} />
          </div>
        </div>
        {resources.length === 0 && <div className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted">Noch keine Wissens-Quellen.</div>}
        <div className="space-y-2">
          {resources.map((r) => {
            const exists = resources.some((o) => o.id !== r.id && o.source === r.source)
            return (
              <div key={r.id} className="flex items-center gap-3 rounded-lg border border-border px-3 py-2">
                {r.kind === 'url' ? <Globe size={16} className="text-info" /> : <FileText size={16} className="text-error" />}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-text">{r.display_name}</div>
                  <div className="truncate text-xs text-muted">{r.source} · {r.chunk_count} Chunks{exists ? ' · Duplikat' : ''}</div>
                </div>
                <StatusBadge status={r.status} />
                <button onClick={() => reindex.mutate(r.id)} title="Neu indizieren" className="text-muted hover:text-body"><RefreshCw size={15} /></button>
                <button onClick={() => delRes.mutate(r.id)} title="Löschen" className="text-muted hover:text-error"><Trash2 size={15} /></button>
              </div>
            )
          })}
        </div>
      </Card>

      <Modal open={urlOpen} onOpenChange={setUrlOpen} title="URL als Wissens-Quelle" footer={
        <div className="flex gap-3">
          <button onClick={() => setUrlOpen(false)} className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body">Abbrechen</button>
          <button disabled={!url.trim() || addUrl.isPending} onClick={() => addUrl.mutate()} className="flex-1 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white disabled:opacity-50">Hinzufügen</button>
        </div>
      }>
        <div className="space-y-3">
          <Field label="URL"><input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" className={inputCls} /></Field>
          <Field label="Anzeigename"><input value={urlName} onChange={(e) => setUrlName(e.target.value)} placeholder="z. B. Leistungsübersicht" className={inputCls} /></Field>
        </div>
      </Modal>
    </div>
  )
}

// ─── Terminregeln ────────────────────────────────────────────────────────────
export function TerminregelnSection({ data, flash }: Props) {
  const c = data.config
  const patch = useConfigPatch('/scheduling-rules', flash)
  const [f, setF] = useState({
    scheduling_enabled: c.scheduling_enabled, buffer_minutes: c.buffer_minutes,
    max_appointments_per_day: c.max_appointments_per_day, parallel_slots: c.parallel_slots,
    lead_time_days: c.lead_time_days, lead_time_only_weekdays: c.lead_time_only_weekdays,
    lead_time_earliest_clock: c.lead_time_earliest_clock ?? '',
  })
  const set = (k: keyof typeof f, v: unknown) => setF((p) => ({ ...p, [k]: v }))

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-center justify-between">
          <div><div className="text-sm font-bold text-text">Terminvergabe aktiv</div><div className="text-xs text-muted">Kiki vereinbart eigenständig Termine im Kalender.</div></div>
          <Toggle on={f.scheduling_enabled} onChange={(v) => set('scheduling_enabled', v)} />
        </div>
      </Card>
      <Card>
        <GroupLabel>Regeln</GroupLabel>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Pufferzeit zwischen Terminen (Min.)"><input type="number" value={f.buffer_minutes} onChange={(e) => set('buffer_minutes', Number(e.target.value))} className={inputCls} /></Field>
          <Field label="Max. Termine pro Tag"><input type="number" value={f.max_appointments_per_day} onChange={(e) => set('max_appointments_per_day', Number(e.target.value))} className={inputCls} /></Field>
          <Field label="Parallele Termine"><input type="number" value={f.parallel_slots} onChange={(e) => set('parallel_slots', Number(e.target.value))} className={inputCls} /></Field>
          <Field label="Vorlaufzeit (Tage)"><input type="number" value={f.lead_time_days} onChange={(e) => set('lead_time_days', Number(e.target.value))} className={inputCls} /></Field>
          <Field label="Frühester Termin (Uhrzeit)"><input type="time" value={f.lead_time_earliest_clock} onChange={(e) => set('lead_time_earliest_clock', e.target.value)} className={inputCls} /></Field>
        </div>
        <label className="mt-4 flex items-center gap-2 text-sm text-text"><Toggle on={f.lead_time_only_weekdays} onChange={(v) => set('lead_time_only_weekdays', v)} /> Vorlaufzeit nur an Werktagen zählen</label>
        <SaveBar onReset={() => setF({ scheduling_enabled: c.scheduling_enabled, buffer_minutes: c.buffer_minutes, max_appointments_per_day: c.max_appointments_per_day, parallel_slots: c.parallel_slots, lead_time_days: c.lead_time_days, lead_time_only_weekdays: c.lead_time_only_weekdays, lead_time_earliest_clock: c.lead_time_earliest_clock ?? '' })} onSave={() => patch.mutate({ ...f, lead_time_earliest_clock: f.lead_time_earliest_clock || null })} saving={patch.isPending} />
      </Card>
      <div className="flex items-start gap-3 rounded-xl border border-info/30 bg-info-bg/40 p-4 text-sm text-body">
        <Info size={16} className="mt-0.5 shrink-0 text-info" />
        <span>Geschäftszeiten werden im <a href="/calendar/business-hours" className="font-medium text-green-deep hover:underline">Kalender</a> verwaltet und hier nicht dupliziert.</span>
      </div>
    </div>
  )
}

// ─── Terminkategorien ────────────────────────────────────────────────────────
export function TerminkategorienSection({ flash }: Props) {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['kiki-zentrale', 'categories'], queryFn: () => apiFetch<{ categories: KzCategory[] }>(`${KZ}/appointment-categories`) })
  const cats = data?.categories ?? []
  const [edit, setEdit] = useState<Partial<KzCategory> | null>(null)
  const inv = () => qc.invalidateQueries({ queryKey: ['kiki-zentrale', 'categories'] })

  const saveCat = useMutation({
    mutationFn: (cat: Partial<KzCategory>) => cat.id
      ? apiFetch(`${KZ}/appointment-categories/${cat.id}`, { method: 'PATCH', body: JSON.stringify(cat) })
      : apiFetch(`${KZ}/appointment-categories`, { method: 'POST', body: JSON.stringify(cat) }),
    onSuccess: () => { setEdit(null); inv(); flash('Gespeichert.') },
  })
  const delCat = useMutation({ mutationFn: (id: string) => apiFetch(`${KZ}/appointment-categories/${id}`, { method: 'DELETE' }), onSuccess: inv })

  return (
    <Card>
      <div className="mb-3 flex items-center justify-between">
        <GroupLabel>Terminkategorien</GroupLabel>
        <button onClick={() => setEdit({ name: '', duration_minutes: 60 })} className="flex items-center gap-1.5 rounded-md bg-green-primary px-3 py-1.5 text-sm font-semibold text-white hover:brightness-110"><Plus size={14} /> Neue Kategorie</button>
      </div>
      {cats.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center">
          <Clock size={22} className="mx-auto text-faint" />
          <p className="mt-2 text-sm text-muted">Noch keine Kategorien. Legen Sie Termintypen wie „Beratung" oder „Wartung" an.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {cats.map((cat) => (
            <button key={cat.id} onClick={() => setEdit(cat)} className="flex w-full items-center justify-between rounded-lg border border-border px-3 py-2 text-left hover:bg-alt">
              <div><div className="text-sm font-medium text-text">{cat.name}</div>{cat.description && <div className="text-xs text-muted">{cat.description}</div>}</div>
              <span className="text-xs text-muted">{cat.duration_minutes} Min.</span>
            </button>
          ))}
        </div>
      )}
      <Modal open={!!edit} onOpenChange={(v) => !v && setEdit(null)} title={edit?.id ? 'Kategorie bearbeiten' : 'Neue Kategorie'} footer={
        <div className="flex gap-3">
          {edit?.id && <button onClick={() => { delCat.mutate(edit.id!); setEdit(null) }} className="rounded-md border border-error px-4 py-2.5 text-sm font-medium text-error">Löschen</button>}
          <button onClick={() => setEdit(null)} className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body">Abbrechen</button>
          <button disabled={!edit?.name?.trim()} onClick={() => saveCat.mutate(edit!)} className="flex-1 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white disabled:opacity-50">Speichern</button>
        </div>
      }>
        {edit && (
          <div className="space-y-3">
            <Field label="Name"><input value={edit.name ?? ''} onChange={(e) => setEdit({ ...edit, name: e.target.value })} className={inputCls} /></Field>
            <Field label="Beschreibung"><input value={edit.description ?? ''} onChange={(e) => setEdit({ ...edit, description: e.target.value })} className={inputCls} /></Field>
            <Field label="Dauer (Minuten)"><input type="number" value={edit.duration_minutes ?? 60} onChange={(e) => setEdit({ ...edit, duration_minutes: Number(e.target.value) })} className={inputCls} /></Field>
          </div>
        )}
      </Modal>
    </Card>
  )
}

// ─── KVA-Automatisierung ─────────────────────────────────────────────────────
export function KvaAutomationSection({ data, flash }: Props) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [on, setOn] = useState(data.config.kva_automation_enabled)
  const toggle = useMutation({
    mutationFn: (v: boolean) => apiFetch(`${KZ}/kva-automation`, { method: 'PATCH', body: JSON.stringify({ enabled: v }) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['kiki-zentrale'] }); flash('Gespeichert.') },
  })
  const rows = [['Stufe 1', 'KVA wird nicht automatisch erstellt'], ['Stufe 2', 'Entwurf wird zur Freigabe vorbereitet'], ['Stufe 3', 'KVA wird direkt an den Kunden gesendet']]
  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-center justify-between">
          <div><div className="text-sm font-bold text-text">KVA-Automatisierung</div><div className="text-xs text-muted">Kiki erstellt nach Anrufen passende Kostenvoranschläge.</div></div>
          <Toggle on={on} onChange={(v) => { setOn(v); toggle.mutate(v) }} />
        </div>
      </Card>
      <Card>
        <GroupLabel>Verhalten je Autonomie-Stufe</GroupLabel>
        <div className="space-y-2">
          {rows.map(([s, d]) => (
            <div key={s} className={cn('flex items-center gap-3 rounded-lg border border-border px-3 py-2', data.config.kiki_level === Number(s.slice(-1)) && 'border-green-primary bg-green-tint-50')}>
              <Tag variant={data.config.kiki_level === Number(s.slice(-1)) ? 'green' : 'neutral'}>{s}</Tag>
              <span className="text-sm text-body">{d}</span>
            </div>
          ))}
        </div>
        <button onClick={() => navigate('/kiki-zentrale/verhalten')} className="mt-4 text-sm font-medium text-green-deep hover:underline">Autonomie-Stufe ändern →</button>
      </Card>
    </div>
  )
}

// ─── Preisauskunft ───────────────────────────────────────────────────────────
export function PreisauskunftSection({ data, flash }: Props) {
  const qc = useQueryClient()
  const [on, setOn] = useState(data.config.price_info_enabled)
  const toggle = useMutation({
    mutationFn: (v: boolean) => apiFetch(`${KZ}/price-info`, { method: 'PATCH', body: JSON.stringify({ enabled: v }) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['kiki-zentrale'] }); flash('Gespeichert.') },
  })
  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-center justify-between">
          <div><div className="text-sm font-bold text-text">Preisauskunft am Telefon</div><div className="text-xs text-muted">Kiki nennt Richtpreise. Standardmäßig deaktiviert.</div></div>
          <Toggle on={on} onChange={(v) => { setOn(v); toggle.mutate(v) }} />
        </div>
      </Card>
      <div className={cn('flex items-start gap-3 rounded-xl border p-4 text-sm', on ? 'border-warning/30 bg-warning-bg/40 text-body' : 'border-border bg-alt text-muted')}>
        <Info size={16} className={cn('mt-0.5 shrink-0', on ? 'text-warning' : 'text-faint')} />
        <span>{on ? 'Kiki gibt telefonisch Richtpreise heraus. Achten Sie auf korrekt gepflegte Katalogpreise.' : 'Kiki gibt keine Preise heraus und verweist auf einen Kostenvoranschlag.'}</span>
      </div>
    </div>
  )
}

// ─── Leistungsangebot ────────────────────────────────────────────────────────
export function LeistungsangebotSection({ flash }: Props) {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['kiki-zentrale', 'services'], queryFn: () => apiFetch<{ services: KzService[] }>(`${KZ}/services`) })
  const services = data?.services ?? []
  const [name, setName] = useState('')
  const inv = () => qc.invalidateQueries({ queryKey: ['kiki-zentrale', 'services'] })
  const add = useMutation({ mutationFn: () => apiFetch(`${KZ}/services`, { method: 'POST', body: JSON.stringify({ name, is_offered: true }) }), onSuccess: () => { setName(''); inv() }, onError: (e: Error) => flash(e.message || 'Hinzufügen fehlgeschlagen.') })
  const toggle = useMutation({ mutationFn: (s: KzService) => apiFetch(`${KZ}/services/${s.id}`, { method: 'PATCH', body: JSON.stringify({ is_offered: !s.is_offered }) }), onSuccess: inv })
  const del = useMutation({ mutationFn: (id: string) => apiFetch(`${KZ}/services/${id}`, { method: 'DELETE' }), onSuccess: inv })
  const offered = services.filter((s) => s.is_offered)
  const notOffered = services.filter((s) => !s.is_offered)

  const Col = ({ title, items, green }: { title: string; items: KzService[]; green?: boolean }) => (
    <div className="flex-1">
      <div className="mb-2 text-xs font-bold uppercase tracking-wide text-muted">{title}</div>
      <div className="flex flex-wrap gap-2">
        {items.length === 0 && <span className="text-sm text-faint">—</span>}
        {items.map((s) => (
          <span key={s.id} className={cn('group inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm', green ? 'bg-green-tint-100 text-green-deep' : 'bg-alt text-muted')}>
            <button onClick={() => toggle.mutate(s)} title="Umschalten">{s.name}</button>
            <button onClick={() => del.mutate(s.id)} className="opacity-50 hover:opacity-100"><X size={12} /></button>
          </span>
        ))}
      </div>
    </div>
  )
  return (
    <Card>
      <GroupLabel>Leistungsangebot</GroupLabel>
      <p className="mb-4 text-sm text-muted">Klicken Sie einen Eintrag an, um ihn zwischen angeboten und nicht angeboten zu verschieben.</p>
      <div className="flex flex-col gap-6 sm:flex-row">
        <Col title="Angebotene Leistungen" items={offered} green />
        <Col title="Nicht angebotene Leistungen" items={notOffered} />
      </div>
      <div className="mt-5 flex items-end gap-2 border-t border-border pt-4">
        <div className="flex-1"><Field label="Leistung hinzufügen"><input value={name} onChange={(e) => setName(e.target.value)} placeholder="z. B. Badsanierung" className={inputCls} /></Field></div>
        <button onClick={() => name.trim() && add.mutate()} disabled={!name.trim() || add.isPending} className="rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">Hinzufügen</button>
      </div>
    </Card>
  )
}

// ─── Notdienst ───────────────────────────────────────────────────────────────
export function NotdienstSection({ data, flash }: Props) {
  const c = data.config
  const patch = useConfigPatch('/emergency', flash)
  const [f, setF] = useState({
    emergency_enabled: c.emergency_enabled, emergency_number: c.emergency_number ?? '',
    emergency_only_outside_business_hours: c.emergency_only_outside_business_hours,
    emergency_keywords: c.emergency_keywords ?? [],
    emergency_surcharge_notice_enabled: c.emergency_surcharge_notice_enabled,
    emergency_surcharge_text: c.emergency_surcharge_text ?? '',
  })
  const [kw, setKw] = useState('')
  const set = (k: keyof typeof f, v: unknown) => setF((p) => ({ ...p, [k]: v }))
  const addKw = () => { if (kw.trim()) { set('emergency_keywords', [...f.emergency_keywords, kw.trim()]); setKw('') } }

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2"><Siren size={18} className="text-error" /><div><div className="text-sm font-bold text-text">Notdienst aktiv</div><div className="text-xs text-muted">Kiki erkennt Notfälle und leitet entsprechend weiter.</div></div></div>
          <Toggle on={f.emergency_enabled} onChange={(v) => set('emergency_enabled', v)} />
        </div>
        <div className="mt-4"><Field label="Notdienst-Nummer"><input value={f.emergency_number} onChange={(e) => set('emergency_number', e.target.value)} placeholder="+49 …" className={cn(inputCls, 'max-w-xs')} /></Field></div>
      </Card>
      <Card>
        <GroupLabel>Wann ist der Notdienst aktiv?</GroupLabel>
        <label className="flex items-center gap-2 text-sm text-text"><Toggle on={f.emergency_only_outside_business_hours} onChange={(v) => set('emergency_only_outside_business_hours', v)} /> Nur außerhalb der Geschäftszeiten</label>
        <p className="mt-2 text-xs text-muted">Geschäftszeiten werden im <a href="/calendar/business-hours" className="font-medium text-green-deep hover:underline">Kalender</a> verwaltet.</p>
      </Card>
      <Card>
        <GroupLabel>Stichwörter</GroupLabel>
        <div className="flex flex-wrap gap-2">
          {f.emergency_keywords.map((k, i) => (
            <span key={i} className="inline-flex items-center gap-1.5 rounded-full bg-alt px-3 py-1 text-sm text-muted">
              {k}<button onClick={() => set('emergency_keywords', f.emergency_keywords.filter((_, j) => j !== i))} className="opacity-50 hover:opacity-100"><X size={12} /></button>
            </span>
          ))}
        </div>
        <div className="mt-3 flex gap-2">
          <input value={kw} onChange={(e) => setKw(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && addKw()} placeholder="z. B. Wasserrohrbruch" className={cn(inputCls, 'max-w-xs')} />
          <button onClick={addKw} className="rounded-md border border-border bg-surface px-3 py-2 text-sm font-medium text-body hover:bg-alt">Hinzufügen</button>
        </div>
      </Card>
      <Card>
        <div className="flex items-center justify-between">
          <GroupLabel>Zusatzkostenhinweis</GroupLabel>
          <Toggle on={f.emergency_surcharge_notice_enabled} onChange={(v) => set('emergency_surcharge_notice_enabled', v)} />
        </div>
        <textarea value={f.emergency_surcharge_text} onChange={(e) => set('emergency_surcharge_text', e.target.value)} placeholder="z. B. Für Notdiensteinsätze außerhalb der Geschäftszeiten fällt ein Zuschlag an." className={cn(inputCls, 'min-h-[80px]')} />
      </Card>
      <div className="rounded-xl border border-border bg-surface px-6 py-4 text-right">
        <button onClick={() => patch.mutate({ ...f, emergency_number: f.emergency_number || null, emergency_surcharge_text: f.emergency_surcharge_text || null })} disabled={patch.isPending} className="rounded-md bg-green-primary px-6 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">{patch.isPending ? 'Speichert…' : 'Speichern'}</button>
      </div>
    </div>
  )
}

// ─── Telefon ─────────────────────────────────────────────────────────────────
export function TelefonSection({ data, flash }: Props) {
  const c = data.config
  const patch = useConfigPatch('/phone', flash)
  const [fwd, setFwd] = useState(c.forwarding_number ?? '')
  const [inc, setInc] = useState(c.incoming_forwarding_number ?? '')
  return (
    <Card>
      <GroupLabel>Telefonie</GroupLabel>
      <Field label="Telefonnummer (von HeyKiki bereitgestellt)">
        <div className="flex items-center gap-2 rounded-md border border-border bg-alt px-3 py-2 text-sm text-muted">
          <Lock size={14} className="text-faint" /><Phone size={14} className="text-faint" />
          <span className="text-text">{data.phone_number || 'Nicht zugewiesen'}</span>
        </div>
      </Field>
      <p className="mt-1 text-xs text-muted">Zur Änderung der Rufnummer wenden Sie sich an support@heykiki.de.</p>
      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Weiterleitungsnummer (Notdienst/Staff)"><input value={fwd} onChange={(e) => setFwd(e.target.value)} className={inputCls} /></Field>
        <Field label="Eingehende Weiterleitungsnummer"><input value={inc} onChange={(e) => setInc(e.target.value)} className={inputCls} /></Field>
      </div>
      <SaveBar onReset={() => { setFwd(c.forwarding_number ?? ''); setInc(c.incoming_forwarding_number ?? '') }} onSave={() => patch.mutate({ forwarding_number: fwd || null, incoming_forwarding_number: inc || null })} saving={patch.isPending} />
    </Card>
  )
}

// ─── Ausgehende Anrufe ───────────────────────────────────────────────────────
export function AusgehendeSection({ data, flash }: Props) {
  const c = data.config
  const patch = useConfigPatch('/outbound', flash)
  const [f, setF] = useState({
    outbound_enabled: c.outbound_enabled, outbound_occasions: { ...(c.outbound_occasions || {}) } as Record<string, boolean>,
    outbound_time_from: (c.outbound_time_from || '09:00').slice(0, 5), outbound_time_to: (c.outbound_time_to || '20:00').slice(0, 5),
    outbound_weekdays: c.outbound_weekdays ?? [],
  })
  const set = (k: keyof typeof f, v: unknown) => setF((p) => ({ ...p, [k]: v }))
  const enabledCount = Object.values(f.outbound_occasions).filter(Boolean).length
  const estMinutes = enabledCount * 10 * 3 // ~10 calls/occasion/month × 3 min
  const quota = data.ai_minutes_quota ?? 0
  const pct = quota ? Math.round((estMinutes / quota) * 100) : 0
  const over = quota > 0 && estMinutes > quota
  const warn = quota > 0 && pct >= 70

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-center justify-between">
          <div><div className="text-sm font-bold text-text">Ausgehende Anrufe</div><div className="text-xs text-muted">Kiki ruft Kunden proaktiv zu den gewählten Anlässen an.</div></div>
          <Toggle on={f.outbound_enabled} onChange={(v) => set('outbound_enabled', v)} />
        </div>
      </Card>
      <Card>
        <GroupLabel>Anlässe</GroupLabel>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {OCCASIONS.map(([k, l]) => (
            <label key={k} className="flex items-center gap-2 rounded-md border border-border p-2 text-sm text-text">
              <input type="checkbox" checked={!!f.outbound_occasions[k]} onChange={(e) => set('outbound_occasions', { ...f.outbound_occasions, [k]: e.target.checked })} className="h-4 w-4 accent-green-primary" /> {l}
            </label>
          ))}
        </div>
      </Card>
      <Card className={cn(over && 'border-error/50')}>
        <GroupLabel>Geschätzte Belastung</GroupLabel>
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted">Geschätzte KI-Minuten / Monat</span>
          <span className={cn('text-lg font-bold', over ? 'text-error' : warn ? 'text-warning' : 'text-text')}>{estMinutes} {quota ? `/ ${quota}` : ''}</span>
        </div>
        {quota > 0 && (
          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-alt">
            <div className={cn('h-full rounded-full', over ? 'bg-error' : warn ? 'bg-warning' : 'bg-green-primary')} style={{ width: `${Math.min(pct, 100)}%` }} />
          </div>
        )}
        {over && <p className="mt-2 text-xs font-medium text-error">Warnung: Die Schätzung übersteigt Ihr monatliches Kontingent.</p>}
      </Card>
      <Card>
        <GroupLabel>Zeitfenster</GroupLabel>
        <div className="flex flex-wrap items-end gap-4">
          <Field label="Von"><input type="time" value={f.outbound_time_from} onChange={(e) => set('outbound_time_from', e.target.value)} className={inputCls} /></Field>
          <Field label="Bis"><input type="time" value={f.outbound_time_to} onChange={(e) => set('outbound_time_to', e.target.value)} className={inputCls} /></Field>
        </div>
        <div className="mt-3">
          <div className={labelCls}>Wochentage</div>
          <div className="flex gap-1.5">
            {WEEKDAYS.map(([k, l]) => {
              const on = f.outbound_weekdays.includes(k)
              return <button key={k} onClick={() => set('outbound_weekdays', on ? f.outbound_weekdays.filter((d) => d !== k) : [...f.outbound_weekdays, k])} className={cn('h-9 w-9 rounded-md text-sm font-medium transition', on ? 'bg-green-primary text-white' : 'bg-alt text-muted hover:bg-border')}>{l}</button>
            })}
          </div>
        </div>
        <SaveBar onReset={() => setF({ outbound_enabled: c.outbound_enabled, outbound_occasions: { ...(c.outbound_occasions || {}) }, outbound_time_from: (c.outbound_time_from || '09:00').slice(0, 5), outbound_time_to: (c.outbound_time_to || '20:00').slice(0, 5), outbound_weekdays: c.outbound_weekdays ?? [] })} onSave={() => patch.mutate(f)} saving={patch.isPending} />
      </Card>
    </div>
  )
}
