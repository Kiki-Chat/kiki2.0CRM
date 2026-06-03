import { Bell, ChevronLeft, Moon, Sun } from 'lucide-react'

import { useTheme } from '../../lib/theme'
import { cn } from '../../lib/utils'

export function Topbar({
  collapsed,
  onToggleCollapse,
}: {
  collapsed: boolean
  onToggleCollapse: () => void
}) {
  const { theme, toggle } = useTheme()

  return (
    <header className="sticky top-0 z-10 flex h-14 items-center gap-3.5 border-b border-border bg-sidebar px-7">
      <button
        onClick={onToggleCollapse}
        className="flex rounded-md p-1.5 text-muted hover:bg-alt"
        aria-label="Seitenleiste umschalten"
      >
        <ChevronLeft
          size={16}
          className={cn('transition-transform', collapsed && 'rotate-180')}
        />
      </button>

      <div className="ml-auto flex items-center gap-2">
        <button
          onClick={toggle}
          className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-alt text-body"
          aria-label="Design umschalten"
        >
          {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
        </button>

        <button
          className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-alt text-body"
          aria-label="Benachrichtigungen"
        >
          <Bell size={15} />
        </button>
      </div>
    </header>
  )
}
