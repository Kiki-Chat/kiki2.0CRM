// Center pane: compact header, green subject strip, on-demand custom audio
// player (with the transcript↔audio active-line sync), and the chat thread.
import {
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Download,
  Pause,
  Phone,
  Play,
  Search,
  Sparkles,
  Volume2,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import kikiAvatar from '../../assets/kiki-avatar.png'
import { apiBlobUrl } from '../../lib/api'
import { cn, initials } from '../../lib/utils'
import { GhostBtn } from './ui'
import { DirBadge, NotdienstBadge, PhantomCaptureBadge } from './atoms'
import { type CallDetailData, displayName, fmtDuration, fmtTime } from './shared'

const clock = (s: number) =>
  Number.isFinite(s) ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}` : '0:00'
const SPEEDS = [1, 1.25, 1.5, 2]

export function Transcript({
  call,
  isSuperAdmin,
  onOpenSummary,
  onToggleRight,
  rightOpen,
}: {
  call: CallDetailData
  isSuperAdmin: boolean
  onOpenSummary: () => void
  onToggleRight?: () => void
  rightOpen?: boolean
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [audioState, setAudioState] = useState<'idle' | 'loading' | 'error'>('idle')
  const [showAudio, setShowAudio] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [cur, setCur] = useState(0)
  const [dur, setDur] = useState(0)
  const [rate, setRate] = useState(1)
  const [activeIdx, setActiveIdx] = useState(-1)
  const [query, setQuery] = useState<string | null>(null)
  const turnRefs = useRef<Map<number, HTMLDivElement>>(new Map())

  // Reset all audio/search state when switching calls.
  useEffect(() => {
    setAudioUrl(null)
    setAudioState('idle')
    setShowAudio(false)
    setPlaying(false)
    setCur(0)
    setDur(0)
    setRate(1)
    setActiveIdx(-1)
    setQuery(null)
  }, [call.id])

  const transcript = useMemo(() => call.transcript ?? [], [call.transcript])
  const timedTurns = useMemo(
    () =>
      transcript
        .map((t, i) => (typeof t.time_in_call_secs === 'number' ? { idx: i, t: t.time_in_call_secs } : null))
        .filter((x): x is { idx: number; t: number } => x !== null)
        .sort((a, b) => a.t - b.t),
    [transcript],
  )
  const hasTurnTimings = timedTurns.length > 0

  function activeIndexForTime(time: number): number {
    let chosen = -1
    for (let i = 0; i < timedTurns.length; i++) {
      if (timedTurns[i].t <= time) chosen = timedTurns[i].idx
      else break
    }
    return chosen
  }

  async function loadAudio() {
    setAudioState('loading')
    try {
      setAudioUrl(await apiBlobUrl(`/api/calls/${call.id}/audio`))
      setAudioState('idle')
    } catch {
      setAudioState('error')
    }
  }

  // Reveal the player → kick off the lazy load on first open.
  function toggleAudio() {
    setShowAudio((s) => {
      const next = !s
      if (next && !audioUrl && audioState !== 'loading') loadAudio()
      return next
    })
  }

  // Keep playbackRate applied across loads.
  useEffect(() => {
    if (audioRef.current) audioRef.current.playbackRate = rate
  }, [rate, audioUrl])

  // Smooth-scroll the active turn into view.
  useEffect(() => {
    if (activeIdx < 0) return
    turnRefs.current.get(activeIdx)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [activeIdx])

  const custInit = initials(displayName(call))
  const visibleTurns = transcript
    .map((turn, i) => ({ turn, i }))
    .filter(({ turn }) => {
      if (!query) return true
      return (turn.message ?? '').toLowerCase().includes(query.toLowerCase())
    })

  return (
    <section className="flex min-w-0 flex-1 flex-col bg-surface">
      {/* Compact header */}
      <header className="flex items-center gap-3 border-b border-border px-6 py-2.5">
        <span className="flex h-[42px] w-[42px] flex-shrink-0 items-center justify-center rounded-full bg-green-tint-100 text-[15px] font-extrabold text-green-deep">
          {custInit}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-base font-extrabold text-text">{displayName(call)}</span>
            {call.emergency_flag && <NotdienstBadge small />}
            {call.data_collection?.phantom_capture && <PhantomCaptureBadge small />}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[12.5px] text-muted">
            <span className="font-semibold">Anruf-Transkript</span>
            <Dot />
            <DirBadge dir={call.direction} withLabel />
            <Dot />
            <span>{fmtTime(call.started_at)}</span>
            <Dot />
            <span className="tabular-nums">{fmtDuration(call.duration_seconds)}</span>
          </div>
        </div>
        <div className="flex flex-shrink-0 items-center gap-1">
          <GhostBtn
            icon={Search}
            title="Im Transkript suchen"
            active={query !== null}
            onClick={() => setQuery((q) => (q === null ? '' : null))}
          />
          <GhostBtn icon={Volume2} title="Aufnahme anhören" active={showAudio} onClick={toggleAudio} />
          {onToggleRight && (
            <GhostBtn
              icon={rightOpen ? ChevronsRight : ChevronsLeft}
              active={!rightOpen}
              title={rightOpen ? 'Arbeitsbereich ausblenden' : 'Arbeitsbereich einblenden'}
              onClick={onToggleRight}
            />
          )}
        </div>
      </header>

      {/* Green subject strip */}
      <div className="flex items-center gap-3 border-b border-border bg-green-tint-50 px-6 py-2.5">
        <span className="h-[18px] w-1 flex-shrink-0 rounded-full bg-green-primary" />
        <span className="flex-1 truncate text-[13.5px] font-extrabold text-green-deep">
          {call.summary_title ?? 'Anruf'}
        </span>
        <button
          onClick={onOpenSummary}
          title="Zusammenfassung in Details öffnen"
          className="inline-flex flex-shrink-0 items-center gap-1.5 rounded-lg border border-green-tint-200 bg-surface px-2.5 py-1.5 text-xs font-bold text-green-deep hover:bg-green-tint-50"
        >
          <Sparkles size={13} className="text-ai" /> Zusammenfassung <ChevronRight size={13} />
        </button>
      </div>

      {/* Transcript search box */}
      {query !== null && (
        <div className="flex items-center gap-2 border-b border-border bg-alt px-6 py-2">
          <Search size={14} className="text-faint" />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Im Transkript suchen…"
            className="flex-1 bg-transparent text-sm text-text outline-none placeholder:text-faint"
          />
          <button onClick={() => setQuery(null)} className="text-faint hover:text-muted">
            <X size={15} />
          </button>
        </div>
      )}

      {/* On-demand custom audio player */}
      {showAudio && (
        <div className="flex items-center gap-3 border-b border-border bg-alt px-6 py-2.5">
          <Volume2 size={16} className="flex-shrink-0 text-muted" />
          {audioState === 'loading' ? (
            <span className="text-sm text-muted">Aufnahme wird geladen…</span>
          ) : audioState === 'error' ? (
            <span className="text-xs text-error">Aufnahme nicht verfügbar.</span>
          ) : !audioUrl ? (
            <button
              onClick={loadAudio}
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface px-3.5 py-2 text-sm font-bold text-body hover:bg-alt"
            >
              <Play size={14} /> Aufnahme laden
            </button>
          ) : (
            <div className="flex max-w-[560px] flex-1 items-center gap-3">
              <button
                onClick={() => {
                  const el = audioRef.current
                  if (!el) return
                  if (el.paused) void el.play()
                  else el.pause()
                }}
                className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-green-primary text-white"
              >
                {playing ? <Pause size={15} /> : <Play size={15} />}
              </button>
              <span className="flex-shrink-0 text-[11.5px] tabular-nums text-muted">{clock(cur)}</span>
              <div
                className="relative h-1.5 flex-1 cursor-pointer overflow-hidden rounded-full bg-border"
                onClick={(e) => {
                  const el = audioRef.current
                  if (!el || !dur) return
                  const r = e.currentTarget.getBoundingClientRect()
                  el.currentTime = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * dur
                }}
              >
                <div
                  className="absolute inset-y-0 left-0 rounded-full bg-green-primary"
                  style={{ width: dur ? `${(cur / dur) * 100}%` : '0%' }}
                />
              </div>
              <span className="flex-shrink-0 text-[11.5px] tabular-nums text-faint">{clock(dur)}</span>
              <button
                title="Wiedergabegeschwindigkeit"
                onClick={() => setRate((r) => SPEEDS[(SPEEDS.indexOf(r) + 1) % SPEEDS.length])}
                className="flex h-8 min-w-[34px] flex-shrink-0 items-center justify-center rounded-lg border border-border bg-surface px-2 text-xs font-bold text-muted"
              >
                {rate}×
              </button>
              <a
                href={audioUrl}
                download={`anruf-${call.id}.mp3`}
                title="Herunterladen"
                className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg border border-border bg-surface text-muted hover:text-body"
              >
                <Download size={15} />
              </a>
            </div>
          )}
          {audioUrl && !hasTurnTimings && (
            <span className="text-[11px] text-faint">Älterer Anruf — Sprungmarken nicht verfügbar.</span>
          )}
          <audio
            ref={audioRef}
            src={audioUrl ?? undefined}
            preload="metadata"
            className="hidden"
            onLoadedMetadata={(e) => setDur(e.currentTarget.duration || 0)}
            onTimeUpdate={(e) => {
              setCur(e.currentTarget.currentTime)
              setActiveIdx(activeIndexForTime(e.currentTarget.currentTime))
            }}
            onPlay={() => setPlaying(true)}
            onPause={() => {
              setPlaying(false)
              setActiveIdx(-1)
            }}
            onEnded={() => {
              setPlaying(false)
              setActiveIdx(-1)
            }}
          />
        </div>
      )}

      {/* Thread */}
      <div className="scroll flex flex-1 flex-col gap-[18px] overflow-y-auto p-[22px]">
        {visibleTurns.map(({ turn, i }) => {
          const isKiki = turn.role === 'agent'
          const hasMessage = !!(turn.message && turn.message.trim())
          const visibleToolCalls = isSuperAdmin ? turn.tool_calls.filter(Boolean) : []
          if (!hasMessage && visibleToolCalls.length === 0) return null
          const isActive = activeIdx === i
          const ts = typeof turn.time_in_call_secs === 'number' ? clock(turn.time_in_call_secs) : ''
          return (
            <div
              key={i}
              ref={(node) => {
                if (node) turnRefs.current.set(i, node)
                else turnRefs.current.delete(i)
              }}
              className={cn('flex items-end gap-2.5', isKiki ? 'flex-row-reverse' : 'flex-row')}
            >
              {isKiki ? (
                <img
                  src={kikiAvatar}
                  alt="Kiki"
                  className="h-8 w-8 flex-shrink-0 rounded-full bg-green-tint-100 object-cover shadow-e1"
                  style={{ objectPosition: '50% 8%' }}
                />
              ) : (
                <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-alt text-xs font-extrabold text-muted">
                  {custInit}
                </span>
              )}
              <div className={cn('flex max-w-[72%] flex-col gap-1', isKiki ? 'items-end' : 'items-start')}>
                <span className={cn('px-1 text-[11px] font-extrabold', isKiki ? 'text-green-deep' : 'text-muted')}>
                  {isKiki ? 'Kiki' : displayName(call)}
                </span>
                {hasMessage && (
                  <div
                    className={cn(
                      'rounded-2xl px-3.5 py-2.5 text-[13.5px] leading-relaxed transition-shadow',
                      isKiki
                        ? 'rounded-br-sm bg-green-primary text-white'
                        : 'rounded-bl-sm border border-border bg-surface text-text',
                      isActive && 'shadow-e2',
                    )}
                  >
                    {turn.message}
                    {ts && (
                      <span
                        className={cn(
                          'mt-1 block text-right text-[10.5px]',
                          isKiki ? 'text-white/70' : 'text-faint',
                        )}
                      >
                        {ts}
                      </span>
                    )}
                  </div>
                )}
                {visibleToolCalls.map((t, j) => (
                  <span
                    key={j}
                    className="inline-block rounded-full bg-ai-bg px-2 py-0.5 text-[11px] font-semibold text-ai"
                  >
                    ⚙ {t}
                  </span>
                ))}
              </div>
            </div>
          )
        })}
        {!transcript.length && <p className="text-sm text-muted">Kein Transkript vorhanden.</p>}
        {!!transcript.length && query && !visibleTurns.length && (
          <p className="text-sm text-muted">Keine Treffer im Transkript.</p>
        )}
      </div>
    </section>
  )
}

function Dot() {
  return <span className="h-[3px] w-[3px] flex-shrink-0 rounded-full bg-faint" />
}

// Empty-state when no call is selected (used by CallLogsPage).
export function NoCallSelected() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 text-muted">
      <Phone size={30} className="text-faint" />
      <span className="text-[13.5px]">Wähle einen Anruf aus.</span>
    </div>
  )
}
