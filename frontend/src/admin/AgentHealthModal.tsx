/**
 * AgentHealthModal — per-org agent health detail modal.
 * Calls GET /api/super-admin/orgs/{id}/agent-health on open.
 * Shows each check (name, ok, detail) so admin can diagnose misconfigs.
 */
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, X } from 'lucide-react'

import { apiFetch } from '../lib/adminApi'
import { cn } from '../lib/utils'

interface AgentHealthDetail {
  ok: boolean
  provisioned_at: string | null
  checks: Array<{
    name: string
    ok: boolean
    detail: string
  }>
}

const CHECK_LABELS: Record<string, string> = {
  hk_tools_attached: 'Tools angehängt',
  webhook_url_is_prod: 'Webhook-URL (Prod)',
  webhook_enabled: 'Webhook aktiv',
  audio_event_present: 'Audio-Event',
  prompt_rendered: 'Prompt gerendert',
  override_flags_on: 'Override-Flags',
  phone_bound: 'Telefonnummer',
}

const fmtDate = (s: string | null) =>
  s
    ? new Date(s).toLocaleString('de-DE', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        timeZone: 'Europe/Berlin',
      })
    : '—'

interface Props {
  orgId: string
  orgName: string | null
  onClose: () => void
}

export function AgentHealthModal({ orgId, orgName, onClose }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['admin', 'agent-health', orgId],
    queryFn: () =>
      apiFetch<AgentHealthDetail>(`/api/super-admin/orgs/${orgId}/agent-health`),
    staleTime: 30 * 1000,
  })

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg space-y-4 rounded-xl border border-slate-700 bg-slate-900 p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-bold text-slate-100">
              Agent-Zustand —{' '}
              <span className="text-amber-300">{orgName ?? orgId}</span>
            </h2>
            {data && (
              <p className="mt-0.5 text-xs text-slate-500">
                Provisioniert:{' '}
                <span className="text-slate-400">
                  {fmtDate(data.provisioned_at)}
                </span>
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-100"
          >
            <X size={16} />
          </button>
        </div>

        {/* Overall badge */}
        {data && (
          <div
            className={cn(
              'flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold',
              data.ok
                ? 'bg-emerald-950/60 text-emerald-300 ring-1 ring-emerald-900/60'
                : 'bg-red-950/60 text-red-300 ring-1 ring-red-900/60',
            )}
          >
            {data.ok ? (
              <CheckCircle2 size={15} />
            ) : (
              <AlertTriangle size={15} />
            )}
            {data.ok
              ? 'Alle Checks bestanden'
              : `${data.checks.filter((c) => !c.ok).length} Problem${data.checks.filter((c) => !c.ok).length === 1 ? '' : 'e'} gefunden`}
          </div>
        )}

        {/* Loading */}
        {isLoading && (
          <div className="py-8 text-center text-sm text-slate-400">Wird geladen…</div>
        )}

        {/* Error */}
        {error && (
          <div className="rounded-md border border-red-900/60 bg-red-950/40 p-3 text-sm text-red-300">
            {(error as Error).message}
          </div>
        )}

        {/* Checks list */}
        {data && (
          <div className="divide-y divide-slate-800 overflow-hidden rounded-lg border border-slate-800">
            {data.checks.map((c) => (
              <div
                key={c.name}
                className="flex items-start gap-3 px-4 py-3 hover:bg-slate-800/30"
              >
                <div className="mt-0.5 shrink-0">
                  {c.ok ? (
                    <CheckCircle2 size={15} className="text-emerald-400" />
                  ) : (
                    <AlertTriangle size={15} className="text-red-400" />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div
                    className={cn(
                      'text-sm font-medium',
                      c.ok ? 'text-slate-200' : 'text-red-300',
                    )}
                  >
                    {CHECK_LABELS[c.name] ?? c.name}
                  </div>
                  <div className="mt-0.5 text-xs text-slate-400">{c.detail}</div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Close button */}
        <div className="flex justify-end pt-1">
          <button
            onClick={onClose}
            className="rounded-md border border-slate-700 bg-slate-800 px-4 py-2 text-sm font-medium text-slate-200 hover:bg-slate-700"
          >
            Schließen
          </button>
        </div>
      </div>
    </div>
  )
}
