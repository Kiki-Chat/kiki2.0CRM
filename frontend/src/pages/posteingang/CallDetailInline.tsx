// Inline call detail — the call's Kiki summary · transcript · recording, rendered
// straight inside an expanded Posteingang card (NOT a drawer/slider). Mounted only
// when its card is expanded, so the call (and its transcript) is fetched lazily.
import { Clock, Phone, Play, Sparkles } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'

import { apiBlobUrl } from '../../lib/api'
import { Avatar, DirBadge, NotdienstBadge, StatusPill } from '../calls/atoms'
import { type CallDetailVM, useCallDetail } from './api'
import { Btn } from './parts'

const KIKI_AV = '/kiki-avatar.png'
const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`

function Fact({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12.5, color: 'var(--muted)', fontFamily: 'var(--font-mono)' }}>
      {icon}
      {children}
    </span>
  )
}

function Bubble({ role, m, t }: { role: 'agent' | 'customer'; m: string; t: number }) {
  const agent = role === 'agent'
  return (
    <div style={{ display: 'flex', flexDirection: agent ? 'row-reverse' : 'row', alignItems: 'flex-end', gap: 8, marginBottom: 12 }}>
      {agent ? (
        <img src={KIKI_AV} alt="Kiki" style={{ width: 26, height: 26, borderRadius: '50%', objectFit: 'cover', flexShrink: 0 }} />
      ) : (
        <Avatar employeeId="caller" text="?" size={26} />
      )}
      <div style={{ maxWidth: '80%' }}>
        <div style={{ padding: '8px 12px', borderRadius: 15, fontSize: 13, lineHeight: 1.5, background: agent ? 'var(--green-primary)' : 'var(--surface-alt)', color: agent ? '#fff' : 'var(--body)', borderBottomRightRadius: agent ? 4 : 15, borderBottomLeftRadius: agent ? 15 : 4 }}>{m}</div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--faint)', marginTop: 3, textAlign: agent ? 'right' : 'left' }}>{clock(t)}</div>
      </div>
    </div>
  )
}

function AudioPlayer({ callId }: { callId: string }) {
  const [state, setState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => () => { if (url) URL.revokeObjectURL(url) }, [url])
  const load = async () => {
    setState('loading')
    try {
      setUrl(await apiBlobUrl(`/api/calls/${callId}/audio`))
      setState('ready')
    } catch {
      setState('error')
    }
  }
  if (state === 'ready' && url) {
    return <audio src={url} controls autoPlay aria-label="Anrufaufnahme" style={{ width: '100%' }} />
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: '100%' }}>
      <Btn variant="secondary" icon={<Play size={15} />} disabled={state === 'loading'} onClick={load}>
        {state === 'loading' ? 'Aufnahme wird geladen…' : 'Aufnahme abspielen'}
      </Btn>
      {state === 'error' && <span style={{ fontSize: 12.5, color: 'var(--muted)' }}>Aufnahme derzeit nicht verfügbar.</span>}
    </div>
  )
}

export function CallDetailInline({ callId, showSummary = true }: { callId: string; showSummary?: boolean }) {
  const { data: c, isLoading } = useCallDetail(callId)
  if (isLoading || !c) {
    return <div style={{ padding: '18px 2px', textAlign: 'center', color: 'var(--muted)', fontSize: 13.5 }}>Anruf wird geladen…</div>
  }
  const cc: CallDetailVM = c
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap', marginBottom: 13 }}>
        <Fact icon={<Clock size={13} color="var(--faint)" />}>{cc.date}</Fact>
        <Fact icon={<Phone size={13} color="var(--faint)" />}>{cc.dur} Min</Fact>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}><DirBadge dir={cc.dir} withLabel /></span>
        {cc.emergency && <NotdienstBadge small />}
        {cc.status && <StatusPill status={cc.status} />}
      </div>

      {/* The card already shows the summary + next step in their own panels, so the
          inline transcript view skips the summary box to avoid duplication. */}
      {showSummary && (
        <div style={{ background: 'var(--ai-bg)', borderRadius: 'var(--radius-xl)', padding: 14, marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, color: 'var(--ai)', fontFamily: 'var(--font-poster)', fontSize: 10.5, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}><Sparkles size={13} /> Kiki-Zusammenfassung</div>
          <p style={{ margin: 0, fontSize: 13.5, lineHeight: 1.55, color: 'var(--body)', whiteSpace: 'pre-wrap' }}>{cc.summary}</p>
          {cc.nextAction && (
            <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 13, color: 'var(--text)', marginTop: 11 }}>
              <span style={{ fontFamily: 'var(--font-poster)', fontWeight: 700, color: 'var(--ai)', whiteSpace: 'nowrap' }}>Nächste Aufgabe:</span>
              <span>{cc.nextAction}</span>
            </div>
          )}
        </div>
      )}

      {cc.transcript.length > 0 && (
        <>
          <div style={{ fontFamily: 'var(--font-poster)', fontSize: 10.5, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--muted)', marginBottom: 13 }}>Transkript</div>
          <div style={{ marginBottom: 16, maxHeight: 320, overflowY: 'auto', paddingRight: 4 }}>
            {cc.transcript.map((e, i) => <Bubble key={i} role={e.role} m={e.m} t={e.t} />)}
          </div>
        </>
      )}

      <AudioPlayer callId={cc.id} />
    </div>
  )
}
