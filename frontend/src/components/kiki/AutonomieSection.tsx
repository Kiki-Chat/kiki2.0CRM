import { useMutation, useQueryClient } from '@tanstack/react-query'
import { HelpCircle } from 'lucide-react'
import { useState } from 'react'

import { apiFetch } from '../../lib/api'
import { KZ, type KzOverview } from '../../lib/kikiApi'
import { cn } from '../../lib/utils'
import { Modal } from '../ui/Modal'
import { Card, GroupLabel, Toggle, useKikiConfirm } from './shared'

type CapKey = 'appointments' | 'kva' | 'projects' | 'invoices'
// Per-capability autonomy (topics 19/21/22). Termine + KVA act in the call;
// Projekte + Rechnungen run in the background. levels[0..2] = Stufe 1..3 — but the
// UI no longer exposes "Stufe": the on/off Toggle IS level 1 (off = record-only),
// and when on the user picks halb- (2) or vollautomatisch (3). The stored 1/2/3
// integers are unchanged, so backend/agent behaviour is identical.
const CAPABILITIES: { key: CapKey; label: string; hint: string; backOffice?: boolean; levels: [string, string, string] }[] = [
  { key: 'appointments', label: 'Termine', hint: 'Die Telefon-KI bucht Termine im Gespräch.',
    levels: ['Nur Anfrage aufnehmen — keine Buchung', 'Vorläufig buchen — das Team bestätigt', 'Verbindlich buchen & im Gespräch bestätigen'] },
  { key: 'kva', label: 'Kostenvoranschläge (KVA)', hint: 'Die Telefon-KI erstellt Kostenvoranschläge.',
    levels: ['Nur Anfrage aufnehmen — kein KVA', 'Entwurf erstellen — das Team versendet', 'Entwurf erstellen & direkt an den Kunden senden'] },
  { key: 'projects', label: 'Projekte & Plantafel', hint: 'Im Hintergrund bei Terminbestätigung.', backOffice: true,
    levels: ['Kein Projekt anlegen', 'Projekt als Entwurf bei Terminbestätigung', 'Projekt automatisch bei Terminbestätigung'] },
  { key: 'invoices', label: 'Rechnungen', hint: 'Im Hintergrund bei Projektabschluss.', backOffice: true,
    levels: ['Keine Rechnung anlegen', 'Rechnungsentwurf bei Projektabschluss', 'Rechnung automatisch erstellen (Versand folgt manuell)'] },
]

export function AutonomieSection({ data, flash }: { data: KzOverview; flash: (m: string) => void }) {
  const qc = useQueryClient()
  const cfg = data.config
  const kc = useKikiConfirm()

  // Keep the RAW stored values — no silent normalisation. OFF (enabled=false)
  // AND the legacy "enabled + Stufe 1" are both record-only on the backend, so
  // the toggle treats "on" as enabled AND level>=2 (see isOn). This way a
  // record-only org never shows as on, and an incidental save never flips it to
  // auto-book.
  const initialCaps = {
    appointments_enabled: cfg.appointments_enabled,
    appointments_level: cfg.appointments_level,
    reschedule_request_timeout_hours: cfg.reschedule_request_timeout_hours ?? 24,
    kva_enabled: cfg.kva_enabled,
    kva_level: cfg.kva_level,
    projects_enabled: cfg.projects_enabled,
    projects_level: cfg.projects_level,
    invoices_enabled: cfg.invoices_enabled,
    invoices_level: cfg.invoices_level,
  }
  const [caps, setCaps] = useState(initialCaps)
  const [hintOpen, setHintOpen] = useState(false)
  const setCap = (k: keyof typeof caps, v: boolean | number) => setCaps((p) => ({ ...p, [k]: v }))
  // "On" = enabled AND Stufe>=2 (Stufe 1 is record-only, same as off).
  const isOn = (key: CapKey) => caps[`${key}_enabled`] && caps[`${key}_level`] >= 2
  // Toggling ON ⇒ enabled + Stufe>=2 (never persists Stufe 1); OFF ⇒ enabled=false,
  // keeping the chosen level so re-enabling restores it.
  const setEnabled = (key: CapKey, v: boolean) =>
    setCaps((p) => ({
      ...p,
      [`${key}_enabled`]: v,
      [`${key}_level`]: v ? Math.max(2, p[`${key}_level`]) : p[`${key}_level`],
    }))

  // The autonomy card saves on its own button (batched) so toggling levels never
  // pushes in realtime.
  const capsDirty = (Object.keys(caps) as (keyof typeof caps)[]).some((k) => caps[k] !== initialCaps[k])
  const saveAutonomy = useMutation({
    mutationFn: () => apiFetch(`${KZ}/verhalten`, { method: 'PATCH', body: JSON.stringify(caps) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['kiki-zentrale'] })
      flash('Autonomie gespeichert.')
    },
    onError: (e: Error) => flash(e.message || 'Speichern fehlgeschlagen.'),
  })

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-center gap-1.5">
          <GroupLabel>Autonomie pro Bereich</GroupLabel>
          <button
            type="button"
            onClick={() => setHintOpen(true)}
            aria-label="Was bedeuten halb- und vollautomatisch?"
            title="Was bedeuten die Modi?"
            className="text-muted transition-colors hover:text-green-deep"
          >
            <HelpCircle size={15} />
          </button>
        </div>
        <p className="mb-3 text-xs text-muted">
          Schalten Sie jeden Bereich einzeln ein und wählen Sie, wie selbstständig Kiki arbeitet. Ist der
          Schalter aus, nimmt Kiki die Anfrage nur auf. Termine &amp; KVA wirken im Telefongespräch; Projekte
          &amp; Rechnungen laufen im Hintergrund.
        </p>
        <div className="space-y-3">
          {CAPABILITIES.map((cap) => {
            const enabled = isOn(cap.key)
            const lvl = caps[`${cap.key}_level`]
            return (
              <div key={cap.key} className={cn('rounded-lg border p-4 transition', enabled ? 'border-border' : 'border-border bg-alt/40')}>
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold text-text">{cap.label}</span>
                      {cap.backOffice && (
                        <span className="rounded-full bg-ai-bg px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ai">Hintergrund</span>
                      )}
                    </div>
                    <div className="text-xs text-muted">{cap.hint}</div>
                  </div>
                  <Toggle on={enabled} onChange={(v) => setEnabled(cap.key, v)} />
                </div>
                {enabled && (
                  <div className="mt-3">
                    <div className="flex gap-1.5">
                      {([2, 3] as const).map((s) => (
                        <button
                          key={s}
                          onClick={() => setCap(`${cap.key}_level`, s)}
                          className={cn(
                            'flex-1 rounded-md border px-2 py-1.5 text-xs font-semibold transition',
                            lvl === s ? 'border-green-primary bg-green-tint-50 text-green-deep' : 'border-border text-muted hover:bg-alt',
                          )}
                        >
                          {s === 2 ? 'Halbautomatisch' : 'Vollautomatisch'}
                        </button>
                      ))}
                    </div>
                    <p className="mt-2 text-xs text-body">{cap.levels[lvl - 1]}</p>
                    {cap.key === 'appointments' && (
                      <div className="mt-3 border-t border-border pt-3">
                        <label className="flex items-center justify-between gap-3">
                          <span className="min-w-0">
                            <span className="block text-xs font-semibold text-text">Umbuchungs-Timer</span>
                            <span className="block text-xs text-muted">
                              Stunden, die eine offene Umbuchung auf Ihre Entscheidung wartet.
                              {lvl >= 3
                                ? ' Danach wird sie automatisch aufgelöst.'
                                : ' Danach wird sie als überfällig markiert (keine automatische Stornierung).'}
                            </span>
                          </span>
                          <input
                            type="number"
                            min={1}
                            max={168}
                            value={caps.reschedule_request_timeout_hours}
                            onChange={(e) =>
                              setCap('reschedule_request_timeout_hours', Math.max(1, Number(e.target.value) || 1))
                            }
                            className="w-20 shrink-0 rounded-md border border-border bg-surface px-2 py-1.5 text-sm text-text outline-none focus:border-green-primary"
                          />
                        </label>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
        <div className="mt-4 flex items-center justify-end gap-3 border-t border-border pt-3">
          {capsDirty && <span className="text-xs font-medium text-amber-600">Nicht gespeichert</span>}
          <button
            onClick={() => kc.confirm(() => saveAutonomy.mutate())}
            disabled={!capsDirty || saveAutonomy.isPending}
            className="rounded-md bg-green-primary px-5 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
          >
            {saveAutonomy.isPending ? 'Speichert…' : 'Autonomie speichern'}
          </button>
        </div>
      </Card>

      <Modal open={hintOpen} onOpenChange={setHintOpen} title="So funktioniert die Autonomie">
        <p className="mb-4 text-sm text-body">
          Pro Bereich legen Sie fest, wie selbstständig Kiki arbeitet. Der Schalter steuert „aus“ (Stufe&nbsp;1);
          ist er an, wählen Sie zwischen halb- und vollautomatisch (Stufe&nbsp;2 oder&nbsp;3).
        </p>
        <div className="overflow-hidden rounded-lg border border-border">
          <table className="w-full text-left text-sm">
            <thead className="bg-alt text-xs uppercase tracking-wide text-muted">
              <tr>
                <th className="px-3 py-2 font-semibold">Stufe</th>
                <th className="px-3 py-2 font-semibold">Modus</th>
                <th className="px-3 py-2 font-semibold">Was passiert</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              <tr>
                <td className="px-3 py-2.5 align-top font-semibold text-text">1</td>
                <td className="whitespace-nowrap px-3 py-2.5 align-top font-medium text-text">Aus</td>
                <td className="px-3 py-2.5 text-body">Der Schalter ist aus — Kiki nimmt die Anfrage nur auf, ohne weitere Aktion.</td>
              </tr>
              <tr>
                <td className="px-3 py-2.5 align-top font-semibold text-text">2</td>
                <td className="whitespace-nowrap px-3 py-2.5 align-top font-medium text-text">Halbautomatisch</td>
                <td className="px-3 py-2.5 text-body">Kiki erledigt die Aufgabe (z. B. Entwurf oder Vorschlag) — Ihr Team bestätigt bzw. gibt sie frei.</td>
              </tr>
              <tr>
                <td className="px-3 py-2.5 align-top font-semibold text-text">3</td>
                <td className="whitespace-nowrap px-3 py-2.5 align-top font-medium text-text">Vollautomatisch</td>
                <td className="px-3 py-2.5 text-body">Kiki übernimmt alles automatisch — ohne weitere Bestätigung durch Ihr Team.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Modal>

      {kc.element}
    </div>
  )
}
