import { useEffect, useState } from 'react'

/**
 * Subscribe to a CSS media query and re-render on change. SSR-safe (defaults to
 * false when `window` is absent). Used for JS-driven responsive switches that
 * can't be expressed with Tailwind classes alone (e.g. the Call-Logs cockpit
 * collapsing its 3 panes into single-pane navigation below the `lg` breakpoint).
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia(query).matches
      : false,
  )

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const mql = window.matchMedia(query)
    const onChange = () => setMatches(mql.matches)
    onChange()
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [query])

  return matches
}
