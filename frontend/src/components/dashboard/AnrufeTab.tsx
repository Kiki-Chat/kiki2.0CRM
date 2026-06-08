import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Phone, PhoneIncoming, PhoneMissed, PhoneOutgoing } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { apiFetch } from '../../lib/api'
import { type AnrufeData, fmtDur } from '../../lib/dashApi'
import { CHART, DashError, DashKpi, DashLoading, KpiRow, Panel, tooltipStyle, TrendBadge, usePeriodFilter } from './shared'

export function AnrufeTab() {
  const navigate = useNavigate()
  const { qs, queryKey, element } = usePeriodFilter()
  const { data, isLoading, error } = useQuery({
    queryKey: ['dash', 'anrufe', ...queryKey],
    queryFn: () => apiFetch<AnrufeData>(`/api/dashboard/anrufe${qs}`),
    staleTime: 5 * 60 * 1000,
  })
  if (isLoading) return <div className="space-y-5">{element}<DashLoading /></div>
  if (error || !data) return <div className="space-y-5">{element}<DashError msg={(error as Error)?.message} /></div>

  const k = data.kpis
  const vol = data.series
  const pl = data.period_label
  const bd = data.breakdown
  const bdTotal = bd.inbound + bd.outbound + bd.missed || 1
  const bdData = [
    { name: 'Eingehend', value: bd.inbound, color: CHART.green },
    { name: 'Ausgehend', value: bd.outbound, color: CHART.info },
    { name: 'Verpasst', value: bd.missed, color: CHART.error },
  ]

  return (
    <div className="space-y-5">
      {element}
      <KpiRow>
        <DashKpi label={`Gesamtanrufe (${pl})`} value={k.total_calls} icon={Phone} spark={vol.map((d) => d.count)} trend={<TrendBadge delta={k.total_calls - k.prev_total_calls} />} />
        <DashKpi label="Beantwortet" value={k.answered} sub={`${k.answer_rate}% Antwortrate`} icon={PhoneIncoming} trend={<TrendBadge delta={k.answered - k.prev_answered} />} />
        <DashKpi label="Durchschnittsdauer" value={fmtDur(k.avg_duration_seconds)} icon={Phone} trend={<TrendBadge delta={k.avg_duration_seconds - k.prev_avg_duration_seconds} unit="Sek" goodWhenUp={false} />} />
        <DashKpi label="Ausgehend" value={k.outbound} icon={PhoneOutgoing} trend={<TrendBadge delta={k.outbound - k.prev_outbound} />} />
      </KpiRow>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <Panel title={`Anrufvolumen (${pl})`} className="lg:col-span-8">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={vol} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: 'var(--muted)' }} tickLine={false} axisLine={false} />
                <YAxis tick={{ fontSize: 11, fill: 'var(--muted)' }} tickLine={false} axisLine={false} allowDecimals={false} />
                <Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${v} Anrufe`, '']} labelFormatter={(l) => `${data.series_x_label} ${l}`} />
                <Line type="monotone" dataKey="count" stroke={CHART.green} strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel title="Aufschlüsselung" className="lg:col-span-4">
          <div className="space-y-4 pt-2">
            {bdData.map((b) => (
              <div key={b.name}>
                <div className="mb-1 flex justify-between text-sm">
                  <span className="text-body">{b.name}</span>
                  <span className="font-semibold text-text">{b.value} · {Math.round((b.value / bdTotal) * 100)}%</span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-alt">
                  <div className="h-full rounded-full" style={{ width: `${(b.value / bdTotal) * 100}%`, background: b.color }} />
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <Panel
        title="Letzte Anrufe"
        action={
          <button onClick={() => navigate('/calls')} className="flex items-center gap-1 text-sm font-medium text-green-deep hover:underline">
            Alle Anrufe ansehen <ArrowRight size={14} />
          </button>
        }
      >
        {data.recent_calls.length === 0 ? (
          <div className="py-8 text-center text-sm text-muted">Keine Anrufe in diesem Zeitraum.</div>
        ) : (
          <div className="divide-y divide-border">
            {data.recent_calls.map((c) => {
              const Icon = c.direction === 'outbound' ? PhoneOutgoing : c.status === 'missed' ? PhoneMissed : PhoneIncoming
              return (
                <button key={c.id} onClick={() => navigate('/calls')} className="flex w-full items-center gap-3 rounded-md px-1 py-2.5 text-left hover:bg-alt">
                  <Icon size={16} className={c.status === 'missed' ? 'text-error' : 'text-green-deep'} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-text">{c.customer_name || 'Unbekannt'}</div>
                    <div className="text-xs text-muted">{c.started_at ? new Date(c.started_at).toLocaleString('de-DE', { timeZone: 'Europe/Berlin' }) : '—'}</div>
                  </div>
                  <span className="text-xs text-muted">{fmtDur(c.duration_seconds)}</span>
                </button>
              )
            })}
          </div>
        )}
      </Panel>
    </div>
  )
}
