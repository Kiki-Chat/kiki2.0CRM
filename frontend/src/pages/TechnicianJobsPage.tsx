// Authenticated technician portal — "Meine Aufträge". Lists the logged-in
// technician's own assigned visits. Modelled on the public TechnicianPortalPage
// card style, but behind a real login (users.role='technician').
import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, Clock, Loader2, MapPin, Phone, Wrench } from 'lucide-react'

import { apiFetch } from '../lib/api'

interface TechJob {
  appointment_id: string
  title: string | null
  scheduled_at: string | null
  duration_minutes: number | null
  status: string
  category: string | null
  customer_name: string | null
  customer_phone: string | null
  customer_address: string | null
}
interface JobsData {
  employee_id: string | null
  display_name: string | null
  jobs: TechJob[]
}

const fmtTime = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString('de-DE', {
        weekday: 'short', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit',
        timeZone: 'Europe/Berlin',
      }) + ' Uhr'
    : 'Kein Termin'

const STATUS: Record<string, { label: string; cls: string }> = {
  confirmed: { label: 'Bestätigt', cls: 'bg-green-tint-100 text-green-deep' },
  pending: { label: 'Vorgeschlagen', cls: 'bg-warning-bg text-warning' },
  completed: { label: 'Abgeschlossen', cls: 'bg-green-tint-100 text-green-deep' },
}

export function TechnicianJobsPage() {
  const { data, error } = useQuery({
    queryKey: ['technician-jobs'],
    queryFn: () => apiFetch<JobsData>('/api/technician/me/jobs'),
    retry: false,
  })

  if (error) {
    return (
      <div className="rounded-xl border border-border bg-surface p-6 text-center">
        <div className="text-base font-bold text-text">Konnte Aufträge nicht laden</div>
        <p className="mt-2 text-sm text-muted">{(error as Error).message}</p>
      </div>
    )
  }
  if (!data) {
    return (
      <div className="flex items-center justify-center gap-2 p-10 text-muted">
        <Loader2 size={18} className="animate-spin" /> Wird geladen…
      </div>
    )
  }

  const now = Date.now()
  const upcoming = data.jobs.filter((j) => !j.scheduled_at || new Date(j.scheduled_at).getTime() >= now - 3_600_000)
  const past = data.jobs.filter((j) => j.scheduled_at && new Date(j.scheduled_at).getTime() < now - 3_600_000)

  return (
    <div className="space-y-5">
      <Section title={`Anstehende Aufträge${upcoming.length ? ` (${upcoming.length})` : ''}`}>
        {upcoming.length ? (
          upcoming.map((j) => <JobCard key={j.appointment_id} job={j} />)
        ) : (
          <p className="rounded-xl border border-border bg-surface p-4 text-sm text-muted">
            Aktuell keine anstehenden Aufträge.
          </p>
        )}
      </Section>
      {past.length > 0 && (
        <Section title={`Vergangene (${past.length})`}>
          {past.map((j) => <JobCard key={j.appointment_id} job={j} />)}
        </Section>
      )}
    </div>
  )
}

function JobCard({ job }: { job: TechJob }) {
  const s = STATUS[job.status] ?? { label: job.status, cls: 'bg-info-bg text-info' }
  const done = job.status === 'completed'
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-green-tint-100 text-green-deep">
          {done ? <CheckCircle2 size={18} /> : <Wrench size={18} />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-bold text-text">{job.title ?? 'Auftrag'}</span>
            <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${s.cls}`}>{s.label}</span>
          </div>
          {job.category && <div className="mt-0.5 text-xs text-muted">{job.category}</div>}
          <div className="mt-1 flex items-center gap-1.5 text-xs text-muted">
            <Clock size={12} /> {fmtTime(job.scheduled_at)}
          </div>
          {job.customer_name && <div className="mt-0.5 truncate text-xs text-body">{job.customer_name}</div>}
          {job.customer_address && (
            <div className="mt-0.5 flex items-center gap-1.5 truncate text-xs text-muted">
              <MapPin size={12} /> {job.customer_address}
            </div>
          )}
          {job.customer_phone && (
            <a href={`tel:${job.customer_phone}`} className="mt-1 inline-flex items-center gap-1.5 text-xs text-green-deep hover:underline">
              <Phone size={12} /> {job.customer_phone}
            </a>
          )}
        </div>
      </div>
    </div>
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
