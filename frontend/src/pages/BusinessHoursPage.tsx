import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Clock, Coffee, Copy, Info } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { apiFetch } from '../lib/api'
import { cn } from '../lib/utils'

interface DayHours {
  open: boolean
  start: string
  end: string
  break_start: string | null
  break_end: string | null
}
type Hours = Record<string, DayHours>

const DAYS: { key: string; label: string }[] = [
  { key: 'monday', label: 'Montag' },
  { key: 'tuesday', label: 'Dienstag' },
  { key: 'wednesday', label: 'Mittwoch' },
  { key: 'thursday', label: 'Donnerstag' },
  { key: 'friday', label: 'Freitag' },
  { key: 'saturday', label: 'Samstag' },
  { key: 'sunday', label: 'Sonntag' },
]

const day = (over: Partial<DayHours> = {}): DayHours => ({
  open: false,
  start: '08:00',
  end: '17:00',
  break_start: null,
  break_end: null,
  ...over,
})

const PRESETS: { key: string; label: string; build: () => Hours }[] = [
  {
    key: 'standard',
    label: 'Standard (Mo–Fr 8–17)',
    build: () => mk((i) => day({ open: i < 5 })),
  },
  {
    key: 'lunch',
    label: 'Mit Mittagspause',
    build: () => mk((i) => day({ open: i < 5, break_start: '12:00', break_end: '13:00' })),
  },
  {
    key: 'fulltime',
    label: 'Vollzeit (inkl. Samstag)',
    build: () => mk((i) => day({ open: i < 6 })),
  },
  {
    key: 'parttime',
    label: 'Teilzeit (Mo–Fr 8–13)',
    build: () => mk((i) => day({ open: i < 5, end: '13:00' })),
  },
]

function mk(fn: (i: number) => DayHours): Hours {
  const out: Hours = {}
  DAYS.forEach((d, i) => (out[d.key] = fn(i)))
  return out
}

export function BusinessHoursPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [hours, setHours] = useState<Hours>(() => mk((i) => day({ open: i < 5 })))
  const [saved, setSaved] = useState(false)

  const { data } = useQuery({
    queryKey: ['calendar-settings'],
    queryFn: () => apiFetch<{ business_hours: Hours }>('/api/calendar/settings'),
  })
  useEffect(() => {
    if (data?.business_hours) setHours(data.business_hours)
  }, [data])

  const save = useMutation({
    mutationFn: () =>
      apiFetch('/api/calendar/business-hours', {
        method: 'PUT',
        body: JSON.stringify({ business_hours: hours }),
      }),
    onSuccess: () => {
      setSaved(true)
      qc.invalidateQueries({ queryKey: ['calendar-settings'] })
      setTimeout(() => setSaved(false), 3000)
    },
  })

  const update = (key: string, patch: Partial<DayHours>) =>
    setHours((h) => ({ ...h, [key]: { ...h[key], ...patch } }))

  const toggleBreak = (key: string) => {
    const d = hours[key]
    if (d.break_start) update(key, { break_start: null, break_end: null })
    else update(key, { break_start: '12:00', break_end: '13:00' })
  }

  const copyToWeekdays = (key: string) => {
    const src = hours[key]
    setHours((h) => {
      const next = { ...h }
      DAYS.slice(0, 5).forEach((d) => {
        next[d.key] = { ...next[d.key], start: src.start, end: src.end, break_start: src.break_start, break_end: src.break_end }
      })
      return next
    })
  }

  return (
    <div className="mx-auto max-w-3xl p-8">
      <div className="mb-6 flex items-center gap-3">
        <button onClick={() => navigate('/calendar')} className="rounded-md p-1.5 text-muted hover:bg-alt">
          <ArrowLeft size={20} />
        </button>
        <Clock size={26} className="text-green-primary" />
        <h1 className="text-2xl font-bold text-text">Geschäftszeiten</h1>
      </div>

      <div className="mb-6 flex gap-3 rounded-lg border border-info/30 bg-info-bg px-4 py-3 text-sm text-info">
        <Info size={18} className="mt-0.5 shrink-0" />
        <div>
          Diese Zeiten werden verwendet für:
          <ul className="ml-4 mt-1 list-disc">
            <li>Terminbuchungen im Kalender</li>
            <li>Terminvorschläge der KI an Kunden</li>
          </ul>
          <span className="mt-1 block">Änderungen werden automatisch mit der KI synchronisiert.</span>
        </div>
      </div>

      <div className="mb-5">
        <div className="mb-2 text-sm font-semibold text-body">Schnellauswahl:</div>
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((p) => (
            <button
              key={p.key}
              onClick={() => setHours(p.build())}
              className="rounded-md border border-border bg-surface px-3 py-1.5 text-sm font-medium text-body hover:bg-alt"
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <div className="divide-y divide-border rounded-xl border border-border bg-surface">
        {DAYS.map((d) => {
          const h = hours[d.key]
          return (
            <div key={d.key} className="px-5 py-4">
              <div className="flex flex-wrap items-center gap-3">
                <Switch checked={h.open} onChange={(v) => update(d.key, { open: v })} />
                <span className={cn('w-28 font-semibold', h.open ? 'text-text' : 'text-muted')}>{d.label}</span>
                {h.open ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <TimeInput value={h.start} onChange={(v) => update(d.key, { start: v })} />
                    <span className="text-muted">–</span>
                    <TimeInput value={h.end} onChange={(v) => update(d.key, { end: v })} />
                    <button
                      onClick={() => toggleBreak(d.key)}
                      className={cn(
                        'inline-flex items-center gap-1.5 rounded-md border px-2.5 py-2 text-sm font-medium',
                        h.break_start
                          ? 'border-warning/40 bg-warning-bg text-warning'
                          : 'border-border text-muted hover:bg-alt',
                      )}
                    >
                      <Coffee size={14} /> Pause
                    </button>
                    <button
                      onClick={() => copyToWeekdays(d.key)}
                      title="Zeiten auf alle Wochentage übertragen"
                      className="ml-auto rounded-md p-2 text-muted hover:bg-alt"
                    >
                      <Copy size={15} />
                    </button>
                  </div>
                ) : (
                  <span className="text-sm text-muted">Geschlossen</span>
                )}
              </div>
              {h.open && h.break_start && (
                <div className="mt-3 flex items-center gap-2 pl-[3.25rem]">
                  <Coffee size={14} className="text-warning" />
                  <span className="text-sm text-body">Pause:</span>
                  <TimeInput value={h.break_start} onChange={(v) => update(d.key, { break_start: v })} amber />
                  <span className="text-muted">–</span>
                  <TimeInput value={h.break_end ?? '13:00'} onChange={(v) => update(d.key, { break_end: v })} amber />
                </div>
              )}
            </div>
          )
        })}
      </div>

      <p className="mt-3 text-sm text-muted">
        <strong>Tipp:</strong> Klicke auf „Pause", um eine Mittagspause für den Tag zu aktivieren. Mit dem
        Kopier-Symbol überträgst du die Zeiten auf alle Wochentage.
      </p>

      <div className="mt-6 flex items-center gap-3">
        <button
          onClick={() => save.mutate()}
          disabled={save.isPending}
          className="rounded-md bg-green-primary px-6 py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
        >
          {save.isPending ? 'Speichert…' : 'Speichern'}
        </button>
        {saved && <span className="text-sm font-medium text-green-deep">Gespeichert ✓</span>}
      </div>
    </div>
  )
}

function Switch({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!checked)}
      className={cn(
        'relative h-6 w-11 shrink-0 rounded-full transition-colors',
        checked ? 'bg-green-primary' : 'bg-border',
      )}
    >
      <span
        className={cn(
          'absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform',
          checked ? 'left-0.5 translate-x-5' : 'left-0.5',
        )}
      />
    </button>
  )
}

function TimeInput({
  value,
  onChange,
  amber,
}: {
  value: string
  onChange: (v: string) => void
  amber?: boolean
}) {
  return (
    <input
      type="time"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={cn(
        'rounded-md border px-2.5 py-2 text-sm text-text outline-none focus:border-green-primary',
        amber ? 'border-warning/40 bg-warning-bg' : 'border-border bg-alt',
      )}
    />
  )
}
