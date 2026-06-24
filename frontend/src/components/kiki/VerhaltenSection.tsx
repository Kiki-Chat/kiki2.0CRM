import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Languages, Mic, Play, Plus, User, X } from 'lucide-react'
import { useRef, useState } from 'react'

import { apiFetch } from '../../lib/api'
import { KZ, KZ_STALE, type KzOverview, type KzVoice } from '../../lib/kikiApi'
import { cn } from '../../lib/utils'
import { Card, ConfirmDialog, Field, GroupLabel, inputCls, labelCls } from './shared'

// "Autonomie pro Bereich" lives in its own section now → AutonomieSection.tsx.
const LANGUAGES: [string, string][] = [
  ['de', 'Deutsch'], ['en', 'Englisch'], ['fr', 'Französisch'], ['es', 'Spanisch'], ['it', 'Italienisch'],
]

export function VerhaltenSection({ data, flash }: { data: KzOverview; flash: (m: string) => void }) {
  const qc = useQueryClient()
  const agent = data.agent
  const cfg = data.config

  const [welcome, setWelcome] = useState(cfg.welcome_message ?? '')
  const [welcomeMsgs, setWelcomeMsgs] = useState<{ from?: string; to?: string; message?: string }[]>(cfg.welcome_messages ?? [])
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

  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { welcome_message: welcome, welcome_messages: welcomeMsgs }
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

  // Every Verhalten save runs through the confirm dialog — saving here always
  // re-renders + pushes the agent prompt, even when only welcome texts changed.
  const onSave = () => setConfirmOpen(true)
  const playPreview = (url: string | null) => {
    if (!url) return
    audioRef.current?.pause()
    const a = new Audio(url)
    audioRef.current = a
    a.play().catch(() => flash('Vorschau konnte nicht abgespielt werden.'))
  }

  return (
    <div className="space-y-4">
      {/* Card 1 — Persona & Stimme (ElevenLabs) */}
      <Card>
        <GroupLabel>Stimme & Auftreten</GroupLabel>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Name der Stimme">
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
          <Field label="Begrüßung" hint={`${firstMessage.length}/500 Zeichen`}>
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
        <GroupLabel>Begrüßungstext (von HeyKiki vorgegeben)</GroupLabel>
        <textarea value={welcome} onChange={(e) => setWelcome(e.target.value)} className={cn(inputCls, 'min-h-[90px]')} />
        <p className="mt-1 text-xs text-muted">
          Dieser Text wird zusätzlich zu Kikis Begrüßung verwendet, um den Gesprächseinstieg zu steuern.
        </p>
      </Card>

      {/* Card 4 — Zeitabhängige Begrüßung (topic 20) */}
      <Card>
        <GroupLabel>Zeitabhängige Begrüßung (optional)</GroupLabel>
        <p className="mb-3 text-xs text-muted">
          Unterschiedliche Begrüßungen je Tageszeit. Bei eingehenden Anrufen wählt Kiki automatisch die passende
          Variante (sonst gilt die Standard-Begrüßung von Kiki oben).
        </p>
        <div className="space-y-2">
          {welcomeMsgs.length === 0 && <p className="text-sm text-faint">Keine zeitabhängigen Begrüßungen.</p>}
          {welcomeMsgs.map((w, i) => (
            <div key={i} className="rounded-lg border border-border bg-alt p-3">
              <div className="flex flex-wrap items-center gap-2">
                <input type="time" value={w.from ?? ''} onChange={(e) => setWelcomeMsgs((p) => p.map((x, j) => (j === i ? { ...x, from: e.target.value } : x)))} className={cn(inputCls, 'w-auto')} />
                <span className="text-sm text-muted">bis</span>
                <input type="time" value={w.to ?? ''} onChange={(e) => setWelcomeMsgs((p) => p.map((x, j) => (j === i ? { ...x, to: e.target.value } : x)))} className={cn(inputCls, 'w-auto')} />
                <button onClick={() => setWelcomeMsgs((p) => p.filter((_, j) => j !== i))} title="Entfernen" className="ml-auto text-muted hover:text-error"><X size={15} /></button>
              </div>
              <textarea value={w.message ?? ''} onChange={(e) => setWelcomeMsgs((p) => p.map((x, j) => (j === i ? { ...x, message: e.target.value } : x)))} placeholder="Begrüßung für dieses Zeitfenster (z. B. Guten Morgen! …)" className={cn(inputCls, 'mt-2 min-h-[60px]')} />
            </div>
          ))}
        </div>
        <button onClick={() => setWelcomeMsgs((p) => [...p, { from: '', to: '', message: '' }])} className="mt-3 inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-3 py-2 text-sm font-medium text-body hover:bg-alt"><Plus size={14} /> Zeitfenster</button>
      </Card>

      {/* Save bar (one green button) */}
      <div className="flex items-center justify-between rounded-xl border border-border bg-surface px-6 py-4">
        <button
          onClick={() => {
            setWelcome(cfg.welcome_message ?? ''); setWelcomeMsgs(cfg.welcome_messages ?? [])
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
        title="Kiki-Änderungen bestätigen"
        message="Diese Änderung an Persona, Stimme, Sprache oder Begrüßung wirkt sich sofort auf alle eingehenden Anrufe aus. Fortfahren?"
        confirmLabel="Speichern & anwenden"
        busy={save.isPending}
        onConfirm={() => save.mutate()}
      />
    </div>
  )
}
