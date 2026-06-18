// Centralised date/time formatting — ALWAYS rendered in Europe/Berlin, regardless
// of the viewer's browser timezone. The backend stores every timestamp as UTC
// (timestamptz / ISO-8601 with offset); without pinning the zone here, toLocale*
// would render in the browser's local tz, so a tester outside Germany saw shifted
// times (the reported "call log timestamps are not in Berlin time" bug).
//
// Use these everywhere a server timestamp is shown. (Durations/relative spans are
// tz-independent.)

export const BERLIN_TZ = 'Europe/Berlin'

// "08. Jun, 14:30" — compact day+time (call list, action rows).
export const fmtTime = (iso: string | null): string =>
  iso
    ? new Date(iso).toLocaleString('de-DE', {
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
        timeZone: BERLIN_TZ,
      })
    : '—'

// "14:30" — time only (the day is implied by the call-log group header).
export const fmtClock = (iso: string | null): string =>
  iso
    ? new Date(iso).toLocaleTimeString('de-DE', {
        hour: '2-digit',
        minute: '2-digit',
        timeZone: BERLIN_TZ,
      })
    : '—'

// "14:30 Uhr" — time only with the German "Uhr" suffix so it reads unmistakably
// as a clock time (call-log Uhrzeit column). Falls back to "—" when there's no value.
export const fmtClockUhr = (iso: string | null): string => {
  const t = fmtClock(iso)
  return t === '—' ? t : `${t} Uhr`
}

// "08.06.2026" — date only.
export const fmtDate = (iso: string | null): string =>
  iso
    ? new Date(iso).toLocaleDateString('de-DE', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        timeZone: BERLIN_TZ,
      })
    : '—'

// "08.06.2026, 14:30" — full date + time.
export const fmtDateTime = (iso: string | null): string =>
  iso
    ? new Date(iso).toLocaleString('de-DE', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        timeZone: BERLIN_TZ,
      })
    : '—'

// Tight German relative-time for timelines; falls back to absolute (Berlin) past a week.
export function relativeTimeDe(iso: string): string {
  const now = Date.now()
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const diffSec = Math.max(0, Math.round((now - then) / 1000))
  if (diffSec < 60) return 'gerade eben'
  const min = Math.round(diffSec / 60)
  if (min < 60) return `vor ${min} Min`
  const hours = Math.round(min / 60)
  if (hours < 24) return `vor ${hours} Std`
  const days = Math.round(hours / 24)
  if (days < 7) return `vor ${days} ${days === 1 ? 'Tag' : 'Tagen'}`
  return new Date(iso).toLocaleDateString('de-DE', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    timeZone: BERLIN_TZ,
  })
}

export function absoluteTimeDe(iso: string): string {
  return new Date(iso).toLocaleString('de-DE', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: BERLIN_TZ,
  })
}
