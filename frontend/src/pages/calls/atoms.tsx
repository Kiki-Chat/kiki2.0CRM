// Presentational atoms for the Call Logs redesign. No data fetching here —
// everything is props-driven so the orchestration stays in CallLogsPage / CallDetail.
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import {
  AlertTriangle,
  Calendar,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleDot,
  Clock,
  PhoneIncoming,
  PhoneOutgoing,
  SlidersHorizontal,
  type LucideIcon,
} from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'

import { cn, initials } from '../../lib/utils'
import {
  avatarColorForEmployee,
  type DateFilter,
  type DirFilter,
  type Employee,
  type InboxFilters,
  type StatusFilter,
} from './shared'

// ─── Avatar (employee-hashed initials circle) ──────────────────────────────
export function Avatar({
  employeeId,
  text,
  size = 26,
}: {
  employeeId: string | null
  text: string
  size?: number
}) {
  const c = avatarColorForEmployee(employeeId)
  return (
    <span
      className={cn('flex flex-shrink-0 items-center justify-center rounded-full font-extrabold', c.bg, c.text)}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.4) }}
    >
      {text || '?'}
    </span>
  )
}

// ─── Status pill (Offen / In Bearbeitung / Erledigt) ───────────────────────
const STATUS_CFG: Record<string, { label: string; text: string; bg: string; dot: string; Icon: LucideIcon }> = {
  open: { label: 'Offen', text: 'text-info', bg: 'bg-info-bg', dot: 'bg-info', Icon: CircleDot },
  in_progress: { label: 'In Bearbeitung', text: 'text-warning', bg: 'bg-warning-bg', dot: 'bg-warning', Icon: Clock },
  completed: { label: 'Erledigt', text: 'text-success', bg: 'bg-success-bg', dot: 'bg-success', Icon: CheckCircle2 },
}

export function StatusPill({ status, dot = false }: { status: string | null; dot?: boolean }) {
  const s = status ? STATUS_CFG[status] : null
  if (!s) return null
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-[11.5px] font-bold',
        s.bg,
        s.text,
      )}
    >
      {dot ? <span className={cn('h-1.5 w-1.5 rounded-full', s.dot)} /> : <s.Icon size={12} />}
      {s.label}
    </span>
  )
}

// ─── Direction badge (teal inbound / amber outbound) ───────────────────────
export function DirBadge({ dir, withLabel = false }: { dir: string | null; withLabel?: boolean }) {
  const out = dir === 'outbound'
  return (
    <span className={cn('inline-flex items-center gap-1.5 text-[11.5px] font-semibold', out ? 'text-outbound' : 'text-inbound')}>
      {out ? <PhoneOutgoing size={13} /> : <PhoneIncoming size={13} />}
      {withLabel && (out ? 'Ausgehend' : 'Eingehend')}
    </span>
  )
}

// ─── Emergency badge — the ONLY blinking element ───────────────────────────
export function NotdienstBadge({ small = false }: { small?: boolean }) {
  return (
    <span
      className={cn(
        'inline-flex flex-shrink-0 animate-pulse items-center gap-1 rounded-md bg-error font-extrabold uppercase tracking-wider text-white',
        small ? 'px-1.5 py-0.5 text-[9px]' : 'px-2 py-0.5 text-[10.5px]',
      )}
    >
      <AlertTriangle size={small ? 10 : 11} /> Notdienst
    </span>
  )
}

export function MoodPill({ mood }: { mood: string }) {
  const m =
    /positiv/i.test(mood)
      ? 'bg-success-bg text-success'
      : /negativ/i.test(mood)
        ? 'bg-error-bg text-error'
        : 'bg-alt text-muted'
  return <span className={cn('rounded-full px-2 py-0.5 text-[11px] font-bold', m)}>{mood}</span>
}

// ─── Segmented control (inbox tabs) ────────────────────────────────────────
export interface SegOption {
  value: string
  label: string
  icon?: LucideIcon
  badge?: number | null
  badgeTone?: 'red' | 'neutral'
}
export function Segmented({
  options,
  value,
  onChange,
  full = false,
}: {
  options: SegOption[]
  value: string
  onChange: (v: string) => void
  full?: boolean
}) {
  return (
    <div className={cn('flex gap-1 rounded-xl border border-border bg-alt p-1', full && 'w-full')}>
      {options.map((o) => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            onClick={() => onChange(o.value)}
            className={cn(
              'inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-bold transition-colors',
              full && 'flex-1',
              active ? 'bg-surface text-text shadow-e1' : 'text-muted hover:text-body',
            )}
          >
            {o.icon && <o.icon size={14} />}
            {o.label}
            {o.badge != null && (
              <span
                className={cn(
                  'flex h-[17px] min-w-[17px] items-center justify-center rounded-full px-1 text-[10px] font-extrabold',
                  o.badgeTone === 'red' ? 'bg-error text-white' : 'bg-alt text-muted',
                )}
              >
                {o.badge}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

// ─── Frosted-glass filter popover (Richtung / Status / NEW Zeitraum) ───────
const DATE_PRESETS: { value: DateFilter; label: string }[] = [
  { value: 'all', label: 'Alle' },
  { value: 'today', label: 'Heute' },
  { value: '7d', label: '7 Tage' },
  { value: '30d', label: '30 Tage' },
  { value: 'custom', label: 'Zeitraum…' },
]

function ChipRow<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: string; dot?: string }[]
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            onClick={() => onChange(o.value)}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1.5 text-xs font-bold transition-colors',
              active
                ? 'border-green-primary bg-green-tint-100 text-green-deep'
                : 'border-border bg-surface text-body hover:bg-alt',
            )}
          >
            {o.dot && <span className="h-1.5 w-1.5 rounded-full" style={{ background: o.dot }} />}
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

export function FilterPopover({
  filters,
  setFilters,
}: {
  filters: InboxFilters
  setFilters: (f: InboxFilters | ((f: InboxFilters) => InboxFilters)) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    function h(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    if (open) document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [open])

  const activeCount =
    (filters.dir !== 'all' ? 1 : 0) + (filters.status !== 'all' ? 1 : 0) + (filters.date !== 'all' ? 1 : 0)
  const set = <K extends keyof InboxFilters>(k: K, v: InboxFilters[K]) =>
    setFilters((f) => ({ ...f, [k]: v }))

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className={cn(
          'inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-bold transition-colors',
          activeCount
            ? 'border-green-primary bg-green-tint-50 text-green-deep'
            : 'border-border bg-surface text-body hover:bg-alt',
        )}
      >
        <SlidersHorizontal size={15} /> Filter
        {activeCount > 0 && (
          <span className="flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-green-primary px-1 text-[10.5px] font-extrabold text-white">
            {activeCount}
          </span>
        )}
        <ChevronDown size={13} className={cn('transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        <div
          className="absolute right-0 z-[60] mt-2 w-[min(300px,calc(100vw-1.5rem))] rounded-2xl border p-4 shadow-e3"
          style={{
            background: 'var(--glass-bg)',
            backdropFilter: 'blur(20px) saturate(1.6)',
            WebkitBackdropFilter: 'blur(20px) saturate(1.6)',
            borderColor: 'var(--glass-border)',
          }}
        >
          <FilterGroup label="Richtung">
            <ChipRow<DirFilter>
              value={filters.dir}
              onChange={(v) => set('dir', v)}
              options={[
                { value: 'all', label: 'Alle' },
                { value: 'inbound', label: 'Eingehend', dot: 'var(--inbound)' },
                { value: 'outbound', label: 'Ausgehend', dot: 'var(--outbound)' },
              ]}
            />
          </FilterGroup>
          <FilterGroup label="Status">
            <ChipRow<StatusFilter>
              value={filters.status}
              onChange={(v) => set('status', v)}
              options={[
                { value: 'all', label: 'Alle' },
                { value: 'open', label: 'Offen', dot: 'var(--info)' },
                { value: 'in_progress', label: 'In Bearbeitung', dot: 'var(--warning)' },
                { value: 'completed', label: 'Erledigt', dot: 'var(--success)' },
              ]}
            />
          </FilterGroup>
          <FilterGroup label="Zeitraum">
            <ChipRow<DateFilter>
              value={filters.date}
              onChange={(v) => set('date', v)}
              options={DATE_PRESETS.map((p) => ({ value: p.value, label: p.label }))}
            />
            {filters.date === 'custom' && (
              <div className="mt-2 flex gap-2">
                <input
                  type="date"
                  value={filters.from}
                  max={filters.to || undefined}
                  onChange={(e) => set('from', e.target.value)}
                  className="min-w-0 flex-1 rounded-lg border border-border bg-alt px-2 py-1.5 text-xs text-text outline-none focus:border-green-primary"
                />
                <input
                  type="date"
                  value={filters.to}
                  min={filters.from || undefined}
                  onChange={(e) => set('to', e.target.value)}
                  className="min-w-0 flex-1 rounded-lg border border-border bg-alt px-2 py-1.5 text-xs text-text outline-none focus:border-green-primary"
                />
              </div>
            )}
          </FilterGroup>
          <div className="mt-1.5 flex items-center justify-between border-t border-border pt-3">
            <button
              onClick={() => setFilters((f) => ({ ...f, dir: 'all', status: 'all', date: 'all', from: '', to: '' }))}
              className="text-xs font-bold text-muted hover:text-body"
            >
              Zurücksetzen
            </button>
            <button
              onClick={() => setOpen(false)}
              className="rounded-lg bg-green-primary px-4 py-1.5 text-sm font-bold text-white hover:brightness-105"
            >
              Anwenden
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function FilterGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="mb-3.5">
      <div className="mb-2 text-[10.5px] font-extrabold uppercase tracking-wider text-muted">{label}</div>
      {children}
    </div>
  )
}

// ─── Calendar icon re-export for inbox header (kept here for one import site) ──
export { Calendar as FilterCalendarIcon }

// ─── Numbered pager (pinned to inbox bottom) ───────────────────────────────
export function PagerNumbered({ page, pages, onPage }: { page: number; pages: number; onPage: (p: number) => void }) {
  if (pages <= 1) return null
  const nums = Array.from({ length: pages }, (_, i) => i + 1)
  const edge =
    'flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-surface text-body disabled:cursor-default disabled:opacity-50'
  return (
    <div className="flex items-center justify-between gap-2 border-t border-border bg-surface px-3 py-2.5">
      <button disabled={page === 1} onClick={() => onPage(page - 1)} className={edge} aria-label="Vorherige Seite">
        <ChevronLeft size={15} />
      </button>
      <div className="flex gap-1">
        {nums.map((n) => (
          <button
            key={n}
            onClick={() => onPage(n)}
            className={cn(
              'h-8 min-w-[32px] rounded-lg text-sm font-bold',
              n === page ? 'bg-green-primary text-white' : 'text-muted hover:bg-alt',
            )}
          >
            {n}
          </button>
        ))}
      </div>
      <button disabled={page === pages} onClick={() => onPage(page + 1)} className={edge} aria-label="Nächste Seite">
        <ChevronRight size={15} />
      </button>
    </div>
  )
}

// ─── Assign dropdown (radix) — reused by the row avatar + the workspace field ─
export function AssignDropdown({
  current,
  employees,
  onAssign,
  disabled = false,
  align = 'start',
  children,
}: {
  current: string | null
  employees: Employee[]
  onAssign: (employeeId: string | null) => void
  disabled?: boolean
  align?: 'start' | 'end'
  children: ReactNode
}) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild disabled={disabled}>
        {children}
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align={align}
          sideOffset={6}
          onClick={(e) => e.stopPropagation()}
          className="z-[70] max-h-64 w-56 overflow-y-auto rounded-xl border border-border bg-surface p-1.5 shadow-e3"
        >
          <div className="px-2 pb-1.5 pt-1 text-[10px] font-extrabold uppercase tracking-wider text-faint">
            Zuweisen an
          </div>
          <DropdownMenu.Item
            onSelect={() => onAssign(null)}
            className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm font-medium text-body outline-none data-[highlighted]:bg-alt"
          >
            <span className="flex h-[22px] w-[22px] flex-shrink-0 items-center justify-center rounded-full bg-alt text-[11px] font-extrabold text-faint">
              —
            </span>
            <span className="flex-1">Niemand</span>
            {current == null && <Check size={14} className="text-green-deep" />}
          </DropdownMenu.Item>
          {employees.length > 0 && <DropdownMenu.Separator className="my-1 h-px bg-border" />}
          {employees.map((e) => (
            <DropdownMenu.Item
              key={e.id}
              onSelect={() => onAssign(e.id)}
              className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm font-medium text-body outline-none data-[highlighted]:bg-alt"
            >
              <Avatar employeeId={e.id} text={initials(e.display_name ?? '?')} size={22} />
              <span className="flex-1 truncate text-left">{e.display_name ?? '—'}</span>
              {current === e.id && <Check size={14} className="text-green-deep" />}
            </DropdownMenu.Item>
          ))}
          {!employees.length && <div className="px-3 py-2 text-xs text-muted">Keine Mitarbeiter.</div>}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
