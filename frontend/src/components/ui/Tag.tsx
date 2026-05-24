import type { ReactNode } from 'react'

import { cn } from '../../lib/utils'

type Variant = 'neutral' | 'info' | 'warning' | 'error' | 'ai' | 'success' | 'green'

const variants: Record<Variant, string> = {
  neutral: 'bg-alt text-muted',
  info: 'bg-info-bg text-info',
  warning: 'bg-warning-bg text-warning',
  error: 'bg-error-bg text-error',
  ai: 'bg-ai-bg text-ai',
  success: 'bg-success-bg text-success',
  green: 'bg-green-tint-100 text-green-deep',
}

export function Tag({
  variant = 'neutral',
  children,
  className,
}: {
  variant?: Variant
  children: ReactNode
  className?: string
}) {
  return (
    <span
      className={cn(
        'inline-block whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-bold',
        variants[variant],
        className,
      )}
    >
      {children}
    </span>
  )
}
