// Posteingang — the pending-DECISIONS queue. Reached via the dashboard "Alle
// ansehen" link. Shows ONLY the decisions; the Fälle themselves live on /cases
// (no duplication — Amber 2026-06-16). Decisions come from /api/actions/pending
// and resolve through the real appointment/Angebot endpoints.
import { Check, Folder, Inbox } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { initials } from '../lib/utils'
import { useMe } from '../lib/useMe'
import { Avatar } from './calls/atoms'
import { ActionDrawer } from './posteingang/ActionDrawer'
import { AssigneeDot, Btn, ProgressMeter, SectionHead, TypeTag } from './posteingang/parts'
import { type DecisionVM, usePosteingang, usePosteingangActions } from './posteingang/api'


function DecisionCard({
  d,
  employees,
  onAssign,
  onResolve,
  onOpen,
}: {
  d: DecisionVM
  employees: Parameters<typeof AssigneeDot>[0]['employees']
  onAssign: (inquiryId: string, employeeId: string | null) => void
  onResolve: (c: 'primary' | 'secondary' | 'tertiary') => void
  onOpen: () => void
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
        {/* Header is clickable → opens the "open action" drawer (call context + buttons). */}
        <div onClick={onOpen} title="Details & Anruf ansehen" style={{ display: 'flex', alignItems: 'center', gap: 11, marginBottom: 14, cursor: 'pointer' }}>
          <Avatar employeeId={d.custId} text={initials(d.customer)} size={40} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontFamily: 'var(--font-poster)', fontSize: 15.5, fontWeight: 700, color: 'var(--text)' }}>{d.customer}</div>
            <div style={{ fontSize: 12.5, color: 'var(--muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{d.problem}</div>
          </div>
          <TypeTag type={d.type} label={d.typeLabel} />
        </div>

        {/* Which case (Vorgang) this decision belongs to — point 2/6. */}
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
        {d.notify ? (
          // Notification card: a single neutral "check" link — NO direct decision.
          (d.opensDrawer || d.route) ? (
            <Btn variant="secondary" onClick={onOpen}>{d.cardCta} →</Btn>
          ) : (
            <span style={{ fontSize: 12.5, color: 'var(--muted)', fontWeight: 600 }}>Nur zur Information</span>
          )
        ) : (
          <>
            <Btn variant={d.type === 'storno' ? 'danger' : 'primary'} onClick={() => onResolve('primary')} disabled={needsAssignee} title={needsAssignee ? 'Erst zuweisen, dann bestätigen' : undefined}>{d.primary}</Btn>
            {d.secondary && <Btn variant="secondary" onClick={() => onResolve('secondary')}>{d.secondary}</Btn>}
            {d.tertiary && <Btn variant="ghost" onClick={() => onResolve('tertiary')}>{d.tertiary}</Btn>}
            {needsAssignee && <span style={{ fontSize: 12, color: 'var(--warning)', fontWeight: 600 }}>Erst zuweisen</span>}
            <button type="button" onClick={onOpen} style={{ marginLeft: 'auto', border: 'none', background: 'transparent', cursor: 'pointer', fontFamily: 'var(--font-poster)', fontSize: 12.5, fontWeight: 700, color: 'var(--green-deep)' }}>Details →</button>
          </>
        )}
      </div>
    </div>
  )
}

export function PosteingangPage() {
  const { isAdmin } = useMe()
  const navigate = useNavigate()
  const { loading, error, employees, decisions, vorgaenge, callsCount } = usePosteingang()
  const actions = usePosteingangActions()
  // Employee portal: this is the person's personal to-do list ("Meine Aufgaben"),
  // scoped server-side to their own work. The admin login sees the org Posteingang.
  const eyebrow = isAdmin ? 'Posteingang' : 'Meine Aufgaben'
  const taskNoun = isAdmin ? 'Entscheidung' : 'Aufgabe'
  const taskNounPl = isAdmin ? 'Entscheidungen' : 'Aufgaben'
  const introCopy = isAdmin
    ? 'Kiki hat deine Anrufe bearbeitet und in Vorgänge sortiert. Hier triffst du die offenen Entscheidungen — die Vorgänge selbst findest du unter „Vorgänge".'
    : 'Das sind deine offenen Aufgaben — was Kiki für dich vorbereitet hat und worauf du reagieren musst. Die Vorgänge selbst findest du unter „Vorgänge".'
  const [resolvedKeys, setResolvedKeys] = useState<Set<string>>(new Set())
  // The decision currently expanded in the "open action" drawer (by action_key).
  const [openKey, setOpenKey] = useState<string | null>(null)
  // Optimistic assignee overrides per inquiry: assigneeId on a decision is derived
  // from the windowed calls list, so a fresh assignment may not be reflected by the
  // refetch. Override locally so the assign-then-confirm gating updates immediately.
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
  const openDecision = openKey ? liveDecisions.find((d) => d.actionKey === openKey) ?? null : null

  const resolve = (d: DecisionVM, choice: 'primary' | 'secondary' | 'tertiary') => {
    // AI-suggested KVA/Rechnung: open the pre-filled create-form instead of POSTing.
    if (choice === 'primary' && d.route) {
      navigate(d.route)
      return
    }
    setOpenKey(null) // close the drawer if the action came from there
    setResolvedKeys((s) => new Set(s).add(d.actionKey))
    actions.resolve(d, choice).catch(() => setResolvedKeys((s) => { const n = new Set(s); n.delete(d.actionKey); return n }))
  }
  const onAssign = (inquiryId: string, employeeId: string | null) => {
    setAssignOverrides((m) => new Map(m).set(inquiryId, employeeId))
    actions.assignInquiry.mutate({ inquiryId, employeeId })
  }
  // Appointment + suggestion cards open the drawer; notification cards link
  // straight to the document/caller.
  const handleOpen = (d: DecisionVM) => {
    if (d.opensDrawer) setOpenKey(d.actionKey)
    else if (d.route) navigate(d.route)
  }

  return (
    <div style={{ maxWidth: 740, margin: '0 auto', width: '100%', padding: '38px 26px 90px' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 18, marginBottom: 30, flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: 260 }}>
          <div style={{ fontFamily: 'var(--font-poster)', fontSize: 11, fontWeight: 800, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--green-primary)', marginBottom: 9 }}>{eyebrow}</div>
          <h1 style={{ margin: '0 0 8px', fontFamily: 'var(--font-poster)', fontWeight: 800, fontSize: 31, letterSpacing: '-0.025em', color: 'var(--text)', lineHeight: 1.08 }}>
            {loading ? 'Wird geladen…' : allDone ? 'Alles erledigt — gut gemacht.' : `${liveDecisions.length} ${liveDecisions.length === 1 ? `${taskNoun} wartet` : `${taskNounPl} warten`} auf dich`}
          </h1>
          <p style={{ margin: 0, fontSize: 14.5, color: 'var(--muted)', lineHeight: 1.5, maxWidth: 460 }}>{introCopy}</p>
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
      ) : allDone ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '22px 24px', borderRadius: 'var(--radius-2xl)', background: 'var(--green-tint-50)', boxShadow: 'inset 0 0 0 1px var(--green-tint-200)' }}>
          <span style={{ width: 44, height: 44, borderRadius: '50%', display: 'grid', placeItems: 'center', background: 'var(--green-primary)', color: '#fff', flexShrink: 0 }}><Check size={24} strokeWidth={2.4} /></span>
          <div style={{ flex: 1 }}>
            <div style={{ fontFamily: 'var(--font-poster)', fontSize: 17, fontWeight: 800, color: 'var(--green-deep)' }}>Posteingang leer</div>
            <div style={{ fontSize: 13.5, color: 'var(--muted)', marginTop: 2 }}>Alle Entscheidungen getroffen. Kiki meldet sich, sobald etwas Neues reinkommt.</div>
          </div>
        </div>
      ) : (
        <>
          <SectionHead icon={Inbox} color="var(--error)" label={isAdmin ? 'Jetzt entscheiden' : 'Zu erledigen'} trailing={<ProgressMeter done={doneCount} total={total} />} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {liveDecisions.map((d) => (
              <DecisionCard key={d.actionKey} d={d} employees={employees} onAssign={onAssign} onResolve={(c) => resolve(d, c)} onOpen={() => handleOpen(d)} />
            ))}
          </div>
        </>
      )}

      <ActionDrawer
        decision={openDecision}
        employees={employees}
        onResolve={resolve}
        onAssign={onAssign}
        onClose={() => setOpenKey(null)}
      />
    </div>
  )
}
