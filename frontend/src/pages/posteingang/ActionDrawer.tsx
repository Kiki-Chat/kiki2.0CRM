// The "open action" drawer — the context-then-act surface a decision opens into.
// Clicking a decision card (on the dashboard deck or in the Posteingang) opens
// this right-side panel: it shows WHY the decision exists (the originating call's
// Kiki summary · transcript · recording, plus the proposed appointment slot and
// the named Vorgang) and hosts the REAL action buttons, with assign-before-confirm
// gating. Resolving here removes the card and closes the drawer — so every button
// has a visible effect instead of firing blind.
import { Clock, Folder, Phone, Play, Sparkles, X } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'

import { apiBlobUrl } from '../../lib/api'
import { Avatar, DirBadge, NotdienstBadge, StatusPill } from '../calls/atoms'
import { type DecisionVM, type Employee, useCallDetail } from './api'
import { AssigneeDot, Btn, TypeTag } from './parts'

const KIKI_AV = '/kiki-avatar.png'
const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`

// Full Berlin-time slot label for a proposed appointment (the one fact you need
// before confirming a Termin). Backend timestamps are UTC → render in Europe/Berlin.
function slotLabel(iso: string | null): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleString('de-DE', {
    weekday: 'short',
    day: 'numeric',
    month: 'long',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Europe/Berlin',
  })
}

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
      <div style={{ maxWidth: '78%' }}>
        <div style={{ padding: '8px 12px', borderRadius: 15, fontSize: 13, lineHeight: 1.5, background: agent ? 'var(--green-primary)' : 'var(--surface)', color: agent ? '#fff' : 'var(--body)', boxShadow: agent ? 'none' : 'var(--ring)', borderBottomRightRadius: agent ? 4 : 15, borderBottomLeftRadius: agent ? 15 : 4 }}>{m}</div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--faint)', marginTop: 3, textAlign: agent ? 'right' : 'left' }}>{clock(t)}</div>
      </div>
    </div>
  )
}

// On-demand recording playback (auth'd blob → object URL). Mirrors CallDrawer.
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

// The originating-call context block. Only rendered when the decision resolved a
// callId; fetches the call detail lazily (the drawer is the first place it's needed).
function CallContext({ callId }: { callId: string }) {
  const { data: c, isLoading } = useCallDetail(callId)
  if (isLoading || !c) {
    return <div style={{ padding: 24, textAlign: 'center', color: 'var(--muted)', fontSize: 13.5 }}>Anruf wird geladen…</div>
  }
  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap', marginBottom: 14 }}>
        <Fact icon={<Clock size={13} color="var(--faint)" />}>{c.date}</Fact>
        <Fact icon={<Phone size={13} color="var(--faint)" />}>{c.dur} Min</Fact>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}><DirBadge dir={c.dir} withLabel /></span>
        {c.emergency && <NotdienstBadge small />}
        {c.status && <StatusPill status={c.status} />}
      </div>

      <div style={{ background: 'var(--ai-bg)', borderRadius: 'var(--radius-xl)', padding: 14, marginBottom: 18 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 7, color: 'var(--ai)', fontFamily: 'var(--font-poster)', fontSize: 10.5, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}><Sparkles size={13} /> Kiki-Zusammenfassung</div>
        <p style={{ margin: 0, fontSize: 13.5, lineHeight: 1.55, color: 'var(--body)' }}>{c.summary}</p>
        {c.nextAction && (
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 13, color: 'var(--text)', marginTop: 11 }}>
            <span style={{ fontFamily: 'var(--font-poster)', fontWeight: 700, color: 'var(--ai)', whiteSpace: 'nowrap' }}>Nächste Aufgabe:</span>
            <span>{c.nextAction}</span>
          </div>
        )}
      </div>

      {c.transcript.length > 0 && (
        <>
          <div style={{ fontFamily: 'var(--font-poster)', fontSize: 10.5, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--muted)', marginBottom: 14 }}>Transkript</div>
          <div style={{ marginBottom: 18 }}>
            {c.transcript.map((e, i) => <Bubble key={i} role={e.role} m={e.m} t={e.t} />)}
          </div>
        </>
      )}

      <div style={{ paddingTop: 14, borderTop: '1px solid var(--border-faint)' }}>
        <AudioPlayer callId={c.id} />
      </div>
    </>
  )
}

export function ActionDrawer({
  decision: d,
  employees,
  busy = false,
  onResolve,
  onAssign,
  onClose,
}: {
  decision: DecisionVM | null
  employees: Employee[]
  busy?: boolean
  onResolve: (d: DecisionVM, choice: 'primary' | 'secondary' | 'tertiary') => void
  onAssign: (inquiryId: string, employeeId: string | null) => void
  onClose: () => void
}) {
  if (!d) return null
  // Assign ≠ confirm: a Termin tied to an inquiry can only be confirmed once
  // someone is assigned (same gate as the Posteingang card).
  const needsAssignee = d.kind === 'termin_anfrage' && !!d.inquiryId && !d.assigneeId
  const assignee = d.assigneeId ? employees.find((e) => e.id === d.assigneeId) : null
  const slot = slotLabel(d.dueAt)

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 90 }}>
      <div onClick={onClose} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.4)' }} />
      <div style={{ position: 'absolute', top: 0, right: 0, bottom: 0, width: 'min(540px, 96%)', background: 'var(--surface)', boxShadow: 'var(--elevation-3)', borderLeft: '1px solid var(--border)', display: 'flex', flexDirection: 'column' }}>
        {/* Scrollable body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px 24px' }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 16 }}>
            <Avatar employeeId={d.custId} text={(d.customer || '?').slice(0, 1).toUpperCase()} size={38} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontFamily: 'var(--font-poster)', fontSize: 16.5, fontWeight: 800, letterSpacing: '-0.01em', color: 'var(--text)' }}>{d.customer}</div>
              <div style={{ marginTop: 4 }}><TypeTag type={d.type} label={d.typeLabel} /></div>
            </div>
            <button type="button" onClick={onClose} style={{ border: 'none', background: 'var(--surface-alt)', borderRadius: 'var(--radius-lg)', width: 34, height: 34, display: 'grid', placeItems: 'center', cursor: 'pointer', color: 'var(--body)', flexShrink: 0 }}>
              <X size={17} />
            </button>
          </div>

          <h2 style={{ margin: '0 0 14px', fontFamily: 'var(--font-poster)', fontSize: 21, fontWeight: 800, letterSpacing: '-0.02em', lineHeight: 1.2, color: 'var(--text)' }}>{d.title}</h2>

          {/* Proposed slot — the decisive fact for a Termin / Verschiebung. */}
          {slot && (
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, marginBottom: 12, padding: '8px 13px', background: 'color-mix(in srgb, var(--info) 10%, transparent)', borderRadius: 'var(--radius-lg)' }}>
              <Clock size={15} color="var(--info)" />
              <span style={{ fontFamily: 'var(--font-poster)', fontSize: 13.5, fontWeight: 700, color: 'var(--text)' }}>{slot}</span>
            </div>
          )}

          {/* Which Vorgang this belongs to. */}
          {d.caseName && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, padding: '9px 13px', background: 'var(--green-tint-50)', borderRadius: 'var(--radius-lg)' }}>
              <Folder size={15} color="var(--green-deep)" style={{ flexShrink: 0 }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontFamily: 'var(--font-poster)', fontSize: 13, fontWeight: 700, color: 'var(--green-deep)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{d.caseName}</div>
              </div>
              {d.caseTicket && <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--muted)', flexShrink: 0 }}>{d.caseTicket}</span>}
            </div>
          )}

          {/* Kiki's recommendation for this decision. */}
          {d.reco && (
            <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', marginBottom: 18, fontSize: 13.5, color: 'var(--body)', lineHeight: 1.5 }}>
              <Sparkles size={15} color="var(--ai)" style={{ flexShrink: 0, marginTop: 2 }} />
              <span><span style={{ fontWeight: 700, color: 'var(--text)' }}>Kiki empfiehlt:</span> {d.reco}</span>
            </div>
          )}

          {/* Assignment is its own step — surfaced before confirming. */}
          {d.assignable && d.inquiryId && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18, padding: '11px 13px', background: 'var(--surface-alt)', borderRadius: 'var(--radius-lg)' }}>
              <span style={{ fontFamily: 'var(--font-poster)', fontSize: 11, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--muted)' }}>Zuständig</span>
              <AssigneeDot inquiryId={d.inquiryId} code={d.assigneeId} employees={employees} onAssign={onAssign} size={26} />
              <span style={{ fontSize: 13, fontWeight: 600, color: assignee ? 'var(--text)' : 'var(--faint)' }}>
                {assignee?.display_name ?? 'Niemand — zum Zuweisen klicken'}
              </span>
            </div>
          )}

          {/* Originating call context — summary, transcript, recording. */}
          {d.callId ? (
            <CallContext callId={d.callId} />
          ) : (
            <div style={{ padding: '13px 15px', background: 'var(--surface-alt)', borderRadius: 'var(--radius-lg)', fontSize: 13.5, color: 'var(--body)', lineHeight: 1.55 }}>
              {d.problem || 'Kein verknüpfter Anruf — diese Aufgabe stammt aus einem Dokument-Status.'}
            </div>
          )}
        </div>

        {/* Sticky action bar — the real buttons live here. */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', padding: '14px 24px', borderTop: '1px solid var(--border)', background: 'var(--surface)' }}>
          <Btn variant={d.type === 'storno' ? 'danger' : 'primary'} disabled={busy || needsAssignee} title={needsAssignee ? 'Erst zuweisen, dann bestätigen' : undefined} onClick={() => onResolve(d, 'primary')}>{d.primary}</Btn>
          {d.secondary && <Btn variant="secondary" disabled={busy} onClick={() => onResolve(d, 'secondary')}>{d.secondary}</Btn>}
          {d.tertiary && <Btn variant="ghost" disabled={busy} onClick={() => onResolve(d, 'tertiary')}>{d.tertiary}</Btn>}
          {needsAssignee && <span style={{ fontSize: 12, color: 'var(--warning)', fontWeight: 600, marginLeft: 'auto' }}>Erst zuweisen</span>}
        </div>
      </div>
    </div>
  )
}
