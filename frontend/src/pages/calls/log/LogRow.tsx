// One horizontal call-log row. Read-only: the whole row opens the detail drawer;
// only the Fall/Vorgang chip is a separate click target (jumps to the case).
// Responsive: mobile shows the essentials (caller · case · time); subject appears
// from md, the Projekt badge from lg. The meta column is fixed-width + no-wrap so
// the emergency badge can never squeeze the date/duration into a ragged wrap.
import { ChevronRight, Folder, Layers, Phone } from 'lucide-react'

import { cn } from '../../../lib/utils'
import { Avatar, DirBadge, NotdienstBadge } from '../atoms'
import { BERLIN_TZ } from '../../../lib/datetime'
import { fmtClock, fmtDuration, type CallListItem } from '../shared'
import { callerTitle, caseLink, projectLink } from './util'

const shortDate = (iso: string | null): string =>
  iso ? new Date(iso).toLocaleDateString('de-DE', { day: '2-digit', month: 'short', timeZone: BERLIN_TZ }) : ''

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
        'group relative flex w-full cursor-pointer items-center gap-2 rounded-xl py-2.5 pl-2.5 pr-2.5 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-green-primary sm:gap-3 sm:pl-3 sm:pr-3.5',
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

      {/* assigned employee (display only) — hidden on phones to give the name room */}
      <span className="hidden flex-shrink-0 sm:block">
        <EmpAvatar id={call.assigned_employee_id} text={call.assigned_employee_initials} name={assigneeName} />
      </span>

      {/* caller name + number — flexes until lg (the sidebar leaves little room on
          tablet), then a fixed column so the subject can sit beside it */}
      <div className="min-w-0 flex-1 lg:flex-none lg:w-[180px]">
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

      {/* subject — only on wide screens (tablet content is too narrow with the sidebar) */}
      <p className="hidden min-w-0 flex-1 truncate text-[13px] text-muted lg:block">
        {call.summary_title || 'Ohne Betreff'}
      </p>

      {/* emergency + case + project chips (never shrinks; chips truncate instead) */}
      <div className="flex flex-shrink-0 items-center gap-1.5">
        {call.emergency_flag && (
          <>
            <span
              className="h-2.5 w-2.5 flex-shrink-0 animate-pulse rounded-full bg-error lg:hidden"
              title="Notdienst"
              aria-label="Notdienst"
            />
            <span className="hidden lg:inline-flex">
              <NotdienstBadge small />
            </span>
          </>
        )}
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
            className="inline-flex max-w-[84px] items-center gap-1.5 rounded-lg border border-green-primary/40 bg-green-tint-50 px-2 py-1 font-mono text-[11.5px] font-bold text-green-deep transition hover:bg-green-tint-100 sm:max-w-[140px] lg:max-w-[180px]"
          >
            <Folder size={12} className="flex-shrink-0" />
            <span className="truncate">{link.number ?? (link.kind === 'fall' ? 'Fall' : 'Anfrage')}</span>
            <ChevronRight size={12} className="hidden flex-shrink-0 opacity-60 lg:block" />
          </button>
        ) : (
          <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-lg bg-warning-bg px-2 py-1 text-[11px] font-bold text-warning">
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
            className="hidden max-w-[140px] items-center gap-1 rounded-lg border border-ai/30 bg-ai-bg px-2 py-1 font-mono text-[11px] font-bold text-ai transition hover:brightness-95 xl:inline-flex"
          >
            <Layers size={11} className="flex-shrink-0" />
            <span className="truncate">{proj.number ?? 'Projekt'}</span>
          </button>
        )}
      </div>

      {/* time/date + duration — fixed width, right-aligned, never wraps */}
      <div className="flex w-[58px] flex-shrink-0 flex-col items-end gap-0.5 text-right leading-tight sm:w-[64px]">
        {mixed && <span className="whitespace-nowrap font-mono text-[10.5px] text-faint">{shortDate(call.started_at)}</span>}
        <span className="whitespace-nowrap font-mono text-xs text-muted">{fmtClock(call.started_at)}</span>
        <span className="flex items-center gap-1 whitespace-nowrap font-mono text-[11px] text-faint">
          <Phone size={10} className="flex-shrink-0" />
          {fmtDuration(call.duration_seconds)}
        </span>
      </div>
    </div>
  )
}
