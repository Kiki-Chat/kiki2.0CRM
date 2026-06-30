import { useEffect, useMemo, useState } from 'react'

// Lightweight country-code phone input (no extra dependency). Curated list covers
// DACH + common EU/intl. Auto-detects the country from the browser locale, shows
// the flag, and emits a combined E.164 string + validity to the parent.
interface Country {
  code: string // ISO-3166 alpha-2
  dial: string // E.164 country calling code, incl. '+'
  name: string
}

const COUNTRIES: Country[] = [
  { code: 'DE', dial: '+49', name: 'Deutschland' },
  { code: 'AT', dial: '+43', name: 'Österreich' },
  { code: 'CH', dial: '+41', name: 'Schweiz' },
  { code: 'NL', dial: '+31', name: 'Niederlande' },
  { code: 'BE', dial: '+32', name: 'Belgien' },
  { code: 'FR', dial: '+33', name: 'Frankreich' },
  { code: 'IT', dial: '+39', name: 'Italien' },
  { code: 'ES', dial: '+34', name: 'Spanien' },
  { code: 'PL', dial: '+48', name: 'Polen' },
  { code: 'GB', dial: '+44', name: 'Großbritannien' },
  { code: 'US', dial: '+1', name: 'USA' },
  { code: 'TR', dial: '+90', name: 'Türkei' },
]

function flagEmoji(code: string): string {
  return code
    .toUpperCase()
    .replace(/./g, (ch) => String.fromCodePoint(127397 + ch.charCodeAt(0)))
}

function detectCountry(): Country {
  const region = (navigator.language?.split('-')[1] || 'DE').toUpperCase()
  return COUNTRIES.find((c) => c.code === region) || COUNTRIES[0]
}

export function PhoneField({
  onChange,
}: {
  onChange: (value: { e164: string; valid: boolean }) => void
}) {
  const [country, setCountry] = useState<Country>(() => detectCountry())
  const [national, setNational] = useState('')

  const e164 = useMemo(() => {
    const digits = national.replace(/[^\d]/g, '').replace(/^0+/, '') // drop spaces + leading 0
    return digits ? `${country.dial}${digits}` : ''
  }, [country, national])

  // Valid: a plausible E.164 (calling code + 4–14 national digits).
  const valid = useMemo(() => {
    const nat = national.replace(/[^\d]/g, '').replace(/^0+/, '')
    return nat.length >= 4 && nat.length <= 14
  }, [national])

  useEffect(() => {
    onChange({ e164, valid })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [e164, valid])

  return (
    <div className="flex gap-2">
      <div className="relative">
        <select
          value={country.code}
          onChange={(e) => setCountry(COUNTRIES.find((c) => c.code === e.target.value) || COUNTRIES[0])}
          className="h-full appearance-none rounded-md border border-border bg-alt py-2.5 pl-3 pr-8 text-sm text-text outline-none focus:border-green-primary"
          aria-label="Ländervorwahl"
        >
          {COUNTRIES.map((c) => (
            <option key={c.code} value={c.code}>
              {flagEmoji(c.code)} {c.dial}
            </option>
          ))}
        </select>
      </div>
      <input
        type="tel"
        inputMode="tel"
        value={national}
        onChange={(e) => setNational(e.target.value)}
        placeholder="151 23456789"
        className="w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary"
      />
    </div>
  )
}
