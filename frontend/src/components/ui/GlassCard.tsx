import type { HTMLAttributes, ReactNode } from 'react'

import { cn } from '../../lib/utils'

/** Liquid-glass / glassmorphism card — frosted translucency via `.glass-card` in index.css. */
export function GlassCard({
  className,
  children,
  ...props
}: HTMLAttributes<HTMLDivElement> & { children: ReactNode }) {
  return (
    <div className={cn('glass-card', className)} {...props}>
      {children}
    </div>
  )
}
