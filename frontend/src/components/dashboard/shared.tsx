import { ArrowDownRight, ArrowUpRight, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { Line, LineChart, ResponsiveContainer } from 'recharts'

import { cn } from '../../lib/utils'

export function Panel({
  title,
  action,
  children,
  className,
}: {
  title: string
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cn('rounded-xl border border-border bg-surface p-5', className)}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-bold text-text">{title}</h2>
        {action}
      </div>
      {children}
    </div>
  )
}

function Sparkline({ data, color = 'var(--green-primary)' }: { data: number[]; color?: string }) {
  const d = data.map((v, i) => ({ i, v }))
  return (
    <div className="h-9 w-24 shrink-0">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={d}>
          <Line type="monotone" dataKey="v" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export function TrendBadge({ delta, unit, goodWhenUp = true }: { delta: number; unit?: string; goodWhenUp?: boolean }) {
  if (!delta) return <div className="mt-2 text-xs text-muted">±0{unit ? ` ${unit}` : ''} ggü. Vormonat</div>
  const up = delta > 0
  const positive = goodWhenUp ? up : !up
  const Icon = up ? ArrowUpRight : ArrowDownRight
  return (
    <div className={cn('mt-2 flex items-center gap-1 text-xs font-medium', positive ? 'text-success' : 'text-error')}>
      <Icon size={12} />
      {up ? '+' : ''}{delta}{unit ? ` ${unit}` : ''} ggü. Vormonat
    </div>
  )
}

export function DashKpi({
  label,
  value,
  sub,
  icon: Icon,
  spark,
  sparkColor,
  trend,
  children,
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  icon?: LucideIcon
  spark?: number[]
  sparkColor?: string
  trend?: ReactNode
  children?: ReactNode
}) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</span>
        {Icon && <Icon size={16} className="text-muted" />}
      </div>
      <div className="mt-1.5 flex items-end justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-2xl font-bold leading-tight text-text">{value}</div>
          {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
        </div>
        {spark && spark.length > 1 && <Sparkline data={spark} color={sparkColor} />}
      </div>
      {trend}
      {children}
    </div>
  )
}

export function KpiRow({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">{children}</div>
}

// Tailwind-token colors usable as recharts stroke/fill values.
export const CHART = {
  green: 'var(--green-primary)',
  ai: 'var(--ai)',
  info: 'var(--info)',
  warning: 'var(--warning)',
  error: 'var(--error)',
  muted: 'var(--muted)',
}

export const tooltipStyle = {
  background: 'var(--surface)',
  border: '1px solid var(--border)',
  borderRadius: 8,
  fontSize: 12,
  color: 'var(--text)',
}

export function DashLoading() {
  return <div className="rounded-xl border border-border bg-surface p-12 text-center text-sm text-muted">Lädt…</div>
}
export function DashError({ msg }: { msg?: string }) {
  return <div className="rounded-xl border border-border bg-surface p-12 text-center text-sm text-error">Daten konnten nicht geladen werden{msg ? `: ${msg}` : '.'}</div>
}
export function DashEmpty({ msg }: { msg: string }) {
  return <div className="py-8 text-center text-sm text-muted">{msg}</div>
}
