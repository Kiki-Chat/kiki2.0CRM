import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowUpDown, Clock, FileText, Globe, Info, Loader2, Lock, Phone, Plus, RefreshCw,
  Siren, Trash2, X,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { apiFetch, apiUpload } from '../../lib/api'
import {
  KZ, type KzCategory, type KzOverview, type KzRequiredField, type KzResource, type KzService,
} from '../../lib/kikiApi'
import { cn } from '../../lib/utils'
import { Modal } from '../ui/Modal'
import { Tag } from '../ui/Tag'
import { Card, ConfirmDialog, Field, GroupLabel, inputCls, labelCls, SaveBar, StatusBadge, Toggle, useKikiConfirm } from './shared'

type Props = { data: KzOverview; flash: (m: string) => void }

const TRADES = ['Heizung & Sanitär', 'Elektro', 'Schlüsseldienst', 'Dachdecker', 'Maler & Lackierer', 'Tischler/Schreiner', 'Garten- & Landschaftsbau', 'SHK', 'Sonstiges']
const WEEKDAYS: [string, string][] = [['mon', 'Mo'], ['tue', 'Di'], ['wed', 'Mi'], ['thu', 'Do'], ['fri', 'Fr'], ['sat', 'Sa'], ['sun', 'So']]
const OCCASIONS: [string, string][] = [
  ['kva_followup', 'KVA-Nachfassen'], ['appointment_reminder', 'Terminerinnerung'],
  ['payment_reminder', 'Zahlungserinnerung'], ['maintenance_due', 'Wartung fällig'],
  ['satisfaction_survey', 'Zufriedenheitsumfrage'], ['missed_callback', 'Rückruf bei verpasstem Anruf'],
  ['review_request', 'Bewertungsanfrage'],
]

// Frontend-only trade templates for the Notdienst keyword list (2D). Clicking a
// template appends its keywords to emergency_keywords (deduped); no API change.
export const EMERGENCY_KEYWORD_TEMPLATES: { label: string; keywords: string[] }[] = [
  { label: 'SHK / Sanitär-Heizung-Klima', keywords: ['Rohrbruch', 'Wasserschaden', 'kein Warmwasser', 'Heizungsausfall', 'Gasgeruch', 'Rohrverstopfung', 'Wasser läuft aus', 'Warmwasserausfall'] },
  { label: 'Elektro', keywords: ['Stromausfall', 'Kabelbrand', 'Brandgeruch', 'Funkenflug', 'Sicherung fliegt', 'Stromschlag', 'Kurzschluss'] },
  { label: 'Schlüsseldienst', keywords: ['ausgesperrt', 'Tür zugefallen', 'Schlüssel abgebrochen', 'Einbruch', 'Schloss defekt', 'Person eingeschlossen'] },
  { label: 'Dachdecker', keywords: ['Dach undicht', 'Ziegel lose', 'Hagelschaden'] },
  { label: 'Garten', keywords: ['umgestürzter Baum', 'Ast droht zu fallen'] },
]

// /api/employees row shape (subset). employees.id is the FK target for a
// category's default_employee_id (2B) — there is no raw user_id in this payload.
interface Employee {
  id: string
  display_name: string | null
  has_login?: boolean
}

// ─── Pure helpers (exported for unit tests) ──────────────────────────────────

// Append a batch of keywords to the existing list, skipping any already
// present. Order is preserved (existing first, then new-in-batch in batch
// order) and a keyword already in `existing` is never duplicated, which also
// makes appending the same batch twice idempotent. Used by NotdienstSection's
// "Gewerk-Vorlagen" buttons (2D).
export function mergeKeywords(existing: string[], batch: string[]): string[] {
  return [...existing, ...batch.filter((k) => !existing.includes(k))]
}

// Dropdown option shape for the Standard-Mitarbeiter <select> (2B): the value
// is the employee id, the label is the display_name (with a fallback when the
// row has no name).
export interface EmployeeOption {
  value: string
  label: string
}
export function employeeToOption(e: Employee): EmployeeOption {
  return { value: e.id, label: e.display_name ?? '(ohne Name)' }
}

// Resolve a category's default_employee_id to the matching employee's
// display_name, or null when unset / not found.
export function resolveEmployeeName(
  employees: Employee[],
  id: string | null | undefined,
): string | null {
  return id ? employees.find((e) => e.id === id)?.display_name ?? null : null
}

// Derive the field_key for a new required field (Pflichtfelder, "Neues Feld").
// When the user supplied an explicit key it wins; otherwise the key is slugged
// from the label (lower-cased, whitespace → underscore).
export function deriveFieldKey(explicitKey: string, label: string): string {
  return explicitKey || label.toLowerCase().replace(/\s+/g, '_')
}

// The live AgentSyncBanner (KikiZentralePage) now shows the pending→applied
// state of the background agent sync, so toasts stay short.
const AGENT_SYNC_SUFFIX = ''

function useConfigPatch(path: string, flash: (m: string) => void) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => apiFetch(`${KZ}${path}`, { method: 'PATCH', body: JSON.stringify(body) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['kiki-zentrale'] }); flash('Gespeichert.' + AGENT_SYNC_SUFFIX) },
    onError: (e: Error) => flash(e.message || 'Speichern fehlgeschlagen.'),
  })
}

// Inline-editable description for a single required field. Seeds local state
// from the field's stored description and saves onBlur only when it changed,
// so locked fields can still have their description edited (2A.1).
function FieldDescriptionInput({ field, onSave }: { field: KzRequiredField; onSave: (description: string) => void }) {
  const [val, setVal] = useState(field.description ?? '')
  const commit = () => { if (val !== (field.description ?? '')) onSave(val) }
  // The problem-description field holds multi-line guidance → give it a textarea;
  // the short identification fields keep the single-line input.
  if (field.field_key === 'problem_description') {
    return (
      <textarea
        value={val}
        onChange={(e) => setVal(e.target.value)}
        onBlur={commit}
        placeholder="z. B. Bei Heizungsausfall: Baujahr der Anlage, Fehlermeldung am Display, ob noch Warmwasser vorhanden ist …"
        className={cn(inputCls, 'mt-1 min-h-[80px] text-xs')}
      />
    )
  }
  return (
    <input
      value={val}
      onChange={(e) => setVal(e.target.value)}
      onBlur={commit}
      placeholder="Beschreibung für den KI-Agenten (optional)"
      className={cn(inputCls, 'mt-1 text-xs')}
    />
  )
}

// ─── Leitfaden (ehem. Pflichtfelder) ─────────────────────────────────────────
// Local-state editor: drag + toggles only mutate local state; ONE batch PATCH on
// Speichern (one agent push — no more push-per-drag). Linked rows (Termin/KVA/
// Preisauskunft) mirror their real setting two-way and warn before toggling.
const LINKED_TARGET_LABEL: Record<string, string> = {
  appointments_enabled: 'Autonomie (Bereich „Termine“)',
  kva_enabled: 'Autonomie (Bereich „Kostenvoranschläge“)',
  price_info_enabled: 'Preisauskunft',
}

export function LeitfadenSection({ flash }: Props) {
  const qc = useQueryClient()
  const { data, dataUpdatedAt } = useQuery({ queryKey: ['kiki-zentrale', 'required-fields'], queryFn: () => apiFetch<{ fields: KzRequiredField[] }>(`${KZ}/required-fields`) })
  const serverFields = useMemo(() => data?.fields ?? [], [data])
  const [items, setItems] = useState<KzRequiredField[]>([])
  const [dirty, setDirty] = useState(false)
  const [newKey, setNewKey] = useState('')
  const [newLabel, setNewLabel] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const dragIdx = useRef<number | null>(null)
  // Linked-row toggle confirmation: which row + target value is pending.
  const [linkedConfirm, setLinkedConfirm] = useState<{ id: string; label: string; target: string; value: boolean } | null>(null)

  // Re-seed local state from the server while the user has no unsaved edits.
  useEffect(() => {
    if (!dirty) setItems(serverFields)
  }, [serverFields, dataUpdatedAt, dirty])

  const setActive = (id: string, value: boolean) => {
    setItems((p) => p.map((f) => (f.id === id ? { ...f, is_active: value } : f)))
    setDirty(true)
  }

  const save = useMutation({
    mutationFn: () =>
      apiFetch(`${KZ}/leitfaden`, {
        method: 'PATCH',
        body: JSON.stringify({ items: items.map((f) => ({ id: f.id, is_active: f.is_active })) }),
      }),
    onSuccess: () => {
      setDirty(false)
      // Linked toggles also changed Autonomie/Preisauskunft — refresh everything.
      qc.invalidateQueries({ queryKey: ['kiki-zentrale'] })
      flash('Leitfaden gespeichert.')
    },
    onError: (e: Error) => flash(e.message || 'Speichern fehlgeschlagen.'),
  })

  const create = useMutation({
    mutationFn: () => apiFetch(`${KZ}/required-fields`, { method: 'POST', body: JSON.stringify({ field_key: deriveFieldKey(newKey, newLabel), label: newLabel, description: newDesc || null }) }),
    onSuccess: () => { setNewKey(''); setNewLabel(''); setNewDesc(''); setDirty(false); qc.invalidateQueries({ queryKey: ['kiki-zentrale', 'required-fields'] }) },
    onError: (e: Error) => flash(e.message || 'Hinzufügen fehlgeschlagen.'),
  })
  const del = useMutation({
    mutationFn: (id: string) => apiFetch(`${KZ}/required-fields/${id}`, { method: 'DELETE' }),
    onSuccess: () => { setDirty(false); qc.invalidateQueries({ queryKey: ['kiki-zentrale', 'required-fields'] }) },
    onError: (e: Error) => flash(e.message || 'Löschen fehlgeschlagen.'),
  })
  const patchDesc = useMutation({
    mutationFn: ({ id, description }: { id: string; description: string }) => apiFetch(`${KZ}/required-fields/${id}`, { method: 'PATCH', body: JSON.stringify({ description: description || null }) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['kiki-zentrale', 'required-fields'] }); flash('Beschreibung gespeichert.') },
    onError: (e: Error) => flash(e.message || 'Speichern fehlgeschlagen.'),
  })

  // Drag reorder — LOCAL ONLY; persisted with Speichern.
  const onDrop = (to: number) => {
    const from = dragIdx.current
    dragIdx.current = null
    if (from === null || from === to) return
    setItems((p) => {
      const next = [...p]
      const [m] = next.splice(from, 1)
      next.splice(to, 0, m)
      return next
    })
    setDirty(true)
  }
  const idRoles = serverFields.filter((f) => f.identification_role)

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
        <div className="mb-1 flex items-center justify-between">
          <GroupLabel>Gesprächs-Leitfaden</GroupLabel>
          <span className="text-xs text-muted">Ziehen zum Sortieren — Reihenfolge = Frage-Reihenfolge</span>
        </div>
        <p className="mb-3 text-xs text-muted">
          Kiki arbeitet diese Punkte im Gespräch von oben nach unten ab: Felder werden erfragt,
          Angebots-Punkte (Termin, KVA, Preisauskunft) an ihrer Position aktiv angeboten. Der Schalter
          legt fest, ob ein Punkt überhaupt vorkommt. Erst „Speichern“ überträgt die Änderungen an Kiki.
        </p>
        <div className="space-y-2">
          {items.map((f, i) => (
            <div
              key={f.id}
              draggable
              onDragStart={() => (dragIdx.current = i)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => onDrop(i)}
              className={cn('flex items-start gap-3 rounded-lg border border-border px-3 py-2', f.is_active ? 'bg-alt' : 'bg-alt/40 opacity-70')}
            >
              <ArrowUpDown size={15} className="mt-2 cursor-grab text-faint" />
              <div className="flex-1">
                <div className="flex items-center gap-2 text-sm font-medium text-text">
                  {f.label}
                  {f.is_locked && !f.linked_setting && <Lock size={12} className="text-faint" />}
                  {f.is_duty && <Tag variant="green">Pflicht</Tag>}
                  {f.linked_setting && (
                    <Tag variant="info">Verknüpft · {LINKED_TARGET_LABEL[f.linked_setting]}</Tag>
                  )}
                </div>
                {f.linked_setting ? (
                  <p className="mt-1 text-xs text-muted">{f.description}</p>
                ) : (
                  <FieldDescriptionInput field={f} onSave={(description) => patchDesc.mutate({ id: f.id, description })} />
                )}
              </div>
              <div className="mt-1.5 flex items-center gap-2">
                <Toggle
                  on={f.is_active}
                  onChange={(v) => {
                    if (f.linked_setting) {
                      setLinkedConfirm({ id: f.id, label: f.label, target: LINKED_TARGET_LABEL[f.linked_setting], value: v })
                    } else {
                      setActive(f.id, v)
                    }
                  }}
                />
                <button
                  disabled={f.is_locked || del.isPending}
                  onClick={() => { if (window.confirm(`„${f.label}“ wirklich entfernen?`)) del.mutate(f.id) }}
                  title={f.is_locked ? 'Gesperrter Punkt' : 'Entfernen'}
                  className="text-muted hover:text-error disabled:opacity-30"
                >
                  {del.isPending && del.variables === f.id ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />}
                </button>
              </div>
            </div>
          ))}
        </div>
        <SaveBar
          onReset={() => { setItems(serverFields); setDirty(false) }}
          onSave={() => save.mutate()}
          saving={save.isPending}
          disabled={!dirty}
        />
        <div className="mt-4 space-y-2 border-t border-border pt-4">
          <Field label="Neues Feld"><input value={newLabel} onChange={(e) => setNewLabel(e.target.value)} placeholder="z. B. Kennzeichen" className={inputCls} /></Field>
          <Field label="Beschreibung (optional)"><input value={newDesc} onChange={(e) => setNewDesc(e.target.value)} placeholder="Wofür dient das Feld? (wird dem KI-Agenten erklärt)" className={inputCls} /></Field>
          <div className="flex justify-end">
            <button onClick={() => newLabel.trim() && create.mutate()} disabled={!newLabel.trim() || create.isPending} className="inline-flex items-center gap-1.5 rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">
              {create.isPending && <Loader2 size={14} className="animate-spin" />}
              {create.isPending ? 'Speichert…' : 'Hinzufügen'}
            </button>
          </div>
        </div>
      </Card>

      <ConfirmDialog
        open={!!linkedConfirm}
        onOpenChange={(v) => !v && setLinkedConfirm(null)}
        title="Kiki-Änderungen bestätigen"
        message={
          linkedConfirm
            ? `„${linkedConfirm.label}“ ${linkedConfirm.value ? 'aktivieren' : 'deaktivieren'}? Diese Einstellung ist verknüpft und wirkt sich auch auf den Bereich ${linkedConfirm.target} aus (Zwei-Wege-Verbindung). Übertragen wird die Änderung erst mit „Speichern“.`
            : ''
        }
        confirmLabel="Übernehmen"
        onConfirm={() => {
          if (linkedConfirm) setActive(linkedConfirm.id, linkedConfirm.value)
          setLinkedConfirm(null)
        }}
      />
    </div>
  )
}

// Compatibility alias — KikiZentralePage routed 'pflichtfelder' here historically.
export const PflichtfelderSection = LeitfadenSection

// "Anliegen / Problembeschreibung" is now a locked, reorderable required field
// (field_key 'problem_description', seeded by default + migration 0052), edited
// inline in the "Immer abgefragte Felder" list — no longer a separate input.

// ─── Branche & Kontext ───────────────────────────────────────────────────────
export function BrancheKontextSection({ data, flash }: Props) {
  const qc = useQueryClient()
  const kc = useKikiConfirm()
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
        <div className="flex items-center gap-2">
          <select
            value={trade}
            disabled={patch.isPending}
            onChange={(e) => { const v = e.target.value; kc.confirm(() => { setTrade(v); patch.mutate({ trade: v }) }) }}
            className={cn(inputCls, 'max-w-sm disabled:opacity-50')}
          >
            <option value="">— Branche wählen —</option>
            {TRADES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          {patch.isPending && <Loader2 size={16} className="animate-spin text-muted" />}
        </div>
      </Card>

      <Card>
        <GroupLabel>Wissens-Text</GroupLabel>
        <p className="mb-2 text-sm text-muted">Kurze Anweisungen, die dem System-Prompt zur Laufzeit vorangestellt werden.</p>
        <textarea value={knowledge} maxLength={15000} onChange={(e) => setKnowledge(e.target.value)} className={cn(inputCls, 'min-h-[160px]')} />
        <div className="mt-2 flex items-center justify-between">
          <span className="text-xs text-muted">{knowledge.length}/15.000 Zeichen</span>
          <button onClick={() => kc.confirm(() => patch.mutate({ knowledge_text: knowledge }))} disabled={patch.isPending} className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-body hover:bg-alt disabled:opacity-50">
            {patch.isPending && <Loader2 size={14} className="animate-spin" />}
            {patch.isPending ? 'Speichert…' : 'Text speichern'}
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
          <button disabled={!url.trim() || addUrl.isPending} onClick={() => addUrl.mutate()} className="flex flex-1 items-center justify-center gap-1.5 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white disabled:opacity-50">
            {addUrl.isPending && <Loader2 size={14} className="animate-spin" />}
            {addUrl.isPending ? 'Speichert…' : 'Hinzufügen'}
          </button>
        </div>
      }>
        <div className="space-y-3">
          <Field label="URL"><input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" className={inputCls} /></Field>
          <Field label="Anzeigename"><input value={urlName} onChange={(e) => setUrlName(e.target.value)} placeholder="z. B. Leistungsübersicht" className={inputCls} /></Field>
        </div>
      </Modal>
      {kc.element}
    </div>
  )
}

// ─── Terminregeln ────────────────────────────────────────────────────────────
export function TerminregelnSection({ data, flash }: Props) {
  const c = data.config
  const kc = useKikiConfirm()
  const patch = useConfigPatch('/scheduling-rules', flash)
  // "Terminvergabe aktiv" was removed: whether Kiki books at all is governed by
  // the Autonomie section (Bereich "Termine") — no duplicate switch here.
  const initial = () => ({
    buffer_minutes: c.buffer_minutes,
    max_appointments_per_day: c.max_appointments_per_day, parallel_slots: c.parallel_slots,
    lead_time_hours: c.lead_time_hours ?? (c.lead_time_days ?? 1) * 24,
    lead_time_only_weekdays: c.lead_time_only_weekdays,
    lead_time_earliest_clock: c.lead_time_earliest_clock ?? '',
  })
  const [f, setF] = useState(initial)
  const set = (k: keyof ReturnType<typeof initial>, v: unknown) => setF((p) => ({ ...p, [k]: v }))

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3 rounded-xl border border-info/30 bg-info-bg/40 p-4 text-sm text-body">
        <Info size={16} className="mt-0.5 shrink-0 text-info" />
        <span>Ob Kiki überhaupt Termine vergibt, steuern Sie im Bereich <a href="/kiki-zentrale/autonomie" className="font-medium text-green-deep hover:underline">Autonomie</a> (Bereich „Termine“). Hier legen Sie die Regeln fest, nach denen freie Termine angeboten werden.</span>
      </div>
      <Card>
        <GroupLabel>Kapazität & Pufferzeiten</GroupLabel>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Pufferzeit zwischen Terminen (Min.)" hint="Kiki hält zwischen zwei Terminen so viele Minuten frei — z. B. für An- und Abfahrt."><input type="number" min={0} value={f.buffer_minutes} onChange={(e) => set('buffer_minutes', Number(e.target.value))} className={inputCls} /></Field>
          <Field label="Max. Termine pro Tag" hint="Ist diese Zahl erreicht, bietet Kiki am Telefon keine weiteren Termine an diesem Tag an."><input type="number" min={0} value={f.max_appointments_per_day} onChange={(e) => set('max_appointments_per_day', Number(e.target.value))} className={inputCls} /></Field>
          <Field label="Parallele Termine" hint="Wie viele Termine zur selben Zeit möglich sind, z. B. bei mehreren Teams. Bei mehr als 1 erlaubt auch der Kalender mehrere Buchungen im selben Slot."><input type="number" min={1} value={f.parallel_slots} onChange={(e) => set('parallel_slots', Number(e.target.value))} className={inputCls} /></Field>
        </div>
      </Card>
      <Card>
        <GroupLabel>Vorlaufzeit & frühester Termin</GroupLabel>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Vorlaufzeit (Stunden)" hint="Frühestens so viele Stunden nach dem Anruf vergibt Kiki einen Termin — z. B. 24 = ab morgen zur selben Uhrzeit."><input type="number" min={0} value={f.lead_time_hours} onChange={(e) => set('lead_time_hours', Number(e.target.value))} className={inputCls} /></Field>
          <Field label="Frühester Termin (Uhrzeit)" hint="Am frühestmöglichen Tag beginnen Termine erst ab dieser Uhrzeit; an späteren Tagen gelten die normalen Geschäftszeiten."><input type="time" value={f.lead_time_earliest_clock} onChange={(e) => set('lead_time_earliest_clock', e.target.value)} className={inputCls} /></Field>
        </div>
        <label className="mt-4 flex items-center gap-2 text-sm text-text"><Toggle on={f.lead_time_only_weekdays} onChange={(v) => set('lead_time_only_weekdays', v)} /> Vorlaufzeit nur an Werktagen zählen</label>
        <p className="mt-1 text-xs text-muted">Wochenend-Stunden zählen nicht zur Vorlaufzeit — eine Anfrage am Freitagnachmittag mit 24 h Vorlauf landet so erst am Montag.</p>
        <SaveBar onReset={() => setF(initial())} onSave={() => kc.confirm(() => patch.mutate({ ...f, lead_time_earliest_clock: f.lead_time_earliest_clock || null }))} saving={patch.isPending} />
      </Card>
      <div className="flex items-start gap-3 rounded-xl border border-info/30 bg-info-bg/40 p-4 text-sm text-body">
        <Info size={16} className="mt-0.5 shrink-0 text-info" />
        <span>Geschäftszeiten werden in der Kiki-Zentrale unter <a href="/kiki-zentrale/geschaeftszeiten" className="font-medium text-green-deep hover:underline">Geschäftszeiten</a> verwaltet und hier nicht dupliziert.</span>
      </div>
      {kc.element}
    </div>
  )
}

// ─── Terminkategorien ────────────────────────────────────────────────────────
export function TerminkategorienSection({ flash }: Props) {
  const qc = useQueryClient()
  const kc = useKikiConfirm()
  const { data } = useQuery({ queryKey: ['kiki-zentrale', 'categories'], queryFn: () => apiFetch<{ categories: KzCategory[] }>(`${KZ}/appointment-categories`) })
  const cats = data?.categories ?? []
  const { data: employees = [] } = useQuery({ queryKey: ['employees'], queryFn: () => apiFetch<Employee[]>('/api/employees') })
  // default_employee_id now targets employees.id directly. Show ALL employees in
  // the dropdown (no login filter) and resolve the list-row name by id.
  const empName = (id: string | null | undefined) => resolveEmployeeName(employees, id)
  const [edit, setEdit] = useState<Partial<KzCategory> | null>(null)
  const inv = () => qc.invalidateQueries({ queryKey: ['kiki-zentrale', 'categories'] })

  const saveCat = useMutation({
    mutationFn: (cat: Partial<KzCategory>) => cat.id
      ? apiFetch(`${KZ}/appointment-categories/${cat.id}`, { method: 'PATCH', body: JSON.stringify(cat) })
      : apiFetch(`${KZ}/appointment-categories`, { method: 'POST', body: JSON.stringify(cat) }),
    onSuccess: () => { setEdit(null); inv(); flash('Gespeichert.' + AGENT_SYNC_SUFFIX) },
    onError: (e: Error) => flash(e.message || 'Speichern fehlgeschlagen.'),
  })
  const delCat = useMutation({
    mutationFn: (id: string) => apiFetch(`${KZ}/appointment-categories/${id}`, { method: 'DELETE' }),
    onSuccess: () => { setEdit(null); inv(); flash('Gelöscht.' + AGENT_SYNC_SUFFIX) },
    onError: (e: Error) => flash(e.message || 'Löschen fehlgeschlagen.'),
  })

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
              <div>
                <div className="text-sm font-medium text-text">{cat.name}</div>
                {cat.description && <div className="text-xs text-muted">{cat.description}</div>}
                {empName(cat.default_employee_id) && <div className="text-xs text-muted">Standard-Mitarbeiter: {empName(cat.default_employee_id)}</div>}
              </div>
              <span className="text-xs text-muted">{cat.duration_minutes} Min.</span>
            </button>
          ))}
        </div>
      )}
      <Modal open={!!edit} onOpenChange={(v) => !v && !saveCat.isPending && !delCat.isPending && setEdit(null)} title={edit?.id ? 'Kategorie bearbeiten' : 'Neue Kategorie'} footer={
        <div className="flex gap-3">
          {edit?.id && <button disabled={delCat.isPending || saveCat.isPending} onClick={() => kc.confirm(() => delCat.mutate(edit.id!))} className="inline-flex items-center gap-1.5 rounded-md border border-error px-4 py-2.5 text-sm font-medium text-error disabled:opacity-50">{delCat.isPending && <Loader2 size={14} className="animate-spin" />}{delCat.isPending ? 'Löscht…' : 'Löschen'}</button>}
          <button disabled={saveCat.isPending || delCat.isPending} onClick={() => setEdit(null)} className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body disabled:opacity-50">Abbrechen</button>
          <button disabled={!edit?.name?.trim() || saveCat.isPending || delCat.isPending} onClick={() => kc.confirm(() => saveCat.mutate(edit!))} className="flex flex-1 items-center justify-center gap-1.5 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white disabled:opacity-50">{saveCat.isPending && <Loader2 size={14} className="animate-spin" />}{saveCat.isPending ? 'Speichert…' : 'Speichern'}</button>
        </div>
      }>
        {edit && (
          <div className="space-y-3">
            <Field label="Name"><input value={edit.name ?? ''} onChange={(e) => setEdit({ ...edit, name: e.target.value })} className={inputCls} /></Field>
            <Field label="Beschreibung"><input value={edit.description ?? ''} onChange={(e) => setEdit({ ...edit, description: e.target.value })} className={inputCls} /></Field>
            <Field label="Dauer (Minuten)"><input type="number" value={edit.duration_minutes ?? 60} onChange={(e) => setEdit({ ...edit, duration_minutes: Number(e.target.value) })} className={inputCls} /></Field>
            <Field label="Standard-Mitarbeiter (wird bei passender Kategorie automatisch zugewiesen)">
              <select value={edit.default_employee_id ?? ''} onChange={(e) => setEdit({ ...edit, default_employee_id: e.target.value || null })} className={inputCls}>
                <option value="">— kein Mitarbeiter —</option>
                {employees.map(employeeToOption).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </Field>
          </div>
        )}
      </Modal>
      {kc.element}
    </Card>
  )
}

// ─── Preisauskunft ───────────────────────────────────────────────────────────
interface CatalogItemLite {
  id: string
  unit_price: number | null
  is_active: boolean
}

export function PreisauskunftSection({ data, flash }: Props) {
  const qc = useQueryClient()
  const kc = useKikiConfirm()
  const [on, setOn] = useState(data.config.price_info_enabled)
  // Guard: without priced Artikel the agent has nothing real to quote — the
  // backend rejects enabling too (422), this just explains it upfront.
  const { data: catalog } = useQuery({
    queryKey: ['catalog', 'price-guard'],
    queryFn: () => apiFetch<CatalogItemLite[]>('/api/catalog'),
  })
  const pricedCount = (catalog ?? []).filter((c) => c.is_active && (c.unit_price ?? 0) > 0).length
  const blockEnable = !on && catalog !== undefined && pricedCount === 0
  const toggle = useMutation({
    mutationFn: (v: boolean) => apiFetch(`${KZ}/price-info`, { method: 'PATCH', body: JSON.stringify({ enabled: v }) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['kiki-zentrale'] }); flash('Gespeichert.' + AGENT_SYNC_SUFFIX) },
    onError: (e: Error) => { setOn((p) => !p); flash(e.message || 'Speichern fehlgeschlagen.') },
  })
  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-center justify-between">
          <div><div className="text-sm font-bold text-text">Preisauskunft am Telefon</div><div className="text-xs text-muted">Kiki nennt Richtpreise aus Ihren Artikeln. Standardmäßig deaktiviert.</div></div>
          <div className="flex items-center gap-2">
            {toggle.isPending && <Loader2 size={16} className="animate-spin text-muted" />}
            <Toggle on={on} disabled={toggle.isPending || blockEnable} onChange={(v) => kc.confirm(() => { setOn(v); toggle.mutate(v) })} />
          </div>
        </div>
      </Card>
      {blockEnable && (
        <div className="flex items-start gap-3 rounded-xl border border-error/30 bg-error-bg/40 p-4 text-sm text-body">
          <Info size={16} className="mt-0.5 shrink-0 text-error" />
          <span>
            Preisauskunft kann nicht aktiviert werden: Es sind keine Artikel mit Preisen hinterlegt.
            Bitte pflegen Sie zuerst Preise im Menü <a href="/catalog" className="font-medium text-green-deep hover:underline">Artikel</a>.
          </span>
        </div>
      )}
      <div className={cn('flex items-start gap-3 rounded-xl border p-4 text-sm', on ? 'border-warning/30 bg-warning-bg/40 text-body' : 'border-border bg-alt text-muted')}>
        <Info size={16} className={cn('mt-0.5 shrink-0', on ? 'text-warning' : 'text-faint')} />
        <span>
          {on
            ? `Kiki gibt telefonisch Richtpreise heraus — Quelle ist die automatisch erzeugte Preisliste aus Ihren Artikeln (${pricedCount} Position${pricedCount === 1 ? '' : 'en'} mit Preis). Preise, die dort nicht stehen, nennt Kiki nicht.`
            : 'Kiki gibt keine Preise heraus und verweist auf einen Kostenvoranschlag.'}
        </span>
      </div>
      {kc.element}
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
  // P1.6 — single field + two buttons. `is_offered` is supplied by the
  // caller so the new entry lands in the correct column without forcing the
  // user to add-then-toggle.
  const add = useMutation({ mutationFn: (is_offered: boolean) => apiFetch(`${KZ}/services`, { method: 'POST', body: JSON.stringify({ name, is_offered }) }), onSuccess: () => { setName(''); inv() }, onError: (e: Error) => flash(e.message || 'Hinzufügen fehlgeschlagen.') })
  const toggle = useMutation({ mutationFn: (s: KzService) => apiFetch(`${KZ}/services/${s.id}`, { method: 'PATCH', body: JSON.stringify({ is_offered: !s.is_offered }) }), onSuccess: inv })
  const del = useMutation({ mutationFn: (id: string) => apiFetch(`${KZ}/services/${id}`, { method: 'DELETE' }), onSuccess: inv })
  const offered = services.filter((s) => s.is_offered)
  const notOffered = services.filter((s) => !s.is_offered)

  const Col = ({ title, items, green }: { title: string; items: KzService[]; green?: boolean }) => (
    <div className="flex-1">
      <div className="mb-2 text-xs font-bold uppercase tracking-wide text-muted">{title}</div>
      <div className="flex flex-wrap gap-2">
        {items.length === 0 && <span className="text-sm text-faint">—</span>}
        {items.map((s) => {
          const busy = (toggle.isPending && toggle.variables?.id === s.id) || (del.isPending && del.variables === s.id)
          return (
            <span key={s.id} className={cn('group inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm', busy && 'opacity-60', green ? 'bg-green-tint-100 text-green-deep' : 'bg-alt text-muted')}>
              <button onClick={() => toggle.mutate(s)} disabled={busy} title="Umschalten" className="disabled:cursor-wait">{s.name}</button>
              <button onClick={() => del.mutate(s.id)} disabled={busy} className="opacity-50 hover:opacity-100 disabled:cursor-wait">{busy ? <Loader2 size={12} className="animate-spin" /> : <X size={12} />}</button>
            </span>
          )
        })}
      </div>
    </div>
  )
  return (
    <Card>
      <GroupLabel>Leistungsangebot</GroupLabel>
      <p className="mb-4 text-sm text-muted">Klicken Sie einen bestehenden Eintrag an, um ihn zwischen angeboten und nicht angeboten zu verschieben. Mit den Buttons unten neue Einträge in die jeweilige Liste aufnehmen.</p>
      <div className="flex flex-col gap-6 sm:flex-row">
        <Col title="Angebotene Leistungen" items={offered} green />
        <Col title="Nicht angebotene Leistungen" items={notOffered} />
      </div>
      <div className="mt-5 flex flex-wrap items-end gap-2 border-t border-border pt-4">
        <div className="flex-1 min-w-[240px]"><Field label="Leistung hinzufügen"><input value={name} onChange={(e) => setName(e.target.value)} placeholder="z. B. Badsanierung" className={inputCls} /></Field></div>
        <button onClick={() => name.trim() && add.mutate(true)} disabled={!name.trim() || add.isPending} className="inline-flex items-center gap-1.5 rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">{add.isPending && add.variables === true && <Loader2 size={14} className="animate-spin" />}+ Zu Angebot hinzufügen</button>
        <button onClick={() => name.trim() && add.mutate(false)} disabled={!name.trim() || add.isPending} className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-body hover:bg-alt disabled:opacity-50">{add.isPending && add.variables === false && <Loader2 size={14} className="animate-spin" />}+ Zu Nicht-Angebot hinzufügen</button>
      </div>
    </Card>
  )
}

// ─── Notdienst ───────────────────────────────────────────────────────────────
export function NotdienstSection({ data, flash }: Props) {
  const c = data.config
  const kc = useKikiConfirm()
  const patch = useConfigPatch('/emergency', flash)
  const [f, setF] = useState({
    emergency_enabled: c.emergency_enabled, emergency_number: c.emergency_number ?? '',
    emergency_only_outside_business_hours: c.emergency_only_outside_business_hours,
    emergency_keywords: c.emergency_keywords ?? [],
    emergency_extra_windows: c.emergency_extra_windows ?? [],
    emergency_surcharge_notice_enabled: c.emergency_surcharge_notice_enabled,
    emergency_surcharge_text: c.emergency_surcharge_text ?? '',
  })
  const [kw, setKw] = useState('')
  const set = (k: keyof typeof f, v: unknown) => setF((p) => ({ ...p, [k]: v }))
  const addKw = () => { if (kw.trim()) { set('emergency_keywords', [...f.emergency_keywords, kw.trim()]); setKw('') } }
  // A template is "active" when all its keywords are already present. Clicking an
  // active template removes them again; an inactive one adds them (deduped).
  const isTemplateActive = (keywords: string[]) => keywords.every((k) => f.emergency_keywords.includes(k))
  const toggleTemplate = (keywords: string[]) =>
    set(
      'emergency_keywords',
      isTemplateActive(keywords)
        ? f.emergency_keywords.filter((k) => !keywords.includes(k))
        : mergeKeywords(f.emergency_keywords, keywords),
    )
  const setWindow = (i: number, patchWin: { from?: string; to?: string; label?: string }) =>
    set('emergency_extra_windows', f.emergency_extra_windows.map((w, j) => (j === i ? { ...w, ...patchWin } : w)))
  // Toggle a weekday on a window. No weekdays selected → the window applies every day.
  const toggleWindowDay = (i: number, dayKey: string) =>
    set(
      'emergency_extra_windows',
      f.emergency_extra_windows.map((w, j) => {
        if (j !== i) return w
        const cur = w.weekdays ?? []
        return { ...w, weekdays: cur.includes(dayKey) ? cur.filter((d) => d !== dayKey) : [...cur, dayKey] }
      }),
    )

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
        <p className="mt-2 text-xs text-muted">Geschäftszeiten werden unter <a href="/kiki-zentrale/geschaeftszeiten" className="font-medium text-green-deep hover:underline">Geschäftszeiten</a> verwaltet.</p>
      </Card>
      <Card>
        <GroupLabel>Zusätzliche Zeitfenster (optional)</GroupLabel>
        <p className="mb-3 text-xs text-muted">Standardmäßig gilt der Notdienst außerhalb der Geschäftszeiten; hier optional zusätzliche Fenster mit Uhrzeit und Wochentagen (z. B. Mi 14–18 Uhr).</p>
        <div className="space-y-2">
          {f.emergency_extra_windows.length === 0 && <p className="text-sm text-faint">Keine zusätzlichen Zeitfenster.</p>}
          {f.emergency_extra_windows.map((w, i) => (
            <div key={i} className="rounded-lg border border-border bg-alt px-3 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <input type="time" value={w.from ?? ''} onChange={(e) => setWindow(i, { from: e.target.value })} className={cn(inputCls, 'w-auto')} />
                <span className="text-sm text-muted">bis</span>
                <input type="time" value={w.to ?? ''} onChange={(e) => setWindow(i, { to: e.target.value })} className={cn(inputCls, 'w-auto')} />
                <input type="text" value={w.label ?? ''} onChange={(e) => setWindow(i, { label: e.target.value })} placeholder="Bezeichnung (optional)" className={cn(inputCls, 'min-w-[160px] flex-1')} />
                <button onClick={() => set('emergency_extra_windows', f.emergency_extra_windows.filter((_, j) => j !== i))} title="Entfernen" className="text-muted hover:text-error"><X size={15} /></button>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <span className="mr-1 text-xs text-muted">Tage:</span>
                {WEEKDAYS.map(([key, lbl]) => {
                  const on = (w.weekdays ?? []).includes(key)
                  return (
                    <button
                      key={key}
                      onClick={() => toggleWindowDay(i, key)}
                      className={cn(
                        'rounded-md border px-2 py-1 text-xs font-medium transition-colors',
                        on ? 'border-green-primary bg-green-primary text-white' : 'border-border bg-surface text-body hover:bg-alt',
                      )}
                    >
                      {lbl}
                    </button>
                  )
                })}
                {(w.weekdays?.length ?? 0) === 0 && <span className="text-[11px] text-muted">(gilt an allen Tagen)</span>}
              </div>
            </div>
          ))}
        </div>
        <button onClick={() => set('emergency_extra_windows', [...f.emergency_extra_windows, { from: '', to: '' }])} className="mt-3 flex items-center gap-1.5 rounded-md border border-border bg-surface px-3 py-2 text-sm font-medium text-body hover:bg-alt"><Plus size={14} /> Zeitfenster</button>
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
        <div className="mt-4 border-t border-border pt-4">
          <div className="mb-2 text-xs font-bold uppercase tracking-wide text-muted">Gewerk-Vorlagen</div>
          <p className="mb-2 text-xs text-muted">Vorlage an- oder abwählen — grün markierte Vorlagen sind aktiv; erneutes Klicken entfernt ihre Stichwörter wieder.</p>
          <div className="flex flex-wrap gap-2">
            {EMERGENCY_KEYWORD_TEMPLATES.map((t) => {
              const on = isTemplateActive(t.keywords)
              return (
                <button
                  key={t.label}
                  onClick={() => toggleTemplate(t.keywords)}
                  className={cn(
                    'rounded-md border px-3 py-1.5 text-sm font-medium transition-colors',
                    on ? 'border-green-primary bg-green-primary text-white' : 'border-border bg-surface text-body hover:bg-alt',
                  )}
                >
                  {on ? '✓' : '+'} {t.label}
                </button>
              )
            })}
          </div>
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
        <button onClick={() => kc.confirm(() => patch.mutate({ ...f, emergency_number: f.emergency_number || null, emergency_surcharge_text: f.emergency_surcharge_text || null, emergency_extra_windows: f.emergency_extra_windows.filter((w) => w.from || w.to) }))} disabled={patch.isPending} className="rounded-md bg-green-primary px-6 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">{patch.isPending ? 'Speichert…' : 'Speichern'}</button>
      </div>
      {kc.element}
    </div>
  )
}

// ─── Telefon ─────────────────────────────────────────────────────────────────
export function TelefonSection({ data, flash }: Props) {
  const c = data.config
  const kc = useKikiConfirm()
  const patch = useConfigPatch('/phone', flash)
  const [inc, setInc] = useState(c.incoming_forwarding_number ?? '')
  const [biz, setBiz] = useState(data.existing_business_number ?? '')
  return (
    <Card>
      <GroupLabel>Telefonie</GroupLabel>
      <Field label="HeyKiki-Telefonnummer">
        <div className="flex items-center gap-2 rounded-md border border-border bg-alt px-3 py-2 text-sm text-muted" title="Diese Nummer wird von HeyKiki bereitgestellt und kann nicht geändert werden.">
          <Lock size={14} className="text-faint" /><Phone size={14} className="text-faint" />
          <span className="text-text">{data.phone_number || 'Nicht zugewiesen'}</span>
        </div>
      </Field>
      <p className="mt-1 text-xs text-muted">Diese Nummer wird von HeyKiki bereitgestellt und kann nicht geändert werden. Für eine andere Rufnummer wenden Sie sich an support@heykiki.de.</p>
      <div className="mt-4">
        <Field label="Ihre bestehende Geschäftsnummer">
          <input
            type="tel"
            value={biz}
            onChange={(e) => setBiz(e.target.value)}
            placeholder="+49 …"
            className={inputCls}
          />
        </Field>
        <p className="mt-1 text-xs text-muted">
          Stellen Sie die Rufweiterleitung Ihres Telefonanbieters auf Ihre HeyKiki-Nummer ein, um Kiki Ihre Anrufe entgegennehmen zu lassen.{' '}
          <Link
            to="/docs/rufumleitung"
            target="_blank"
            rel="noopener noreferrer"
            className="text-green-primary underline hover:opacity-80"
          >
            Anleitung
          </Link>
        </p>
      </div>
      <div className="mt-4">
        <Field label="Eingehende Weiterleitung"><input value={inc} onChange={(e) => setInc(e.target.value)} placeholder="+49 …" className={inputCls} /></Field>
      </div>
      <p className="mt-1 text-xs text-muted">„Eingehende Weiterleitung" ist die Nummer, an die Kiki einen Anrufer an einen Menschen weiterleitet, wenn sie das Anliegen nicht selbst übernehmen kann. Die Notdienst-Weiterleitung wird im Bereich <span className="font-medium text-body">Notdienst</span> festgelegt.</p>
      <SaveBar
        onReset={() => {
          setInc(c.incoming_forwarding_number ?? '')
          setBiz(data.existing_business_number ?? '')
        }}
        onSave={() => kc.confirm(() => patch.mutate({
          incoming_forwarding_number: inc || null,
          existing_business_number: biz || null,
        }))}
        saving={patch.isPending}
      />
      {kc.element}
    </Card>
  )
}

// ─── Ausgehende Anrufe ───────────────────────────────────────────────────────
export function AusgehendeSection({ data, flash }: Props) {
  const c = data.config
  const kc = useKikiConfirm()
  const patch = useConfigPatch('/outbound', flash)
  const initialF = {
    outbound_enabled: c.outbound_enabled, outbound_occasions: { ...(c.outbound_occasions || {}) } as Record<string, boolean>,
    outbound_time_from: (c.outbound_time_from || '09:00').slice(0, 5), outbound_time_to: (c.outbound_time_to || '20:00').slice(0, 5),
    outbound_weekdays: c.outbound_weekdays ?? [],
    outbound_appt_confirm_enabled: c.outbound_appt_confirm_enabled ?? true,
    outbound_appt_cancel_enabled: c.outbound_appt_cancel_enabled ?? true,
    outbound_appt_reschedule_enabled: c.outbound_appt_reschedule_enabled ?? true,
    outbound_retry_max_attempts: c.outbound_retry_max_attempts ?? 0,
    outbound_retry_interval_minutes: c.outbound_retry_interval_minutes ?? 5,
    outbound_recall_on_short_hangup: c.outbound_recall_on_short_hangup ?? false,
    outbound_short_hangup_seconds: c.outbound_short_hangup_seconds ?? 20,
  }
  const [f, setF] = useState(initialF)
  const set = (k: keyof typeof f, v: unknown) => setF((p) => ({ ...p, [k]: v }))

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
        {f.outbound_occasions['appointment_reminder'] && (
          <div className="mt-3 rounded-lg border border-border bg-alt/40 p-3">
            <div className="mb-2 text-xs font-semibold text-body">Termin-Anrufe — welche Aktionen lösen einen Anruf aus?</div>
            <div className="flex flex-col gap-2">
              {([['outbound_appt_confirm_enabled', 'Bestätigen'], ['outbound_appt_cancel_enabled', 'Absagen'], ['outbound_appt_reschedule_enabled', 'Verschieben']] as const).map(([k, l]) => (
                <label key={k} className="flex items-center justify-between text-sm text-text">
                  <span>{l}</span>
                  <Toggle on={f[k]} onChange={(v) => set(k, v)} />
                </label>
              ))}
            </div>
            <p className="mt-2 text-[11px] text-muted">Ein Klick auf die jeweilige Aktion in den Anrufen löst nur dann einen Ausgangsanruf (+ E-Mail) aus, wenn sie hier aktiv ist.</p>
          </div>
        )}
        <SaveBar onReset={() => setF(initialF)} onSave={() => kc.confirm(() => patch.mutate(f))} saving={patch.isPending} />
      </Card>
      <Card>
        <GroupLabel>Wiederholung & Rückruf</GroupLabel>
        <p className="mb-3 text-xs text-muted">Nicht angenommene Ausgangsanrufe erneut versuchen und sehr kurze Anrufe (früh aufgelegt) automatisch wiederholen.</p>
        <div className="flex flex-wrap items-end gap-4">
          <Field label="Wiederholungen (max.)"><input type="number" min={0} max={10} value={f.outbound_retry_max_attempts} onChange={(e) => set('outbound_retry_max_attempts', Number(e.target.value))} className={cn(inputCls, 'w-24')} /></Field>
          <Field label="Abstand (Min.)"><input type="number" min={1} max={1440} value={f.outbound_retry_interval_minutes} onChange={(e) => set('outbound_retry_interval_minutes', Number(e.target.value))} className={cn(inputCls, 'w-24')} /></Field>
        </div>
        <label className="mt-3 flex items-center justify-between text-sm text-text">
          <span>Erneut anrufen, wenn der Kunde sehr früh auflegt</span>
          <Toggle on={f.outbound_recall_on_short_hangup} onChange={(v) => set('outbound_recall_on_short_hangup', v)} />
        </label>
        {f.outbound_recall_on_short_hangup && (
          <div className="mt-3">
            <Field label="Schwelle „früh aufgelegt&quot; (Sek.)"><input type="number" min={5} max={120} value={f.outbound_short_hangup_seconds} onChange={(e) => set('outbound_short_hangup_seconds', Number(e.target.value))} className={cn(inputCls, 'w-24')} /></Field>
          </div>
        )}
        <p className="mt-2 text-[11px] text-muted">Hinweis: Wiederholungen werden vom geplanten Ausgangsanruf-Lauf ausgelöst (Taktung extern). „0 Wiederholungen&quot; = aus.</p>
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
        <SaveBar onReset={() => setF(initialF)} onSave={() => kc.confirm(() => patch.mutate(f))} saving={patch.isPending} />
      </Card>
      {kc.element}
    </div>
  )
}
