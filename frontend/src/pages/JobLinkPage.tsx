// Public (no-login) technician job page — /job/:token. The technician opens
// the emailed capability link, starts the job, and submits the report
// (questionnaire + photos). Mobile-first: this is filled out on site.
import { useMutation, useQuery } from '@tanstack/react-query'
import { Camera, CheckCircle2, Loader2, MapPin, Phone, Play } from 'lucide-react'
import { useRef, useState } from 'react'
import { useParams } from 'react-router-dom'

import { apiFetch, apiUpload } from '../lib/api'

interface JobInfo {
  org_name: string | null
  technician_name: string | null
  case_number: string | null
  case_subject: string | null
  appointment: {
    title: string | null
    scheduled_at: string | null
    duration_minutes: number | null
    location: string | null
    notes: string | null
  }
  customer: { name: string | null; phone: string | null; address: string | null }
  started_at: string | null
  finished_at: string | null
  submitted_at: string | null
  photo_count: number
}

const NEEDS = ['Mehr Zeit nötig', 'Mehr Werkzeug/Material nötig', 'Weiterer Termin nötig', 'Rückfrage im Büro']

const fmtTime = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString('de-DE', {
        weekday: 'long', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit',
        timeZone: 'Europe/Berlin',
      }) + ' Uhr'
    : '—'

const inputCls =
  'w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary'

export function JobLinkPage() {
  const { token } = useParams<{ token: string }>()
  const base = `/api/public/jobs/${token}`

  const { data: job, error, refetch } = useQuery({
    queryKey: ['public-job', token],
    queryFn: () => apiFetch<JobInfo>(base),
    retry: false,
  })

  const [experienceGood, setExperienceGood] = useState<boolean | null>(null)
  const [extraDemands, setExtraDemands] = useState('')
  const [siteNotes, setSiteNotes] = useState('')
  const [finished, setFinished] = useState(false)
  const [needs, setNeeds] = useState<string[]>([])
  const [description, setDescription] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [photoCount, setPhotoCount] = useState<number | null>(null)
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const start = useMutation({
    mutationFn: () => apiFetch(`${base}/start`, { method: 'POST' }),
    onSuccess: () => void refetch(),
    onError: (e: Error) => setFormError(e.message),
  })

  const submit = useMutation({
    mutationFn: () =>
      apiFetch(`${base}/submit`, {
        method: 'POST',
        body: JSON.stringify({
          experience_good: experienceGood,
          extra_demands: extraDemands,
          site_visit_notes: siteNotes,
          job_started: true,
          job_finished: finished,
          needs,
          description,
        }),
      }),
    onSuccess: () => void refetch(),
    onError: (e: Error) => setFormError(e.message),
  })

  const uploadPhotos = async (files: FileList | null) => {
    if (!files?.length) return
    setUploading(true)
    setFormError(null)
    try {
      for (const f of Array.from(files)) {
        const fd = new FormData()
        fd.append('file', f)
        const res = await apiUpload<{ photo_count: number }>(`${base}/photos`, fd)
        setPhotoCount(res.photo_count)
      }
    } catch (e) {
      setFormError(e instanceof Error ? e.message : 'Foto-Upload fehlgeschlagen.')
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  if (error) {
    return (
      <Shell>
        <div className="rounded-xl border border-border bg-surface p-6 text-center">
          <div className="text-base font-bold text-text">Link nicht (mehr) gültig</div>
          <p className="mt-2 text-sm text-muted">{error.message}</p>
        </div>
      </Shell>
    )
  }
  if (!job) {
    return (
      <Shell>
        <div className="flex items-center justify-center gap-2 p-10 text-muted">
          <Loader2 size={18} className="animate-spin" /> Lädt…
        </div>
      </Shell>
    )
  }

  const photos = photoCount ?? job.photo_count
  const a = job.appointment

  return (
    <Shell org={job.org_name}>
      {/* Job details */}
      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="text-xs font-semibold uppercase tracking-wide text-muted">
          Einsatz{job.case_number ? ` · Vorgang ${job.case_number}` : ''}
        </div>
        <div className="mt-1 text-lg font-bold text-text">{a.title ?? 'Termin'}</div>
        <div className="mt-1 text-sm text-body">{fmtTime(a.scheduled_at)} ({a.duration_minutes ?? 60} Min)</div>
        {job.customer.name && <div className="mt-2 text-sm font-medium text-text">{job.customer.name}</div>}
        {(job.customer.address || a.location) && (
          <a
            href={`https://maps.google.com/?q=${encodeURIComponent(job.customer.address || a.location || '')}`}
            target="_blank" rel="noreferrer"
            className="mt-1 flex items-center gap-1.5 text-sm text-green-deep underline"
          >
            <MapPin size={14} /> {job.customer.address || a.location}
          </a>
        )}
        {job.customer.phone && (
          <a href={`tel:${job.customer.phone}`} className="mt-1 flex items-center gap-1.5 text-sm text-green-deep underline">
            <Phone size={14} /> {job.customer.phone}
          </a>
        )}
        {a.notes && <p className="mt-2 rounded-md bg-alt p-2 text-sm text-body">{a.notes}</p>}
      </div>

      {job.submitted_at ? (
        <div className="rounded-xl border border-success/40 bg-green-tint-50 p-6 text-center">
          <CheckCircle2 size={28} className="mx-auto text-success" />
          <div className="mt-2 text-base font-bold text-text">Einsatzbericht übermittelt</div>
          <p className="mt-1 text-sm text-muted">
            Vielen Dank{job.technician_name ? `, ${job.technician_name}` : ''}! Der Bericht ist im Vorgang hinterlegt.
          </p>
        </div>
      ) : !job.started_at ? (
        <button
          onClick={() => start.mutate()}
          disabled={start.isPending}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-green-primary py-4 text-base font-bold text-white hover:brightness-110 disabled:opacity-60"
        >
          {start.isPending ? <Loader2 size={18} className="animate-spin" /> : <Play size={18} />}
          Einsatz starten
        </button>
      ) : (
        <div className="space-y-4 rounded-xl border border-border bg-surface p-4">
          <div className="text-sm font-bold text-text">Einsatzbericht</div>

          <FieldBlock label="War die Erfahrung gut?">
            <div className="flex gap-2">
              {[['Ja', true], ['Nein', false]].map(([label, val]) => (
                <button
                  key={String(label)}
                  onClick={() => setExperienceGood(val as boolean)}
                  className={`flex-1 rounded-md border px-3 py-2.5 text-sm font-medium ${
                    experienceGood === val
                      ? 'border-green-primary bg-green-tint-50 text-green-deep'
                      : 'border-border bg-alt text-body'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </FieldBlock>

          <FieldBlock label="Gab es zusätzliche Wünsche des Kunden?">
            <textarea value={extraDemands} onChange={(e) => setExtraDemands(e.target.value)} rows={2} className={inputCls} />
          </FieldBlock>

          <FieldBlock label="Wie war der Vor-Ort-Termin?">
            <textarea value={siteNotes} onChange={(e) => setSiteNotes(e.target.value)} rows={2} className={inputCls} />
          </FieldBlock>

          <FieldBlock label="Auftrag abgeschlossen?">
            <div className="flex gap-2">
              {[['Ja, fertig', true], ['Noch offen', false]].map(([label, val]) => (
                <button
                  key={String(label)}
                  onClick={() => setFinished(val as boolean)}
                  className={`flex-1 rounded-md border px-3 py-2.5 text-sm font-medium ${
                    finished === val
                      ? 'border-green-primary bg-green-tint-50 text-green-deep'
                      : 'border-border bg-alt text-body'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </FieldBlock>

          <FieldBlock label="Wird noch etwas benötigt?">
            <div className="flex flex-wrap gap-1.5">
              {NEEDS.map((n) => {
                const on = needs.includes(n)
                return (
                  <button
                    key={n}
                    onClick={() => setNeeds((p) => (on ? p.filter((x) => x !== n) : [...p, n]))}
                    className={`rounded-full border px-3 py-1.5 text-xs font-medium ${
                      on ? 'border-green-primary bg-green-tint-50 text-green-deep' : 'border-border bg-alt text-body'
                    }`}
                  >
                    {n}
                  </button>
                )
              })}
            </div>
          </FieldBlock>

          <FieldBlock label="Was wurde gemacht? *">
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              placeholder="Kurzbeschreibung der durchgeführten Arbeiten…"
              className={inputCls}
            />
          </FieldBlock>

          <FieldBlock label="Fotos (mind. 1, mehrere möglich) *">
            {/* No `capture` attribute on purpose: with it, mobile jumps straight
                to the camera and blocks the gallery + multi-select. Without it the
                OS shows the chooser (Kamera / Galerie / Dateien) and `multiple`
                works — i.e. take a photo now OR pick existing ones, several at a time. */}
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={(e) => void uploadPhotos(e.target.files)}
            />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={uploading}
              className="flex w-full items-center justify-center gap-2 rounded-md border border-dashed border-border bg-alt py-3 text-sm font-medium text-body hover:bg-border/30 disabled:opacity-60"
            >
              {uploading ? <Loader2 size={16} className="animate-spin" /> : <Camera size={16} />}
              {uploading ? 'Lädt hoch…' : 'Foto aufnehmen / hochladen'}
            </button>
            <p className="mt-1 text-xs text-muted">Auf dem Handy: Kamera oder Galerie. Mehrere Fotos möglich.</p>
            {photos > 0 && (
              <p className="mt-1 text-xs font-medium text-green-deep">✓ {photos} Foto{photos === 1 ? '' : 's'} hochgeladen</p>
            )}
          </FieldBlock>

          {formError && <div className="rounded-md bg-error-bg px-3 py-2 text-sm text-error">{formError}</div>}

          <button
            onClick={() => { setFormError(null); submit.mutate() }}
            disabled={submit.isPending || !description.trim() || photos === 0}
            className="w-full rounded-xl bg-green-primary py-3.5 text-base font-bold text-white hover:brightness-110 disabled:opacity-50"
          >
            {submit.isPending ? 'Wird übermittelt…' : 'Bericht absenden'}
          </button>
        </div>
      )}
    </Shell>
  )
}

function Shell({ org, children }: { org?: string | null; children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-alt">
      <div className="mx-auto max-w-lg space-y-4 p-4 pb-12">
        <div className="pt-4 text-center">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted">Einsatz-Auftrag</div>
          {org && <div className="text-lg font-bold text-text">{org}</div>}
        </div>
        {children}
      </div>
    </div>
  )
}

function FieldBlock({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 text-xs font-semibold text-body">{label}</div>
      {children}
    </div>
  )
}
