// Left inbox: call rows + the Aktionen worklist rows. Presentational — all data
// + handlers come from CallLogsPage.
import {
  Calendar,
  CalendarClock,
  CheckCircle2,
  ChevronRight,
  Info,
  Phone,
  Receipt,
  User,
  type LucideIcon,
} from 'lucide-react'

import { cn } from '../../lib/utils'
import { useMe } from '../../lib/useMe'
import { Tag } from '../../components/ui/Tag'
import { Avatar, AssignDropdown, DirBadge, NotdienstBadge, StatusPill } from './atoms'
import {
  ACTION_KIND_LABEL,
  type ActionItem,
  type CallListItem,
  displayName,
  type Employee,
  fmtDuration,
  fmtTime,
} from './shared'

export function CallRow({
  call,
  active,
  employees,
  onSelect,
  onAssign,
  assigning,
}: {
  call: CallListItem
  active: boolean
  employees: Employee[]
  onSelect: () => void
  onAssign: (employeeId: string | null) => void
  assigning: boolean
}) {
  const isUnread = call.read_at === null
  // Only admins may (re)assign work to employees — see enforce_self_assignment
  // on the backend. Employees get a read-only avatar.
  const { isAdmin } = useMe()
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSelect()
        }
      }}
      className={cn(
        // flex-shrink-0 is the critical fix: the row clips its bottom row otherwise.
        'relative flex flex-shrink-0 cursor-pointer items-start gap-3 overflow-hidden rounded-2xl py-3.5 pl-[17px] pr-3.5 text-left transition-colors',
        active
          ? 'bg-green-tint-50 shadow-[inset_0_0_0_1.5px_var(--green-primary)]'
          : 'bg-surface shadow-[inset_0_0_0_1px_var(--border)] hover:bg-alt',
      )}
    >
      {/* status accent rail: blue = offen · amber = in Bearbeitung · green = erledigt
          (direction is conveyed by the badge, not the colour) */}
      <span
        className={cn(
          'absolute bottom-0 left-0 top-0 w-1',
          call.inquiry_status === 'completed'
            ? 'bg-success'
            : call.inquiry_status === 'in_progress'
              ? 'bg-warning'
              : call.inquiry_status === 'open'
                ? 'bg-info'
                : 'bg-faint',
        )}
      />
      {/* unread dot */}
      {isUnread && <span className="absolute left-[9px] top-[15px] h-[7px] w-[7px] rounded-full bg-green-primary" />}

      <AssignDropdown
        current={call.assigned_employee_id}
        employees={employees}
        onAssign={onAssign}
        disabled={!call.inquiry_id || assigning || !isAdmin}
      >
        <button
          type="button"
          onClick={(e) => e.stopPropagation()}
          disabled={!call.inquiry_id || assigning || !isAdmin}
          title={
            !isAdmin
              ? 'Nur Admins können Mitarbeiter zuweisen'
              : call.inquiry_id
                ? 'Mitarbeiter zuweisen'
                : 'Noch keine Anfrage — kann nicht zugewiesen werden'
          }
          className="flex-shrink-0 rounded-full transition-transform hover:scale-110 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <Avatar employeeId={call.assigned_employee_id} text={call.assigned_employee_initials ?? '?'} size={36} />
        </button>
      </AssignDropdown>

      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          {/* Subject/reason is the headline — the caller name often isn't known,
              so it must never be the primary line. */}
          <span className={cn('truncate text-[14.5px]', isUnread ? 'font-extrabold text-text' : 'font-semibold text-body')}>
            {call.summary_title ?? 'Anruf'}
          </span>
          <DirBadge dir={call.direction} />
        </div>
        <div className={cn('mt-0.5 truncate text-[12.5px]', isUnread ? 'text-body' : 'text-muted')}>
          {displayName(call)}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <StatusPill status={call.inquiry_status} dot />
          {call.emergency_flag && <NotdienstBadge small />}
        </div>
        <div className="mt-1.5 flex items-center gap-1.5 text-[11.5px] text-faint">
          <span>{fmtTime(call.started_at)}</span>
          <span className="h-[3px] w-[3px] flex-shrink-0 rounded-full bg-faint" />
          <span className="tabular-nums">{fmtDuration(call.duration_seconds)}</span>
        </div>
      </div>
    </div>
  )
}

const KIND_ICON: Record<ActionItem['kind'], LucideIcon> = {
  termin_anfrage: Calendar,
  kva_to_send: Receipt,
  kva_pending_acceptance: Receipt,
  callback_owed: Phone,
  alt_time_proposal: CalendarClock,
}
const KIND_TONE: Record<ActionItem['kind'], { tile: string; tag: 'info' | 'ai' | 'warning' }> = {
  termin_anfrage: { tile: 'bg-info-bg text-info', tag: 'info' },
  kva_to_send: { tile: 'bg-ai-bg text-ai', tag: 'ai' },
  kva_pending_acceptance: { tile: 'bg-ai-bg text-ai', tag: 'ai' },
  callback_owed: { tile: 'bg-warning-bg text-warning', tag: 'warning' },
  alt_time_proposal: { tile: 'bg-warning-bg text-warning', tag: 'warning' },
}

export function ActionRow({ item, onSelect }: { item: ActionItem; onSelect: () => void }) {
  const tone = KIND_TONE[item.kind] ?? { tile: 'bg-alt text-muted', tag: 'info' as const }
  const Icon = KIND_ICON[item.kind] ?? Info
  const high = item.priority === 'high'
  const time = item.due_at || item.created_at
  return (
    <button
      onClick={onSelect}
      className="flex w-full flex-shrink-0 items-start gap-3 rounded-2xl bg-surface py-3.5 pl-3.5 pr-3 text-left shadow-[inset_0_0_0_1px_var(--border)] transition-colors hover:bg-alt"
    >
      <span className={cn('relative flex h-[38px] w-[38px] flex-shrink-0 items-center justify-center rounded-xl', tone.tile)}>
        <Icon size={18} />
        {high && (
          <span className="absolute -right-1 -top-1 h-3 w-3 animate-pulse rounded-full border-2 border-surface bg-error" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-center gap-2">
          <span className="flex-shrink-0">
            <Tag variant={tone.tag}>{ACTION_KIND_LABEL[item.kind]}</Tag>
          </span>
          {high && (
            <span className="flex-shrink-0 text-[10.5px] font-extrabold uppercase tracking-wide text-error">Dringend</span>
          )}
          <span className="ml-auto truncate text-[11px] text-faint">{fmtTime(time)}</span>
        </div>
        <div className="truncate text-[13.5px] font-bold leading-snug text-text">{item.summary}</div>
        <div className="mt-1 flex items-center gap-1.5 truncate text-xs text-muted">
          <User size={12} className="text-faint" />
          {item.customer_name || 'Unbekannter Kunde'}
        </div>
      </div>
      <ChevronRight size={16} className="self-center text-faint" />
    </button>
  )
}

export function EmptyAktionen() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
      <span className="flex h-14 w-14 items-center justify-center rounded-full bg-green-tint-100 text-green-deep">
        <CheckCircle2 size={26} />
      </span>
      <div>
        <div className="text-sm font-extrabold text-text">Keine offenen Aktionen</div>
        <div className="mt-0.5 text-[12.5px] text-muted">Kiki hat alles im Griff.</div>
      </div>
    </div>
  )
}
