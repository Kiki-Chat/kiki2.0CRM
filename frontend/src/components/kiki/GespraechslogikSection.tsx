// Gesprächslogik — structured Wenn/Dann builder for tradesmen.
// The whole tree is LOCAL state; one Speichern = one PATCH = one agent push.
// The compiled German preview comes from the backend (single compiler, no TS
// port): POST /conversation-logic/preview, debounced.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUpDown, GitBranch, Plus, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { apiFetch } from '../../lib/api'
import { KZ } from '../../lib/kikiApi'
import { cn } from '../../lib/utils'
import { Card, Field, GroupLabel, inputCls, SaveBar, Toggle, useKikiConfirm } from './shared'

// ─── Tree types (mirror backend/app/schemas/conversation_logic.py) ───────────
type ActionType = 'ask' | 'say' | 'goto' | 'subrule'
interface LogicAction {
  id: string
  type: ActionType
  text?: string
  target?: 'schritt_2' | 'schritt_3' | 'abschluss'
  rule?: LogicRule
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
  ask: 'Frage stellen',
  say: 'Hinweis / Ansage',
  goto: 'Weiter zu …',
  subrule: 'Unterregel (Wenn/Sonst)',
}

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
        target: a.target,
        rule: a.rule ? fixRule(a.rule) : undefined,
      })),
    })),
  })
  return { version: doc.version ?? 1, blocks: (doc.blocks ?? []).map(fixRule) }
}

export function GespraechslogikSection({ flash }: { flash: (m: string) => void }) {
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
  const dragIdx = useRef<number | null>(null)

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

  // Debounced server-side compile for the live preview.
  useEffect(() => {
    if (!blocks.length) {
      setPreview('')
      setPreviewError(null)
      return
    }
    const t = setTimeout(async () => {
      try {
        const res = await apiFetch<{ text: string }>(`${KZ}/conversation-logic/preview`, {
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

  const onDrop = (to: number) => {
    const from = dragIdx.current
    dragIdx.current = null
    if (from === null || from === to) return
    touch((p) => {
      const next = [...p]
      const [m] = next.splice(from, 1)
      next.splice(to, 0, m)
      return next
    })
  }

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
        <div className="mb-1 flex items-center justify-between">
          <GroupLabel>Regeln</GroupLabel>
          <span className="text-xs text-muted">Ziehen zum Sortieren</span>
        </div>
        <div className="space-y-3">
          {blocks.length === 0 && (
            <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted">
              Noch keine Regeln. Beispiel: „Wenn ein Lieferant anruft → Anliegen erfragen → weiter zum Abschluss.“
            </p>
          )}
          {blocks.map((rule, i) => (
            <div
              key={rule.id}
              draggable
              onDragStart={() => (dragIdx.current = i)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => onDrop(i)}
              className="rounded-xl border border-border bg-alt/50 p-3"
            >
              <div className="mb-2 flex items-center gap-2">
                <ArrowUpDown size={14} className="cursor-grab text-faint" />
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
                onChange={(next) => touch((p) => p.map((r) => (r.id === rule.id ? next : r)))}
              />
            </div>
          ))}
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
        <GroupLabel>So liest Kiki diese Regeln</GroupLabel>
        {previewError ? (
          <div className="rounded-md bg-error-bg px-3 py-2 text-sm text-error">{previewError}</div>
        ) : preview ? (
          <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg border border-border bg-alt p-3 font-mono text-xs leading-relaxed text-body">{preview}</pre>
        ) : (
          <p className="text-sm text-faint">Die Vorschau erscheint, sobald Regeln angelegt sind.</p>
        )}
      </Card>
      {kc.element}
    </div>
  )
}

// ─── Rule / branch / action editors ─────────────────────────────────────────
function RuleEditor({ rule, depth, onChange }: { rule: LogicRule; depth: number; onChange: (r: LogicRule) => void }) {
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
          onChange={(next) => setBranch(br.id, next)}
          onRemove={
            rule.branches.length > 1
              ? () => onChange({ ...rule, branches: rule.branches.filter((b) => b.id !== br.id) })
              : undefined
          }
        />
      ))}
      <div className="flex gap-2">
        <button
          onClick={() => {
            // Sonst stays last.
            const sonstIdx = rule.branches.findIndex((b) => b.kind === 'sonst')
            const next = [...rule.branches]
            const nb = newBranch('sonst_wenn')
            if (sonstIdx === -1) next.push(nb)
            else next.splice(sonstIdx, 0, nb)
            onChange({ ...rule, branches: next })
          }}
          className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs font-medium text-body hover:bg-alt"
        >
          + Sonst-wenn
        </button>
        {!hasSonst && (
          <button
            onClick={() => onChange({ ...rule, branches: [...rule.branches, newBranch('sonst')] })}
            className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs font-medium text-body hover:bg-alt"
          >
            + Sonst
          </button>
        )}
      </div>
    </div>
  )
}

function BranchEditor({ branch, depth, onChange, onRemove }: {
  branch: LogicBranch
  depth: number
  onChange: (b: LogicBranch) => void
  onRemove?: () => void
}) {
  const kindLabel = branch.kind === 'wenn' ? 'Wenn' : branch.kind === 'sonst_wenn' ? 'Sonst, wenn' : 'Sonst'
  return (
    <div className="rounded-lg border border-border bg-surface p-2.5">
      <div className="mb-1.5 flex items-center gap-2">
        <span className={cn('rounded-full px-2 py-0.5 text-[11px] font-bold', branch.kind === 'sonst' ? 'bg-alt text-muted' : 'bg-green-tint-100 text-green-deep')}>{kindLabel}</span>
        {onRemove && (
          <button onClick={onRemove} title="Zweig löschen" className="ml-auto text-muted hover:text-error"><Trash2 size={13} /></button>
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
                placeholder="Bedingung, z. B. „der Anrufer ist ein Lieferant (kein Kunde)“"
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
      <div className="space-y-1.5">
        {branch.actions.map((a) => (
          <ActionEditor
            key={a.id}
            action={a}
            depth={depth}
            onChange={(next) => onChange({ ...branch, actions: branch.actions.map((x) => (x.id === a.id ? next : x)) })}
            onRemove={() => onChange({ ...branch, actions: branch.actions.filter((x) => x.id !== a.id) })}
          />
        ))}
        {branch.actions.length < 8 && (
          <AddActionButton depth={depth} onAdd={(type) => {
            const a: LogicAction = { id: uid(), type }
            if (type === 'goto') a.target = 'schritt_2'
            if (type === 'subrule') a.rule = newRule()
            onChange({ ...branch, actions: [...branch.actions, a] })
          }} />
        )}
      </div>
    </div>
  )
}

function AddActionButton({ depth, onAdd }: { depth: number; onAdd: (t: ActionType) => void }) {
  const types: ActionType[] = depth === 0 ? ['ask', 'say', 'goto', 'subrule'] : ['ask', 'say', 'goto']
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

function ActionEditor({ action, depth, onChange, onRemove }: {
  action: LogicAction
  depth: number
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
          <RuleEditor rule={action.rule} depth={1} onChange={(r) => onChange({ ...action, rule: r })} />
        </Field>
      )}
    </div>
  )
}
