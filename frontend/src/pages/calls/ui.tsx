// Tiny shared chrome used across the call-logs panes.
import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { cn } from '../../lib/utils'

export function GhostBtn({
  icon: Icon,
  title,
  active = false,
  onClick,
}: {
  icon: LucideIcon
  title: string
  active?: boolean
  onClick?: () => void
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={cn(
        'flex h-[34px] w-[34px] flex-shrink-0 items-center justify-center rounded-lg transition-colors',
        active ? 'bg-green-tint-100 text-green-deep' : 'text-muted hover:bg-alt',
      )}
    >
      <Icon size={17} />
    </button>
  )
}

// Small uppercase section caption used throughout the workspace pane.
export function SectionLabel({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-2.5 flex items-center justify-between">
      <span className="text-[10.5px] font-extrabold uppercase tracking-wider text-muted">{children}</span>
      {right}
    </div>
  )
}
