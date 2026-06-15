// Right-side call drawer — a read-only call view: Kiki summary · transcript ·
// recording playback, plus a read-only Fall indicator. Triage (Vorgang zuordnen /
// Neuer Vorgang / Als Spam) now lives in the Anrufe cockpit, not in the inbox.
import { Clock, Folder, Inbox, Phone, Play, Sparkles, X } from 'lucide-react'
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

function Bubble({ e }: { e: CallDetailVM['transcript'][number] }) {
  const agent = e.role === 'agent'
  return (
    <div style={{ display: 'flex', flexDirection: agent ? 'row-reverse' : 'row', alignItems: 'flex-end', gap: 8, marginBottom: 14 }}>
      {agent ? (
        <img src={KIKI_AV} alt="Kiki" style={{ width: 28, height: 28, borderRadius: '50%', objectFit: 'cover', flexShrink: 0 }} />
      ) : (
        <Avatar employeeId="caller" text="?" size={28} />
      )}
      <div style={{ maxWidth: '78%' }}>
        <div style={{ padding: '9px 13px', borderRadius: 16, fontSize: 13.5, lineHeight: 1.5, background: agent ? 'var(--green-primary)' : 'var(--surface)', color: agent ? '#fff' : 'var(--body)', boxShadow: agent ? 'none' : 'var(--ring)', borderBottomRightRadius: agent ? 4 : 16, borderBottomLeftRadius: agent ? 16 : 4 }}>{e.m}</div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--faint)', marginTop: 4, textAlign: agent ? 'right' : 'left' }}>{clock(e.t)}</div>
      </div>
    </div>
  )
}

// On-demand recording playback. The audio route needs the bearer token, so we
// fetch it as a blob with auth (apiBlobUrl) and feed the object URL to <audio>.
function AudioPlayer({ callId }: { callId: string }) {
  const [state, setState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const [url, setUrl] = useState<string | null>(null)
  // Revoke the object URL on unmount / change so we don't leak blobs.
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
        {state === 'loading' ? 'Lädt Aufnahme…' : 'Aufnahme abspielen'}
      </Btn>
      {state === 'error' && (
        <span style={{ fontSize: 12.5, color: 'var(--muted)' }}>Aufnahme derzeit nicht verfügbar.</span>
      )}
    </div>
  )
}

export function CallDrawer({ callId, onClose }: { callId: string | null; onClose: () => void }) {
  const { data: c, isLoading } = useCallDetail(callId)
  if (!callId) return null
  const dirColor = c?.dir === 'outbound' ? 'var(--outbound)' : 'var(--inbound)'

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 80 }}>
      <div onClick={onClose} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.4)' }} />
      <div style={{ position: 'absolute', top: 0, right: 0, bottom: 0, width: 'min(540px, 96%)', background: 'var(--surface)', boxShadow: 'var(--elevation-3)', borderLeft: '1px solid var(--border)', overflowY: 'auto' }}>
        <div style={{ padding: '20px 24px 40px' }}>
          {isLoading || !c ? (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--muted)', fontSize: 14 }}>Lädt…</div>
          ) : (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
                <span style={{ width: 34, height: 34, borderRadius: '50%', display: 'grid', placeItems: 'center', flexShrink: 0, background: `color-mix(in srgb, ${dirColor} 14%, transparent)` }}>
                  <DirBadge dir={c.dir} />
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontFamily: 'var(--font-poster)', fontSize: 17, fontWeight: 800, letterSpacing: '-0.01em', color: 'var(--text)' }}>{c.customer}</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12.5, color: 'var(--muted)' }}>{c.number}</div>
                </div>
                <button type="button" onClick={onClose} style={{ border: 'none', background: 'var(--surface-alt)', borderRadius: 'var(--radius-lg)', width: 34, height: 34, display: 'grid', placeItems: 'center', cursor: 'pointer', color: 'var(--body)', flexShrink: 0 }}>
                  <X size={17} />
                </button>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap', marginBottom: 16 }}>
                <Fact icon={<Clock size={13} color="var(--faint)" />}>{c.date}</Fact>
                <Fact icon={<Phone size={13} color="var(--faint)" />}>{c.dur} Min</Fact>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}><DirBadge dir={c.dir} withLabel /></span>
                {c.emergency && <NotdienstBadge small />}
              </div>

              {/* Read-only Fall indicator (triage moved to the Anrufe cockpit). */}
              {c.vorgangProblem ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '11px 13px', background: 'var(--green-tint-50)', borderRadius: 'var(--radius-lg)', marginBottom: 18 }}>
                  <Folder size={16} color="var(--green-deep)" />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontFamily: 'var(--font-poster)', fontSize: 13.5, fontWeight: 700, color: 'var(--green-deep)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.vorgangProblem}</div>
                    {c.ticket && <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--muted)' }}>{c.ticket}</div>}
                  </div>
                  {c.status && <StatusPill status={c.status} />}
                </div>
              ) : c.unsorted ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '11px 13px', background: 'var(--surface-alt)', borderRadius: 'var(--radius-lg)', marginBottom: 18, fontSize: 12.5, color: 'var(--muted)' }}>
                  <Inbox size={14} style={{ flexShrink: 0 }} />
                  <span>Noch keinem Fall zugeordnet — im Anruf-Cockpit zuordnen.</span>
                </div>
              ) : null}

              <div style={{ background: 'var(--ai-bg)', borderRadius: 'var(--radius-xl)', padding: 15, marginBottom: 22 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 7, color: 'var(--ai)', fontFamily: 'var(--font-poster)', fontSize: 10.5, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}><Sparkles size={13} /> Kiki-Zusammenfassung</div>
                <p style={{ margin: '0 0 0', fontSize: 14, lineHeight: 1.55, color: 'var(--body)' }}>{c.summary}</p>
                {c.nextAction && (
                  <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 13, color: 'var(--text)', marginTop: 12 }}>
                    <span style={{ fontFamily: 'var(--font-poster)', fontWeight: 700, color: 'var(--ai)', whiteSpace: 'nowrap' }}>Nächste Aktion:</span>
                    <span>{c.nextAction}</span>
                  </div>
                )}
              </div>

              <div style={{ fontFamily: 'var(--font-poster)', fontSize: 10.5, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--muted)', marginBottom: 16 }}>Transkript</div>
              <div style={{ marginBottom: 24 }}>
                {c.transcript.length > 0 ? c.transcript.map((e, i) => <Bubble key={i} e={e} />) : <div style={{ fontSize: 13, color: 'var(--muted)' }}>Kein Transkript verfügbar.</div>}
              </div>

              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', paddingTop: 16, borderTop: '1px solid var(--border-faint)' }}>
                <AudioPlayer callId={c.id} />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
