// Anrufe — the call log as a real column table. Eight German-headed columns
// (Richtung · Zuständig · Anrufer · Betreff · Fall/Anfrage · Datum · Uhrzeit · Dauer),
// but the rows stay separated by day in the existing manner: Heute / Gestern / full
// date dividers span the whole table as section headers. The whole row opens the
// detail drawer; the Fall/Anfrage chip is a separate click target. Horizontally
// scrollable on narrow screens so all columns survive.
import { ChevronRight, Folder, Layers, Phone } from 'lucide-react'
import { Fragment } from 'react'

import { cn } from '../../../lib/utils'
import { Avatar, DirBadge, StatusPill } from '../atoms'
import { fmtClockUhr, fmtDurationLong, type CallListItem } from '../shared'
import { callerTitle, caseLink, fmtDayDate, projectLink, subjectEmoji } from './util'

export interface DayGroup {
  key: string
  label: string
  calls: CallListItem[]
}

function EmpAvatar({ id, text, name }: { id: string | null; text: string | null; name: string | null }) {
  const title = name ? `Zuständig: ${name}` : 'Noch nicht zugewiesen'
  if (id)
    return (
      <span title={title}>
        <Avatar employeeId={id} text={text || '?'} size={26} />
      </span>
    )
  return (
    <span
      title={title}
      className="flex h-[26px] w-[26px] flex-shrink-0 items-center justify-center rounded-full border border-dashed border-border text-faint"
      aria-label={title}
    >
      <span className="text-[11px] font-bold leading-none">–</span>
    </span>
  )
}

function LogTableRow({
  call,
  active,
  assigneeName,
  onSelect,
  onOpenCase,
}: {
  call: CallListItem
  active: boolean
  assigneeName: string | null
  onSelect: () => void
  onOpenCase: (to: string) => void
}) {
  const out = call.direction === 'outbound'
  const unread = call.read_at === null
  const link = caseLink(call)
  const proj = projectLink(call)
  const td = 'px-3 py-2.5 align-middle'

  return (
    <tr
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
        'group cursor-pointer border-b border-border-faint outline-none transition-colors last:border-b-0',
        'focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-green-primary',
        active ? 'bg-alt' : 'hover:bg-alt',
      )}
    >
      {/* 1 — Richtung (inbound/outbound) — emergency red line wins over unread green */}
      <td
        className={cn(
          td,
          'border-l-2',
          call.emergency_flag ? 'border-error' : unread ? 'border-green-primary' : 'border-transparent',
        )}
      >
        <span
          className="flex h-9 w-9 items-center justify-center rounded-full"
          style={{ background: `color-mix(in srgb, var(--${out ? 'outbound' : 'inbound'}) 14%, transparent)` }}
          title={out ? 'Ausgehend' : 'Eingehend'}
          role="img"
          aria-label={out ? 'Ausgehend' : 'Eingehend'}
        >
          <DirBadge dir={call.direction} />
        </span>
      </td>

      {/* 2 — Status (Vorgangsstatus, full label) */}
      <td className={td}>
        {call.inquiry_status ? (
          <StatusPill status={call.inquiry_status} />
        ) : (
          <span className="text-[12px] text-faint">—</span>
        )}
      </td>

      {/* 3 — Zuständig (employee avatar) */}
      <td className={cn(td, 'text-center')}>
        <span className="inline-flex">
          <EmpAvatar id={call.assigned_employee_id} text={call.assigned_employee_initials} name={assigneeName} />
        </span>
      </td>

      {/* 4 — Anrufer (name + number) — flexes to share the slack on wide screens */}
      <td className={td}>
        <div className="min-w-0">
          <div className={cn('truncate text-[13.5px]', unread ? 'font-extrabold text-text' : 'font-bold text-body')}>
            {callerTitle(call)}
          </div>
          <div className="truncate font-mono text-[11.5px] text-faint">{call.caller_number || '—'}</div>
        </div>
      </td>

      {/* 5 — Betreff (subject) — for emergencies the emoji+title sit in a red-outlined
          highlight (the 🚨 emoji + red boundary ARE the signal; no extra badge/label). */}
      <td className={td}>
        <div className="flex min-w-0 items-center gap-1.5">
          {call.emergency_flag ? (
            <span className="emrg-glow inline-flex min-w-0 items-center gap-1.5 rounded-lg border border-error/55 bg-error-bg px-2 py-[3px]">
              <span className="flex-shrink-0 text-[15px] leading-none" aria-hidden>
                {subjectEmoji(call)}
              </span>
              <span className="truncate text-[13.5px] font-extrabold text-error">
                {call.summary_title || 'Ohne Betreff'}
              </span>
            </span>
          ) : (
            <>
              <span className="flex-shrink-0 text-[15px] leading-none" aria-hidden>
                {subjectEmoji(call)}
              </span>
              <span
                className={cn(
                  'truncate text-[13.5px]',
                  unread ? 'font-extrabold text-text' : 'font-semibold text-body',
                )}
              >
                {call.summary_title || 'Ohne Betreff'}
              </span>
            </>
          )}
          {unread && (
            <span className="flex-shrink-0 rounded-full bg-green-tint-100 px-1.5 py-px text-[9.5px] font-extrabold uppercase tracking-wide text-green-deep">
              Neu
            </span>
          )}
        </div>
      </td>

      {/* 6 — Vorgang / Anfrage (case) */}
      <td className={td}>
        <div className="flex max-w-[190px] flex-col items-start gap-1">
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
              title={`${link.kind === 'fall' ? 'Vorgang' : 'Anfrage'} öffnen${link.title ? ` · ${link.title}` : ''}`}
              className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-green-primary/40 bg-green-tint-50 px-2 py-0.5 font-mono text-[11px] font-bold text-green-deep transition hover:bg-green-tint-100"
            >
              <Folder size={11} className="flex-shrink-0" />
              <span className="truncate">{link.number ?? (link.kind === 'fall' ? 'Vorgang' : 'Anfrage')}</span>
              <ChevronRight size={11} className="flex-shrink-0 opacity-60" />
            </button>
          ) : (
            <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-lg bg-warning-bg px-2 py-0.5 text-[10.5px] font-bold text-warning">
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
              className="inline-flex max-w-full items-center gap-1 rounded-lg border border-ai/30 bg-ai-bg px-2 py-0.5 font-mono text-[10.5px] font-bold text-ai transition hover:brightness-95"
            >
              <Layers size={10} className="flex-shrink-0" />
              <span className="truncate">{proj.number ?? 'Projekt'}</span>
            </button>
          )}
        </div>
      </td>

      {/* 7 — Datum (Sonntag, 14. Juni) */}
      <td className={cn(td, 'whitespace-nowrap text-[12.5px] capitalize text-muted')}>
        {fmtDayDate(call.started_at || call.created_at)}
      </td>

      {/* 8 — Uhrzeit (mit "Uhr") */}
      <td className={cn(td, 'whitespace-nowrap font-mono text-[12.5px] text-muted')}>{fmtClockUhr(call.started_at)}</td>

      {/* 9 — Dauer (ausgeschrieben: "2 Min 45 Sek") — extra left padding so it
          isn't crammed against the Uhrzeit column. */}
      <td className={cn(td, 'whitespace-nowrap pl-6')}>
        <span className="inline-flex items-center gap-1 text-[12px] text-faint">
          <Phone size={11} className="flex-shrink-0" />
          {fmtDurationLong(call.duration_seconds)}
        </span>
      </td>
    </tr>
  )
}

export function LogTable({
  dayGroups,
  selectedId,
  employeeName,
  onSelect,
  onOpenCase,
}: {
  dayGroups: DayGroup[]
  selectedId: string | null
  employeeName: Map<string, string>
  onSelect: (id: string) => void
  onOpenCase: (to: string) => void
}) {
  const th = 'px-3 py-2.5 text-left text-[11px] font-extrabold uppercase tracking-wide text-muted'

  return (
    <div className="scroll overflow-x-auto rounded-2xl border border-border bg-surface">
      <table className="w-full min-w-[1040px] border-collapse text-left">
        <thead className="sticky top-0 z-10 border-b border-border bg-alt">
          <tr>
            <th className={cn(th, 'border-l-2 border-transparent')}>Richtung</th>
            <th className={th}>Status</th>
            <th className={cn(th, 'text-center')}>Zuständig</th>
            <th className={cn(th, 'w-1/4')}>Anrufer</th>
            <th className={cn(th, 'w-1/2')}>Betreff</th>
            <th className={th}>Vorgang</th>
            <th className={th}>Datum</th>
            <th className={th}>Uhrzeit</th>
            <th className={cn(th, 'pl-6')}>Dauer</th>
          </tr>
        </thead>
        <tbody>
          {dayGroups.map((g) => (
            <Fragment key={g.key}>
              <tr className="bg-bg">
                <td
                  colSpan={9}
                  className="border-y border-border-faint px-3 py-2 text-[12.5px] font-extrabold capitalize tracking-wide text-muted"
                >
                  <span className="inline-flex items-center gap-2">
                    {g.label}
                    <span className="rounded-full bg-alt px-2 py-px text-[10.5px] font-bold text-faint">
                      {g.calls.length} {g.calls.length === 1 ? 'Anruf' : 'Anrufe'}
                    </span>
                  </span>
                </td>
              </tr>
              {g.calls.map((c) => (
                <LogTableRow
                  key={c.id}
                  call={c}
                  active={c.id === selectedId}
                  assigneeName={c.assigned_employee_id ? (employeeName.get(c.assigned_employee_id) ?? null) : null}
                  onSelect={() => onSelect(c.id)}
                  onOpenCase={onOpenCase}
                />
              ))}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  )
}
