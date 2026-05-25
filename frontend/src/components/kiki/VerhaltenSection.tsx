import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Languages, Mic, Play, User } from 'lucide-react'
import { useRef, useState } from 'react'

import { apiFetch } from '../../lib/api'
import { KZ, KZ_STALE, type KzOverview, type KzVoice } from '../../lib/kikiApi'
import { cn } from '../../lib/utils'
import { Card, ConfirmDialog, Field, GroupLabel, inputCls, labelCls } from './shared'

const LEVELS = [
  { n: 1, title: 'Assistenz', summary: 'Protokolliert & informiert Sie' },
  { n: 2, title: 'Halbautomatisch', summary: 'Handelt nach Ihrer Bestätigung' },
  { n: 3, title: 'Vollautomatisch', summary: 'Handelt eigenständig' },
]
const MATRIX: [string, string, string, string][] = [
  ['Termine', 'Nur Anfrage', 'Nach Bestätigung', 'Automatisch'],
  ['KVAs', 'Nicht erstellt', 'Entwurf zur Freigabe', 'Direkt an Kunde'],
  ['Notdienst', 'Protokollieren', 'Bestätigung', 'Direkt weiterleiten'],
  ['Termin verschieben', 'Notiz', 'Vorschlag', 'Automatisch'],
]
const LANGUAGES: [string, string][] = [
  ['de', 'Deutsch'], ['en', 'Englisch'], ['fr', 'Französisch'], ['es', 'Spanisch'], ['it', 'Italienisch'],
]

export function VerhaltenSection({ data, flash }: { data: KzOverview; flash: (m: string) => void }) {
  const qc = useQueryClient()
  const agent = data.agent
  const cfg = data.config

  const [level, setLevel] = useState(cfg.kiki_level)
  const [welcome, setWelcome] = useState(cfg.welcome_message ?? '')
  const [personaName, setPersonaName] = useState(agent.persona_name ?? '')
  const [language, setLanguage] = useState(agent.language ?? 'de')
  const [voiceId, setVoiceId] = useState(agent.voice_id ?? '')
  const [firstMessage, setFirstMessage] = useState(agent.first_message ?? '')
  const [confirmOpen, setConfirmOpen] = useState(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  const { data: voicesData } = useQuery({
    queryKey: ['kiki-zentrale', 'voices'],
    queryFn: () => apiFetch<{ voices: KzVoice[] }>(`${KZ}/voices`),
    staleTime: KZ_STALE,
  })
  const voices = voicesData?.voices ?? []
  const filtered = voices.filter((v) => !v.languages.length || v.languages.includes(language))
  const voicePool = filtered.length ? filtered : voices

  const elDirty =
    personaName !== (agent.persona_name ?? '') ||
    firstMessage !== (agent.first_message ?? '') ||
    voiceId !== (agent.voice_id ?? '') ||
    language !== (agent.language ?? 'de')

  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { kiki_level: level, welcome_message: welcome }
      if (personaName !== (agent.persona_name ?? '')) body.persona_name = personaName
      if (firstMessage !== (agent.first_message ?? '')) body.first_message = firstMessage
      if (voiceId !== (agent.voice_id ?? '')) body.voice_id = voiceId
      if (language !== (agent.language ?? 'de')) body.language = language
      return apiFetch(`${KZ}/verhalten`, { method: 'PATCH', body: JSON.stringify(body) })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['kiki-zentrale'] })
      setConfirmOpen(false)
      flash('Verhalten gespeichert.')
    },
    onError: (e: Error) => { setConfirmOpen(false); flash(e.message || 'Speichern fehlgeschlagen.') },
  })

  const onSave = () => (elDirty ? setConfirmOpen(true) : save.mutate())
  const playPreview = (url: string | null) => {
    if (!url) return
    audioRef.current?.pause()
    const a = new Audio(url)
    audioRef.current = a
    a.play().catch(() => flash('Vorschau konnte nicht abgespielt werden.'))
  }

  return (
    <div className="space-y-4">
      {/* Card 1 — Autonomie-Stufe */}
      <Card>
        <GroupLabel>Autonomie-Stufe</GroupLabel>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {LEVELS.map((l) => (
            <button
              key={l.n}
              onClick={() => setLevel(l.n)}
              className={cn(
                'rounded-lg border p-4 text-left transition',
                level === l.n ? 'border-green-primary bg-green-tint-50' : 'border-border hover:bg-alt',
              )}
            >
              <div className="flex items-center justify-between">
                <span className="text-2xl font-extrabold text-text">{l.n}</span>
                {level === l.n && <Check size={16} className="text-green-deep" />}
              </div>
              <div className="mt-1 text-sm font-bold text-text">{l.title}</div>
              <div className="text-xs text-muted">{l.summary}</div>
            </button>
          ))}
        </div>
        <div className="mt-4 overflow-hidden rounded-lg border border-border">
          <table className="w-full text-left text-sm">
            <thead className="bg-alt text-xs uppercase tracking-wide text-muted">
              <tr>
                <th className="px-3 py-2 font-semibold">Verhalten</th>
                <th className="px-3 py-2 font-semibold">Stufe 1</th>
                <th className="px-3 py-2 font-semibold">Stufe 2</th>
                <th className="px-3 py-2 font-semibold">Stufe 3</th>
              </tr>
            </thead>
            <tbody>
              {MATRIX.map((row) => (
                <tr key={row[0]} className="border-t border-border">
                  <td className="px-3 py-2 font-medium text-body">{row[0]}</td>
                  {[1, 2, 3].map((s) => (
                    <td key={s} className={cn('px-3 py-2 text-muted', level === s && 'bg-green-tint-50 font-semibold text-green-deep')}>
                      {row[s]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Card 2 — Persona & Stimme (ElevenLabs) */}
      <Card>
        <GroupLabel>Persona & Stimme</GroupLabel>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Persona-Name">
            <div className="relative">
              <User size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
              <input value={personaName} onChange={(e) => setPersonaName(e.target.value)} className={cn(inputCls, 'pl-9')} />
            </div>
          </Field>
          <Field label="Sprache">
            <div className="relative">
              <Languages size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
              <select value={language} onChange={(e) => setLanguage(e.target.value)} className={cn(inputCls, 'pl-9')}>
                {LANGUAGES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
          </Field>
        </div>
        <div className="mt-4">
          <div className={labelCls}>Stimme</div>
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Mic size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
              <select value={voiceId} onChange={(e) => setVoiceId(e.target.value)} className={cn(inputCls, 'pl-9')}>
                <option value="">— Stimme wählen —</option>
                {voicePool.map((v) => <option key={v.voice_id} value={v.voice_id}>{v.name}</option>)}
              </select>
            </div>
            <button
              type="button"
              disabled={!voiceId}
              onClick={() => playPreview(voicePool.find((v) => v.voice_id === voiceId)?.preview_url ?? null)}
              title="Stimme anhören"
              className="flex h-9 w-9 items-center justify-center rounded-md border border-border text-body hover:bg-alt disabled:opacity-40"
            >
              <Play size={15} />
            </button>
          </div>
        </div>
        <div className="mt-4">
          <Field label="Begrüßungs-Nachricht (first_message)" hint={`${firstMessage.length}/500 Zeichen`}>
            <textarea
              value={firstMessage}
              maxLength={500}
              onChange={(e) => setFirstMessage(e.target.value)}
              className={cn(inputCls, 'min-h-[90px]')}
            />
          </Field>
        </div>
      </Card>

      {/* Card 3 — Begrüßungstext (HeyKiki-seitig) */}
      <Card>
        <GroupLabel>Begrüßungstext (HeyKiki-seitig)</GroupLabel>
        <textarea value={welcome} onChange={(e) => setWelcome(e.target.value)} className={cn(inputCls, 'min-h-[90px]')} />
        <p className="mt-1 text-xs text-muted">
          Dieser Text wird zusätzlich zur Agenten-Begrüßung verwendet, um die Kontext-Initialisierung zu steuern.
        </p>
      </Card>

      {/* Save bar (one green button) */}
      <div className="flex items-center justify-between rounded-xl border border-border bg-surface px-6 py-4">
        <button
          onClick={() => {
            setLevel(cfg.kiki_level); setWelcome(cfg.welcome_message ?? '')
            setPersonaName(agent.persona_name ?? ''); setLanguage(agent.language ?? 'de')
            setVoiceId(agent.voice_id ?? ''); setFirstMessage(agent.first_message ?? '')
          }}
          className="text-sm font-medium text-muted hover:text-body"
        >
          Zurücksetzen
        </button>
        <button onClick={onSave} disabled={save.isPending} className="rounded-md bg-green-primary px-6 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">
          {save.isPending ? 'Speichert…' : 'Speichern'}
        </button>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Agenten-Änderung bestätigen"
        message="Diese Änderung an Persona, Stimme, Sprache oder Begrüßung wirkt sich sofort auf alle eingehenden Anrufe aus. Fortfahren?"
        confirmLabel="Speichern & anwenden"
        busy={save.isPending}
        onConfirm={() => save.mutate()}
      />
    </div>
  )
}
