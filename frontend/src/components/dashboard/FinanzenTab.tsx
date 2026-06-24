import { useQuery } from '@tanstack/react-query'
import { ArrowRight, BadgeEuro, Euro, FileText, Receipt } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { apiFetch } from '../../lib/api'
import { type FinanzenData, fmtEur, invoiceStatusLabel, invoiceStatusVariant } from '../../lib/dashApi'
import { cn, initials } from '../../lib/utils'
import { Tag } from '../ui/Tag'
import { CHART, DashError, DashKpi, DashLoading, KpiRow, Panel, tooltipStyle, TrendBadge, usePeriodFilter } from './shared'

export function FinanzenTab() {
  const navigate = useNavigate()
  const { qs, queryKey, element } = usePeriodFilter()
  const { data, isLoading, error } = useQuery({
    queryKey: ['dash', 'finanzen', ...queryKey],
    queryFn: () => apiFetch<FinanzenData>(`/api/dashboard/finanzen${qs}`),
    staleTime: 5 * 60 * 1000,
  })
  if (isLoading) return <div className="space-y-5">{element}<DashLoading /></div>
  if (error || !data) return <div className="space-y-5">{element}<DashError msg={(error as Error)?.message} /></div>

  const k = data.kpis
  const pl = data.period_label

  return (
    <div className="space-y-5">
      {element}
      <KpiRow>
        <DashKpi label={`Umsatz (${pl})`} value={fmtEur(k.umsatz_month)} icon={Euro} trend={<TrendBadge delta={Math.round(k.umsatz_month - k.prev_umsatz)} unit="€" />} />
        <DashKpi label="Offene Rechnungen" value={k.open_invoices_count} sub={fmtEur(k.open_invoices_sum)} icon={Receipt} />
        <DashKpi label="Ausstehende Kostenvoranschläge" value={k.kvas_pending_count} sub={fmtEur(k.kvas_pending_sum)} icon={FileText} />
        <DashKpi label={`Bezahlt (${pl})`} value={fmtEur(k.paid_month)} icon={BadgeEuro} trend={<TrendBadge delta={Math.round(k.paid_month - k.prev_paid)} unit="€" />} />
      </KpiRow>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <Panel title="Umsatzentwicklung" className="lg:col-span-8">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data.revenue_series} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="revGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={CHART.green} stopOpacity={0.3} />
                    <stop offset="100%" stopColor={CHART.green} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: 'var(--muted)' }} tickLine={false} axisLine={false} />
                <YAxis tick={{ fontSize: 11, fill: 'var(--muted)' }} tickLine={false} axisLine={false} width={60} tickFormatter={(v) => `${v} €`} />
                <Tooltip contentStyle={tooltipStyle} formatter={(v) => [fmtEur(v as number), 'Umsatz']} />
                <Area type="monotone" dataKey="revenue" stroke={CHART.green} strokeWidth={2} fill="url(#revGrad)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel title="Top-Kunden" className="lg:col-span-4">
          {data.top_customers.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted">Noch keine Umsätze in diesem Zeitraum.</div>
          ) : (
            <div className="space-y-2">
              {data.top_customers.map((c) => (
                <button key={c.customer_id} onClick={() => navigate(`/customers/${c.customer_id}`)} className="flex w-full items-center gap-3 rounded-md px-1 py-1.5 text-left hover:bg-alt">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-green-tint-200 text-xs font-bold text-green-deep">{initials(c.customer_name || '?')}</div>
                  <span className="min-w-0 flex-1 truncate text-sm text-text">{c.customer_name || 'Unbekannt'}</span>
                  <span className="text-sm font-semibold text-text">{fmtEur(c.amount)}</span>
                </button>
              ))}
            </div>
          )}
        </Panel>
      </div>

      <Panel
        title="Letzte Rechnungen"
        action={
          <button onClick={() => navigate('/invoices')} className="flex items-center gap-1 text-sm font-medium text-green-deep hover:underline">
            Alle Rechnungen <ArrowRight size={14} />
          </button>
        }
      >
        {data.recent_invoices.length === 0 ? (
          <div className="py-8 text-center text-sm text-muted">Noch keine Rechnungen.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-muted">
                <tr>
                  <th className="pb-2 font-semibold">Nummer</th>
                  <th className="pb-2 font-semibold">Kunde</th>
                  <th className="pb-2 font-semibold">Status</th>
                  <th className="pb-2 text-right font-semibold">Betrag</th>
                  <th className="pb-2 text-right font-semibold">Fällig</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_invoices.map((i) => (
                  <tr key={i.id} onClick={() => navigate(`/invoices/${i.id}`)} className={cn('cursor-pointer border-t border-border hover:bg-alt')}>
                    <td className="py-2.5 font-medium text-text">{i.number || '—'}</td>
                    <td className="py-2.5 text-body">{i.customer_name || '—'}</td>
                    <td className="py-2.5"><Tag variant={invoiceStatusVariant(i.status)}>{invoiceStatusLabel(i.status)}</Tag></td>
                    <td className="py-2.5 text-right font-semibold text-text">{fmtEur(i.total)}</td>
                    <td className="py-2.5 text-right text-muted">{i.due_date ? new Date(i.due_date).toLocaleDateString('de-DE', { timeZone: 'Europe/Berlin' }) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  )
}
