import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, History, RotateCcw } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { apiFetch } from '../../lib/api'
import { KZ, type KzPromptHistory } from '../../lib/kikiApi'
import { cn } from '../../lib/utils'
import { Card, ConfirmDialog } from './shared'

const TEMPLATES: [string, string][] = [
  ['Heizungs-/Sanitärbetrieb', 'Du bist Kiki, die freundliche Telefon-Assistentin eines Heizungs- und Sanitärbetriebs. Nimm Anliegen rund um Heizung, Bad und Sanitär auf, erkenne Notfälle (z. B. Wasserrohrbruch, Heizungsausfall im Winter) und vereinbare Termine. Frage immer nach Name, Rückrufnummer und Anliegen.'],
  ['Elektroinstallateur', 'Du bist Kiki, die Telefon-Assistentin eines Elektroinstallationsbetriebs. Nimm Aufträge rund um Elektroinstallation, Störungen und Prüfungen auf. Erkenne sicherheitskritische Notfälle (z. B. Stromausfall, Kabelbrand-Geruch) und priorisiere sie. Frage nach Name, Rückrufnummer und Anliegen.'],
  ['Schlüsseldienst', 'Du bist Kiki, die Telefon-Assistentin eines Schlüsseldienstes. Hilf Anrufern bei Aussperrungen und Schließanlagen-Problemen. Behandle Aussperrungen als dringend und kläre Adresse, Rückrufnummer und Türsituation. Nenne transparent mögliche Anfahrts- und Notdienstkosten.'],
  ['Dachdecker', 'Du bist Kiki, die Telefon-Assistentin eines Dachdeckerbetriebs. Nimm Anfragen zu Dachreparaturen, Sturmschäden und Sanierungen auf. Erkenne akute Schäden (z. B. undichtes Dach nach Sturm) und priorisiere sie. Frage nach Name, Rückrufnummer, Adresse und Anliegen.'],
  ['Allgemeiner Handwerksbetrieb', 'Du bist Kiki, die freundliche Telefon-Assistentin eines Handwerksbetriebs. Nimm Kundenanliegen professionell auf, beantworte einfache Fragen und vereinbare Termine. Frage stets nach Name, Rückrufnummer und dem konkreten Anliegen.'],
]

type Tab = 'edit' | 'diff' | 'history'

export function PromptEditorSection({ flash }: { flash: (m: string) => void }) {
  const qc = useQueryClient()
  const [tab, setTab] = useState<Tab>('edit')
  const [text, setText] = useState('')
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [tplOpen, setTplOpen] = useState(false)
  const [diff, setDiff] = useState<string>('')
  const [restoreSnap, setRestoreSnap] = useState<string | null>(null)
  const loaded = useRef(false)

  const { data, isLoading } = useQuery({
    queryKey: ['kiki-zentrale', 'prompt'],
    queryFn: () => apiFetch<{ prompt: string; history: KzPromptHistory[] }>(`${KZ}/prompt`),
  })

  useEffect(() => {
    if (data && !loaded.current) { setText(data.prompt); loaded.current = true }
  }, [data])

  const diffMut = useMutation({
    mutationFn: () => apiFetch<{ diff: string }>(`${KZ}/prompt/diff`, { method: 'POST', body: JSON.stringify({ proposed_prompt: text }) }),
    onSuccess: (r) => setDiff(r.diff),
  })
  const save = useMutation({
    mutationFn: () => apiFetch(`${KZ}/prompt`, { method: 'PATCH', body: JSON.stringify({ prompt: text }) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['kiki-zentrale', 'prompt'] })
      qc.invalidateQueries({ queryKey: ['kiki-zentrale'] })
      setConfirmOpen(false)
      flash('System-Prompt gespeichert.')
    },
    onError: (e: Error) => { setConfirmOpen(false); flash(e.message || 'Speichern fehlgeschlagen.') },
  })
  const restore = useMutation({
    mutationFn: (snapId: string) => apiFetch(`${KZ}/rollback/${snapId}`, { method: 'POST' }),
    onSuccess: () => {
      loaded.current = false
      qc.invalidateQueries({ queryKey: ['kiki-zentrale', 'prompt'] })
      qc.invalidateQueries({ queryKey: ['kiki-zentrale'] })
      setRestoreSnap(null)
      flash('Frühere Prompt-Version wiederhergestellt.')
    },
  })

  const dirty = data ? text !== data.prompt : false

  return (
    <Card>
      {/* Tab strip */}
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex gap-1 rounded-lg bg-alt p-1">
          {(['edit', 'diff', 'history'] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => { setTab(t); if (t === 'diff') diffMut.mutate() }}
              className={cn('rounded-md px-3 py-1.5 text-sm font-medium transition', tab === t ? 'bg-surface text-text shadow-sm' : 'text-muted hover:text-body')}
            >
              {t === 'edit' ? 'Bearbeiten' : t === 'diff' ? 'Vorschau Diff' : 'Verlauf'}
            </button>
          ))}
        </div>
        {tab === 'edit' && (
          <div className="relative">
            <button onClick={() => setTplOpen((o) => !o)} className="flex items-center gap-1.5 rounded-md border border-border bg-surface px-3 py-1.5 text-sm font-medium text-body hover:bg-alt">
              Vorlage einfügen <ChevronDown size={14} />
            </button>
            {tplOpen && (
              <div className="absolute right-0 z-10 mt-1 w-64 overflow-hidden rounded-lg border border-border bg-surface shadow-e3">
                {TEMPLATES.map(([name, body]) => (
                  <button key={name} onClick={() => { setText(body); setTplOpen(false) }} className="block w-full px-3 py-2 text-left text-sm text-body hover:bg-alt">
                    {name}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {isLoading ? (
        <div className="p-12 text-center text-muted">Lädt…</div>
      ) : tab === 'edit' ? (
        <>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="min-h-[600px] w-full rounded-md border border-border bg-alt px-3 py-2 font-mono text-xs leading-relaxed text-text outline-none focus:border-green-primary"
            spellCheck={false}
          />
          <div className="mt-1 text-right text-xs text-muted">{text.length} Zeichen</div>
        </>
      ) : tab === 'diff' ? (
        <div className="min-h-[400px] overflow-x-auto rounded-md border border-border bg-alt p-3 font-mono text-xs">
          {diffMut.isPending ? (
            <div className="p-8 text-center text-muted">Diff wird berechnet…</div>
          ) : diff ? (
            diff.split('\n').map((line, i) => (
              <div
                key={i}
                className={cn(
                  'whitespace-pre-wrap',
                  line.startsWith('+') && !line.startsWith('+++') && 'bg-success-bg text-success',
                  line.startsWith('-') && !line.startsWith('---') && 'bg-error-bg text-error',
                  line.startsWith('@@') && 'text-info',
                )}
              >
                {line || ' '}
              </div>
            ))
          ) : (
            <div className="p-8 text-center text-muted">Keine Änderungen gegenüber der gespeicherten Version.</div>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          {(data?.history ?? []).length === 0 && <div className="p-8 text-center text-muted">Noch keine früheren Versionen.</div>}
          {(data?.history ?? []).map((h) => (
            <div key={h.snapshot_id} className="flex items-center justify-between rounded-lg border border-border p-3">
              <div className="flex items-center gap-2 text-sm">
                <History size={15} className="text-muted" />
                <span className="text-body">{new Date(h.created_at).toLocaleString('de-DE', { timeZone: 'Europe/Berlin' })}</span>
                <span className="text-muted">· {h.prompt.length} Zeichen</span>
              </div>
              <button onClick={() => setRestoreSnap(h.snapshot_id)} className="flex items-center gap-1 text-sm font-medium text-green-deep hover:underline">
                <RotateCcw size={14} /> Wiederherstellen
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Bottom bar */}
      <div className="mt-6 flex items-center justify-between border-t border-border pt-4">
        <div className="flex items-center gap-4">
          <button onClick={() => data && setText(data.prompt)} className="text-sm font-medium text-muted hover:text-body">Verwerfen</button>
          <button onClick={() => { setTab('diff'); diffMut.mutate() }} className="rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-body hover:bg-alt">Vorschau ansehen</button>
        </div>
        <button
          onClick={() => setConfirmOpen(true)}
          disabled={!dirty || save.isPending}
          className="rounded-md bg-green-primary px-6 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
        >
          Prompt speichern
        </button>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="System-Prompt aktualisieren?"
        message="Diese Änderung wirkt sich auf alle zukünftigen Anrufe aus. Die vorherige Version wird im Verlauf gespeichert und kann wiederhergestellt werden."
        confirmLabel="Prompt speichern"
        busy={save.isPending}
        onConfirm={() => save.mutate()}
      />
      <ConfirmDialog
        open={!!restoreSnap}
        onOpenChange={(v) => !v && setRestoreSnap(null)}
        title="Version wiederherstellen?"
        message="Der Agent wird auf diese frühere Prompt-Version zurückgesetzt. Der aktuelle Stand wird zuvor als Snapshot gesichert."
        confirmLabel="Wiederherstellen"
        busy={restore.isPending}
        onConfirm={() => restoreSnap && restore.mutate(restoreSnap)}
      />
    </Card>
  )
}
