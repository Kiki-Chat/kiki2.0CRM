import { Bell, ChevronLeft, Moon, Search, Sun } from 'lucide-react'

import { useLang, type Lang } from '../../lib/i18n'
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
  const { lang, setLang } = useLang()

  return (
    <header className="sticky top-0 z-10 flex h-14 items-center gap-3.5 border-b border-border bg-sidebar px-7">
      <button
        onClick={onToggleCollapse}
        className="flex rounded-md p-1.5 text-muted hover:bg-alt"
        aria-label="Toggle sidebar"
      >
        <ChevronLeft
          size={16}
          className={cn('transition-transform', collapsed && 'rotate-180')}
        />
      </button>

      <div className="relative max-w-md flex-1">
        <Search
          size={14}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-faint"
        />
        <input
          placeholder={
            lang === 'de' ? 'Kunden, Anrufe, Aufträge suchen…' : 'Search customers, calls…'
          }
          className="w-full rounded-md border border-border bg-alt py-2 pl-9 pr-3 text-sm text-body outline-none focus:border-green-primary"
        />
      </div>

      <div className="ml-auto flex items-center gap-2">
        <div className="flex rounded-md border border-border bg-alt p-0.5">
          {(['EN', 'DE'] as const).map((l) => {
            const active = lang === (l.toLowerCase() as Lang)
            return (
              <button
                key={l}
                onClick={() => setLang(l.toLowerCase() as Lang)}
                className={cn(
                  'rounded px-2.5 py-1 text-xs font-bold transition-colors',
                  active ? 'bg-surface text-text' : 'text-muted',
                )}
              >
                {l}
              </button>
            )
          })}
        </div>

        <button
          onClick={toggle}
          className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-alt text-body"
          aria-label="Toggle theme"
        >
          {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
        </button>

        <button
          className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-alt text-body"
          aria-label="Notifications"
        >
          <Bell size={15} />
        </button>
      </div>
    </header>
  )
}
