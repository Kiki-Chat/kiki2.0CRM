/**
 * AdminMigrationPage — super-admin-only Migration view for an existing customer.
 *
 * Internal to us (never shown to org admins). Two read-only sections:
 *  1. Migrierte Daten — how much of the customer's history has been pulled into
 *     the CRM (calls / customers / cases …).
 *  2. Prompt-Abweichung — how far the agent's LIVE ElevenLabs prompt diverges
 *     from the CRM's standard template (coverage %, CUSTOM vs DEFAULT, what
 *     they added / dropped). Visibility only — nothing is ported here.
 *
 * Route: /admin/orgs/:id/migration  →  GET /api/super-admin/orgs/{id}/migration
 */
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ArrowLeft, CheckCircle2, FileText, Info, Loader2, LogOut, Phone, ShieldAlert, Users } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'

import { apiFetch } from '../lib/adminApi'
import { cn } from '../lib/utils'
import { useAdminAuth } from './AdminAuthProvider'

interface MigrationOverview {
  org_id: string
  name: string | null
  agent_id: string | null
  history: {
    calls: number
    customers: number
    inquiries: number
    cases: number
    appointments: number
    last_call_at: string | null
  }
  prompt: {
    available: boolean
    error: string | null
    status: 'CUSTOM' | 'DEFAULT' | null
    coverage_pct: number
    live_chars: number
    template_chars: number
    added_count: number
    removed_count: number
    sample_added: string[]
    sample_removed: string[]
  }
  import_state: {
    status: 'running' | 'complete' | 'incomplete'
    started_at?: string
    finished_at?: string
    imported?: number
    seen?: number
    errors?: number
    more?: boolean
    passes?: number
  } | null
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

export function AdminMigrationPage() {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const { session, signOut } = useAdminAuth()
  const email = session?.user.email ?? ''

  async function handleSignOut() {
    await signOut()
    navigate('/admin/login', { replace: true })
  }

  const { data, isLoading, error } = useQuery({
    queryKey: ['admin', 'migration', id],
    queryFn: () => apiFetch<MigrationOverview>(`/api/super-admin/orgs/${id}/migration`),
    enabled: !!id,
    // Poll live while an import is still running, so the count + status update.
    refetchInterval: (q) =>
      q.state.data?.import_state?.status === 'running' ? 4000 : false,
  })

  return (
    <div className="min-h-screen w-full bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 bg-slate-900">
        <div className="mx-auto flex w-full items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <div className="flex min-w-0 items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-amber-500/15 text-amber-400">
              <ShieldAlert size={16} />
            </div>
            <div className="min-w-0">
              <div className="text-xs font-bold uppercase tracking-widest text-amber-400">
                HeyKiki · Migration
              </div>
              <div className="truncate text-[11px] text-slate-400">
                {data?.name ?? 'Organisation'} — interner Übernahme-Status
              </div>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <div className="hidden text-right sm:block">
              <div className="text-xs text-slate-400">Angemeldet als</div>
              <div className="text-sm font-medium text-slate-200">{email}</div>
            </div>
            <button
              onClick={() => navigate('/admin/orgs')}
              className="flex items-center gap-1.5 rounded-md border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-700"
            >
              <ArrowLeft size={13} /> Zur Liste
            </button>
            <button
              onClick={handleSignOut}
              className="flex items-center gap-1.5 rounded-md border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-700"
            >
              <LogOut size={13} /> Abmelden
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-4xl px-4 py-6 sm:px-6 sm:py-8">
        <div className="space-y-5">
          <header>
            <h1 className="text-2xl font-bold text-slate-100">
              Migration — <span className="text-amber-300">{data?.name ?? '…'}</span>
            </h1>
            <p className="mt-1 text-sm text-slate-400">
              Interner Status der Übernahme aus der Nicht-CRM-Version. Nur für uns sichtbar.
            </p>
          </header>

      {isLoading && (
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-12 text-center text-slate-400">
          Wird geladen…
        </div>
      )}
      {error && (
        <div className="rounded-xl border border-red-900/60 bg-red-950/40 p-4 text-sm text-red-300">
          {(error as Error).message}
        </div>
      )}

      {data && (
        <>
          {/* ── Migrierte Daten ─────────────────────────────────────────── */}
          <section className="space-y-3 rounded-xl border border-slate-800 bg-slate-900 p-5">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
                <Users size={15} className="text-amber-300" /> Migrierte Daten
              </div>
              {data.import_state && <ImportStatusBadge state={data.import_state} />}
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <Stat label="Anrufe importiert" value={data.history.calls} icon={<Phone size={13} />} />
              <Stat label="Kunden erkannt" value={data.history.customers} icon={<Users size={13} />} />
              <Stat label="Anfragen" value={data.history.inquiries} />
              <Stat label="Vorgänge" value={data.history.cases} />
              <Stat label="Termine" value={data.history.appointments} />
            </div>
            <p className="text-xs text-slate-500">
              Letzter importierter Anruf: <span className="text-slate-400">{fmtDate(data.history.last_call_at)}</span>
              {data.import_state && (
                <>
                  {' · '}
                  {data.import_state.status === 'running'
                    ? <>Import gestartet: <span className="text-slate-400">{fmtDate(data.import_state.started_at ?? null)}</span></>
                    : <>Import zuletzt: <span className="text-slate-400">{fmtDate(data.import_state.finished_at ?? null)}</span></>}
                  {(data.import_state.errors ?? 0) > 0 && (
                    <span className="text-amber-400"> · {data.import_state.errors} Fehler</span>
                  )}
                </>
              )}
            </p>
          </section>

          {/* ── Prompt-Abweichung ───────────────────────────────────────── */}
          <section className="space-y-3 rounded-xl border border-slate-800 bg-slate-900 p-5">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
                <FileText size={15} className="text-amber-300" /> Prompt-Abweichung vom Standard
              </div>
              {data.prompt.available && data.prompt.status && (
                <span
                  className={cn(
                    'rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1',
                    data.prompt.status === 'CUSTOM'
                      ? 'bg-amber-950/60 text-amber-300 ring-amber-900/60'
                      : 'bg-emerald-950/60 text-emerald-300 ring-emerald-900/60',
                  )}
                >
                  {data.prompt.status === 'CUSTOM' ? 'INDIVIDUELL' : 'STANDARDNAH'}
                </span>
              )}
            </div>

            {!data.prompt.available ? (
              <div className="flex items-start gap-2 rounded-md border border-slate-800 bg-slate-950/40 p-3 text-sm text-slate-400">
                <AlertTriangle size={15} className="mt-0.5 shrink-0 text-amber-400" />
                {data.prompt.error ?? 'Prompt-Vergleich nicht verfügbar.'}
              </div>
            ) : (
              <>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <Stat label="Deckung" value={`${data.prompt.coverage_pct}%`} />
                  <Stat label="Eigene Zeilen" value={data.prompt.added_count} />
                  <Stat label="Fehlend (Standard)" value={data.prompt.removed_count} />
                  <Stat
                    label="Länge live/Standard"
                    value={`${Math.round(data.prompt.live_chars / 1000)}k / ${Math.round(
                      data.prompt.template_chars / 1000,
                    )}k`}
                  />
                </div>

                <SampleList
                  title="Eigene Inhalte des Kunden (würden bei Migration erhalten bleiben)"
                  tone="amber"
                  lines={data.prompt.sample_added}
                />
                <SampleList
                  title="Standard-Inhalte, die im Live-Prompt fehlen"
                  tone="slate"
                  lines={data.prompt.sample_removed}
                />
              </>
            )}

            <div className="flex items-start gap-2 rounded-md border border-sky-900/50 bg-sky-950/30 p-3 text-xs text-sky-200/80">
              <Info size={14} className="mt-0.5 shrink-0 text-sky-400" />
              <span>
                Nur Analyse — es wird nichts portiert. Ziel der späteren Migration: die echten
                Eigen-Inhalte erhalten und nur diese gezielt in die Kiki-Zentrale-Einstellungen
                übernehmen, damit der Prompt schlank bleibt (kein Aufblähen durch blindes Anhängen).
              </span>
            </div>
          </section>
        </>
      )}
        </div>
      </main>
    </div>
  )
}

function ImportStatusBadge({
  state,
}: {
  state: NonNullable<MigrationOverview['import_state']>
}) {
  const imported = state.imported ?? 0
  const seen = state.seen ?? 0
  const complete = state.status === 'complete'
  // A "running" state whose start is >30 min old is most likely a worker that
  // was restarted mid-pass — flag it so staff know to re-trigger (it resumes).
  const stale =
    state.status === 'running' &&
    !!state.started_at &&
    Date.now() - new Date(state.started_at).getTime() > 30 * 60 * 1000
  const running = state.status === 'running' && !stale

  const tone = complete ? 'emerald' : stale || state.status === 'incomplete' ? 'red' : 'amber'
  const label = complete
    ? 'Import abgeschlossen'
    : state.status === 'incomplete'
      ? 'Import unvollständig'
      : stale
        ? 'Import evtl. unterbrochen'
        : 'Import läuft…'
  const count = seen ? ` · ${imported}/${seen}` : imported ? ` · ${imported}` : ''

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1',
        tone === 'emerald'
          ? 'bg-emerald-950/60 text-emerald-300 ring-emerald-900/60'
          : tone === 'red'
            ? 'bg-red-950/60 text-red-300 ring-red-900/60'
            : 'bg-amber-950/60 text-amber-300 ring-amber-900/60',
      )}
      title={state.passes ? `${state.passes} Durchlauf/Durchläufe` : undefined}
    >
      {running ? (
        <Loader2 size={11} className="animate-spin" />
      ) : complete ? (
        <CheckCircle2 size={11} />
      ) : (
        <AlertTriangle size={11} />
      )}
      {label}
      {count}
    </span>
  )
}

function Stat({
  label,
  value,
  icon,
}: {
  label: string
  value: string | number
  icon?: React.ReactNode
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2">
      <div className="flex items-center gap-1 text-[11px] uppercase tracking-wide text-slate-500">
        {icon}
        {label}
      </div>
      <div className="mt-0.5 text-lg font-bold text-slate-100">{value}</div>
    </div>
  )
}

function SampleList({
  title,
  lines,
  tone,
}: {
  title: string
  lines: string[]
  tone: 'amber' | 'slate'
}) {
  if (!lines.length) return null
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-slate-400">{title}</div>
      <ul className="space-y-1 rounded-md border border-slate-800 bg-slate-950/40 p-3">
        {lines.map((ln, i) => (
          <li
            key={i}
            className={cn(
              'truncate text-xs',
              tone === 'amber' ? 'text-amber-200/90' : 'text-slate-400',
            )}
            title={ln}
          >
            • {ln}
          </li>
        ))}
      </ul>
    </div>
  )
}
