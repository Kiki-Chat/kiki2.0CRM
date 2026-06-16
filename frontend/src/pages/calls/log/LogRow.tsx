// One horizontal call-log row. Read-only: the whole row opens the detail drawer;
// only the Fall/Vorgang chip is a separate click target (jumps to the case).
import { ChevronRight, Folder, Layers, Phone } from 'lucide-react'

import { cn } from '../../../lib/utils'
import { Avatar, DirBadge, NotdienstBadge } from '../atoms'
import { fmtClock, fmtDuration, fmtTime, type CallListItem } from '../shared'
import { callerTitle, caseLink, projectLink } from './util'

function EmpAvatar({ id, text, name }: { id: string | null; text: string | null; name: string | null }) {
  const title = name ? `Zuständig: ${name}` : 'Noch nicht zugewiesen'
  if (id) return <span title={title}><Avatar employeeId={id} text={text || '?'} size={30} /></span>
  return (
    <span
      title={title}
      className="flex h-[30px] w-[30px] flex-shrink-0 items-center justify-center rounded-full border border-dashed border-border text-faint"
      aria-label={title}
    >
      <span className="text-xs font-bold leading-none">–</span>
    </span>
  )
}

export function LogRow({
  call,
  active,
  mixed = false,
  assigneeName = null,
  onSelect,
  onOpenCase,
}: {
  call: CallListItem
  active: boolean
  mixed?: boolean
  assigneeName?: string | null
  onSelect: () => void
  onOpenCase: (to: string) => void
}) {
  const out = call.direction === 'outbound'
  const unread = call.read_at === null
  const link = caseLink(call)
  const proj = projectLink(call)

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`${out ? 'Ausgehender' : 'Eingehender'} Anruf — ${callerTitle(call)} — Details öffnen`}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSelect()
        }
      }}
      className={cn(
        'group relative flex w-full cursor-pointer items-center gap-3 rounded-xl py-2.5 pl-3 pr-3.5 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-green-primary',
        active ? 'bg-alt shadow-[var(--ring)]' : 'hover:bg-alt',
      )}
    >
      {unread && (
        <span className="absolute left-0 top-1/2 h-6 w-[3px] -translate-y-1/2 rounded-full bg-green-primary" aria-hidden />
      )}

      {/* direction */}
      <span
        className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full"
        style={{ background: `color-mix(in srgb, var(--${out ? 'outbound' : 'inbound'}) 14%, transparent)` }}
        title={out ? 'Ausgehend' : 'Eingehend'}
        role="img"
        aria-label={out ? 'Ausgehend' : 'Eingehend'}
      >
        <DirBadge dir={call.direction} />
      </span>

      {/* assigned employee (display only) */}
      <EmpAvatar id={call.assigned_employee_id} text={call.assigned_employee_initials} name={assigneeName} />

      {/* caller name + number */}
      <div className="w-[150px] flex-shrink-0 lg:w-[200px]">
        <div className="flex items-center gap-1.5">
          <span className={cn('truncate text-sm', unread ? 'font-extrabold text-text' : 'font-bold text-body')}>
            {callerTitle(call)}
          </span>
          {unread && (
            <span className="flex-shrink-0 rounded-full bg-green-tint-100 px-1.5 py-px text-[9.5px] font-extrabold uppercase tracking-wide text-green-deep">
              Neu
            </span>
          )}
        </div>
        <div className="truncate font-mono text-[11.5px] text-faint">{call.caller_number ?? '—'}</div>
      </div>

      {/* subject */}
      <p className="hidden min-w-0 flex-1 truncate text-[13px] text-muted sm:block">
        {call.summary_title || 'Ohne Betreff'}
      </p>

      {/* emergency + case chip */}
      <div className="flex flex-shrink-0 items-center gap-2">
        {call.emergency_flag && <NotdienstBadge small />}
        {link ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onOpenCase(link.to)
            }}
            onKeyDown={(e) => {
              // Don't let Enter/Space bubble to the row (which would also open the drawer).
              if (e.key === 'Enter' || e.key === ' ') e.stopPropagation()
            }}
            title={`${link.kind === 'fall' ? 'Fall' : 'Anfrage'} öffnen${link.title ? ` · ${link.title}` : ''}`}
            className="inline-flex max-w-[180px] items-center gap-1.5 rounded-lg border border-green-primary/40 bg-green-tint-50 px-2 py-1 font-mono text-[11.5px] font-bold text-green-deep transition hover:bg-green-tint-100"
          >
            <Folder size={12} className="flex-shrink-0" />
            <span className="truncate">{link.number ?? (link.kind === 'fall' ? 'Fall' : 'Anfrage')}</span>
            <ChevronRight size={12} className="flex-shrink-0 opacity-60" />
          </button>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-lg bg-warning-bg px-2 py-1 text-[11px] font-bold text-warning">
            Nicht zugeordnet
          </span>
        )}
        {proj && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onOpenCase(proj.to)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') e.stopPropagation()
            }}
            title={`Projekt öffnen${proj.title ? ` · ${proj.title}` : ''}`}
            className="hidden max-w-[140px] items-center gap-1 rounded-lg border border-ai/30 bg-ai-bg px-2 py-1 font-mono text-[11px] font-bold text-ai transition hover:brightness-95 lg:inline-flex"
          >
            <Layers size={11} className="flex-shrink-0" />
            <span className="truncate">{proj.number ?? 'Projekt'}</span>
          </button>
        )}
      </div>

      {/* time + duration */}
      <div className="flex w-[88px] flex-shrink-0 flex-col items-end gap-0.5">
        <span className="font-mono text-xs text-muted">{mixed ? fmtTime(call.started_at) : fmtClock(call.started_at)}</span>
        <span className="flex items-center gap-1 font-mono text-[11px] text-faint">
          <Phone size={10} />
          {fmtDuration(call.duration_seconds)}
        </span>
      </div>
    </div>
  )
}
