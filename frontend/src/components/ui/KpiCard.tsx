import type { LucideIcon } from 'lucide-react'

import { Card } from './Card'

export function KpiCard({
  label,
  value,
  sub,
  icon: Icon,
  onClick,
}: {
  label: string
  value: string | number
  sub?: string
  icon?: LucideIcon
  onClick?: () => void
}) {
  const clickable = !!onClick
  return (
    <Card
      variant={clickable ? 'interactive' : 'standard'}
      className="flex items-center gap-4 p-5"
      onClick={onClick}
      role={clickable ? 'button' : undefined}
      tabIndex={clickable ? 0 : undefined}
      onKeyDown={
        clickable
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                onClick?.()
              }
            }
          : undefined
      }
    >
      {Icon && (
        <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-green-tint-100">
          <Icon size={18} className="text-green-deep" />
        </div>
      )}
      <div className="min-w-0">
        <div className="text-xs font-bold uppercase tracking-wide text-muted">{label}</div>
        <div className="text-2xl font-bold leading-tight text-text">{value}</div>
        {sub && <div className="text-xs text-muted">{sub}</div>}
      </div>
    </Card>
  )
}
