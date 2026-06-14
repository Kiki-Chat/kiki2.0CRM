// Posteingang — Fokus·Agenda, wired to live kiki-test-007 data. Decisions come
// from /api/actions/pending and resolve through the real appointment/KVA
// endpoints; Vorgänge from /api/calls (timeline lazy-loaded from the inquiry
// thread); the assignee is a real dropdown everywhere; "Kiki empfiehlt" executes;
// unsorted calls get the triage block (zuordnen / neuer Vorgang / Als Spam).
import { CalendarPlus, Check, ChevronDown, FileText, Folder, Inbox, Receipt } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { initials } from '../lib/utils'
import { Avatar, StatusPill } from './calls/atoms'
import { CallDrawer } from './posteingang/CallDrawer'
import { AssigneeDot, Btn, DecisionPill, ProgressMeter, SectionHead, Timeline, TypeTag } from './posteingang/parts'
import {
  type DecisionVM,
  usePosteingang,
  usePosteingangActions,
  type VorgangVM,
} from './posteingang/api'


function DecisionCard({
  d,
  employees,
  onAssign,
  onResolve,
}: {
  d: DecisionVM
  employees: Parameters<typeof AssigneeDot>[0]['employees']
  onAssign: (inquiryId: string, employeeId: string | null) => void
  onResolve: (c: 'primary' | 'secondary' | 'tertiary') => void
}) {
  const [hover, setHover] = useState(false)
  const assignee = d.assigneeId ? employees.find((e) => e.id === d.assigneeId) : null
  // Strict assign ≠ confirm (point 1): a Termin can only be confirmed once
  // someone is assigned, so the primary button stays disabled until assignment
  // happens as its own visible step. Only gate when an inquiry (and therefore an
  // assign control) actually exists — an inquiry-less appointment has no way to
  // assign and must stay confirmable.
  const needsAssignee = d.kind === 'termin_anfrage' && !!d.inquiryId && !d.assigneeId
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

        {/* Which case (Fall) this decision belongs to — point 2/6. */}
        {d.caseName && (
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 7, maxWidth: '100%', marginBottom: 11, padding: '5px 11px', background: 'var(--green-tint-50)', borderRadius: 'var(--radius-md)' }}>
            <Folder size={13} color="var(--green-deep)" style={{ flexShrink: 0 }} />
            <span style={{ fontFamily: 'var(--font-poster)', fontSize: 12.5, fontWeight: 700, color: 'var(--green-deep)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{d.caseName}</span>
            {d.caseTicket && <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)', flexShrink: 0 }}>{d.caseTicket}</span>}
          </div>
        )}

        <div style={{ fontFamily: 'var(--font-poster)', fontSize: 18, fontWeight: 700, letterSpacing: '-0.01em', color: 'var(--text)', marginBottom: 13, lineHeight: 1.25 }}>{d.title}</div>

        {/* Assignment is its own step (point 1) — never bundled into Bestätigen. */}
        {d.assignable && d.inquiryId && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 14 }}>
            <span style={{ fontFamily: 'var(--font-poster)', fontSize: 11, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--muted)' }}>Zuständig</span>
            <AssigneeDot inquiryId={d.inquiryId} code={d.assigneeId} employees={employees} onAssign={onAssign} size={26} />
            <span style={{ fontSize: 13, fontWeight: 600, color: assignee ? 'var(--text)' : 'var(--faint)' }}>
              {assignee?.display_name ?? 'Niemand — zum Zuweisen klicken'}
            </span>
          </div>
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '14px 20px 16px', flexWrap: 'wrap', borderTop: '1px solid var(--border-faint)' }}>
        <Btn variant={d.type === 'storno' ? 'danger' : 'primary'} onClick={() => onResolve('primary')} disabled={needsAssignee} title={needsAssignee ? 'Erst zuweisen, dann bestätigen' : undefined}>{d.primary}</Btn>
        {d.secondary && <Btn variant="secondary" onClick={() => onResolve('secondary')}>{d.secondary}</Btn>}
        {d.tertiary && <Btn variant="ghost" onClick={() => onResolve('tertiary')}>{d.tertiary}</Btn>}
        {needsAssignee && <span style={{ fontSize: 12, color: 'var(--warning)', fontWeight: 600 }}>Erst zuweisen</span>}
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

export function PosteingangPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { loading, error, employees, decisions, vorgaenge, callsCount } = usePosteingang()
  const actions = usePosteingangActions()
  const [openId, setOpenId] = useState<string | null>(null)
  const [callId, setCallId] = useState<string | null>(null)
  const [resolvedKeys, setResolvedKeys] = useState<Set<string>>(new Set())
  // Optimistic assignee overrides per inquiry: assigneeId on a decision is derived
  // from the windowed calls list, so a fresh assignment may not be reflected by the
  // refetch (the inquiry's call can be outside the window). Override locally so the
  // assign-then-confirm gating updates immediately.
  const [assignOverrides, setAssignOverrides] = useState<Map<string, string | null>>(new Map())

  const liveDecisions = useMemo(
    () =>
      decisions
        .filter((d) => !resolvedKeys.has(d.actionKey))
        .map((d) =>
          d.inquiryId && assignOverrides.has(d.inquiryId)
            ? { ...d, assigneeId: assignOverrides.get(d.inquiryId) ?? null }
            : d,
        ),
    [decisions, resolvedKeys, assignOverrides],
  )
  const total = decisions.length
  const doneCount = total - liveDecisions.length
  const allDone = liveDecisions.length === 0

  // Deep-link from the Anrufe call log (?fall=<project_id|inquiry_id>): open and
  // scroll to that case once the list loads. Acts once per distinct param value.
  const fallParam = searchParams.get('fall')
  const handledFall = useRef<string | null>(null)
  useEffect(() => {
    if (!fallParam || loading || handledFall.current === fallParam) return
    if (!vorgaenge.some((v) => v.key === fallParam)) return
    handledFall.current = fallParam
    setOpenId(fallParam)
    // Re-scroll over a few frames: the decision cards above render after this
    // effect first runs and push the row down, so a single scroll lands short.
    let n = 0
    let id = 0
    const tick = () => {
      document.getElementById(`pe-row-${fallParam}`)?.scrollIntoView({ block: 'center' })
      if (++n < 6) id = window.setTimeout(tick, 120)
    }
    id = window.setTimeout(tick, 60)
    return () => window.clearTimeout(id)
  }, [fallParam, loading, vorgaenge])

  const resolve = (d: DecisionVM, choice: 'primary' | 'secondary' | 'tertiary') => {
    setResolvedKeys((s) => new Set(s).add(d.actionKey))
    actions.resolve(d, choice).catch(() => setResolvedKeys((s) => { const n = new Set(s); n.delete(d.actionKey); return n }))
  }
  const onAssign = (inquiryId: string, employeeId: string | null) => {
    setAssignOverrides((m) => new Map(m).set(inquiryId, employeeId))
    actions.assignInquiry.mutate({ inquiryId, employeeId })
  }

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
                    <DecisionCard key={d.actionKey} d={d} employees={employees} onAssign={onAssign} onResolve={(c) => resolve(d, c)} />
                  ))}
                </div>
              </>
            )}

            <SectionHead icon={Inbox} label="Alle Vorgänge" trailing={<span style={{ fontFamily: 'var(--font-mono)', fontSize: 12.5, color: 'var(--faint)' }}>{vorgaenge.length}</span>} />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {vorgaenge.map((v) => (
                <div key={v.key} id={`pe-row-${v.key}`}>
                  <Row
                    v={v}
                    open={openId === v.key}
                    onToggle={() => setOpenId(openId === v.key ? null : v.key)}
                    employees={employees}
                    onAssign={onAssign}
                    onOpenCall={setCallId}
                    onNav={navigate}
                  />
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      <CallDrawer callId={callId} onClose={() => setCallId(null)} />
    </>
  )
}
