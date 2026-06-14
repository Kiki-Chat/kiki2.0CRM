// Shared parts for the Posteingang Fokus·Agenda — ported from the handoff's
// shared.jsx / _AgendaView.jsx, recreated with our Avatar/Tag/DirBadge + lucide
// and our design tokens (inline var(--token) styling matches the prototype 1:1).
import { Bell, Calendar, Check, FileText, Play, Receipt, type LucideIcon } from 'lucide-react'
import type { CSSProperties, ReactNode } from 'react'

import { initials } from '../../lib/utils'
import { Tag } from '../../components/ui/Tag'
import { AssignDropdown, Avatar, DirBadge } from '../calls/atoms'
import { type DecisionType, type Employee, type TLItem } from './api'

// ── Button matching the handoff DS Button (sm size, leading icon, ghost/danger) ─
type BtnVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
const BTN: Record<BtnVariant, CSSProperties> = {
  primary: { background: 'var(--green-primary)', color: '#fff' },
  secondary: { background: 'transparent', color: 'var(--body)', boxShadow: 'inset 0 0 0 1px var(--border)' },
  ghost: { background: 'transparent', color: 'var(--muted)' },
  danger: { background: 'var(--error)', color: '#fff' },
}
export function Btn({
  variant = 'secondary',
  icon,
  children,
  onClick,
  disabled = false,
  title,
}: {
  variant?: BtnVariant
  icon?: ReactNode
  children: ReactNode
  onClick?: () => void
  disabled?: boolean
  title?: string
}) {
  return (
    <button
      type="button"
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      title={title}
      className="pe-btn"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 7,
        border: 'none',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        padding: '8px 14px',
        borderRadius: 'var(--radius-lg)',
        fontFamily: 'var(--font-poster)',
        fontSize: 13,
        fontWeight: 700,
        whiteSpace: 'nowrap',
        ...BTN[variant],
      }}
    >
      {icon}
      {children}
    </button>
  )
}

export function SectionHead({
  icon: Icon,
  color,
  label,
  trailing,
}: {
  icon: LucideIcon
  color?: string
  label: string
  trailing?: ReactNode
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 14 }}>
      <span style={{ color: color || 'var(--muted)', display: 'grid', placeItems: 'center' }}>
        <Icon size={16} />
      </span>
      <span
        style={{
          fontFamily: 'var(--font-poster)',
          fontSize: 12.5,
          fontWeight: 800,
          textTransform: 'uppercase',
          letterSpacing: '0.07em',
          color: 'var(--text)',
          whiteSpace: 'nowrap',
        }}
      >
        {label}
      </span>
      <span style={{ flex: 1, height: 1, background: 'var(--border-faint)' }} />
      {trailing}
    </div>
  )
}

export function ProgressMeter({ done, total }: { done: number; total: number }) {
  const pct = total ? Math.round((done / total) * 100) : 0
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <div style={{ width: 84, height: 6, borderRadius: 999, background: 'var(--surface-alt)', overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', borderRadius: 999, background: 'var(--green-primary)', transition: 'width 0.35s var(--ease)' }} />
      </div>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--muted)', whiteSpace: 'nowrap' }}>
        {done}/{total}
      </span>
    </div>
  )
}

export function DecisionPill({ label }: { label: string }) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        background: 'var(--error-bg)',
        color: 'var(--error)',
        borderRadius: 'var(--radius-full)',
        padding: '5px 11px 5px 9px',
        fontFamily: 'var(--font-poster)',
        fontSize: 12.5,
        fontWeight: 700,
        whiteSpace: 'nowrap',
        boxShadow: 'inset 0 0 0 1px color-mix(in srgb, var(--error) 22%, transparent)',
      }}
    >
      <Bell size={13} />
      {label}
    </span>
  )
}

export function AssigneeDot({
  inquiryId,
  code,
  employees,
  onAssign,
  size = 28,
}: {
  inquiryId: string | null
  code: string | null
  employees: Employee[]
  onAssign: (inquiryId: string, employeeId: string | null) => void
  size?: number
}) {
  const e = code ? employees.find((x) => x.id === code) : null
  const inner = e ? (
    <Avatar employeeId={e.id} text={initials(e.display_name || '?')} size={size} />
  ) : (
    <span
      style={{ width: size, height: size, borderRadius: '50%', display: 'grid', placeItems: 'center', color: 'var(--faint)', border: '1.5px dashed var(--border)', fontFamily: 'var(--font-mono)', fontSize: 13 }}
    >
      –
    </span>
  )
  if (!inquiryId) return <span style={{ flexShrink: 0 }}>{inner}</span>
  return (
    <AssignDropdown current={code} employees={employees} onAssign={(empId) => onAssign(inquiryId, empId)} align="end">
      <button type="button" title="Zuweisen" onClick={(ev) => ev.stopPropagation()} style={{ border: 'none', background: 'transparent', cursor: 'pointer', padding: 0, display: 'grid', placeItems: 'center', flexShrink: 0 }}>
        {inner}
      </button>
    </AssignDropdown>
  )
}

const TYPE_VARIANT: Record<DecisionType, 'info' | 'green' | 'error' | 'ai' | 'warning'> = { termin: 'info', rueckruf: 'green', storno: 'error', kva: 'ai', reschedule: 'warning' }
export function TypeTag({ type, label }: { type: DecisionType; label: string }) {
  return <Tag variant={TYPE_VARIANT[type]}>{label}</Tag>
}

// ── Timeline (calls + termin/kva/rechnung events) ───────────────────────────
const tint = (c: string, p = 14) => `color-mix(in srgb, ${c} ${p}%, transparent)`
const KIND: Record<TLItem['kind'], { color: string; label?: string; icon?: LucideIcon }> = {
  inbound: { color: 'var(--inbound)', label: 'Eingehend' },
  outbound: { color: 'var(--outbound)', label: 'Ausgehend' },
  termin: { color: 'var(--info)', icon: Calendar },
  kva: { color: 'var(--ai)', icon: Receipt },
  rechnung: { color: 'var(--success)', icon: FileText },
}

function ProgressPill({ done, doneLabel }: { done?: boolean; doneLabel?: string }) {
  if (done) {
    return (
      <Tag variant="success">
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <Check size={11} strokeWidth={2.6} />
          {doneLabel || 'Erledigt'}
        </span>
      </Tag>
    )
  }
  return <Tag variant="warning">Offen</Tag>
}

export function Timeline({ timeline, onOpenCall }: { timeline: TLItem[]; onOpenCall: (id: string) => void }) {
  return (
    <div style={{ position: 'relative' }}>
      <span style={{ position: 'absolute', left: 13.5, top: 8, bottom: 22, width: 2, background: 'var(--border)', zIndex: 0 }} />
      {timeline.map((e, i) => {
        const k = KIND[e.kind]
        const KIcon = k.icon
        const isCall = e.kind === 'inbound' || e.kind === 'outbound'
        const last = i === timeline.length - 1
        return (
          <div key={i} style={{ display: 'flex', gap: 12, paddingBottom: last ? 0 : 18, position: 'relative' }}>
            <span
              style={{
                width: 28,
                height: 28,
                borderRadius: '50%',
                flexShrink: 0,
                display: 'grid',
                placeItems: 'center',
                background: tint(k.color, 14),
                color: k.color,
                position: 'relative',
                zIndex: 1,
                boxShadow: '0 0 0 4px var(--surface)',
              }}
            >
              {isCall ? <DirBadge dir={e.kind} /> : KIcon ? <KIcon size={15} /> : null}
            </span>
            <div style={{ flex: 1, minWidth: 0, paddingTop: 2 }}>
              {isCall ? (
                <>
                  <span style={{ fontFamily: 'var(--font-poster)', fontSize: 12, fontWeight: 700, color: k.color }}>{k.label}</span>
                  <div style={{ fontSize: 13.5, color: 'var(--body)', marginTop: 2 }}>„{e.quote}"</div>
                  {e.callId && (
                    <button
                      type="button"
                      onClick={() => onOpenCall(e.callId as string)}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 6,
                        marginTop: 7,
                        border: 'none',
                        cursor: 'pointer',
                        background: 'var(--surface-alt)',
                        color: 'var(--green-deep)',
                        borderRadius: 'var(--radius-full)',
                        padding: '4px 11px',
                        fontFamily: 'var(--font-poster)',
                        fontSize: 11.5,
                        fontWeight: 700,
                      }}
                    >
                      <Play size={11} /> Aufnahme &amp; Transkript
                    </button>
                  )}
                </>
              ) : (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span style={{ fontFamily: 'var(--font-poster)', fontSize: 13.5, fontWeight: 600, color: 'var(--text)' }}>{e.label}</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12.5, color: 'var(--muted)' }}>{e.detail}</span>
                  <ProgressPill done={e.done} doneLabel={e.doneLabel} />
                </div>
              )}
            </div>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--faint)', whiteSpace: 'nowrap', paddingTop: 3 }}>{e.time}</span>
          </div>
        )
      })}
    </div>
  )
}
