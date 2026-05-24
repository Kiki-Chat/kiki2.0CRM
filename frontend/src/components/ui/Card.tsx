import type { HTMLAttributes, ReactNode } from 'react'

import { cn } from '../../lib/utils'

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: 'standard' | 'subtle' | 'interactive'
  children: ReactNode
}

export function Card({ variant = 'standard', className, children, ...props }: CardProps) {
  const styles = {
    standard: 'bg-surface border border-border shadow-e1',
    subtle: 'bg-alt border border-transparent',
    interactive:
      'bg-surface border border-border shadow-e1 cursor-pointer transition ' +
      'hover:shadow-e2 hover:bg-green-tint-50',
  }[variant]

  return (
    <div className={cn('rounded-lg p-6', styles, className)} {...props}>
      {children}
    </div>
  )
}
