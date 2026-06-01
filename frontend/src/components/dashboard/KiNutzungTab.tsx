import { useQuery } from '@tanstack/react-query'
import { Clock, Hourglass, Phone, Timer } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { apiFetch } from '../../lib/api'
import { fmtDur, type KiNutzungData } from '../../lib/dashApi'
import { cn, initials } from '../../lib/utils'
import { CHART, DashError, DashKpi, DashLoading, KpiRow, Panel, tooltipStyle, TrendBadge, usePeriodFilter } from './shared'

export function KiNutzungTab() {
  const navigate = useNavigate()
  const { qs, queryKey, element } = usePeriodFilter()
  const { data, isLoading, error } = useQuery({
    queryKey: ['dash', 'ki-nutzung', ...queryKey],
    queryFn: () => apiFetch<KiNutzungData>(`/api/dashboard/ki-nutzung${qs}`),
    staleTime: 5 * 60 * 1000,
  })

  if (isLoading) return <div className="space-y-5">{element}<DashLoading /></div>
  if (error || !data) return <div className="space-y-5">{element}<DashError msg={(error as Error)?.message} /></div>

  const k = data.kpis
  const quota = k.minutes_quota || 0
  // The contingent is MONTHLY → the quota bar always tracks the calendar month
  // (month_minutes_used), independent of the selected analytics window.
  const pct = quota ? Math.round((k.month_minutes_used / quota) * 100) : 0
  const barColor = !quota ? CHART.green : pct > 95 ? CHART.error : pct >= 70 ? CHART.warning : CHART.green
  const pl = data.period_label

  // Restlaufzeit label (always the MONTHLY contingent)
  const est = k.estimated_days_remaining
  let restLabel = 'Innerhalb des Kontingents'
  let restColor = 'text-success'
  if (k.over_quota) { restLabel = 'Quota überschritten'; restColor = 'text-error' }
  else if (est !== null && est < 30) {
    restLabel = `Reicht für ~${est} Tage`
    restColor = est <= 5 ? 'text-error' : est <= 10 ? 'text-warning' : 'text-success'
  }

  // cumulative consumption over the selected window
  let cum = 0
  const cumData = data.series.map((d) => { cum += d.minutes; return { label: d.label, cum, minutes: d.minutes, calls: d.calls } })

  return (
    <div className="space-y-5">
      {element}
      <KpiRow>
        <DashKpi
          label={`KI-Minuten verbraucht (${pl})`}
          value={`${k.minutes_used} Min`}
          icon={Clock}
          spark={data.series.map((d) => d.minutes)}
          sparkColor={barColor}
          trend={<TrendBadge delta={k.minutes_used - k.previous_minutes} unit="Min" goodWhenUp={false} />}
        >
          {quota > 0 && (
            <div className="mt-2">
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-alt">
                <div className="h-full rounded-full" style={{ width: `${Math.min(pct, 100)}%`, background: barColor }} />
              </div>
              <div className="mt-1 text-[11px] text-muted">{k.month_minutes_used} / {quota} Min · Monatskontingent</div>
            </div>
          )}
        </DashKpi>
        <DashKpi label={`Anrufe abgewickelt (${pl})`} value={k.calls_count} icon={Phone} spark={data.series.map((d) => d.calls)} trend={<TrendBadge delta={k.calls_count - k.previous_calls} />} />
        <DashKpi label="Durchschnittliche Anrufdauer" value={fmtDur(k.avg_duration_seconds)} icon={Timer} trend={<TrendBadge delta={k.avg_duration_seconds - k.previous_avg_duration} unit="Sek" goodWhenUp={false} />} />
        <DashKpi label="Geschätzte Restlaufzeit (Monat)" value={<span className={restColor}>{restLabel}</span>} icon={Hourglass} />
      </KpiRow>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <Panel title={`Verbrauchsverlauf (${pl})`} className="lg:col-span-8">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={cumData} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="kiCum" x1="0" y1="0" x2="0" y2="1">
                    <stop offset={0} stopColor={CHART.green} stopOpacity={0.3} />
                    <stop offset={1} stopColor={CHART.green} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: 'var(--muted)' }} tickLine={false} axisLine={false} />
                <YAxis tick={{ fontSize: 11, fill: 'var(--muted)' }} tickLine={false} axisLine={false} />
                <Tooltip contentStyle={tooltipStyle} formatter={(v, n) => (n === 'cum' ? [`${v} Min kumuliert`, 'Kumuliert'] : [v, n])} labelFormatter={(l) => `${data.series_x_label} ${l}`} />
                <Area type="monotone" dataKey="cum" stroke={CHART.green} strokeWidth={2} fill="url(#kiCum)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel title={`Top Anrufer (${pl})`} className="lg:col-span-4">
          {data.top_callers.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted">Keine Anrufe in diesem Zeitraum.</div>
          ) : (
            <div className="space-y-2">
              {data.top_callers.map((c) => (
                <button key={c.customer_id} onClick={() => navigate(`/customers/${c.customer_id}`)} className="flex w-full items-center gap-3 rounded-md px-1 py-1.5 text-left hover:bg-alt">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-green-tint-200 text-xs font-bold text-green-deep">{initials(c.customer_name || '?')}</div>
                  <div className="min-w-0 flex-1"><div className="truncate text-sm text-text">{c.customer_name || 'Unbekannt'}</div><div className="text-xs text-muted">{c.call_count} Anrufe</div></div>
                  <span className="text-sm font-semibold text-text">{c.total_minutes} Min</span>
                </button>
              ))}
            </div>
          )}
        </Panel>
      </div>

      <Panel title="Anrufe nach Tageszeit">
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data.calls_by_hour} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis dataKey="hour" tick={{ fontSize: 11, fill: 'var(--muted)' }} tickLine={false} axisLine={false} tickFormatter={(h) => `${h}`} />
              <YAxis tick={{ fontSize: 11, fill: 'var(--muted)' }} tickLine={false} axisLine={false} allowDecimals={false} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v, n) => [v, n === 'count' ? 'Anrufe' : 'Minuten']} labelFormatter={(h) => `${h}:00 Uhr`} />
              <Bar dataKey="count" stackId="a" fill={CHART.green} radius={[0, 0, 0, 0]} />
              <Bar dataKey="minutes" stackId="a" fill={CHART.ai} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Panel>

      <div className={cn('flex items-start gap-3 rounded-xl border border-border bg-alt p-4 text-sm text-muted')}>
        <Hourglass size={16} className="mt-0.5 shrink-0 text-faint" />
        <span>Für Änderungen am Kontingent oder Tarif wenden Sie sich bitte an <a href="mailto:support@heykiki.de" className="font-medium text-green-deep hover:underline">support@heykiki.de</a>. Detaillierte Abrechnungen erscheinen ab dem nächsten Update direkt hier.</span>
      </div>
    </div>
  )
}
