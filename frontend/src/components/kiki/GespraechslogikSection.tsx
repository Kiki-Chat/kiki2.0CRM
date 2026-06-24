// Gesprächslogik — structured Wenn/Dann builder for tradesmen.
// The whole tree is LOCAL state; one Speichern = one PATCH = one agent push.
// The compiled German preview comes from the backend (single compiler, no TS
// port): POST /conversation-logic/preview, debounced.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CornerDownRight, GitBranch, Loader2, Plus, Sparkles, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import { apiFetch } from '../../lib/api'
import { KZ } from '../../lib/kikiApi'
import { cn } from '../../lib/utils'
import { Card, Field, GroupLabel, inputCls, SaveBar, Toggle, useKikiConfirm } from './shared'
import { DragHandle, SortableList, SortableRow } from './SortableList'

// ─── Tree types (mirror backend/app/schemas/conversation_logic.py) ───────────
type ActionType = 'ask' | 'ask_field' | 'say' | 'goto' | 'subrule'
interface LogicAction {
  id: string
  type: ActionType
  text?: string
  /** ask_field: reference to a Leitfaden field; text carries the label snapshot. */
  field_key?: string
  target?: 'schritt_2' | 'schritt_3' | 'abschluss'
  rule?: LogicRule
}
/** Leitfaden fields offered in ask_field selects — shared vocabulary with the guide. */
export interface GuideFieldOption {
  field_key: string
  label: string
  /** ON in the Standard-Ablauf → not selectable here (either/or; Kiki would ask twice). */
  activeInStandard?: boolean
}
interface LogicBranch {
  id: string
  kind: 'wenn' | 'sonst_wenn' | 'sonst'
  conditions: string[]
  condition_op: 'und' | 'oder'
  actions: LogicAction[]
}
interface LogicRule {
  id: string
  branches: LogicBranch[]
}
interface LogicDoc {
  version: number
  blocks: LogicRule[]
}

const uid = () => crypto.randomUUID()
const GOTO_OPTIONS: [string, string][] = [
  ['schritt_2', 'Schritt 2 (Daten aufnehmen)'],
  ['schritt_3', 'Schritt 3 (Termin)'],
  ['abschluss', 'Abschluss (Verabschiedung)'],
]
const ACTION_LABEL: Record<ActionType, string> = {
  ask: 'Freie Frage',
  ask_field: 'Feld aus Standard-Ablauf',
  say: 'Hinweis / Ansage',
  goto: 'Weiter zu …',
  subrule: 'Verschachtelte Regel (Wenn/Sonst)',
}

// Visual identity per branch kind — the if / else-if / else MUST look different
// at a glance (color + plain-German label), so a non-coder reads the structure
// without knowing what "if/else" means (Luca-meeting item 8).
const KIND_META: Record<LogicBranch['kind'], { label: string; badge: string; border: string; help: string }> = {
  wenn: {
    label: 'WENN',
    badge: 'bg-info-bg text-info',
    border: 'border-l-[3px] border-l-info',
    help: 'Die Regel, die Kiki zuerst prüft.',
  },
  sonst_wenn: {
    label: 'ANDERNFALLS, WENN',
    badge: 'bg-warning-bg text-warning',
    border: 'border-l-[3px] border-l-warning',
    help: 'Wird nur geprüft, wenn die Regel darüber NICHT zutrifft.',
  },
  sonst: {
    label: 'IN ALLEN ANDEREN FÄLLEN',
    badge: 'bg-alt text-muted',
    border: 'border-l-[3px] border-l-border',
    help: 'Greift, wenn keine der Regeln darüber zutrifft.',
  },
}

// Offer-point rows (Termin/KVA/Preisauskunft) ARE selectable in rules — they
// were filtered out before, which is why "Termine" and "KVA" were missing from
// the dropdown (item 7). Invoices intentionally have no row here at all.
const RULE_LINKED_OK = new Set(['appointments_enabled', 'kva_enabled', 'price_info_enabled'])

/** Every Leitfaden field referenced by an ask_field action (incl. nested rules). */
function collectUsedFieldKeys(blocks: LogicRule[]): string[] {
  const keys = new Set<string>()
  const walkRule = (r: LogicRule) =>
    r.branches.forEach((b) =>
      b.actions.forEach((a) => {
        if (a.type === 'ask_field' && a.field_key) keys.add(a.field_key)
        if (a.rule) walkRule(a.rule)
      }),
    )
  blocks.forEach(walkRule)
  return [...keys].sort()
}

// Template chips: each prefills the NL textarea with a ready description the
// user tweaks + generates — the manager's "templates", via the NL pipeline.
const NL_TEMPLATES: { label: string; text: string }[] = [
  {
    label: 'Lieferanten-Weiche',
    text: 'Wenn ein Lieferant anruft, frag nach der Lieferantennummer und notiere das Anliegen, danach direkt zum Abschluss. Wenn ein Kunde anruft, frag nach der Kundennummer und fahre normal fort.',
  },
  {
    label: 'Notfall-Weiche',
    text: 'Wenn der Anrufer einen Notfall meldet (z. B. Wasserschaden, Heizungsausfall im Winter), sag, dass wir uns sofort kümmern, und gehe direkt zur Terminvergabe.',
  },
  {
    label: 'Privat / Firma',
    text: 'Wenn ein Firmenkunde anruft, frag nach dem Firmennamen und der Kundennummer. Wenn ein Privatkunde anruft, frag nach dem Namen und der Adresse.',
  },
  {
    label: 'Bestandskunde zuerst',
    text: 'Frag als erstes, ob der Anrufer schon Kunde bei uns ist. Wenn ja, frag nach der Kundennummer. Wenn nein, frag nach Name, Adresse und Telefonnummer.',
  },
]

const newBranch = (kind: LogicBranch['kind']): LogicBranch => ({
  id: uid(), kind, conditions: kind === 'sonst' ? [] : [''], condition_op: 'und', actions: [],
})
const newRule = (): LogicRule => ({ id: uid(), branches: [newBranch('wenn')] })

// Ensure every node has an id (server may return id-less trees).
function withIds(doc: LogicDoc): LogicDoc {
  const fixRule = (r: LogicRule): LogicRule => ({
    id: r.id || uid(),
    branches: (r.branches ?? []).map((b) => ({
      id: b.id || uid(),
      kind: b.kind ?? 'wenn',
      conditions: b.conditions ?? [],
      condition_op: b.condition_op ?? 'und',
      actions: (b.actions ?? []).map((a) => ({
        id: a.id || uid(),
        type: a.type,
        text: a.text,
        field_key: a.field_key,
        target: a.target,
        rule: a.rule ? fixRule(a.rule) : undefined,
      })),
    })),
  })
  return { version: doc.version ?? 1, blocks: (doc.blocks ?? []).map(fixRule) }
}

export function GespraechslogikSection({
  flash,
  onUsedFieldsChange,
}: {
  flash: (m: string) => void
  /** Reports which Leitfaden fields the rules currently use (ask_field) — the
   * Gesprächsablauf page feeds this into the Standard-Ablauf so a field lives
   * EITHER in a Sonderfall OR im Standard, never in both (item 7). */
  onUsedFieldsChange?: (keys: string[]) => void
}) {
  const qc = useQueryClient()
  const kc = useKikiConfirm()
  const { data, dataUpdatedAt } = useQuery({
    queryKey: ['kiki-zentrale', 'conversation-logic'],
    queryFn: () => apiFetch<{ enabled: boolean; logic: LogicDoc }>(`${KZ}/conversation-logic`),
  })
  const [enabled, setEnabled] = useState(true)
  const [blocks, setBlocks] = useState<LogicRule[]>([])
  const [dirty, setDirty] = useState(false)
  const [preview, setPreview] = useState('')
  const [previewError, setPreviewError] = useState<string | null>(null)

  // Shared vocabulary with the Leitfaden: rules can ask guide fields directly
  // (ask_field), so both surfaces work on the same data points. Includes the
  // offer points (Termine/KVA/Preisauskunft) and also INACTIVE fields — a field
  // used here is deliberately off in the Standard-Ablauf (either/or).
  const { data: fieldsData } = useQuery({
    queryKey: ['kiki-zentrale', 'required-fields'],
    queryFn: () => apiFetch<{ fields: (GuideFieldOption & { is_active: boolean; linked_setting: string | null })[] }>(`${KZ}/required-fields`),
  })
  const guideFields: GuideFieldOption[] = (fieldsData?.fields ?? [])
    .filter((f) => !f.linked_setting || RULE_LINKED_OK.has(f.linked_setting))
    .map((f) => ({ field_key: f.field_key, label: f.label, activeInStandard: f.is_active }))

  // Tell the page which fields the Sonderfälle own (either/or with the Standard).
  const usedKeys = collectUsedFieldKeys(blocks).join(',')
  useEffect(() => {
    onUsedFieldsChange?.(usedKeys ? usedKeys.split(',') : [])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [usedKeys])

  // CONFLICTS: fields used here AND still active in the Standard-Ablauf — Kiki
  // would ask them twice. Warn loudly; the user resolves on either side.
  const conflictLabels = (usedKeys ? usedKeys.split(',') : [])
    .map((k) => guideFields.find((f) => f.field_key === k))
    .filter((f): f is GuideFieldOption => !!f && !!f.activeInStandard)
    .map((f) => f.label)

  useEffect(() => {
    if (!dirty && data) {
      setEnabled(data.enabled)
      setBlocks(withIds(data.logic).blocks)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataUpdatedAt])

  const touch = (updater: (p: LogicRule[]) => LogicRule[]) => {
    setBlocks(updater)
    setDirty(true)
  }

  // Debounced server-side compile for the live preview — COMBINED view: the
  // saved Leitfaden (default path) + these rules (exceptions), exactly the two
  // blocks the agent prompt receives. Runs even with zero rules so guide-only
  // users see their default flow here too.
  useEffect(() => {
    const t = setTimeout(async () => {
      try {
        const res = await apiFetch<{ text: string }>(`${KZ}/gespraechsablauf/preview`, {
          method: 'POST',
          body: JSON.stringify({ logic: { version: 1, blocks } }),
        })
        setPreview(res.text)
        setPreviewError(null)
      } catch (e) {
        setPreviewError(e instanceof Error ? e.message : 'Vorschau fehlgeschlagen.')
      }
    }, 500)
    return () => clearTimeout(t)
  }, [blocks])

  // Natural-language path: describe the rules, the AI builds the tree. The
  // result lands in the SAME local editor state (review + Speichern), so the
  // generated rules go through the identical validate/compile/save pipeline.
  const [nlText, setNlText] = useState('')
  const [nlError, setNlError] = useState<string | null>(null)
  const generate = useMutation({
    mutationFn: () =>
      apiFetch<{ logic: LogicDoc; text: string }>(`${KZ}/conversation-logic/generate`, {
        method: 'POST',
        body: JSON.stringify({
          description: nlText,
          existing: blocks.length ? { version: 1, blocks } : null,
        }),
      }),
    onSuccess: (res) => {
      setBlocks(withIds(res.logic).blocks)
      setDirty(true)
      setNlError(null)
      setNlText('')
      flash('Regeln erstellt — bitte prüfen und speichern.')
    },
    onError: (e: Error) => setNlError(e.message || 'Erstellen fehlgeschlagen.'),
  })

  const save = useMutation({
    mutationFn: () =>
      apiFetch(`${KZ}/conversation-logic`, {
        method: 'PATCH',
        body: JSON.stringify({ enabled, logic: { version: 1, blocks } }),
      }),
    onSuccess: () => {
      setDirty(false)
      qc.invalidateQueries({ queryKey: ['kiki-zentrale'] })
      flash('Gesprächslogik gespeichert.')
    },
    onError: (e: Error) => flash(e.message || 'Speichern fehlgeschlagen.'),
  })

  const moveRule = (from: number, to: number) =>
    touch((p) => {
      const next = [...p]
      const [m] = next.splice(from, 1)
      next.splice(to, 0, m)
      return next
    })

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 text-sm font-bold text-text"><GitBranch size={16} className="text-green-deep" /> Gesprächslogik aktiv</div>
            <div className="text-xs text-muted">Eigene Wenn/Dann-Regeln, die Kiki im Gespräch verbindlich abarbeitet (z. B. „Wenn kein Kunde anruft → nur Anliegen notieren“).</div>
          </div>
          <Toggle on={enabled} onChange={(v) => { setEnabled(v); setDirty(true) }} />
        </div>
      </Card>

      <Card>
        <div className="mb-1 flex items-center gap-2">
          <Sparkles size={15} className="text-ai" />
          <GroupLabel>In eigenen Worten beschreiben</GroupLabel>
        </div>
        <p className="mb-2 text-xs text-muted">
          Beschreibe einfach, wie Kiki sich verhalten soll — die KI baut daraus die
          Wenn/Dann-Regeln. Du kannst das Ergebnis unten noch anpassen, bevor du speicherst.
        </p>
        <div className="mb-2 flex flex-wrap gap-1.5">
          {NL_TEMPLATES.map((t) => (
            <button
              key={t.label}
              onClick={() => setNlText(t.text)}
              disabled={generate.isPending}
              className="rounded-full border border-border bg-surface px-3 py-1.5 text-xs font-medium text-body transition hover:border-green-primary hover:text-green-deep disabled:opacity-50"
            >
              {t.label}
            </button>
          ))}
        </div>
        <textarea
          value={nlText}
          onChange={(e) => setNlText(e.target.value)}
          rows={3}
          maxLength={4000}
          placeholder={'z. B. „Als erstes nach dem Namen fragen. Wenn ein Lieferant anruft, nach der Lieferantennummer fragen. Wenn ein Kunde anruft, nach der Kundennummer fragen.“'}
          className={cn(inputCls, 'resize-y text-sm')}
          disabled={generate.isPending}
        />
        {nlError && <div className="mt-2 rounded-md bg-error-bg px-3 py-2 text-sm text-error">{nlError}</div>}
        <div className="mt-2 flex items-center gap-3">
          <button
            onClick={() => generate.mutate()}
            disabled={generate.isPending || nlText.trim().length < 10}
            className="inline-flex items-center gap-1.5 rounded-md bg-green-primary px-3 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
          >
            {generate.isPending ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            {generate.isPending ? 'Erstellt Regeln…' : 'Regeln mit KI erstellen'}
          </button>
          {blocks.length > 0 && !generate.isPending && (
            <span className="text-xs text-muted">Bestehende Regeln werden berücksichtigt und ergänzt.</span>
          )}
        </div>
      </Card>

      <Card>
        <div className="mb-1 flex items-center justify-between">
          <GroupLabel>Wenn/Dann-Regeln</GroupLabel>
          <span className="text-xs text-muted">Ziehen zum Sortieren</span>
        </div>
        {conflictLabels.length > 0 && (
          <div className="mb-3 rounded-md border border-error/40 bg-error-bg/40 px-3 py-2 text-xs font-semibold text-error">
            ⚠ Doppelt abgefragt: {conflictLabels.join(', ')} — auch im Standard-Ablauf aktiv.
            Bitte den Schalter dort ausschalten oder das Feld hier aus dem Sonderfall entfernen.
          </div>
        )}
        <div className="space-y-3">
          {blocks.length === 0 && (
            <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted">
              Noch keine Regeln. Beispiel: „Wenn ein Lieferant anruft → Anliegen erfragen → weiter zum Abschluss.“
            </p>
          )}
          <SortableList ids={blocks.map((r) => r.id)} onMove={moveRule}>
            {blocks.map((rule, i) => (
              <SortableRow key={rule.id} id={rule.id} className="mb-3 rounded-xl border border-border bg-alt/50 p-3">
                {(handleProps) => (
                  <>
                    <div className="mb-2 flex items-center gap-2">
                      <DragHandle {...handleProps} />
                      <span className="text-xs font-bold uppercase tracking-wide text-muted">Regel {i + 1}</span>
                      <button
                        onClick={() => touch((p) => p.filter((r) => r.id !== rule.id))}
                        title="Regel löschen"
                        className="ml-auto text-muted hover:text-error"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                    <RuleEditor
                      rule={rule}
                      depth={0}
                      guideFields={guideFields}
                      onChange={(next) => touch((p) => p.map((r) => (r.id === rule.id ? next : r)))}
                    />
                  </>
                )}
              </SortableRow>
            ))}
          </SortableList>
        </div>
        <button
          onClick={() => touch((p) => [...p, newRule()])}
          className="mt-3 inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-3 py-2 text-sm font-medium text-body hover:bg-alt"
        >
          <Plus size={14} /> Neue Regel
        </button>
        <SaveBar
          onReset={() => { if (data) { setEnabled(data.enabled); setBlocks(withIds(data.logic).blocks) } setDirty(false) }}
          onSave={() => kc.confirm(() => save.mutate())}
          saving={save.isPending}
          disabled={!dirty}
        />
      </Card>

      <Card>
        <GroupLabel>So liest Kiki das Gespräch (Sonderfälle + Standard-Ablauf)</GroupLabel>
        <p className="mb-2 text-xs text-muted">
          Beide Teile zusammen: Deine Wenn/Dann-Regeln gelten zuerst, danach arbeitet Kiki den
          Standard-Ablauf aus dem Leitfaden oben ab.
        </p>
        {previewError ? (
          <div className="rounded-md bg-error-bg px-3 py-2 text-sm text-error">{previewError}</div>
        ) : preview ? (
          <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg border border-border bg-alt p-3 font-mono text-xs leading-relaxed text-body">{preview}</pre>
        ) : (
          <p className="text-sm text-faint">Vorschau wird geladen…</p>
        )}
      </Card>
      {kc.element}
    </div>
  )
}

// ─── Rule / branch / action editors ─────────────────────────────────────────
function RuleEditor({ rule, depth, guideFields, onChange }: { rule: LogicRule; depth: number; guideFields: GuideFieldOption[]; onChange: (r: LogicRule) => void }) {
  const setBranch = (id: string, next: LogicBranch) =>
    onChange({ ...rule, branches: rule.branches.map((b) => (b.id === id ? next : b)) })
  const hasSonst = rule.branches.some((b) => b.kind === 'sonst')
  return (
    <div className="space-y-2">
      {rule.branches.map((br) => (
        <BranchEditor
          key={br.id}
          branch={br}
          depth={depth}
          guideFields={guideFields}
          onChange={(next) => setBranch(br.id, next)}
          onRemove={
            rule.branches.length > 1
              ? () => onChange({ ...rule, branches: rule.branches.filter((b) => b.id !== br.id) })
              : undefined
          }
        />
      ))}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => {
            // The catch-all stays last.
            const sonstIdx = rule.branches.findIndex((b) => b.kind === 'sonst')
            const next = [...rule.branches]
            const nb = newBranch('sonst_wenn')
            if (sonstIdx === -1) next.push(nb)
            else next.splice(sonstIdx, 0, nb)
            onChange({ ...rule, branches: next })
          }}
          className="rounded-md border border-warning/40 bg-warning-bg/40 px-2.5 py-1.5 text-xs font-semibold text-warning hover:bg-warning-bg"
        >
          + Weiterer Fall (andernfalls, wenn …)
        </button>
        {!hasSonst && (
          <button
            onClick={() => onChange({ ...rule, branches: [...rule.branches, newBranch('sonst')] })}
            className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs font-semibold text-muted hover:bg-alt"
          >
            + Auffang-Fall (alle anderen)
          </button>
        )}
      </div>
    </div>
  )
}

function BranchEditor({ branch, depth, guideFields, onChange, onRemove }: {
  branch: LogicBranch
  depth: number
  guideFields: GuideFieldOption[]
  onChange: (b: LogicBranch) => void
  onRemove?: () => void
}) {
  const meta = KIND_META[branch.kind]
  return (
    <div className={cn('rounded-lg border border-border bg-surface p-2.5', meta.border)}>
      <div className="mb-1.5 flex items-center gap-2">
        <span className={cn('rounded-full px-2 py-0.5 text-[11px] font-bold tracking-wide', meta.badge)}>{meta.label}</span>
        <span className="hidden text-[11px] text-faint sm:inline">{meta.help}</span>
        {onRemove && (
          <button onClick={onRemove} title="Regel löschen" className="ml-auto text-muted hover:text-error"><Trash2 size={13} /></button>
        )}
      </div>
      {branch.kind !== 'sonst' && (
        <div className="mb-2 space-y-1.5">
          {branch.conditions.map((c, i) => (
            <div key={i} className="flex items-center gap-1.5">
              {i > 0 && (
                <button
                  onClick={() => onChange({ ...branch, condition_op: branch.condition_op === 'und' ? 'oder' : 'und' })}
                  title="UND/ODER umschalten"
                  className="shrink-0 rounded-md border border-border bg-alt px-1.5 py-1 text-[10px] font-bold uppercase text-body hover:bg-border"
                >
                  {branch.condition_op}
                </button>
              )}
              <input
                value={c}
                onChange={(e) => onChange({ ...branch, conditions: branch.conditions.map((x, j) => (j === i ? e.target.value : x)) })}
                placeholder="Was muss zutreffen? z. B. „Der Anrufer ist ein Lieferant“"
                maxLength={200}
                className={cn(inputCls, 'text-xs')}
              />
              {branch.conditions.length > 1 && (
                <button onClick={() => onChange({ ...branch, conditions: branch.conditions.filter((_, j) => j !== i) })} className="text-muted hover:text-error"><Trash2 size={13} /></button>
              )}
            </div>
          ))}
          {branch.conditions.length < 4 && (
            <button onClick={() => onChange({ ...branch, conditions: [...branch.conditions, ''] })} className="text-[11px] font-medium text-green-deep hover:underline">+ Bedingung</button>
          )}
        </div>
      )}
      <div className="mb-1 flex items-center gap-1 text-[11px] font-bold uppercase tracking-wide text-green-deep">
        <CornerDownRight size={12} /> Dann macht Kiki:
      </div>
      <div className="space-y-1.5 pl-4">
        {branch.actions.map((a) => (
          <ActionEditor
            key={a.id}
            action={a}
            depth={depth}
            guideFields={guideFields}
            onChange={(next) => onChange({ ...branch, actions: branch.actions.map((x) => (x.id === a.id ? next : x)) })}
            onRemove={() => onChange({ ...branch, actions: branch.actions.filter((x) => x.id !== a.id) })}
          />
        ))}
        {branch.actions.length < 8 && (
          <AddActionButton depth={depth} hasFields={guideFields.length > 0} onAdd={(type) => {
            const a: LogicAction = { id: uid(), type }
            if (type === 'goto') a.target = 'schritt_2'
            if (type === 'subrule') a.rule = newRule()
            if (type === 'ask_field' && guideFields[0]) {
              a.field_key = guideFields[0].field_key
              a.text = guideFields[0].label
            }
            onChange({ ...branch, actions: [...branch.actions, a] })
          }} />
        )}
      </div>
    </div>
  )
}

function AddActionButton({ depth, hasFields, onAdd }: { depth: number; hasFields: boolean; onAdd: (t: ActionType) => void }) {
  const base: ActionType[] = depth === 0 ? ['ask', 'say', 'goto', 'subrule'] : ['ask', 'say', 'goto']
  const types: ActionType[] = hasFields ? ['ask_field', ...base] : base
  return (
    <div className="flex flex-wrap gap-1.5 pt-1">
      {types.map((t) => (
        <button key={t} onClick={() => onAdd(t)} className="rounded-md border border-dashed border-border px-2 py-1 text-[11px] font-medium text-muted hover:bg-alt hover:text-body">
          + {ACTION_LABEL[t]}
        </button>
      ))}
    </div>
  )
}

function ActionEditor({ action, depth, guideFields, onChange, onRemove }: {
  action: LogicAction
  depth: number
  guideFields: GuideFieldOption[]
  onChange: (a: LogicAction) => void
  onRemove: () => void
}) {
  return (
    <div className={cn('rounded-md border border-border p-2', action.type === 'subrule' ? 'bg-info-bg/30' : 'bg-alt/60')}>
      <div className="mb-1 flex items-center gap-2">
        <span className="text-[10px] font-bold uppercase tracking-wide text-muted">{ACTION_LABEL[action.type]}</span>
        <button onClick={onRemove} title="Aktion löschen" className="ml-auto text-muted hover:text-error"><Trash2 size={12} /></button>
      </div>
      {(action.type === 'ask' || action.type === 'say') && (
        <input
          value={action.text ?? ''}
          onChange={(e) => onChange({ ...action, text: e.target.value })}
          placeholder={action.type === 'ask' ? 'z. B. „Warst du schonmal mit deinem Fahrzeug bei uns?“' : 'z. B. „Bitte ein Foto des Fahrzeugscheins per WhatsApp senden.“'}
          maxLength={200}
          className={cn(inputCls, 'text-xs')}
        />
      )}
      {action.type === 'ask_field' && (
        <select
          value={action.field_key ?? ''}
          onChange={(e) => {
            const f = guideFields.find((x) => x.field_key === e.target.value)
            onChange({ ...action, field_key: f?.field_key, text: f?.label })
          }}
          className={cn(inputCls, 'text-xs')}
        >
          {!action.field_key && <option value="">Feld wählen…</option>}
          {guideFields.map((f) => (
            // Either/or: a field that's ON in the Standard-Ablauf is not
            // selectable here — Kiki would ask it twice. (The currently saved
            // selection stays selectable so existing rules render; the conflict
            // banner above pushes the user to resolve it.)
            <option
              key={f.field_key}
              value={f.field_key}
              disabled={!!f.activeInStandard && f.field_key !== action.field_key}
            >
              {f.label}{f.activeInStandard ? ' — im Standard aktiv (dort ausschalten)' : ''}
            </option>
          ))}
          {/* Saved tree may reference a field that was since deleted/deactivated. */}
          {action.field_key && !guideFields.some((f) => f.field_key === action.field_key) && (
            <option value={action.field_key}>{action.text ?? action.field_key} (nicht mehr im Leitfaden)</option>
          )}
        </select>
      )}
      {action.type === 'goto' && (
        <select
          value={action.target ?? 'schritt_2'}
          onChange={(e) => onChange({ ...action, target: e.target.value as LogicAction['target'] })}
          className={cn(inputCls, 'text-xs')}
        >
          {GOTO_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      )}
      {action.type === 'subrule' && action.rule && depth === 0 && (
        <Field label="">
          <RuleEditor rule={action.rule} depth={1} guideFields={guideFields} onChange={(r) => onChange({ ...action, rule: r })} />
        </Field>
      )}
    </div>
  )
}
