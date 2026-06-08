import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Clock, FileText, Receipt, Sparkles, UserX } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { apiFetch } from '../../lib/api'
import type { AiInsightsData } from '../../lib/dashApi'
import { cn } from '../../lib/utils'
import { DashError, DashKpi, DashLoading, KpiRow, Panel } from './shared'

const CATEGORY: Record<string, { icon: typeof FileText; color: string; bg: string; route: string }> = {
  kva_followup: { icon: FileText, color: 'text-info', bg: 'bg-info-bg', route: '/cost-estimates' },
  invoice_overdue: { icon: Receipt, color: 'text-error', bg: 'bg-error-bg', route: '/invoices' },
  inactive_customer: { icon: UserX, color: 'text-warning', bg: 'bg-warning-bg', route: '/customers' },
}

export function KiInsightsTab() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [toast, setToast] = useState<string | null>(null)
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(null), 3000) }

  const { data, isLoading, error } = useQuery({
    queryKey: ['dash', 'ai-insights'],
    queryFn: () => apiFetch<AiInsightsData>('/api/dashboard/ai-insights'),
    staleTime: 15 * 60 * 1000,
  })

  const act = useMutation({
    mutationFn: (body: { suggestion_key: string; action: 'done' | 'snooze'; snooze_days?: number }) =>
      apiFetch('/api/dashboard/ai-insights/action', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: (_r, body) => {
      qc.invalidateQueries({ queryKey: ['dash', 'ai-insights'] })
      flash(body.action === 'done' ? 'Als erledigt markiert.' : 'Für 3 Tage zurückgestellt.')
    },
  })

  if (isLoading) return <DashLoading />
  if (error || !data) return <DashError msg={(error as Error)?.message} />

  const k = data.kpis

  return (
    <div className="space-y-5">
      {toast && <div className="rounded-md bg-green-tint-50 px-3 py-2 text-sm font-medium text-green-deep">{toast}</div>}

      {!data.enabled && (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-warning/30 bg-warning-bg/40 px-4 py-3 text-sm text-body">
          <span className="flex items-center gap-2"><AlertTriangle size={16} className="text-warning" /> KI-Vorschläge sind deaktiviert.</span>
          <button onClick={() => navigate('/settings/ki-vorschlaege')} className="font-medium text-green-deep hover:underline">In den Einstellungen aktivieren</button>
        </div>
      )}

      <KpiRow>
        <DashKpi label="KI-Vorschläge offen" value={k.open_count} icon={Sparkles} />
        <DashKpi label="KVAs zum Nachfassen" value={k.kva_followup_count} icon={FileText} />
        <DashKpi label="Überfällige Rechnungen" value={k.overdue_invoices_count} icon={Receipt} />
        <DashKpi label="Inaktive Kunden" value={k.inactive_customers_count} icon={UserX} />
      </KpiRow>

      <Panel title="Aktionsempfehlungen">
        {data.suggestions.length === 0 ? (
          <div className="flex flex-col items-center gap-3 py-14 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-success-bg">
              <CheckCircle2 size={28} className="text-success" />
            </div>
            <div className="max-w-md space-y-1">
              <p className="text-base font-semibold text-text">Sie sind auf dem Laufenden!</p>
              <p className="text-sm text-muted">
                Keine offenen Vorschläge. Kiki prüft regelmäßig auf KVAs, die ein Nachfassen brauchen, überfällige Rechnungen und seit langem inaktive Kunden — sobald etwas zu tun ist, erscheint es hier.
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-2.5">
            {data.suggestions.map((s) => {
              const cat = CATEGORY[s.category] ?? CATEGORY.kva_followup
              const Icon = cat.icon
              return (
                <div key={s.id} className="flex items-start gap-3 rounded-lg border border-border p-3">
                  <div className={cn('flex h-9 w-9 shrink-0 items-center justify-center rounded-lg', cat.bg)}><Icon size={17} className={cat.color} /></div>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold text-text">{s.title}</div>
                    <div className="mt-0.5 flex items-center gap-2 text-xs text-muted">
                      <span>{s.subtitle}</span>
                      {s.created_at && <span className="flex items-center gap-1"><Clock size={11} /> {new Date(s.created_at).toLocaleDateString('de-DE', { timeZone: 'Europe/Berlin' })}</span>}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <button onClick={() => navigate(s.customer_id ? `/customers/${s.customer_id}` : cat.route)} className="rounded-md border border-border bg-surface px-3 py-1.5 text-xs font-medium text-body hover:bg-alt">Erinnerung senden</button>
                    <button onClick={() => act.mutate({ suggestion_key: s.id, action: 'done' })} className="rounded-md px-2.5 py-1.5 text-xs font-medium text-muted hover:bg-alt">Erledigt markieren</button>
                    <button onClick={() => act.mutate({ suggestion_key: s.id, action: 'snooze', snooze_days: 3 })} className="rounded-md px-2.5 py-1.5 text-xs font-medium text-muted hover:bg-alt">Snooze 3 Tage</button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </Panel>
    </div>
  )
}
