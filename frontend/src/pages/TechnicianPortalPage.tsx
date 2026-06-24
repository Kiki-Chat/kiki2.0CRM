// Public (no-login) technician portal — /techniker/:token. The technician opens
// their STANDING link and sees all their jobs (past + current); each card opens
// that job's report form at /job/:job_token. No login: the token is the
// credential (same model as the per-job link).
import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, ChevronRight, Clock, Loader2, MapPin, Wrench } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'

import { apiFetch } from '../lib/api'

interface PortalJob {
  job_token: string
  title: string | null
  scheduled_at: string | null
  customer_name: string | null
  customer_address: string | null
  status: 'offen' | 'läuft' | 'abgeschlossen'
  submitted_at: string | null
  photo_count: number
}
interface PortalData {
  technician_name: string | null
  org_name: string | null
  jobs: PortalJob[]
}

const fmtTime = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString('de-DE', {
        weekday: 'short', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit',
        timeZone: 'Europe/Berlin',
      }) + ' Uhr'
    : 'Kein Termin'

const STATUS: Record<PortalJob['status'], { label: string; cls: string }> = {
  offen: { label: 'Offen', cls: 'bg-info-bg text-info' },
  'läuft': { label: 'In Bearbeitung', cls: 'bg-warning-bg text-warning' },
  abgeschlossen: { label: 'Abgeschlossen', cls: 'bg-green-tint-100 text-green-deep' },
}

export function TechnicianPortalPage() {
  const { token } = useParams<{ token: string }>()
  const { data, error } = useQuery({
    queryKey: ['technician-portal', token],
    queryFn: () => apiFetch<PortalData>(`/api/public/technician/${token}`),
    retry: false,
  })

  if (error) {
    return (
      <Shell>
        <div className="rounded-xl border border-border bg-surface p-6 text-center">
          <div className="text-base font-bold text-text">Link nicht (mehr) gültig</div>
          <p className="mt-2 text-sm text-muted">{(error as Error).message}</p>
        </div>
      </Shell>
    )
  }
  if (!data) {
    return (
      <Shell>
        <div className="flex items-center justify-center gap-2 p-10 text-muted">
          <Loader2 size={18} className="animate-spin" /> Lädt…
        </div>
      </Shell>
    )
  }

  const open = data.jobs.filter((j) => j.status !== 'abgeschlossen')
  const done = data.jobs.filter((j) => j.status === 'abgeschlossen')

  return (
    <Shell org={data.org_name} name={data.technician_name}>
      <Section title={`Aktuelle Einsätze${open.length ? ` (${open.length})` : ''}`}>
        {open.length ? (
          open.map((j) => <JobCard key={j.job_token} job={j} />)
        ) : (
          <p className="rounded-xl border border-border bg-surface p-4 text-sm text-muted">
            Aktuell keine offenen Einsätze.
          </p>
        )}
      </Section>
      {done.length > 0 && (
        <Section title={`Erledigt (${done.length})`}>
          {done.map((j) => <JobCard key={j.job_token} job={j} />)}
        </Section>
      )}
    </Shell>
  )
}

function JobCard({ job }: { job: PortalJob }) {
  const s = STATUS[job.status]
  return (
    <Link
      to={`/job/${job.job_token}`}
      className="flex items-center gap-3 rounded-xl border border-border bg-surface p-4 transition hover:border-green-tint-200"
    >
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-green-tint-100 text-green-deep">
        {job.status === 'abgeschlossen' ? <CheckCircle2 size={18} /> : <Wrench size={18} />}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-bold text-text">{job.title}</span>
          <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${s.cls}`}>{s.label}</span>
        </div>
        <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted">
          <Clock size={12} /> {fmtTime(job.scheduled_at)}
        </div>
        {job.customer_name && <div className="mt-0.5 truncate text-xs text-body">{job.customer_name}</div>}
        {job.customer_address && (
          <div className="mt-0.5 flex items-center gap-1.5 truncate text-xs text-muted">
            <MapPin size={12} /> {job.customer_address}
          </div>
        )}
      </div>
      <ChevronRight size={18} className="shrink-0 text-faint" />
    </Link>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{title}</div>
      <div className="space-y-2">{children}</div>
    </div>
  )
}

function Shell({ org, name, children }: { org?: string | null; name?: string | null; children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-alt">
      <div className="mx-auto max-w-lg space-y-5 p-4 pb-12">
        <div className="pt-4 text-center">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted">Techniker-Portal</div>
          {org && <div className="text-lg font-bold text-text">{org}</div>}
          {name && <div className="text-sm text-body">Hallo {name} 👋</div>}
        </div>
        {children}
      </div>
    </div>
  )
}
