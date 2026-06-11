/**
 * Wave 2 / Agent 2.4 — OFFENE AKTIONEN inline appointment card.
 *
 * Renders at the TOP of the call-detail right panel (above the title/tabs)
 * when the selected call has a pending appointment that needs a decision.
 * Four action buttons:
 *   - Bestätigen → POST /api/appointments/{id}/confirm
 *   - Alternative vorschlagen → opens inline date/time picker → POST /propose-alternative
 *   - Ablehnen → POST /api/appointments/{id}/reject
 *   - Ausblenden → collapses the card to a one-line summary (re-expandable)
 *   - ✕ (header) → removes the card from the list for the session
 *
 * After Bestätigen/Ablehnen the card STAYS visible with a "Bestätigt/Abgelehnt"
 * banner (a reminder, so the appointment isn't created twice) — the parent keeps
 * it on screen from a snapshot even though the row leaves the pending set. If
 * `appointment.alternative_proposed_at` is non-null, the card shows the
 * "Alternative gesendet" state (locked) instead of action buttons.
 *
 * Compact NOTIFICATION-style card (no calendar grid). The only expandable
 * surface is "Kategorie, Dauer & Zuweisung"; Bestätigen books immediately
 * (no popup) and Alternative vorschlagen opens the inline date/time picker.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  Clock,
  EyeOff,
  MapPin,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { apiFetch } from '../../lib/api'
import { cn } from '../../lib/utils'

// ─── shapes ──────────────────────────────────────────────────────────────────
export interface PendingAppointment {
  id: string
  title: string | null
  scheduled_at: string | null
  duration_minutes: number | null
  status: string
  category: string | null
  location: { raw?: string | null } | null
  notes: string | null
  assigned_employee_id: string | null
  confirmed_at: string | null
  rejected_at: string | null
  rejection_reason: string | null
  cancelled_at: string | null
  rescheduled_at: string | null
  alternative_start_time: string | null
  alternative_end_time: string | null
  alternative_note: string | null
  alternative_proposed_at: string | null
  // Customer counter-proposal recorded by the agent on a reschedule call
  // (migration 0037). When customer_proposed_at is set, the card shows the
  // "Kunde schlägt … vor — Genehmigen / Ablehnen" approval state.
  customer_proposed_start_time: string | null
  customer_proposed_end_time: string | null
  customer_proposed_at: string | null
  customer_proposal_source: string | null
  // True when the customer abandoned the OLD slot — so declining the proposal
  // CANCELS the appointment and calls/emails the customer (not a silent discard).
  reschedule_replace_intent: boolean | null
  // 2-line issue summary from the call (calls.summary) — shown under the date.
  issue_summary: string | null
}

export interface PendingAppointmentResponse {
  appointment: PendingAppointment | null
}

interface KzCategory {
  id: string
  name: string
  description: string | null
  duration_minutes: number
  default_employee_id: string | null
  sort_order: number
}

interface Employee {
  id: string
  display_name: string | null
}

// ─── helpers ─────────────────────────────────────────────────────────────────
// Base duration pills. When a category is selected, its default duration is
// merged in (and highlighted) so categories with non-standard defaults — e.g.
// a 20-min Beratung — surface their default as a real pill rather than only
// in the custom field.
const BASE_DURATIONS = [30, 60, 90, 120]

const fmtFullDate = (iso: string | null): string => {
  if (!iso) return '—'
  const d = new Date(iso)
  // dd.MM.yyyy um HH:mm — matches the reference card "28.05.2026 um 10:00".
  return `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.${d.getFullYear()} um ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

// Build a `YYYY-MM-DDTHH:mm` value for <input type="datetime-local"> from an ISO
// string. Local-tz aware — datetime-local has no timezone, so we strip the offset.
const isoToDtLocal = (iso: string | null, plusHours = 1): string => {
  const d = iso ? new Date(iso) : new Date(Date.now() + plusHours * 3_600_000)
  return dateToDtLocal(d)
}

// Same as above but takes a Date directly.
const dateToDtLocal = (d: Date): string => {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// ─── component ──────────────────────────────────────────────────────────────
export function AppointmentCard({
  appointment,
  callId,
  result,
  onConfirmed,
  onRejected,
  onRemove,
}: {
  appointment: PendingAppointment
  callId: string
  /** Set by the parent once a completed action was snapshotted (Bestätigt/Abgelehnt). */
  result?: 'confirmed' | 'rejected'
  /** Notify the parent so the card stays on screen after the row leaves "pending". */
  onConfirmed: () => void
  onRejected: () => void
  /** Full removal (✕) — drops the card for the session. */
  onRemove: () => void
}) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [expanded, setExpanded] = useState(false)
  // Ausblenden minimises the card to a one-line summary rather than removing it.
  const [collapsed, setCollapsed] = useState(false)
  const [altPickerOpen, setAltPickerOpen] = useState(false)
  const [altStart, setAltStart] = useState(() => isoToDtLocal(appointment.scheduled_at))
  const [altEnd, setAltEnd] = useState(() =>
    isoToDtLocal(appointment.scheduled_at, 2),
  )
  const [altNote, setAltNote] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)

  // Editable fields inside the expandable "Kategorie, Dauer & Zuweisung" section.
  // Pre-filled from the appointment row (the agent/auto-classifier already set
  // category, duration + employee at booking time); every edit here PERSISTS via
  // PATCH /api/appointments/{id}.
  const [categoryId, setCategoryId] = useState<string>('')
  const [duration, setDuration] = useState<number>(appointment.duration_minutes ?? 60)
  const [customDuration, setCustomDuration] = useState<number | null>(null)
  const [assignedEmployeeId, setAssignedEmployeeId] = useState<string>(
    appointment.assigned_employee_id ?? '',
  )

  const categoriesQuery = useQuery({
    queryKey: ['kiki-zentrale', 'categories'],
    queryFn: () =>
      apiFetch<{ categories: KzCategory[] }>(
        '/api/kiki-zentrale/appointment-categories',
      ),
  })
  const categories = categoriesQuery.data?.categories ?? []

  const employeesQuery = useQuery({
    queryKey: ['employees'],
    queryFn: () => apiFetch<Employee[]>('/api/employees'),
  })
  const employees = employeesQuery.data ?? []

  const selectedCategory = useMemo(
    () => categories.find((c) => c.id === categoryId) ?? null,
    [categories, categoryId],
  )

  // Seed the category select from the stored appointment.category (a name) once
  // the category list arrives — exactly once per appointment, so a manual pick
  // is never stomped by a refetch.
  const seededForRef = useRef<string | null>(null)
  useEffect(() => {
    if (seededForRef.current === appointment.id || !categories.length) return
    seededForRef.current = appointment.id
    setDuration(appointment.duration_minutes ?? 60)
    setCustomDuration(null)
    setAssignedEmployeeId(appointment.assigned_employee_id ?? '')
    const stored = (appointment.category ?? '').trim().toLowerCase()
    if (stored) {
      const match = categories.find((c) => c.name.trim().toLowerCase() === stored)
      if (match) setCategoryId(match.id)
    }
  }, [appointment.id, appointment.category, appointment.duration_minutes, appointment.assigned_employee_id, categories])

  // Persist category/duration/employee edits immediately (the card is the
  // editing surface while the appointment is pending).
  const patchAppt = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      apiFetch(`/api/appointments/${appointment.id}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pendingAppointment', callId] })
      qc.invalidateQueries({ queryKey: ['appointments'] })
      qc.invalidateQueries({ queryKey: ['actions', 'pending'] })
    },
    onError: (e: Error) => setActionError(e.message || 'Änderung konnte nicht gespeichert werden.'),
  })

  // When the user picks a category, auto-fill duration + default employee from
  // the category's defaults and persist all three in one PATCH.
  const [defaultsApplied, setDefaultsApplied] = useState<string | null>(null)
  const onPickCategory = (id: string) => {
    setCategoryId(id)
    const cat = categories.find((c) => c.id === id)
    if (cat) {
      setDuration(cat.duration_minutes)
      setCustomDuration(null)
      if (cat.default_employee_id) {
        setAssignedEmployeeId(cat.default_employee_id)
      }
      setDefaultsApplied(cat.name)
      patchAppt.mutate({
        category: cat.name,
        duration_minutes: cat.duration_minutes,
        ...(cat.default_employee_id ? { assigned_employee_id: cat.default_employee_id } : {}),
      })
    } else {
      setDefaultsApplied(null)
      patchAppt.mutate({ category: null })
    }
  }

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['pendingAppointment', callId] })
    qc.invalidateQueries({ queryKey: ['callInquiry', callId] })
    qc.invalidateQueries({ queryKey: ['dashboard', 'overview'] })
    qc.invalidateQueries({ queryKey: ['customerDetail'] })
    // Card ↔ calendar are the same appointment row: refresh the calendar + the
    // open-actions worklist so a confirm/reject here shows up there immediately.
    qc.invalidateQueries({ queryKey: ['appointments'] })
    qc.invalidateQueries({ queryKey: ['actions', 'pending'] })
  }

  const confirm = useMutation({
    mutationFn: () =>
      apiFetch(`/api/appointments/${appointment.id}/confirm`, {
        method: 'POST',
      }),
    onSuccess: () => {
      invalidate()
      onConfirmed()
    },
    onError: (e: Error) => setActionError(e.message || 'Bestätigung fehlgeschlagen.'),
  })

  const reject = useMutation({
    mutationFn: () =>
      apiFetch(`/api/appointments/${appointment.id}/reject`, {
        method: 'POST',
        body: JSON.stringify({}),
      }),
    onSuccess: () => {
      invalidate()
      onRejected()
    },
    onError: (e: Error) => setActionError(e.message || 'Ablehnen fehlgeschlagen.'),
  })

  const proposeAlt = useMutation({
    mutationFn: () =>
      apiFetch(`/api/appointments/${appointment.id}/propose-alternative`, {
        method: 'POST',
        body: JSON.stringify({
          start_time: new Date(altStart).toISOString(),
          end_time: new Date(altEnd).toISOString(),
          note: altNote || null,
        }),
      }),
    onSuccess: () => {
      setAltPickerOpen(false)
      invalidate()
    },
    onError: (e: Error) => setActionError(e.message || 'Alternative konnte nicht gesendet werden.'),
  })

  const approveProposal = useMutation({
    mutationFn: () =>
      apiFetch(`/api/appointments/${appointment.id}/approve-proposal`, {
        method: 'POST',
      }),
    onSuccess: invalidate,
    onError: (e: Error) => setActionError(e.message || 'Genehmigung fehlgeschlagen.'),
  })

  const declineProposal = useMutation({
    mutationFn: () =>
      apiFetch(`/api/appointments/${appointment.id}/decline-proposal`, {
        method: 'POST',
      }),
    onSuccess: invalidate,
    onError: (e: Error) => setActionError(e.message || 'Ablehnen fehlgeschlagen.'),
  })

  const busy =
    confirm.isPending ||
    reject.isPending ||
    proposeAlt.isPending ||
    approveProposal.isPending ||
    declineProposal.isPending
  const altAlreadySent = !!appointment.alternative_proposed_at
  // A customer counter-proposal supersedes the "Alternative gesendet" state —
  // it's the next thing needing a human decision (approve → confirm + call).
  const customerProposed = !!appointment.customer_proposed_at

  const location = appointment.location?.raw ?? null
  const effectiveDuration = customDuration ?? duration

  // Category-aware duration pills: base set + the selected category's default
  // (deduped, sorted) so a category with a non-standard default duration still
  // surfaces it as a selectable pill rather than only via the custom field.
  const durationOptions = useMemo(() => {
    const set = new Set(BASE_DURATIONS)
    const def = selectedCategory?.duration_minutes
    if (def && def > 0) set.add(def)
    return [...set].sort((a, b) => a - b)
  }, [selectedCategory])

  // Completed-action state: after Bestätigen/Ablehnen the row leaves the pending
  // set, but the card stays (parent passes `result`; the row may also carry
  // confirmed_at/rejected_at) as a reminder until removed with ✕.
  // The card STAYS after any decision (no vanish), colour-coded by the CURRENT
  // lifecycle: pending=green, confirmed=dark green, reschedule=orange, cancelled/
  // rejected=dark. Precedence matters: a 'cancelled' status wins over a historical
  // confirmed_at (the appointment was confirmed, then cancelled → show Storniert, not
  // Bestätigt). cancelled_at can be null for pre-migration cancellations, so key the
  // cancelled state off the status, not the timestamp.
  const rejectedDone = result === 'rejected' || !!appointment.rejected_at
  const cancelledDone = !rejectedDone && appointment.status === 'cancelled'
  const confirmedDone = !cancelledDone && !rejectedDone && (result === 'confirmed' || !!appointment.confirmed_at)
  const isDone = confirmedDone || rejectedDone || cancelledDone
  const statusPill = confirmedDone
    ? { label: 'Bestätigt', cls: 'bg-green-primary text-white' }
    : cancelledDone
      ? { label: 'Storniert', cls: 'bg-slate-700 text-white' }
      : rejectedDone
        ? { label: 'Abgelehnt', cls: 'bg-slate-600 text-white' }
        : customerProposed
          ? { label: 'Kundenvorschlag', cls: 'bg-orange-100 text-orange-700' }
          : altAlreadySent
            ? { label: 'Alternative gesendet', cls: 'bg-orange-100 text-orange-700' }
            : { label: 'Wartet auf Bestätigung', cls: 'bg-green-tint-100 text-green-deep' }

  // Collapsed (Ausblenden): one-line summary, click to re-expand.
  if (collapsed) {
    return (
      <div>
        <button
          onClick={() => setCollapsed(false)}
          className="flex w-full items-center justify-between gap-2 rounded-xl border border-green-tint-200 bg-surface px-3.5 py-2.5 text-left hover:bg-alt"
        >
          <span className="flex min-w-0 items-center gap-2">
            <CalendarClock size={14} className="flex-shrink-0 text-green-deep" />
            <span className="truncate text-sm font-semibold text-text">{appointment.title ?? 'Termin nach Telefonat'}</span>
            <span className="flex-shrink-0 text-xs text-muted">· {fmtFullDate(appointment.scheduled_at)}</span>
          </span>
          <span className="flex flex-shrink-0 items-center gap-1.5">
            <span className={cn('rounded-full px-2 py-0.5 text-[11px] font-semibold', statusPill.cls)}>{statusPill.label}</span>
            <ChevronDown size={14} className="text-muted" />
          </span>
        </button>
      </div>
    )
  }

  return (
    <div>
      {/* The "Offene Aktion" section label is rendered once by the parent
          Workspace; this card no longer repeats its own header. */}
      <div className="rounded-xl border border-green-tint-200 bg-surface p-3.5 shadow-sm ring-1 ring-green-tint-100">
        {/* Status pill + remove (✕) on one row. The pill reflects the lifecycle
            (incl. Bestätigt/Abgelehnt); ✕ drops the card from the list. */}
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className={cn('inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold', statusPill.cls)}>
            {confirmedDone ? <CheckCircle2 size={12} className="flex-shrink-0" /> : <Clock size={12} className="flex-shrink-0" />}
            {statusPill.label}
          </span>
          {!isDone && (
            <button
              onClick={onRemove}
              title="Aus der Liste entfernen"
              className="rounded p-1 text-muted transition-colors hover:bg-alt hover:text-error"
            >
              <X size={14} />
            </button>
          )}
        </div>

        {/* Subject is the bold heading; the date/time sits just below it (bold,
            clock icon) so it grabs attention without being the main title. */}
        <div className="text-sm font-bold leading-snug text-text">
          {appointment.title ?? 'Termin nach Telefonat'}
        </div>
        <div className="mt-1.5 flex items-center gap-1.5 text-sm font-semibold text-green-deep">
          <Clock size={13} className="flex-shrink-0" />
          <span>{fmtFullDate(appointment.scheduled_at)}</span>
        </div>

        {/* Up-to-two-line issue summary from the call (calls.summary). */}
        {appointment.issue_summary && (
          <div className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-muted">
            {appointment.issue_summary}
          </div>
        )}

        {location && (
          <div className="mt-1.5 flex items-start gap-1.5 text-xs text-muted">
            <MapPin size={12} className="mt-0.5 flex-shrink-0" />
            <span>{location}</span>
          </div>
        )}

        {/* "Kategorie, Dauer & Zuweisung" — editable while pending, LOCKED (grey,
            not expandable) once confirmed; from then on it's changed in the calendar. */}
        <button
          onClick={() => !confirmedDone && setExpanded((o) => !o)}
          disabled={confirmedDone}
          className={cn(
            'mt-4 flex w-full items-center gap-2 border-t border-border pt-3 text-left text-sm',
            confirmedDone ? 'cursor-default text-muted' : 'text-text hover:text-green-deep',
          )}
          aria-expanded={expanded && !confirmedDone}
        >
          <ChevronDown
            size={14}
            className={cn(
              'text-muted transition-transform',
              expanded && !confirmedDone && 'rotate-180',
            )}
          />
          <span className="flex-1 font-medium">Kategorie, Dauer &amp; Zuweisung</span>
          {(!expanded || confirmedDone) && (
            <span className={cn('text-xs', confirmedDone ? 'text-muted' : 'text-green-deep')}>
              (
              {[selectedCategory?.name ?? appointment.category, `${effectiveDuration} Min`]
                .filter(Boolean)
                .join(', ')}
              )
            </span>
          )}
        </button>

        {expanded && !confirmedDone && (
          <div className="mt-3 space-y-3 rounded-md bg-alt p-3">
            {/* Kategorie */}
            <div>
              <div className="mb-1 text-xs font-semibold text-body">Kategorie</div>
              <select
                value={categoryId}
                onChange={(e) => onPickCategory(e.target.value)}
                disabled={busy || altAlreadySent}
                className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-green-primary disabled:opacity-60"
              >
                <option value="">— Kategorie wählen —</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.duration_minutes} Min)
                  </option>
                ))}
              </select>
              {defaultsApplied && (
                <p className="mt-1 text-[11px] text-muted">
                  Defaults für „{defaultsApplied}" wurden übernommen — du kannst
                  sie unten überschreiben.
                </p>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3">
              {/* Dauer pills */}
              <div>
                <div className="mb-1 text-xs font-semibold text-body">Dauer</div>
                <div className="flex flex-wrap gap-1.5">
                  {durationOptions.map((m) => {
                    const active = customDuration === null && duration === m
                    return (
                      <button
                        key={m}
                        onClick={() => {
                          setDuration(m)
                          setCustomDuration(null)
                          patchAppt.mutate({ duration_minutes: m })
                        }}
                        disabled={busy || altAlreadySent}
                        className={cn(
                          'rounded-md border px-2.5 py-1 text-xs font-medium transition-colors disabled:opacity-60',
                          active
                            ? 'border-green-primary bg-green-primary text-white'
                            : 'border-border bg-surface text-body hover:bg-alt',
                        )}
                      >
                        {m} Min
                      </button>
                    )
                  })}
                </div>
                <div className="mt-1.5 flex items-center gap-1.5">
                  <input
                    type="number"
                    min={5}
                    max={480}
                    placeholder="z. B. 45"
                    value={customDuration ?? ''}
                    onChange={(e) => {
                      const v = e.target.value ? Number(e.target.value) : null
                      setCustomDuration(v && v > 0 ? v : null)
                    }}
                    onBlur={() => {
                      if (customDuration && customDuration > 0) {
                        patchAppt.mutate({ duration_minutes: customDuration })
                      }
                    }}
                    disabled={busy || altAlreadySent}
                    className="w-24 rounded-md border border-border bg-surface px-2 py-1 text-xs text-text outline-none focus:border-green-primary disabled:opacity-60"
                  />
                  <span className="text-[11px] text-muted">Min</span>
                  {customDuration !== null && (
                    <button
                      onClick={() => setCustomDuration(null)}
                      className="text-[11px] text-green-deep underline"
                    >
                      zurücksetzen
                    </button>
                  )}
                </div>
              </div>

              {/* Mitarbeiter dropdown */}
              <div>
                <div className="mb-1 text-xs font-semibold text-body">Mitarbeiter</div>
                <select
                  value={assignedEmployeeId}
                  onChange={(e) => {
                    setAssignedEmployeeId(e.target.value)
                    patchAppt.mutate({ assigned_employee_id: e.target.value || null })
                  }}
                  disabled={busy || altAlreadySent}
                  className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-green-primary disabled:opacity-60"
                >
                  <option value="">— nicht zugewiesen —</option>
                  {employees.map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.display_name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        )}

        {/* Alternative picker (inline; opens via "Alternative vorschlagen" button) */}
        {altPickerOpen && !altAlreadySent && (
          <div className="mt-3 space-y-2 rounded-md border border-info/30 bg-info-bg/50 p-3">
            <div className="text-xs font-semibold text-text">
              Alternativen Termin vorschlagen
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-[11px] font-medium text-muted">Von</label>
                <input
                  type="datetime-local"
                  value={altStart}
                  onChange={(e) => setAltStart(e.target.value)}
                  className="w-full rounded-md border border-border bg-surface px-2 py-1.5 text-xs text-text outline-none focus:border-green-primary"
                />
              </div>
              <div>
                <label className="block text-[11px] font-medium text-muted">Bis</label>
                <input
                  type="datetime-local"
                  value={altEnd}
                  onChange={(e) => setAltEnd(e.target.value)}
                  className="w-full rounded-md border border-border bg-surface px-2 py-1.5 text-xs text-text outline-none focus:border-green-primary"
                />
              </div>
            </div>
            <input
              type="text"
              value={altNote}
              onChange={(e) => setAltNote(e.target.value)}
              placeholder="Notiz an den Kunden (optional)"
              className="w-full rounded-md border border-border bg-surface px-2 py-1.5 text-xs text-text outline-none focus:border-green-primary"
            />
            <div className="flex gap-2 pt-1">
              <button
                onClick={() => proposeAlt.mutate()}
                disabled={busy || !altStart || !altEnd}
                className="flex-1 rounded-md bg-info py-1.5 text-xs font-semibold text-white hover:brightness-110 disabled:opacity-50"
              >
                {proposeAlt.isPending ? 'Sendet…' : 'Alternative senden'}
              </button>
              <button
                onClick={() => setAltPickerOpen(false)}
                disabled={busy}
                className="rounded-md border border-border bg-surface px-3 py-1.5 text-xs font-medium text-body hover:bg-alt"
              >
                Abbrechen
              </button>
            </div>
          </div>
        )}

        {/* Customer counter-proposal (reschedule loop): recorded by the agent on
            the call. Approving applies the slot + fires the confirmation call+email;
            Ablehnen clears it. Takes priority over the "Alternative gesendet" state. */}
        {customerProposed && !isDone && (
          <div className="mt-3 space-y-2 rounded-md border border-amber-300 bg-amber-50 p-3">
            <div className="text-xs font-semibold text-amber-700">
              Kunde schlägt einen neuen Termin vor
            </div>
            <div className="text-sm font-bold text-text">
              {fmtFullDate(appointment.customer_proposed_start_time)}
            </div>
            <p className="text-[11px] text-muted">
              Im Anruf vom Kunden vorgeschlagen. „Genehmigen" verschiebt den Termin
              und bestätigt ihn dem Kunden (Anruf + E-Mail);{' '}
              {appointment.reschedule_replace_intent
                ? '„Ablehnen" storniert den Termin und informiert den Kunden (Anruf + E-Mail) — der Kunde wollte den ursprünglichen Termin nicht behalten.'
                : '„Ablehnen" verwirft nur den Vorschlag; der ursprüngliche Termin bleibt bestehen.'}
            </p>
            <div className="flex flex-wrap gap-1.5 pt-1">
              <button
                onClick={() => {
                  setActionError(null)
                  approveProposal.mutate()
                }}
                disabled={busy}
                className="inline-flex items-center gap-1 rounded-md bg-green-primary px-2.5 py-1.5 text-xs font-semibold text-white transition-colors hover:brightness-110 disabled:opacity-50"
              >
                <CheckCircle2 size={13} />
                {approveProposal.isPending ? 'Genehmigt…' : 'Genehmigen'}
              </button>
              <button
                onClick={() => {
                  setActionError(null)
                  declineProposal.mutate()
                }}
                disabled={busy}
                className="inline-flex items-center gap-1 rounded-md bg-faint px-2.5 py-1.5 text-xs font-medium text-white transition-colors hover:brightness-110 disabled:opacity-50"
              >
                <X size={13} />
                Ablehnen
              </button>
            </div>
          </div>
        )}

        {/* Inline status display for the "Alternative gesendet" lock state */}
        {altAlreadySent && !customerProposed && (
          <div className="mt-3 rounded-md border border-info/30 bg-info-bg/40 p-3 text-xs text-body">
            <div className="font-semibold text-info">Alternative gesendet</div>
            {appointment.alternative_start_time && (
              <div className="mt-1 text-muted">
                Vorgeschlagen: {fmtFullDate(appointment.alternative_start_time)}
              </div>
            )}
            {appointment.alternative_note && (
              <div className="mt-1 italic text-muted">
                „{appointment.alternative_note}"
              </div>
            )}
          </div>
        )}

        {isDone && (
          <div
            className={cn(
              'mt-3 rounded-md border p-3 text-xs',
              confirmedDone ? 'border-green-tint-200 bg-green-tint-50 text-green-deep' : 'border-border bg-alt text-muted',
            )}
          >
            <div className="font-semibold">
              {confirmedDone ? 'Termin bestätigt — im Kalender' : cancelledDone ? 'Termin storniert' : 'Termin abgelehnt'}
            </div>
            {confirmedDone && appointment.scheduled_at ? (
              <button
                onClick={() =>
                  navigate(
                    `/calendar?date=${new Date(appointment.scheduled_at as string).toISOString().slice(0, 10)}&appointment=${appointment.id}`,
                  )
                }
                className="mt-1 font-semibold text-green-deep underline hover:opacity-80"
              >
                Im Kalender öffnen → (Ändern/Verschieben dort)
              </button>
            ) : (
              <div className="mt-0.5">Bleibt als Status in den Aktionen sichtbar.</div>
            )}
          </div>
        )}

        {actionError && (
          <div className="mt-3 rounded-md bg-error-bg px-3 py-2 text-xs text-error">
            {actionError}
          </div>
        )}

        {/* Action buttons — single row (matches the WerkPilot reference):
            Bestätigen · Alternative vorschlagen · Ablehnen · Ausblenden.
            `flex-wrap` lets them flow onto a second line only when the panel
            is dragged narrower than the row needs. Hidden once an alternative
            has been sent (the appointment is locked pending the reply). Also
            hidden while a customer counter-proposal awaits approval. */}
        {!altAlreadySent && !customerProposed && !isDone && (
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <button
              onClick={() => {
                setActionError(null)
                // A confirmed appointment must have an employee assigned. If
                // none is set, open the assignment section and surface why,
                // instead of silently confirming with "— nicht zugewiesen —".
                if (!assignedEmployeeId) {
                  setExpanded(true)
                  setActionError(
                    'Bitte zuerst einen Mitarbeiter zuweisen, bevor der Termin bestätigt wird.',
                  )
                  return
                }
                confirm.mutate()
              }}
              disabled={busy}
              className="inline-flex items-center gap-1 rounded-md bg-green-primary px-2.5 py-1.5 text-xs font-semibold text-white transition-colors hover:brightness-110 disabled:opacity-50"
            >
              <CheckCircle2 size={13} />
              Bestätigen
            </button>
            <button
              onClick={() => {
                setActionError(null)
                setAltPickerOpen((o) => !o)
              }}
              disabled={busy}
              className="inline-flex items-center gap-1 rounded-md bg-green-tint-200 px-2.5 py-1.5 text-xs font-semibold text-green-deep transition-colors hover:brightness-105 disabled:opacity-50"
            >
              <CalendarClock size={13} />
              Alternative vorschlagen
            </button>
            <button
              onClick={() => {
                setActionError(null)
                reject.mutate()
              }}
              disabled={busy}
              className="inline-flex items-center gap-1 rounded-md bg-faint px-2.5 py-1.5 text-xs font-medium text-white transition-colors hover:brightness-110 disabled:opacity-50"
            >
              <X size={13} />
              Ablehnen
            </button>
            <button
              onClick={() => {
                setActionError(null)
                setCollapsed(true)
              }}
              disabled={busy}
              title="Karte einklappen (bleibt als kurze Zeile sichtbar)"
              className="inline-flex items-center gap-1 rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs font-medium text-body transition-colors hover:bg-alt disabled:opacity-50"
            >
              <EyeOff size={13} />
              Ausblenden
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// Stable hook used by CallLogsPage to fetch the pending appointment for a
// call. Exported here so the parent can decide WHETHER to render the card
// (and so the empty-state path doesn't pull in the heavy <AppointmentCard>
// component until needed).
export function usePendingAppointment(callId: string | null) {
  return useQuery({
    queryKey: ['pendingAppointment', callId],
    queryFn: () =>
      apiFetch<PendingAppointmentResponse>(
        `/api/appointments/by-call/${callId}/pending`,
      ),
    enabled: !!callId,
    // 1 minute — pending appointments don't change often; the user-driven
    // mutations explicitly invalidate this key.
    staleTime: 60_000,
  })
}
