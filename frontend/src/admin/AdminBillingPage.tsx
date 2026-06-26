import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, CreditCard, RefreshCw, ShieldCheck } from 'lucide-react'
import { useState } from 'react'

import { billingStatusLabel, fmtCents } from '../lib/dashApi'
import { apiFetch } from '../lib/adminApi'
import { cn } from '../lib/utils'

interface Overview {
  total_orgs: number
  by_status: Record<string, number>
  delinquent_count: number
  unlinked_orgs: number
  mrr_estimate_cents: number
  revenue_ytd_cents: number
  currency: string
}
interface OrgBilling {
  org_id: string
  org_name: string | null
  stripe_customer_id: string | null
  billing_status: string | null
  billing_plan_title: string | null
  is_legacy: boolean
  quota_minutes: number | null
  period_end: string | null
  last_sync_at: string | null
}
interface Health {
  configured: boolean
  charges_enabled: boolean | null
  payouts_enabled: boolean | null
  default_currency: string | null
  requirements_past_due: string[]
  requirements_currently_due: string[]
  disabled_reason: string | null
}
interface Match {
  id: string
  org_id: string
  org_name: string | null
  stripe_customer_id: string | null
  match_method: string | null
  match_confidence: number | null
  candidate: Record<string, unknown> | null
  status: string
}

const fmtDate = (s: string | null) =>
  s ? new Date(s).toLocaleDateString('de-DE', { year: 'numeric', month: '2-digit', day: '2-digit', timeZone: 'Europe/Berlin' }) : '—'

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: 'warn' | 'ok' }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{label}</div>
      <div className={cn('mt-1 text-2xl font-bold', tone === 'warn' ? 'text-red-400' : tone === 'ok' ? 'text-emerald-400' : 'text-slate-100')}>
        {value}
      </div>
    </div>
  )
}

export function AdminBillingPage() {
  const qc = useQueryClient()
  const [toast, setToast] = useState<string | null>(null)
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(null), 3500) }

  const overviewQ = useQuery({ queryKey: ['admin', 'billing', 'overview'], queryFn: () => apiFetch<Overview>('/api/super-admin/billing/overview'), retry: false })
  const healthQ = useQuery({ queryKey: ['admin', 'billing', 'health'], queryFn: () => apiFetch<Health>('/api/super-admin/billing/stripe-health'), retry: false })
  const orgsQ = useQuery({ queryKey: ['admin', 'billing', 'orgs'], queryFn: () => apiFetch<OrgBilling[]>('/api/super-admin/billing/orgs?limit=500'), retry: false })
  const matchesQ = useQuery({ queryKey: ['admin', 'billing', 'matches'], queryFn: () => apiFetch<Match[]>('/api/super-admin/billing/migration-matches'), retry: false })

  const runMatcher = useMutation({
    mutationFn: () => apiFetch<{ proposals_created: number; orgs_scanned: number }>('/api/super-admin/billing/run-matcher', { method: 'POST' }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ['admin', 'billing', 'matches'] }); flash(`${r.proposals_created} Vorschläge aus ${r.orgs_scanned} Orgs erstellt.`) },
    onError: (e: Error) => flash(e.message),
  })
  const approveMatch = useMutation({
    mutationFn: (id: string) => apiFetch(`/api/super-admin/billing/matches/${id}/approve`, { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'billing', 'matches'] })
      qc.invalidateQueries({ queryKey: ['admin', 'billing', 'orgs'] })
      flash('Verknüpfung freigegeben — heykiki_org_id in Stripe geschrieben.')
    },
    onError: (e: Error) => flash(e.message),
  })
  const rejectMatch = useMutation({
    mutationFn: (id: string) => apiFetch(`/api/super-admin/billing/matches/${id}/reject`, { method: 'POST' }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin', 'billing', 'matches'] }); flash('Vorschlag abgelehnt.') },
    onError: (e: Error) => flash(e.message),
  })

  const ov = overviewQ.data
  const health = healthQ.data
  const cur = ov?.currency ?? 'eur'
  const disabledByGate = (overviewQ.error as Error | null)?.message?.includes('404')

  return (
    <div className="space-y-6">
      <header>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-100"><CreditCard size={20} className="text-amber-400" /> Abrechnung</h1>
          <p className="mt-0.5 text-sm text-slate-400">Stripe-Zustand über alle Organisationen — Lesemodus (Phase 1).</p>
        </header>

        {toast && <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm font-medium text-amber-300">{toast}</div>}

        {disabledByGate && (
          <div className="rounded-xl border border-slate-700 bg-slate-900 p-4 text-sm text-slate-300">
            Das Billing-Modul ist derzeit deaktiviert (<code className="text-amber-300">STRIPE_BILLING_ENABLED=0</code>). Aktivieren, um Live-Daten zu sehen.
          </div>
        )}

        {/* Overview */}
        {ov && (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
            <Stat label="Organisationen" value={ov.total_orgs} />
            <Stat label="Im Verzug" value={ov.delinquent_count} tone={ov.delinquent_count ? 'warn' : undefined} />
            <Stat label="Nicht verknüpft" value={ov.unlinked_orgs} tone={ov.unlinked_orgs ? 'warn' : undefined} />
            <Stat label="Wiederkehrender Umsatz (geschätzt)" value={fmtCents(ov.mrr_estimate_cents, cur)} />
            <Stat label="Umsatz lfd. Jahr" value={fmtCents(ov.revenue_ytd_cents, cur)} />
            <Stat label="Aktiv" value={ov.by_status['active'] ?? 0} tone="ok" />
          </div>
        )}

        {/* Stripe account health */}
        {health?.configured && (
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
            <div className="mb-2 flex items-center gap-2 text-sm font-bold text-slate-200"><ShieldCheck size={15} className="text-amber-400" /> Stripe-Kontozustand</div>
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-slate-300">
              <span>Zahlungen: <span className={health.charges_enabled ? 'text-emerald-400' : 'text-red-400'}>{health.charges_enabled ? 'aktiv' : 'inaktiv'}</span></span>
              <span>Auszahlungen: <span className={health.payouts_enabled ? 'text-emerald-400' : 'text-red-400'}>{health.payouts_enabled ? 'aktiv' : 'inaktiv'}</span></span>
              <span>Währung: <span className="uppercase text-slate-200">{health.default_currency ?? '—'}</span></span>
            </div>
            {health.requirements_past_due.length > 0 && (
              <div className="mt-3 flex items-start gap-2 rounded-md border border-red-900/60 bg-red-950/40 p-3 text-sm text-red-300">
                <AlertTriangle size={15} className="mt-0.5 shrink-0" />
                <div>
                  <div className="font-semibold">Überfällige Stripe-Anforderungen:</div>
                  <ul className="mt-1 list-inside list-disc font-mono text-xs">
                    {health.requirements_past_due.map((r) => <li key={r}>{r}</li>)}
                  </ul>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Migration matches (dry-run review queue) */}
        <div className="rounded-xl border border-slate-800 bg-slate-900">
          <div className="flex items-center justify-between gap-3 border-b border-slate-800 px-4 py-3">
            <div className="text-sm font-bold text-slate-200">Kunden-Verknüpfung — Vorschläge ({matchesQ.data?.length ?? 0})</div>
            <button
              onClick={() => runMatcher.mutate()}
              disabled={runMatcher.isPending}
              className="flex items-center gap-2 rounded-md bg-amber-500 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-amber-400 disabled:opacity-50"
            >
              <RefreshCw size={13} className={runMatcher.isPending ? 'animate-spin' : ''} /> Probelauf starten
            </button>
          </div>
          <div className="overflow-x-auto">
          <table className="w-full min-w-[48rem] text-sm">
            <thead className="text-left text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-4 py-2">Organisation</th>
                <th className="px-4 py-2">Methode</th>
                <th className="px-4 py-2 text-right">Konfidenz</th>
                <th className="px-4 py-2">Stripe-Kunde</th>
                <th className="px-4 py-2 text-right">Aufgabe</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {(matchesQ.data ?? []).map((m) => (
                <tr key={m.id} className="hover:bg-slate-800/40">
                  <td className="px-4 py-2 text-slate-100">{m.org_name ?? m.org_id}</td>
                  <td className="px-4 py-2 text-slate-300">{m.match_method ?? '—'}</td>
                  <td className="px-4 py-2 text-right font-mono text-slate-300">{m.match_confidence != null ? `${Math.round(m.match_confidence * 100)}%` : '—'}</td>
                  <td className="px-4 py-2">
                    <div className="text-slate-300">{(m.candidate?.name as string) ?? '—'}</div>
                    <div className="font-mono text-[11px] text-slate-500">{m.stripe_customer_id ?? 'kein Treffer'}</div>
                  </td>
                  <td className="px-4 py-2 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        onClick={() => approveMatch.mutate(m.id)}
                        disabled={approveMatch.isPending || !m.stripe_customer_id || m.status !== 'proposed'}
                        title={m.stripe_customer_id ? 'Verknüpfen + heykiki_org_id zu Stripe schreiben' : 'Kein Treffer zum Freigeben'}
                        className="rounded-md bg-amber-500 px-2 py-1 text-xs font-semibold text-slate-950 hover:bg-amber-400 disabled:opacity-40"
                      >
                        Freigeben
                      </button>
                      <button
                        onClick={() => rejectMatch.mutate(m.id)}
                        disabled={rejectMatch.isPending || m.status !== 'proposed'}
                        className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40"
                      >
                        Ablehnen
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {(matchesQ.data?.length ?? 0) === 0 && (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-500">Keine Vorschläge — „Probelauf starten“ testet den Abgleich (kein Schreibzugriff auf Stripe).</td></tr>
              )}
            </tbody>
          </table>
          </div>
        </div>

        {/* Per-org billing state */}
        <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900">
          <div className="border-b border-slate-800 px-4 py-3 text-sm font-bold text-slate-200">Organisationen — Abrechnungsstatus</div>
          <table className="w-full min-w-[48rem] text-sm">
            <thead className="text-left text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-4 py-2">Organisation</th>
                <th className="px-4 py-2">Tarif</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2 text-right">Kontingent</th>
                <th className="px-4 py-2">Periode bis</th>
                <th className="px-4 py-2">Abgleich</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {(orgsQ.data ?? []).map((o) => (
                <tr key={o.org_id} className="hover:bg-slate-800/40">
                  <td className="px-4 py-2">
                    <div className="text-slate-100">{o.org_name ?? '—'}</div>
                    {o.is_legacy && <span className="rounded-full bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber-300">Bestandskunden (ChatDash)</span>}
                  </td>
                  <td className="px-4 py-2 text-slate-300">{o.billing_plan_title ?? '—'}</td>
                  <td className="px-4 py-2">
                    <span className={cn('text-sm', o.billing_status === 'past_due' || o.billing_status === 'unpaid' ? 'text-red-400' : 'text-slate-300')}>
                      {billingStatusLabel(o.billing_status)}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-slate-300">{o.quota_minutes ?? '—'}</td>
                  <td className="px-4 py-2 text-slate-400">{fmtDate(o.period_end)}</td>
                  <td className="px-4 py-2 text-slate-500">{o.stripe_customer_id ? <CheckCircle2 size={14} className="text-emerald-500" /> : '—'}</td>
                </tr>
              ))}
              {(orgsQ.data?.length ?? 0) === 0 && (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-500">Keine Organisationen.</td></tr>
              )}
            </tbody>
          </table>
        </div>
    </div>
  )
}
