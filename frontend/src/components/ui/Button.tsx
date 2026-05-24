import type { ButtonHTMLAttributes, ReactNode } from 'react'

import { cn } from '../../lib/utils'

type Variant = 'primary' | 'secondary' | 'tertiary' | 'destructive'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  children: ReactNode
}

const base =
  'inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium ' +
  'transition-colors disabled:opacity-50 disabled:pointer-events-none px-4 py-2'

const variants: Record<Variant, string> = {
  // One primary per screen — the only filled green CTA.
  primary: 'bg-green-primary text-white hover:brightness-110',
  secondary: 'border border-border text-body bg-transparent hover:bg-alt',
  tertiary: 'text-green-deep bg-transparent hover:underline',
  destructive: 'bg-error text-white hover:brightness-110',
}

export function Button({ variant = 'secondary', className, children, ...props }: ButtonProps) {
  return (
    <button className={cn(base, variants[variant], className)} {...props}>
      {children}
    </button>
  )
}
