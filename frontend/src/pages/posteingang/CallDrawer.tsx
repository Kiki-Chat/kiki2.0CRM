// Right-side call drawer — real transcript · Kiki summary · facts, plus the
// triage block: an unsorted call gets "Vorgang zuordnen / Neuer Vorgang / Als
// Spam"; a filed call shows its Vorgang + a "change case" picker.
import { Clock, Folder, FolderPlus, Inbox, Phone, Play, Sparkles, Trash2, X } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { Avatar, DirBadge, NotdienstBadge, StatusPill } from '../calls/atoms'
import { type CallDetailVM, useCallDetail, type VorgangVM } from './api'
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

function VorgangPicker({ candidates, onPick }: { candidates: VorgangVM[]; onPick: (inquiryId: string) => void }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 10 }}>
      {candidates.map((cand) => (
        <button
          key={cand.inquiryId}
          type="button"
          onClick={() => onPick(cand.inquiryId)}
          style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 11px', borderRadius: 'var(--radius-md)', border: 'none', background: 'var(--surface)', boxShadow: 'var(--ring)', cursor: 'pointer', textAlign: 'left', fontSize: 13, color: 'var(--text)' }}
        >
          <Folder size={14} style={{ color: 'var(--green-deep)' }} />
          <span style={{ flex: 1, minWidth: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{cand.problem}</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)' }}>{cand.ticket}</span>
        </button>
      ))}
    </div>
  )
}

export function CallDrawer({
  callId,
  onClose,
  candidates,
  onMove,
  onNew,
  onSpam,
}: {
  callId: string | null
  onClose: () => void
  candidates: VorgangVM[]
  onMove: (callId: string, inquiryId: string) => void
  onNew: (callId: string) => void
  onSpam: (callId: string) => void
}) {
  const [picking, setPicking] = useState(false)
  const { data: c, isLoading } = useCallDetail(callId)
  if (!callId) return null
  const dirColor = c?.dir === 'outbound' ? 'var(--outbound)' : 'var(--inbound)'
  const custCandidates = c ? candidates.filter((v) => v.custId && v.custId === c.custId) : candidates

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

              {c.unsorted ? (
                <div style={{ background: 'var(--warning-bg)', borderRadius: 'var(--radius-xl)', padding: 14, marginBottom: 18, boxShadow: 'inset 0 0 0 1px color-mix(in srgb, var(--warning) 26%, transparent)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 7, color: 'var(--warning)', fontFamily: 'var(--font-poster)', fontSize: 10.5, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}><Inbox size={13} /> Nicht zugeordnet</div>
                  <p style={{ margin: '0 0 12px', fontSize: 13, color: 'var(--body)', lineHeight: 1.45 }}>Dieser Anruf gehört noch zu keinem Vorgang. Ordnen Sie ihn zu oder legen Sie einen neuen an.</p>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {custCandidates.length > 0 && <Btn variant="primary" icon={<Folder size={14} />} onClick={() => setPicking((p) => !p)}>Vorgang zuordnen</Btn>}
                    <Btn variant="secondary" icon={<FolderPlus size={14} />} onClick={() => onNew(c.id)}>Neuer Vorgang</Btn>
                    <Btn variant="ghost" icon={<Trash2 size={14} />} onClick={() => onSpam(c.id)}>Als Spam</Btn>
                  </div>
                  {picking && <VorgangPicker candidates={custCandidates} onPick={(iid) => onMove(c.id, iid)} />}
                </div>
              ) : c.vorgangProblem ? (
                <div style={{ marginBottom: 18 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '11px 13px', background: 'var(--green-tint-50)', borderRadius: 'var(--radius-lg)' }}>
                    <Folder size={16} color="var(--green-deep)" />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontFamily: 'var(--font-poster)', fontSize: 13.5, fontWeight: 700, color: 'var(--green-deep)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.vorgangProblem}</div>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--muted)' }}>{c.ticket}</div>
                    </div>
                    {c.status && <StatusPill status={c.status} />}
                  </div>
                  {custCandidates.length > 0 && (
                    <button type="button" onClick={() => setPicking((p) => !p)} style={{ marginTop: 7, border: 'none', background: 'transparent', color: 'var(--muted)', fontSize: 12, fontFamily: 'var(--font-poster)', fontWeight: 600, cursor: 'pointer' }}>Falsch zugeordnet? Vorgang ändern</button>
                  )}
                  {picking && <VorgangPicker candidates={custCandidates} onPick={(iid) => onMove(c.id, iid)} />}
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
                <Btn variant="secondary" icon={<Play size={15} />}>Aufnahme abspielen</Btn>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
