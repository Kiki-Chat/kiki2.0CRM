// The Anrufe filter bar: search + four direction pills (Alle/Eingehend/Ausgehend/
// Notdienst, with live counts) + Status / Zuständig / Zeitraum dropdowns + a
// "Kurze Anrufe ausblenden" toggle. All filtering is client-side over the loaded list.
import { CalendarDays, Check, ChevronDown, EyeOff, RotateCcw, Search, Users } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'

import { cn, initials } from '../../../lib/utils'
import { Avatar } from '../atoms'
import type { Employee } from '../shared'
import { activeSecondaryCount, type DirPill, type LogFilters, type StatusF } from './util'

export interface PillCounts {
  all: number
  inbound: number
  outbound: number
  emergency: number
}

const DIR_PILLS: { value: DirPill; label: string; dot?: string; danger?: boolean }[] = [
  { value: 'all', label: 'Alle' },
  { value: 'inbound', label: 'Eingehend', dot: 'var(--inbound)' },
  { value: 'outbound', label: 'Ausgehend', dot: 'var(--outbound)' },
  { value: 'emergency', label: 'Notdienst', dot: 'var(--error)', danger: true },
]

const STATUS_OPTS: { value: StatusF; label: string; dot?: string }[] = [
  { value: 'all', label: 'Alle' },
  { value: 'unread', label: 'Neu (ungelesen)', dot: 'var(--green-primary)' },
  { value: 'open', label: 'Offen', dot: 'var(--info)' },
  { value: 'in_progress', label: 'In Bearbeitung', dot: 'var(--warning)' },
  { value: 'completed', label: 'Erledigt', dot: 'var(--success)' },
]

const DATE_OPTS: { value: LogFilters['date']; label: string }[] = [
  { value: 'all', label: 'Alle' },
  { value: 'today', label: 'Heute' },
  { value: '7d', label: 'Letzte 7 Tage' },
  { value: '30d', label: 'Letzte 30 Tage' },
  { value: 'custom', label: 'Zeitraum…' },
]

// ─── Generic dropdown shell (trigger + outside-click panel) ─────────────────
function Menu({
  label,
  valueLabel,
  icon,
  active,
  children,
}: {
  label: string
  valueLabel?: string | null
  icon?: ReactNode
  active: boolean
  children: (close: () => void) => ReactNode
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [open])

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          'inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[13px] font-bold transition-colors',
          active ? 'border-green-primary bg-green-tint-50 text-green-deep' : 'border-border bg-surface text-body hover:bg-alt',
        )}
      >
        {icon}
        {label}
        {valueLabel ? <span className="text-green-deep">: {valueLabel}</span> : null}
        <ChevronDown size={13} className={cn('transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="absolute right-0 z-[60] mt-2 w-[min(240px,calc(100vw-1.5rem))] rounded-xl border border-border bg-surface p-1.5 shadow-e3">
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  )
}

function Option({
  label,
  dot,
  selected,
  onClick,
  children,
}: {
  label: string
  dot?: string
  selected: boolean
  onClick: () => void
  children?: ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-sm font-medium text-body outline-none hover:bg-alt"
    >
      {children ?? (dot && <span className="h-2 w-2 flex-shrink-0 rounded-full" style={{ background: dot }} />)}
      <span className="flex-1 truncate">{label}</span>
      {selected && <Check size={14} className="flex-shrink-0 text-green-deep" />}
    </button>
  )
}

export function LogFilters({
  filters,
  setFilters,
  search,
  setSearch,
  employees,
  counts,
}: {
  filters: LogFilters
  setFilters: (f: LogFilters | ((f: LogFilters) => LogFilters)) => void
  search: string
  setSearch: (s: string) => void
  employees: Employee[]
  counts: PillCounts
}) {
  const set = <K extends keyof LogFilters>(k: K, v: LogFilters[K]) => setFilters((f) => ({ ...f, [k]: v }))

  const statusLabel = STATUS_OPTS.find((o) => o.value === filters.status && o.value !== 'all')?.label ?? null
  const dateLabel = DATE_OPTS.find((o) => o.value === filters.date && o.value !== 'all')?.label ?? null
  const empLabel =
    filters.employeeId === 'all'
      ? null
      : filters.employeeId === 'none'
        ? 'Niemand'
        : (employees.find((e) => e.id === filters.employeeId)?.display_name ?? 'Mitarbeiter')

  const dirty = filters.dir !== 'all' || activeSecondaryCount(filters) > 0 || search.trim().length > 0
  const pillCount = (v: DirPill) =>
    v === 'all' ? counts.all : v === 'inbound' ? counts.inbound : v === 'outbound' ? counts.outbound : counts.emergency

  return (
    <div className="flex flex-col gap-3">
      {/* search */}
      <div className="relative">
        <Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-faint" />
        <input
          type="search"
          name="call-log-search"
          autoComplete="off"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Anrufe durchsuchen — Name, Nummer oder Betreff …"
          className="w-full rounded-xl border border-border bg-surface py-2.5 pl-10 pr-3 text-sm text-body outline-none transition-colors focus:border-green-primary"
        />
      </div>

      {/* pills + secondary filters */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2.5">
        <div className="flex flex-wrap items-center gap-1.5">
          {DIR_PILLS.map((p) => {
            const active = filters.dir === p.value
            const n = pillCount(p.value)
            return (
              <button
                key={p.value}
                type="button"
                onClick={() => set('dir', p.value)}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-[13px] font-bold transition-colors',
                  active
                    ? p.danger
                      ? 'bg-error text-white'
                      : 'bg-green-primary text-white'
                    : 'bg-alt text-muted hover:text-body',
                )}
              >
                {p.dot && !active && <span className="h-2 w-2 rounded-full" style={{ background: p.dot }} />}
                {p.label}
                <span
                  className={cn(
                    'flex h-[17px] min-w-[17px] items-center justify-center rounded-full px-1 text-[10px] font-extrabold',
                    active ? 'bg-white/25 text-white' : 'bg-surface text-faint',
                  )}
                >
                  {n}
                </span>
              </button>
            )
          })}
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          {/* Status */}
          <Menu label="Status" valueLabel={statusLabel} active={filters.status !== 'all'}>
            {(close) =>
              STATUS_OPTS.map((o) => (
                <Option
                  key={o.value}
                  label={o.label}
                  dot={o.dot}
                  selected={filters.status === o.value}
                  onClick={() => {
                    set('status', o.value)
                    close()
                  }}
                />
              ))
            }
          </Menu>

          {/* Zuständig */}
          <Menu label="Zuständig" icon={<Users size={14} />} valueLabel={empLabel} active={filters.employeeId !== 'all'}>
            {(close) => (
              <div className="max-h-72 overflow-y-auto">
                <Option
                  label="Alle"
                  selected={filters.employeeId === 'all'}
                  onClick={() => {
                    set('employeeId', 'all')
                    close()
                  }}
                />
                <Option
                  label="Niemand (nicht zugewiesen)"
                  selected={filters.employeeId === 'none'}
                  onClick={() => {
                    set('employeeId', 'none')
                    close()
                  }}
                >
                  <span className="flex h-[22px] w-[22px] flex-shrink-0 items-center justify-center rounded-full border border-dashed border-border text-[11px] font-bold text-faint">
                    –
                  </span>
                </Option>
                {employees.length > 0 && <div className="my-1 h-px bg-border" />}
                {employees.map((e) => (
                  <Option
                    key={e.id}
                    label={e.display_name ?? '—'}
                    selected={filters.employeeId === e.id}
                    onClick={() => {
                      set('employeeId', e.id)
                      close()
                    }}
                  >
                    <Avatar employeeId={e.id} text={initials(e.display_name ?? '?')} size={22} />
                  </Option>
                ))}
              </div>
            )}
          </Menu>

          {/* Zeitraum */}
          <Menu label="Zeitraum" icon={<CalendarDays size={14} />} valueLabel={dateLabel} active={filters.date !== 'all'}>
            {(close) => (
              <>
                {DATE_OPTS.map((o) => (
                  <Option
                    key={o.value}
                    label={o.label}
                    selected={filters.date === o.value}
                    onClick={() => {
                      set('date', o.value)
                      if (o.value !== 'custom') close()
                    }}
                  />
                ))}
                {filters.date === 'custom' && (
                  <div className="mt-1.5 flex flex-col gap-2 border-t border-border px-1 pt-2.5">
                    <input
                      type="date"
                      aria-label="Von"
                      value={filters.from}
                      max={filters.to || undefined}
                      onChange={(e) => set('from', e.target.value)}
                      className="rounded-lg border border-border bg-alt px-2 py-1.5 text-xs text-text outline-none focus:border-green-primary"
                    />
                    <input
                      type="date"
                      aria-label="Bis"
                      value={filters.to}
                      min={filters.from || undefined}
                      onChange={(e) => set('to', e.target.value)}
                      className="rounded-lg border border-border bg-alt px-2 py-1.5 text-xs text-text outline-none focus:border-green-primary"
                    />
                  </div>
                )}
              </>
            )}
          </Menu>

          {/* Kurze Anrufe ausblenden */}
          <button
            type="button"
            onClick={() => set('hideShort', !filters.hideShort)}
            title="Sehr kurze Anrufe (Auflegen / Testanrufe) ausblenden"
            className={cn(
              'inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[13px] font-bold transition-colors',
              filters.hideShort
                ? 'border-green-primary bg-green-tint-50 text-green-deep'
                : 'border-border bg-surface text-muted hover:bg-alt',
            )}
          >
            <EyeOff size={14} />
            Kurze Anrufe
          </button>

          {dirty && (
            <button
              type="button"
              onClick={() => {
                setFilters(() => ({ dir: 'all', status: 'all', employeeId: 'all', date: 'all', from: '', to: '', hideShort: false }))
                setSearch('')
              }}
              className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] font-bold text-muted hover:text-body"
            >
              <RotateCcw size={13} />
              Zurücksetzen
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
