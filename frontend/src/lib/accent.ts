// Accent theming: the org's accent_color overrides the brand-green CSS variables
// at runtime so every button / link / active state across the app reflects it.
// Tints are emitted as rgba(accent, α) so they read correctly in both light and
// dark themes; --green-deep is darkened for readable link/text contrast.

const DEFAULT_ACCENT = '#4a9b3f' // matches the base --green-primary in index.css

const clamp = (n: number) => Math.max(0, Math.min(255, Math.round(n)))

function parseHex(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  const f = h.length === 3 ? h.split('').map((c) => c + c).join('') : h
  return [parseInt(f.slice(0, 2), 16), parseInt(f.slice(2, 4), 16), parseInt(f.slice(4, 6), 16)]
}

export function isHexColor(s?: string | null): s is string {
  return !!s && /^#?[0-9a-fA-F]{6}$/.test(s.trim())
}

function darken(hex: string, ratio: number): string {
  const [r, g, b] = parseHex(hex)
  return `rgb(${clamp(r * (1 - ratio))}, ${clamp(g * (1 - ratio))}, ${clamp(b * (1 - ratio))})`
}

function rgba(hex: string, alpha: number): string {
  const [r, g, b] = parseHex(hex)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

/** Override the brand-green CSS variables on :root from an accent hex. */
export function applyAccent(input?: string | null): void {
  const hex = isHexColor(input)
    ? input.trim().startsWith('#') ? input.trim() : `#${input.trim()}`
    : DEFAULT_ACCENT
  const s = document.documentElement.style
  s.setProperty('--green-primary', hex)
  s.setProperty('--green-brand', hex)
  s.setProperty('--green-deep', darken(hex, 0.18))
  s.setProperty('--green-tint-50', rgba(hex, 0.08))
  s.setProperty('--green-tint-100', rgba(hex, 0.14))
  s.setProperty('--green-tint-200', rgba(hex, 0.24))
}
