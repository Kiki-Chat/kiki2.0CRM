import { Bell, ChevronLeft, Menu, Moon, Sparkles, Sun } from 'lucide-react'

import { useTheme } from '../../lib/theme'
import { cn } from '../../lib/utils'

export function Topbar({
  collapsed,
  onToggleCollapse,
  onOpenNav,
  copilotOpen,
  onToggleCopilot,
}: {
  collapsed: boolean
  onToggleCollapse: () => void
  onOpenNav?: () => void
  /** "Hey Kiki" side-panel toggle — undefined when the copilot is disabled. */
  copilotOpen?: boolean
  onToggleCopilot?: () => void
}) {
  const { theme, toggle } = useTheme()

  return (
    <header className="sticky top-0 z-10 flex h-14 items-center gap-3.5 border-b border-border bg-sidebar px-5 sm:px-7 lg:px-8">
      {/* Mobile: open the nav drawer. */}
      <button
        onClick={onOpenNav}
        className="flex rounded-md p-1.5 text-muted hover:bg-alt md:hidden"
        aria-label="Menü öffnen"
      >
        <Menu size={18} />
      </button>
      {/* Desktop: collapse the rail. */}
      <button
        onClick={onToggleCollapse}
        className="hidden rounded-md p-1.5 text-muted hover:bg-alt md:inline-flex"
        aria-label="Seitenleiste ein/aus"
      >
        <ChevronLeft
          size={16}
          className={cn('transition-transform', collapsed && 'rotate-180')}
        />
      </button>

      <div className="ml-auto flex items-center gap-2">
        {onToggleCopilot && (
          <button
            onClick={onToggleCopilot}
            className={cn(
              'flex h-8 items-center gap-1.5 rounded-md border px-3 text-sm font-semibold transition',
              copilotOpen
                ? 'border-ai/40 bg-ai-bg text-ai'
                : 'border-border bg-alt text-body hover:bg-ai-bg hover:text-ai',
            )}
            aria-label="Kiki-Assistent ein/aus"
            aria-pressed={copilotOpen}
            title="Hey Kiki — dein CRM-Assistent"
          >
            <Sparkles size={14} />
            Hey Kiki
          </button>
        )}

        <button
          onClick={toggle}
          className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-alt text-body"
          aria-label="Darstellung wechseln"
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
