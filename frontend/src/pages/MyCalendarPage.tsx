import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import { CalendarCheck, RefreshCw } from 'lucide-react'

import { apiFetch } from '../lib/api'
import { fmtDateTime } from '../lib/datetime'
import { useToast } from '../lib/useToast'
import { cn } from '../lib/utils'

interface MyCalState {
  has_employee: boolean
  connected: boolean
  account_email?: string | null
  token_expires_at?: string | null
}

// Per-employee Google connect: reuses the SAME popup + postMessage OAuth flow as
// the org Kalender-Sync, but with purpose=employee_calendar so the grant lands on
// the employee (employee_calendar_connections), never the company calendar.
function startEmployeeConnect(qc: QueryClient, flash: (m: string) => void) {
  const popup = window.open('', 'heykiki-oauth', 'width=520,height=680')
  if (!popup) {
    flash('Bitte Popups für diese Seite erlauben und erneut versuchen.')
    return
  }
  let cleaned = false
  const cleanup = () => {
    if (cleaned) return
    cleaned = true
    window.removeEventListener('message', onMessage)
    clearTimeout(timer)
  }
  const onMessage = (e: MessageEvent) => {
    if (!e.data || e.data.source !== 'heykiki-oauth') return
    cleanup()
    flash(e.data.message || (e.data.success ? 'Verbunden.' : 'Verbindung fehlgeschlagen.'))
    if (e.data.success) qc.invalidateQueries({ queryKey: ['employee-calendar-me'] })
  }
  window.addEventListener('message', onMessage)
  const timer = setTimeout(cleanup, 30000)
  apiFetch<{ url: string }>('/api/settings/oauth/google/authorize?purpose=employee_calendar')
    .then(({ url }) => {
      popup.location.href = url
    })
    .catch((err: Error) => {
      cleanup()
      popup.close()
      flash(err.message || 'OAuth nicht verfügbar.')
    })
}

export function MyCalendarPage() {
  const qc = useQueryClient()
  const { toast, flash } = useToast()

  const { data, isLoading } = useQuery({
    queryKey: ['employee-calendar-me'],
    queryFn: () => apiFetch<MyCalState>('/api/employee-calendar/me'),
  })

  const disconnect = useMutation({
    mutationFn: () => apiFetch('/api/employee-calendar/disconnect', { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['employee-calendar-me'] })
      flash('Kalender getrennt.')
    },
    onError: (e: Error) => flash(e.message || 'Trennen fehlgeschlagen.'),
  })

  const connected = !!data?.connected

  return (
    <div className="p-8">
      <div className="mb-6 flex items-center gap-3">
        <CalendarCheck size={26} className="text-green-primary" />
        <div>
          <h1 className="text-2xl font-bold text-text">Mein Kalender</h1>
          <p className="mt-0.5 text-sm text-muted">Verbinde deinen eigenen Google-Kalender</p>
        </div>
      </div>

      {toast && (
        <div className="mb-4 rounded-md bg-green-tint-50 px-3 py-2 text-sm font-medium text-green-deep">
          {toast}
        </div>
      )}

      {isLoading ? (
        <div className="rounded-xl border border-border bg-surface p-6 text-sm text-muted">Wird geladen…</div>
      ) : !data?.has_employee ? (
        <div className="rounded-xl border border-border bg-surface p-6 text-sm text-muted">
          Für dieses Konto ist kein Mitarbeiterprofil hinterlegt. Bitte wende dich an die
          Administration, damit dein Profil verknüpft wird.
        </div>
      ) : (
        <div className="max-w-xl rounded-xl border border-border bg-surface p-6">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-bold text-text">Google Kalender</span>
            <span className={cn('rounded-full px-2.5 py-0.5 text-xs font-medium', connected ? 'bg-success-bg text-success' : 'bg-alt text-muted')}>
              {connected ? 'Verbunden' : 'Nicht verbunden'}
            </span>
          </div>
          <p className="mt-2 text-sm text-muted">
            Dein persönlicher Kalender zeigt, wann du belegt bist — so wirst du bei der Terminvergabe
            nie doppelt verplant. Bestätigte Aufträge erscheinen automatisch in deinem Kalender
            (also auch auf deinem Handy). Persönliche Termine sind für andere nur als „Gebucht“
            sichtbar, ohne Details.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            {connected ? (
              <>
                {data?.account_email && (
                  <span className="text-sm font-medium text-success">✓ {data.account_email}</span>
                )}
                <button
                  onClick={() => disconnect.mutate()}
                  disabled={disconnect.isPending}
                  className="rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-body hover:bg-alt disabled:opacity-60"
                >
                  {disconnect.isPending ? 'Trennt…' : 'Trennen'}
                </button>
                <button
                  onClick={() => startEmployeeConnect(qc, flash)}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-3 py-2 text-sm font-medium text-body hover:bg-alt"
                >
                  <RefreshCw size={14} /> Neu verbinden
                </button>
              </>
            ) : (
              <button
                onClick={() => startEmployeeConnect(qc, flash)}
                className="rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110"
              >
                Google Kalender verbinden
              </button>
            )}
          </div>
          {connected && data?.token_expires_at && (
            <p className="mt-3 text-xs text-muted">Zugriff gültig bis {fmtDateTime(data.token_expires_at)}.</p>
          )}
        </div>
      )}
    </div>
  )
}
