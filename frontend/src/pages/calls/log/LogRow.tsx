// One call-log row, messages-app style: the SUBJECT is the hero line (emoji +
// bold), with caller · number · case chip on the secondary line and time/duration
// in a fixed, right-aligned, no-wrap meta column. The whole row opens the drawer;
// the Fall/Vorgang + Projekt chips are separate click targets. Fully responsive.
import { ChevronRight, Folder, Layers, Phone } from 'lucide-react'

import { cn } from '../../../lib/utils'
import { Avatar, DirBadge, NotdienstBadge } from '../atoms'
import { fmtClock, fmtDuration, type CallListItem } from '../shared'
import { callerTitle, caseLink, projectLink, subjectEmoji } from './util'

function EmpAvatar({ id, text, name }: { id: string | null; text: string | null; name: string | null }) {
  const title = name ? `Zuständig: ${name}` : 'Noch nicht zugewiesen'
  if (id) return <span title={title}><Avatar employeeId={id} text={text || '?'} size={22} /></span>
  return (
    <span
      title={title}
      className="flex h-[22px] w-[22px] flex-shrink-0 items-center justify-center rounded-full border border-dashed border-border text-faint"
      aria-label={title}
    >
      <span className="text-[10px] font-bold leading-none">–</span>
    </span>
  )
}

export function LogRow({
  call,
  active,
  assigneeName = null,
  onSelect,
  onOpenCase,
}: {
  call: CallListItem
  active: boolean
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
      aria-label={`${out ? 'Ausgehender' : 'Eingehender'} Anruf — ${call.summary_title || callerTitle(call)} — Details öffnen`}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSelect()
        }
      }}
      className={cn(
        'group relative flex w-full cursor-pointer items-center gap-2.5 rounded-xl py-2.5 pl-2.5 pr-2.5 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-green-primary sm:gap-3 sm:pl-3 sm:pr-3.5',
        active ? 'bg-alt shadow-[var(--ring)]' : 'hover:bg-alt',
      )}
    >
      {unread && (
        <span className="absolute left-0 top-1/2 h-8 w-[3px] -translate-y-1/2 rounded-full bg-green-primary" aria-hidden />
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

      {/* hero subject + secondary caller line */}
      <div className="min-w-0 flex-1">
        {/* line 1 — subject (emoji + bold, prominent) */}
        <div className="flex items-center gap-1.5">
          <span className="flex-shrink-0 text-[15px] leading-none" aria-hidden>
            {subjectEmoji(call)}
          </span>
          <span className={cn('truncate text-[14.5px]', unread ? 'font-extrabold text-text' : 'font-bold text-body')}>
            {call.summary_title || 'Ohne Betreff'}
          </span>
          {unread && (
            <span className="flex-shrink-0 rounded-full bg-green-tint-100 px-1.5 py-px text-[9.5px] font-extrabold uppercase tracking-wide text-green-deep">
              Neu
            </span>
          )}
          {call.emergency_flag && (
            <>
              <span
                className="h-2.5 w-2.5 flex-shrink-0 animate-pulse rounded-full bg-error lg:hidden"
                title="Notdienst"
                aria-label="Notdienst"
              />
              <span className="hidden flex-shrink-0 lg:inline-flex">
                <NotdienstBadge small />
              </span>
            </>
          )}
        </div>

        {/* line 2 — caller · number + case chip */}
        <div className="mt-0.5 flex items-center gap-1.5">
          <span className="hidden flex-shrink-0 sm:block">
            <EmpAvatar id={call.assigned_employee_id} text={call.assigned_employee_initials} name={assigneeName} />
          </span>
          <span className="min-w-0 flex-1 truncate text-[12px] text-muted">
            <span className="font-semibold text-body">{callerTitle(call)}</span>
            {call.caller_number && <span className="font-mono text-faint"> · {call.caller_number}</span>}
          </span>
          {link ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onOpenCase(link.to)
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') e.stopPropagation()
              }}
              title={`${link.kind === 'fall' ? 'Fall' : 'Anfrage'} öffnen${link.title ? ` · ${link.title}` : ''}`}
              className="inline-flex max-w-[100px] flex-shrink-0 items-center gap-1.5 rounded-lg border border-green-primary/40 bg-green-tint-50 px-2 py-0.5 font-mono text-[11px] font-bold text-green-deep transition hover:bg-green-tint-100 sm:max-w-[150px] lg:max-w-[190px]"
            >
              <Folder size={11} className="flex-shrink-0" />
              <span className="truncate">{link.number ?? (link.kind === 'fall' ? 'Fall' : 'Anfrage')}</span>
              <ChevronRight size={11} className="hidden flex-shrink-0 opacity-60 lg:block" />
            </button>
          ) : (
            <span className="inline-flex flex-shrink-0 items-center gap-1 whitespace-nowrap rounded-lg bg-warning-bg px-2 py-0.5 text-[10.5px] font-bold text-warning">
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
              className="hidden max-w-[150px] flex-shrink-0 items-center gap-1 rounded-lg border border-ai/30 bg-ai-bg px-2 py-0.5 font-mono text-[10.5px] font-bold text-ai transition hover:brightness-95 xl:inline-flex"
            >
              <Layers size={10} className="flex-shrink-0" />
              <span className="truncate">{proj.number ?? 'Projekt'}</span>
            </button>
          )}
        </div>
      </div>

      {/* time + duration — fixed width, right-aligned, never wraps */}
      <div className="flex w-[52px] flex-shrink-0 flex-col items-end gap-0.5 text-right leading-tight sm:w-[58px]">
        <span className="whitespace-nowrap font-mono text-xs text-muted">{fmtClock(call.started_at)}</span>
        <span className="flex items-center gap-1 whitespace-nowrap font-mono text-[11px] text-faint">
          <Phone size={10} className="flex-shrink-0" />
          {fmtDuration(call.duration_seconds)}
        </span>
      </div>
    </div>
  )
}
