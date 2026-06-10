import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import { apiFetch } from '../../lib/api'
import { KZ } from '../../lib/kikiApi'

interface SyncStatus {
  status: 'idle' | 'pending' | 'applied' | 'failed'
  label: string | null
  error: string | null
  seq: number
  requested_at: string | null
  finished_at: string | null
}

const SUCCESS_VISIBLE_MS = 8_000

// Live "Einstellungen werden an Kiki übertragen" banner. Every Kiki-Zentrale
// save flips the backend sync state to 'pending' before the response returns;
// the existing ['kiki-zentrale'] invalidation in each mutation refetches this
// query immediately (prefix match), and while pending we poll until the
// ElevenLabs PATCH resolved to applied/failed.
export function AgentSyncBanner() {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['kiki-zentrale', 'sync-status'],
    queryFn: () => apiFetch<SyncStatus>(`${KZ}/sync-status`),
    refetchInterval: (q) => (q.state.data?.status === 'pending' ? 2_500 : false),
    // Keep polling while the tab is hidden — the user may tab away during the
    // ~minute-long ElevenLabs push and must still see the resolution on return.
    refetchIntervalInBackground: true,
  })

  // Show the green "applied" state only briefly after a fresh completion.
  const [showSuccess, setShowSuccess] = useState(false)
  useEffect(() => {
    if (data?.status !== 'applied' || !data.finished_at) return
    const age = Date.now() - new Date(data.finished_at).getTime()
    if (age > SUCCESS_VISIBLE_MS) return
    setShowSuccess(true)
    const t = setTimeout(() => setShowSuccess(false), SUCCESS_VISIBLE_MS - age)
    return () => clearTimeout(t)
  }, [data?.status, data?.finished_at])

  const retry = useMutation({
    mutationFn: () => apiFetch(`${KZ}/sync-status/retry`, { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['kiki-zentrale', 'sync-status'] }),
  })

  if (!data) return null

  if (data.status === 'pending') {
    return (
      <div className="mb-4 flex items-center gap-2.5 rounded-lg border border-info/30 bg-info-bg/60 px-4 py-2.5 text-sm font-medium text-info">
        <Loader2 size={16} className="shrink-0 animate-spin" />
        <span>
          Änderungen werden an Kiki übertragen… Das dauert in der Regel weniger als eine Minute —
          erst danach gelten die neuen Einstellungen für Anrufe.
        </span>
      </div>
    )
  }

  if (data.status === 'failed') {
    return (
      <div className="mb-4 flex items-center gap-2.5 rounded-lg border border-error/30 bg-error-bg/60 px-4 py-2.5 text-sm font-medium text-error">
        <AlertTriangle size={16} className="shrink-0" />
        <span className="flex-1">
          Übertragung an Kiki fehlgeschlagen — die Einstellungen sind gespeichert, aber noch nicht
          am Telefon aktiv.
        </span>
        <button
          onClick={() => retry.mutate()}
          disabled={retry.isPending}
          className="shrink-0 rounded-md border border-error/40 bg-surface px-3 py-1 text-xs font-semibold text-error hover:bg-error-bg disabled:opacity-50"
        >
          {retry.isPending ? 'Versucht…' : 'Erneut versuchen'}
        </button>
      </div>
    )
  }

  if (data.status === 'applied' && showSuccess) {
    return (
      <div className="mb-4 flex items-center gap-2.5 rounded-lg border border-success/30 bg-success-bg/60 px-4 py-2.5 text-sm font-medium text-success">
        <CheckCircle2 size={16} className="shrink-0" />
        <span>Einstellungen aktiv — Kiki verwendet ab sofort den neuen Stand.</span>
      </div>
    )
  }

  return null
}
