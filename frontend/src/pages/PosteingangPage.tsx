// Posteingang — Fokus·Agenda, wired to live kiki-test-007 data. Decisions come
// from /api/actions/pending and resolve through the real appointment/KVA
// endpoints; Vorgänge from /api/calls (timeline lazy-loaded from the inquiry
// thread); the assignee is a real dropdown everywhere; "Kiki empfiehlt" executes;
// unsorted calls get the triage block (zuordnen / neuer Vorgang / Als Spam).
import { CalendarPlus, Check, ChevronDown, FileText, FolderPlus, Inbox, Receipt, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { initials } from '../lib/utils'
import { Avatar, StatusPill } from './calls/atoms'
import { CallDrawer } from './posteingang/CallDrawer'
import { AssigneeDot, Btn, DecisionPill, ProgressMeter, SectionHead, Timeline, TypeTag } from './posteingang/parts'
import {
  type DecisionVM,
  type UnsortedCall,
  usePosteingang,
  usePosteingangActions,
  type VorgangVM,
} from './posteingang/api'


function DecisionCard({ d, onResolve }: { d: DecisionVM; onResolve: (c: 'primary' | 'secondary' | 'tertiary') => void }) {
  const [hover, setHover] = useState(false)
  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{ position: 'relative', borderRadius: 'var(--radius-2xl)', background: 'var(--surface)', boxShadow: hover ? 'var(--elevation-2)' : 'var(--ring)', overflow: 'hidden', transition: 'box-shadow 0.18s var(--ease), transform 0.18s var(--ease)', transform: hover ? 'translateY(-2px)' : 'none' }}
    >
      <span style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 3, background: d.accent }} />
      <div style={{ padding: '17px 20px 0' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 11, marginBottom: 14 }}>
          <Avatar employeeId={d.custId} text={initials(d.customer)} size={40} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontFamily: 'var(--font-poster)', fontSize: 15.5, fontWeight: 700, color: 'var(--text)' }}>{d.customer}</div>
            <div style={{ fontSize: 12.5, color: 'var(--muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{d.problem}</div>
          </div>
          <TypeTag type={d.type} label={d.typeLabel} />
        </div>
        <div style={{ fontFamily: 'var(--font-poster)', fontSize: 18, fontWeight: 700, letterSpacing: '-0.01em', color: 'var(--text)', marginBottom: 13, lineHeight: 1.25 }}>{d.title}</div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '14px 20px 16px', flexWrap: 'wrap', borderTop: '1px solid var(--border-faint)' }}>
        <Btn variant={d.type === 'storno' ? 'danger' : 'primary'} onClick={() => onResolve('primary')}>{d.primary}</Btn>
        {d.secondary && <Btn variant="secondary" onClick={() => onResolve('secondary')}>{d.secondary}</Btn>}
        {d.tertiary && <Btn variant="ghost" onClick={() => onResolve('tertiary')}>{d.tertiary}</Btn>}
      </div>
    </div>
  )
}

function Row({
  v,
  open,
  onToggle,
  employees,
  onAssign,
  onOpenCall,
  onNav,
}: {
  v: VorgangVM
  open: boolean
  onToggle: () => void
  employees: Parameters<typeof AssigneeDot>[0]['employees']
  onAssign: (inquiryId: string, employeeId: string | null) => void
  onOpenCall: (id: string) => void
  onNav: (path: string) => void
}) {
  const [hover, setHover] = useState(false)
  const statusColor = v.status === 'completed' ? 'var(--success)' : v.status === 'in_progress' ? 'var(--warning)' : 'var(--info)'
  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{ position: 'relative', background: 'var(--surface)', borderRadius: 'var(--radius-xl)', overflow: 'hidden', boxShadow: open ? 'var(--ring-active)' : hover ? 'var(--elevation-2)' : 'var(--ring)', transition: 'box-shadow 0.15s var(--ease)' }}
    >
      <span style={{ position: 'absolute', left: 0, top: 14, bottom: 14, width: 3, borderRadius: 3, background: statusColor, opacity: open ? 0 : 0.85 }} />
      <div onClick={onToggle} style={{ display: 'flex', alignItems: 'center', gap: 13, padding: '13px 16px', cursor: 'pointer' }}>
        <Avatar employeeId={v.custId} text={initials(v.customer)} size={38} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontFamily: 'var(--font-poster)', fontSize: 15, fontWeight: 700, color: 'var(--text)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{v.problem}</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 12.5, color: 'var(--muted)', marginTop: 2, whiteSpace: 'nowrap' }}>
            <span>{v.customer}</span>
            <span style={{ color: 'var(--faint)' }}>·</span>
            <span>{v.calls} {v.calls === 1 ? 'Anruf' : 'Anrufe'}</span>
            <span style={{ color: 'var(--faint)' }}>·</span>
            <span style={{ color: 'var(--faint)' }}>{v.activity}</span>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
          {v.decision && <DecisionPill label={v.decision} />}
          <StatusPill status={v.status} />
          <AssigneeDot inquiryId={v.inquiryId} code={v.assigneeId} employees={employees} onAssign={onAssign} size={26} />
          <span style={{ color: 'var(--faint)', transition: 'transform 0.15s', transform: open ? 'rotate(180deg)' : 'none', display: 'grid', placeItems: 'center' }}>
            <ChevronDown size={17} />
          </span>
        </div>
      </div>
      {open && (
        <div style={{ borderTop: '1px solid var(--border-faint)', padding: '16px 18px 18px' }}>
          <Timeline timeline={v.callEntries.map((e) => ({ kind: e.dir, callId: e.id, quote: e.title, time: e.time, ts: e.ts }))} onOpenCall={onOpenCall} />
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', paddingTop: 16, marginTop: 4, borderTop: '1px solid var(--border-faint)' }}>
            <Btn variant="secondary" icon={<CalendarPlus size={15} />} onClick={() => onNav('/calendar')}>Termin</Btn>
            <Btn variant="secondary" icon={<Receipt size={15} />} onClick={() => onNav('/cost-estimates/new')}>KVA</Btn>
            <Btn variant="ghost" icon={<FileText size={15} />} onClick={() => onNav('/invoices/new')}>Rechnung</Btn>
          </div>
        </div>
      )}
    </div>
  )
}

function UnsortedRow({
  c,
  candidates,
  onMove,
  onNew,
  onSpam,
  onOpen,
}: {
  c: UnsortedCall
  candidates: VorgangVM[]
  onMove: (callId: string, inquiryId: string) => void
  onNew: (callId: string) => void
  onSpam: (callId: string) => void
  onOpen: (callId: string) => void
}) {
  const [picking, setPicking] = useState(false)
  return (
    <div style={{ borderRadius: 'var(--radius-lg)', background: 'var(--surface)', boxShadow: 'var(--ring)', padding: '11px 13px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
        <button type="button" onClick={() => onOpen(c.id)} style={{ display: 'flex', alignItems: 'center', gap: 11, flex: 1, minWidth: 0, border: 'none', background: 'transparent', cursor: 'pointer', textAlign: 'left' }}>
          <Avatar employeeId={c.custId} text={initials(c.customer)} size={34} />
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ fontFamily: 'var(--font-poster)', fontSize: 13.5, fontWeight: 700, color: 'var(--text)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.title}</div>
            <div style={{ fontSize: 12, color: 'var(--muted)' }}>{c.customer} · {c.activity}</div>
          </div>
        </button>
        <div style={{ display: 'flex', gap: 6, flexShrink: 0, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {candidates.length > 0 && <Btn variant="primary" icon={<Inbox size={14} />} onClick={() => setPicking((p) => !p)}>Vorgang zuordnen</Btn>}
          <Btn variant="secondary" icon={<FolderPlus size={14} />} onClick={() => onNew(c.id)}>Neuer Vorgang</Btn>
          <Btn variant="ghost" icon={<Trash2 size={14} />} onClick={() => onSpam(c.id)}>Als Spam</Btn>
        </div>
      </div>
      {picking && candidates.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--border-faint)' }}>
          {candidates.map((cand) => (
            <button
              key={cand.inquiryId}
              type="button"
              onClick={() => { onMove(c.id, cand.inquiryId); setPicking(false) }}
              style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', borderRadius: 'var(--radius-md)', border: 'none', background: 'var(--surface-alt)', cursor: 'pointer', textAlign: 'left', fontSize: 13, color: 'var(--text)' }}
            >
              <Inbox size={14} style={{ color: 'var(--green-deep)' }} />
              <span style={{ flex: 1, minWidth: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{cand.problem}</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)' }}>{cand.ticket}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export function PosteingangPage() {
  const navigate = useNavigate()
  const { loading, error, employees, decisions, vorgaenge, unsorted, callsCount } = usePosteingang()
  const actions = usePosteingangActions()
  const [openId, setOpenId] = useState<string | null>(null)
  const [callId, setCallId] = useState<string | null>(null)
  const [resolvedKeys, setResolvedKeys] = useState<Set<string>>(new Set())
  const [hiddenCalls, setHiddenCalls] = useState<Set<string>>(new Set())
  const [undo, setUndo] = useState<{ callId: string } | null>(null)

  const liveDecisions = useMemo(() => decisions.filter((d) => !resolvedKeys.has(d.actionKey)), [decisions, resolvedKeys])
  const liveUnsorted = useMemo(() => unsorted.filter((c) => !hiddenCalls.has(c.id)), [unsorted, hiddenCalls])
  const total = decisions.length
  const doneCount = total - liveDecisions.length
  const allDone = liveDecisions.length === 0

  const resolve = (d: DecisionVM, choice: 'primary' | 'secondary' | 'tertiary') => {
    setResolvedKeys((s) => new Set(s).add(d.actionKey))
    actions.resolve(d, choice).catch(() => setResolvedKeys((s) => { const n = new Set(s); n.delete(d.actionKey); return n }))
  }
  const onAssign = (inquiryId: string, employeeId: string | null) => actions.assignInquiry.mutate({ inquiryId, employeeId })
  const onMove = (cid: string, inquiryId: string) => { setHiddenCalls((s) => new Set(s).add(cid)); actions.moveCall.mutate({ callId: cid, inquiryId }) }
  const onNew = (cid: string) => { setHiddenCalls((s) => new Set(s).add(cid)); actions.newVorgang.mutate({ callId: cid }) }
  const onSpam = (cid: string) => { setHiddenCalls((s) => new Set(s).add(cid)); setUndo({ callId: cid }); actions.spamCall.mutate({ callId: cid, spam: true }) }
  const onUndoSpam = () => { if (!undo) return; actions.spamCall.mutate({ callId: undo.callId, spam: false }); setHiddenCalls((s) => { const n = new Set(s); n.delete(undo.callId); return n }); setUndo(null) }

  return (
    <>
      <div style={{ maxWidth: 740, margin: '0 auto', width: '100%', padding: '38px 26px 90px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 18, marginBottom: 30, flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 260 }}>
            <div style={{ fontFamily: 'var(--font-poster)', fontSize: 11, fontWeight: 800, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--green-primary)', marginBottom: 9 }}>Posteingang</div>
            <h1 style={{ margin: '0 0 8px', fontFamily: 'var(--font-poster)', fontWeight: 800, fontSize: 31, letterSpacing: '-0.025em', color: 'var(--text)', lineHeight: 1.08 }}>
              {loading ? 'Lädt…' : allDone ? 'Alles erledigt — gut gemacht.' : `${liveDecisions.length} ${liveDecisions.length === 1 ? 'Entscheidung wartet' : 'Entscheidungen warten'} auf Sie`}
            </h1>
            <p style={{ margin: 0, fontSize: 14.5, color: 'var(--muted)', lineHeight: 1.5, maxWidth: 460 }}>Kiki hat Ihre Anrufe bearbeitet und in Vorgänge sortiert. Den Rest haben Sie im Griff.</p>
          </div>
          <div style={{ display: 'flex', gap: 0, background: 'var(--surface)', borderRadius: 'var(--radius-xl)', boxShadow: 'var(--ring)', overflow: 'hidden', flexShrink: 0 }}>
            {[
              { n: callsCount, l: 'Anrufe', c: 'var(--text)' },
              { n: vorgaenge.length, l: 'Vorgänge', c: 'var(--text)' },
              { n: liveDecisions.length, l: 'Offen', c: liveDecisions.length ? 'var(--error)' : 'var(--green-primary)' },
            ].map((s, i) => (
              <div key={s.l} style={{ padding: '13px 18px', textAlign: 'center', borderLeft: i ? '1px solid var(--border-faint)' : 'none', minWidth: 64 }}>
                <div style={{ fontFamily: 'var(--font-poster)', fontSize: 23, fontWeight: 800, letterSpacing: '-0.02em', color: s.c, lineHeight: 1 }}>{s.n}</div>
                <div style={{ fontFamily: 'var(--font-poster)', fontSize: 10.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--muted)', marginTop: 5 }}>{s.l}</div>
              </div>
            ))}
          </div>
        </div>

        {error ? (
          <div style={{ borderRadius: 'var(--radius-xl)', background: 'var(--error-bg)', color: 'var(--error)', padding: 16, fontWeight: 600, marginBottom: 30 }}>Posteingang konnte nicht geladen werden.</div>
        ) : (
          <>
            {allDone ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '22px 24px', borderRadius: 'var(--radius-2xl)', background: 'var(--green-tint-50)', boxShadow: 'inset 0 0 0 1px var(--green-tint-200)', marginBottom: 38 }}>
                <span style={{ width: 44, height: 44, borderRadius: '50%', display: 'grid', placeItems: 'center', background: 'var(--green-primary)', color: '#fff', flexShrink: 0 }}><Check size={24} strokeWidth={2.4} /></span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontFamily: 'var(--font-poster)', fontSize: 17, fontWeight: 800, color: 'var(--green-deep)' }}>Posteingang leer</div>
                  <div style={{ fontSize: 13.5, color: 'var(--muted)', marginTop: 2 }}>Alle Entscheidungen getroffen. Kiki meldet sich, sobald etwas Neues reinkommt.</div>
                </div>
              </div>
            ) : (
              <>
                <SectionHead icon={Inbox} color="var(--error)" label="Jetzt entscheiden" trailing={<ProgressMeter done={doneCount} total={total} />} />
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 40 }}>
                  {liveDecisions.map((d) => (
                    <DecisionCard key={d.actionKey} d={d} onResolve={(c) => resolve(d, c)} />
                  ))}
                </div>
              </>
            )}

            {liveUnsorted.length > 0 && (
              <div style={{ marginBottom: 40 }}>
                <SectionHead icon={Inbox} color="var(--warning)" label="Nicht zugeordnet" trailing={<span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--warning)' }}>{liveUnsorted.length} brauchen Zuordnung</span>} />
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {liveUnsorted.map((c) => (
                    <UnsortedRow key={c.id} c={c} candidates={vorgaenge.filter((v) => v.custId && v.custId === c.custId)} onMove={onMove} onNew={onNew} onSpam={onSpam} onOpen={setCallId} />
                  ))}
                </div>
              </div>
            )}

            <SectionHead icon={Inbox} label="Alle Vorgänge" trailing={<span style={{ fontFamily: 'var(--font-mono)', fontSize: 12.5, color: 'var(--faint)' }}>{vorgaenge.length}</span>} />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {vorgaenge.map((v) => (
                <Row
                  key={v.key}
                  v={v}
                  open={openId === v.key}
                  onToggle={() => setOpenId(openId === v.key ? null : v.key)}
                  employees={employees}
                  onAssign={onAssign}
                  onOpenCall={setCallId}
                  onNav={navigate}
                />
              ))}
            </div>
          </>
        )}
      </div>

      {undo && (
        <div style={{ position: 'fixed', bottom: 22, left: '50%', transform: 'translateX(-50%)', zIndex: 70, display: 'flex', alignItems: 'center', gap: 14, padding: '10px 16px', borderRadius: 'var(--radius-xl)', background: 'var(--surface)', boxShadow: 'var(--elevation-3)' }}>
          <span style={{ fontSize: 13, color: 'var(--body)' }}>Als Spam markiert.</span>
          <button type="button" onClick={onUndoSpam} style={{ border: 'none', background: 'transparent', color: 'var(--green-primary)', fontFamily: 'var(--font-poster)', fontWeight: 700, fontSize: 13, cursor: 'pointer' }}>Rückgängig</button>
          <button type="button" onClick={() => setUndo(null)} style={{ border: 'none', background: 'transparent', color: 'var(--faint)', cursor: 'pointer', fontSize: 13 }}>✕</button>
        </div>
      )}

      <CallDrawer
        callId={callId}
        onClose={() => setCallId(null)}
        candidates={vorgaenge}
        onMove={(cid, iid) => { onMove(cid, iid); setCallId(null) }}
        onNew={(cid) => { onNew(cid); setCallId(null) }}
        onSpam={(cid) => { onSpam(cid); setCallId(null) }}
      />
    </>
  )
}
