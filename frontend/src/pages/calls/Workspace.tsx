// Right workspace pane: header + Aktionen / Details / Verlauf tabs.
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import {
  ArrowRight,
  AtSign,
  CalendarPlus,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Clock,
  ExternalLink,
  FolderInput,
  History,
  Info,
  Layers,
  ListChecks,
  MapPin,
  MoreVertical,
  Pencil,
  Phone,
  PhoneIncoming,
  Receipt,
  RotateCcw,
  Smile,
  Sparkles,
  Target,
  Trash2,
  UserPlus,
  X,
  type LucideIcon,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import { cn, initials } from '../../lib/utils'
import { useMe } from '../../lib/useMe'
import { Tag } from '../../components/ui/Tag'
import { AssignDropdown, Avatar, MoodPill, NotdienstBadge, StatusPill } from './atoms'
import { SectionLabel } from './ui'
import {
  absoluteTimeDe,
  type CallDetailData,
  displayName,
  type Employee,
  fmtTime,
  type Inquiry,
  isMeaningful,
  relativeTimeDe,
  type TimelineEvent,
  type TimelineEventKind,
} from './shared'

// ─── Status switcher (primary) ─────────────────────────────────────────────
const STATUS_OPTS: {
  value: string
  label: string
  Icon: LucideIcon
  border: string
  bg: string
  text: string
  chipOn: string
  chipOff: string
}[] = [
  { value: 'open', label: 'Offen', Icon: CircleDot, border: 'border-info', bg: 'bg-info-bg', text: 'text-info', chipOn: 'bg-info text-white', chipOff: 'bg-info-bg text-info' },
  { value: 'in_progress', label: 'In Bearbeitung', Icon: Clock, border: 'border-warning', bg: 'bg-warning-bg', text: 'text-warning', chipOn: 'bg-warning text-white', chipOff: 'bg-warning-bg text-warning' },
  { value: 'completed', label: 'Erledigt', Icon: CheckCircle2, border: 'border-success', bg: 'bg-success-bg', text: 'text-success', chipOn: 'bg-success text-white', chipOff: 'bg-success-bg text-success' },
]

function StatusSwitcher({ status, onChange, disabled }: { status: string; onChange: (s: string) => void; disabled: boolean }) {
  return (
    <div className="flex gap-2">
      {STATUS_OPTS.map((o) => {
        const active = o.value === status
        return (
          <button
            key={o.value}
            disabled={disabled}
            onClick={() => onChange(o.value)}
            className={cn(
              'relative flex flex-1 flex-col items-center gap-1.5 rounded-xl border-[1.5px] px-1.5 py-3 text-xs font-bold transition disabled:opacity-60',
              active ? cn(o.border, o.bg, o.text, 'shadow-e1') : 'border-border bg-surface text-muted hover:bg-alt',
            )}
          >
            <span className={cn('flex h-[30px] w-[30px] items-center justify-center rounded-full transition', active ? o.chipOn : o.chipOff)}>
              <o.Icon size={16} />
            </span>
            {o.label}
            {active && <CheckCircle2 size={13} className="absolute right-1.5 top-1.5" />}
          </button>
        )
      })}
    </div>
  )
}

// ─── Assignment field ──────────────────────────────────────────────────────
function AssignField({ current, employees, onAssign, disabled }: { current: string | null; employees: Employee[]; onAssign: (id: string | null) => void; disabled: boolean }) {
  const e = employees.find((x) => x.id === current)
  // Only admins may (re)assign — employees see a read-only assignee.
  const { isAdmin } = useMe()
  const locked = disabled || !isAdmin
  return (
    <AssignDropdown current={current} employees={employees} onAssign={onAssign} disabled={locked}>
      <button
        disabled={locked}
        title={!isAdmin ? 'Nur Admins können Mitarbeiter zuweisen' : undefined}
        className="flex w-full items-center gap-3 rounded-xl border border-border bg-surface px-3 py-2.5 disabled:opacity-60"
      >
        <Avatar employeeId={current} text={e ? initials(e.display_name ?? '?') : '—'} size={28} />
        <span className={cn('flex-1 text-left text-[13.5px] font-bold', e ? 'text-text' : 'text-muted')}>
          {e ? e.display_name : 'Nicht zugewiesen'}
        </span>
        <ChevronDown size={16} className="text-faint" />
      </button>
    </AssignDropdown>
  )
}

// ─── Primary action card ───────────────────────────────────────────────────
function PrimaryAction({ icon: Icon, label, tone, onClick, disabled }: { icon: LucideIcon; label: string; tone: 'green' | 'money' | 'steel'; onClick?: () => void; disabled?: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="flex flex-1 flex-col items-start gap-2.5 rounded-2xl border border-border bg-surface p-3.5 text-left transition hover:shadow-e2 disabled:opacity-50 disabled:hover:shadow-none"
    >
      <span className={cn('flex h-[38px] w-[38px] items-center justify-center rounded-xl', tone === 'money' ? 'bg-ai-bg text-ai' : tone === 'steel' ? 'bg-info-bg text-info' : 'bg-green-tint-100 text-green-deep')}>
        <Icon size={19} />
      </span>
      <span className="text-[13px] font-extrabold leading-tight text-text">{label}</span>
    </button>
  )
}

// ─── Overflow kebab (Anruf löschen) ────────────────────────────────────────
function MoreMenu({ onDelete, disabled }: { onDelete: () => void; disabled: boolean }) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild disabled={disabled}>
        <button className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl border border-border bg-surface text-muted disabled:opacity-50">
          <MoreVertical size={18} />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={6} className="z-[60] w-52 rounded-xl border border-border bg-surface p-1.5 shadow-e3">
          <DropdownMenu.Item onSelect={onDelete} className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm font-bold text-error outline-none data-[highlighted]:bg-error-bg">
            <Trash2 size={15} /> Anruf löschen
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}

// ─── Outbound outcome panel (replaces intake actions on outbound calls) ──────
// Spec: an OUTBOUND screen must NOT offer create-appointment / Angebot / change-customer
// (those are inbound intake). It shows a minimal outcome instead.
const OUTCOMES: { key: string; label: string; on: string }[] = [
  { key: 'confirmed', label: 'Bestätigt', on: 'border-success bg-success-bg text-success' },
  { key: 'rescheduled', label: 'Verschoben', on: 'border-warning bg-warning-bg text-warning' },
  { key: 'declined', label: 'Abgelehnt', on: 'border-error bg-error-bg text-error' },
  { key: 'aborted', label: 'Abgebrochen', on: 'border-warning bg-warning-bg text-warning' },
  { key: 'noreach', label: 'Nicht erreicht', on: 'border-border bg-alt text-muted' },
]

function OutcomePanel({ call }: { call: CallDetailData }) {
  const dur = call.duration_seconds
  // Cut-off heuristic (spec): a very short outbound confirmation/reschedule call
  // likely didn't complete → surface "Abgebrochen — nachfassen".
  const cutoff = dur != null && dur < 20
  const inferred = cutoff ? 'aborted' : null
  return (
    <div>
      <SectionLabel>Gesprächsergebnis</SectionLabel>
      <div className="rounded-2xl border border-border bg-surface p-3.5">
        <p className="mb-2.5 text-[12.5px] text-muted">
          Ausgehender Anruf — kein Intake. Ergebnis des Bestätigungs- / Verschiebungsanrufs:
        </p>
        <div className="flex flex-wrap gap-2">
          {OUTCOMES.map((o) => (
            <span
              key={o.key}
              className={cn(
                'rounded-full border px-3 py-1.5 text-xs font-bold',
                inferred === o.key ? o.on : 'border-border bg-surface text-muted',
              )}
            >
              {o.label}
            </span>
          ))}
        </div>
        {cutoff && (
          <div className="mt-3 flex items-center gap-2 rounded-xl border border-warning bg-warning-bg px-3 py-2 text-[12.5px] font-bold text-warning">
            <Clock size={14} className="flex-shrink-0" /> Kurzes Gespräch ({dur}s) — Bestätigung nicht abgeschlossen, nachfassen.
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Triage (moved here from the Posteingang inbox) ────────────────────────
export type MoveCandidate = { inquiryId: string; label: string; ticket: string | null }
function TriageSection({
  candidates,
  onMoveToInquiry,
  onSpam,
  busy,
}: {
  candidates: MoveCandidate[]
  onMoveToInquiry: (inquiryId: string) => void
  onSpam: () => void
  busy: boolean
}) {
  const [picking, setPicking] = useState(false)
  return (
    <div>
      <SectionLabel>Zuordnung</SectionLabel>
      <div className="flex flex-col gap-2">
        {candidates.length > 0 && (
          <>
            <button
              onClick={() => setPicking((p) => !p)}
              disabled={busy}
              className="flex items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2.5 text-[13px] font-bold text-body transition hover:bg-alt disabled:opacity-50"
            >
              <FolderInput size={16} className="text-green-deep" />
              <span className="flex-1 text-left">Anderem Vorgang zuordnen</span>
              <ChevronDown size={16} className={cn('text-faint transition-transform', picking && 'rotate-180')} />
            </button>
            {picking && (
              <div className="flex flex-col gap-1.5">
                {candidates.map((c) => (
                  <button
                    key={c.inquiryId}
                    onClick={() => {
                      onMoveToInquiry(c.inquiryId)
                      setPicking(false)
                    }}
                    className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-left text-[13px] text-text transition hover:bg-green-tint-50"
                  >
                    <Layers size={14} className="flex-shrink-0 text-green-deep" />
                    <span className="flex-1 truncate">{c.label}</span>
                    {c.ticket && <span className="flex-shrink-0 font-mono text-[11px] text-muted">{c.ticket}</span>}
                  </button>
                ))}
              </div>
            )}
          </>
        )}
        <button
          onClick={onSpam}
          disabled={busy}
          className="flex items-center justify-center gap-2 rounded-xl border border-border bg-surface py-2.5 text-[13px] font-bold text-error transition hover:bg-error-bg disabled:opacity-50"
        >
          <Trash2 size={15} /> Als Spam markieren
        </button>
      </div>
    </div>
  )
}

// ─── Aktionen tab ──────────────────────────────────────────────────────────
function ActionsTab({
  call,
  inquiry,
  employees,
  status,
  busy,
  appointmentSlot,
  candidates,
  onStatus,
  onDelete,
  onAssign,
  onEdit,
  onAppointment,
  onKva,
  onMoveToInquiry,
  onSpam,
}: {
  call: CallDetailData
  inquiry: Inquiry | undefined
  employees: Employee[]
  status: string
  busy: boolean
  appointmentSlot?: ReactNode
  candidates: MoveCandidate[]
  onStatus: (s: string) => void
  onDelete: () => void
  onAssign: (id: string | null) => void
  onEdit: () => void
  onAppointment: () => void
  onKva?: () => void
  onMoveToInquiry: (inquiryId: string) => void
  onSpam: () => void
}) {
  const isOutbound = call.direction === 'outbound'
  return (
    <div className="flex flex-col gap-5">
      <div>
        <SectionLabel>Status</SectionLabel>
        <StatusSwitcher status={status} onChange={onStatus} disabled={busy || !inquiry} />
      </div>
      <div>
        <SectionLabel>Zugewiesen an</SectionLabel>
        <AssignField current={inquiry?.assigned_employee_id ?? null} employees={employees} onAssign={onAssign} disabled={busy || !inquiry} />
      </div>
      {isOutbound ? (
        <OutcomePanel call={call} />
      ) : (
        <>
          {appointmentSlot && (
            <div>
              <SectionLabel>Offene Aktion</SectionLabel>
              {appointmentSlot}
            </div>
          )}
          <div>
            <SectionLabel>Aufgabe erstellen</SectionLabel>
            <div className="flex gap-2.5">
              <PrimaryAction icon={CalendarPlus} label="Termin erstellen" tone="green" onClick={onAppointment} />
              <PrimaryAction icon={Receipt} label="Angebot" tone="money" onClick={onKva} disabled={!onKva} />
            </div>
            {/* Techniker-Einsatz: lebt am bestätigten Termin (Kalender →
                Termin-Details → „Techniker einsetzen“), nicht am Anrufprotokoll. */}
          </div>
        </>
      )}
      <TriageSection candidates={candidates} onMoveToInquiry={onMoveToInquiry} onSpam={onSpam} busy={busy} />
      <div>
        <SectionLabel>Weitere</SectionLabel>
        <div className="flex gap-2.5">
          <button
            onClick={onEdit}
            disabled={!inquiry}
            className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-border bg-surface py-3 text-sm font-bold text-body hover:bg-alt disabled:opacity-50"
          >
            <Pencil size={16} /> Bearbeiten
          </button>
          <MoreMenu onDelete={onDelete} disabled={busy} />
        </div>
      </div>
    </div>
  )
}

// ─── Collapsibles (Details tab) ────────────────────────────────────────────
function Collapsible({ title, icon: Icon, accent = false, defaultOpen = false, children }: { title: string; icon: LucideIcon; accent?: boolean; defaultOpen?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className={cn('overflow-hidden rounded-2xl border', accent ? 'border-ai-bg bg-ai-bg' : 'border-border bg-surface')}>
      <button onClick={() => setOpen((o) => !o)} className={cn('flex w-full items-center gap-2.5 px-3.5 py-3 text-[13px] font-extrabold', accent ? 'text-ai' : 'text-text')}>
        <Icon size={15} />
        <span className="flex-1 text-left">{title}</span>
        <ChevronDown size={16} className={cn('text-faint transition-transform', open && 'rotate-180')} />
      </button>
      {open && <div className="px-3.5 pb-3.5">{children}</div>}
    </div>
  )
}

// Header-button section whose content reveals BELOW (Kontaktdaten/Erfasste/Info).
function CollapsibleSection({ title, icon: Icon, count, defaultOpen = false, children }: { title: string; icon: LucideIcon; count?: number; defaultOpen?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div>
      <button
        onClick={() => setOpen((o) => !o)}
        className={cn('flex w-full items-center gap-2.5 rounded-xl border border-border px-3 py-2.5 transition-colors', open ? 'bg-green-tint-50' : 'bg-surface hover:bg-alt')}
      >
        <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg bg-green-tint-100 text-green-deep">
          <Icon size={15} />
        </span>
        <span className="flex-1 text-left text-[12.5px] font-extrabold text-text">{title}</span>
        {count != null && <span className="text-[11px] font-bold text-faint">{count}</span>}
        <ChevronDown size={16} className={cn('text-faint transition-transform', open && 'rotate-180')} />
      </button>
      {open && <div className="mt-2.5">{children}</div>}
    </div>
  )
}

function ContactRow({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: string }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-border bg-green-tint-50 px-3 py-2.5">
      <span className="flex h-[34px] w-[34px] flex-shrink-0 items-center justify-center rounded-lg bg-green-tint-100 text-green-deep">
        <Icon size={16} />
      </span>
      <div className="min-w-0">
        <div className="text-[10.5px] font-extrabold uppercase tracking-wider text-muted">{label}</div>
        <div className="truncate text-[13.5px] font-bold text-text">{value}</div>
      </div>
    </div>
  )
}

function DataRow({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <Icon size={15} className="mt-0.5 flex-shrink-0 text-faint" />
      <div className="min-w-0 flex-1">
        <div className="mb-0.5 text-[10.5px] font-extrabold uppercase tracking-wider text-faint">{label}</div>
        <div className="text-[13.5px] font-semibold text-text">{value}</div>
      </div>
    </div>
  )
}

function DetailsTab({ call, onOpenCustomer }: { call: CallDetailData; onOpenCustomer: () => void }) {
  const dc = call.data_collection ?? {}
  const c = call.customers
  const phone = isMeaningful(c?.phone) ? c!.phone! : isMeaningful(call.caller_number) ? call.caller_number! : null
  const contacts: { icon: LucideIcon; label: string; value: string }[] = []
  if (phone) contacts.push({ icon: Phone, label: 'Telefon', value: phone })
  if (isMeaningful(c?.email)) contacts.push({ icon: AtSign, label: 'E-Mail', value: c!.email! })
  if (isMeaningful(dc.customer_address)) contacts.push({ icon: MapPin, label: 'Adresse', value: dc.customer_address! })
  contacts.push({ icon: Phone, label: 'Kanal', value: 'Telefon' })

  return (
    <div className="flex flex-col gap-3.5">
      <Collapsible title="Zusammenfassung" icon={Sparkles} accent defaultOpen>
        <p className="text-[13px] leading-relaxed text-body">{call.summary ?? 'Keine Zusammenfassung.'}</p>
        {dc.ultimate_summary && (
          <details className="mt-2.5">
            <summary className="inline-flex cursor-pointer items-center gap-1.5 text-[12.5px] font-extrabold text-ai">
              <ChevronRight size={13} /> Vollständige Zusammenfassung
            </summary>
            <pre className="mt-2 whitespace-pre-wrap font-sans text-[13px] leading-relaxed text-body">{dc.ultimate_summary}</pre>
          </details>
        )}
      </Collapsible>

      <div>
        <SectionLabel
          right={
            call.customer_id ? (
              <button onClick={onOpenCustomer} className="inline-flex items-center gap-1 text-xs font-extrabold text-green-deep hover:underline">
                Profil öffnen <ExternalLink size={12} />
              </button>
            ) : undefined
          }
        >
          Kunde
        </SectionLabel>
        <button
          onClick={call.customer_id ? onOpenCustomer : undefined}
          className={cn('flex w-full items-center gap-3 rounded-2xl border border-border bg-surface p-3 text-left', call.customer_id && 'hover:bg-green-tint-50')}
        >
          <span className="flex h-[42px] w-[42px] flex-shrink-0 items-center justify-center rounded-full bg-green-tint-100 text-[15px] font-extrabold text-green-deep">
            {initials(displayName(call))}
          </span>
          <div className="min-w-0 flex-1">
            <div className="truncate text-[14.5px] font-extrabold text-text">
              {isMeaningful(c?.full_name) ? c!.full_name : displayName(call)}
            </div>
            {c?.customer_number && <div className="font-mono text-xs text-muted">#{c.customer_number}</div>}
          </div>
        </button>
      </div>

      <CollapsibleSection title="Kontaktdaten" icon={AtSign} count={contacts.length}>
        <div className="flex flex-col gap-2.5">
          {contacts.map((ct, i) => (
            <ContactRow key={i} icon={ct.icon} label={ct.label} value={ct.value} />
          ))}
        </div>
      </CollapsibleSection>

      {(isMeaningful(dc.issue_summary) || isMeaningful(dc.customer_sentiment) || isMeaningful(dc.next_action)) && (
        <CollapsibleSection title="Erfasste Daten" icon={Target} defaultOpen>
          <div className="flex flex-col gap-3.5 rounded-2xl border border-border bg-surface p-3.5">
            {isMeaningful(dc.issue_summary) && <DataRow icon={Target} label="Betreff" value={dc.issue_summary!} />}
            {isMeaningful(dc.customer_sentiment) && <DataRow icon={Smile} label="Stimmung" value={<MoodPill mood={dc.customer_sentiment!} />} />}
            {isMeaningful(dc.next_action) && <DataRow icon={ArrowRight} label="Nächste Schritte" value={dc.next_action!} />}
          </div>
        </CollapsibleSection>
      )}

      <CollapsibleSection title="Anfrage-Info" icon={Info}>
        <div className="flex flex-col gap-2.5 rounded-2xl border border-border bg-surface p-3.5 text-[12.5px] text-muted">
          <Row label="Erstellt" value={fmtTime(call.started_at)} />
          <Row label="Von" value="KI-Telefonassistent" />
          <Row label="Richtung" value={call.direction === 'outbound' ? 'Ausgehend' : 'Eingehend'} />
        </div>
      </CollapsibleSection>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <span>{label}</span>
      <span className="font-semibold text-text">{value}</span>
    </div>
  )
}

// ─── Verlauf tab (icon-tile timeline) ──────────────────────────────────────
const TL_KIND: Record<TimelineEventKind, { Icon: LucideIcon; tile: string }> = {
  call_created: { Icon: PhoneIncoming, tile: 'bg-green-tint-100 text-green-deep' },
  inquiry_status_changed: { Icon: Clock, tile: 'bg-warning-bg text-warning' },
  appointment_created: { Icon: CalendarPlus, tile: 'bg-green-tint-100 text-green-deep' },
  appointment_rescheduled: { Icon: RotateCcw, tile: 'bg-warning-bg text-warning' },
  appointment_confirmed: { Icon: CheckCircle2, tile: 'bg-success-bg text-success' },
  appointment_rejected: { Icon: X, tile: 'bg-error-bg text-error' },
  appointment_cancelled: { Icon: X, tile: 'bg-error-bg text-error' },
  alternative_proposed: { Icon: CalendarPlus, tile: 'bg-warning-bg text-warning' },
  kva_sent: { Icon: Receipt, tile: 'bg-ai-bg text-ai' },
  kva_accepted: { Icon: Receipt, tile: 'bg-ai-bg text-ai' },
  kva_rejected: { Icon: Receipt, tile: 'bg-ai-bg text-ai' },
  assignment_changed: { Icon: UserPlus, tile: 'bg-info-bg text-info' },
}

function VerlaufTab({ events, isLoading }: { events: TimelineEvent[]; isLoading: boolean }) {
  if (isLoading) return <p className="text-sm text-muted">Lade Verlauf …</p>
  if (!events.length) return <p className="text-sm text-muted">Keine Verlaufs-Einträge.</p>
  return (
    <div className="flex flex-col">
      {events.map((ev, i) => {
        const k = TL_KIND[ev.kind] ?? { Icon: Info, tile: 'bg-alt text-muted' }
        const last = i === events.length - 1
        return (
          <div key={ev.id} className={cn('relative flex items-start gap-3.5', !last && 'pb-5')}>
            {!last && <span className="absolute bottom-0 left-[19px] top-[42px] w-0.5 bg-border" aria-hidden />}
            <span className={cn('z-[1] flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full', k.tile)}>
              <k.Icon size={18} />
            </span>
            <div className="min-w-0 flex-1 pt-0.5">
              <div className="text-sm font-bold leading-snug text-text">{ev.description}</div>
              <div className="mt-0.5 text-[12.5px] text-muted" title={absoluteTimeDe(ev.timestamp)}>
                {relativeTimeDe(ev.timestamp)} · {ev.actor_name}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ─── Workspace shell ───────────────────────────────────────────────────────
export function Workspace({
  call,
  inquiry,
  employees,
  busy,
  emergency,
  tab,
  setTab,
  timeline,
  timelineLoading,
  appointmentSlot,
  candidates,
  onStatus,
  onDelete,
  onAssign,
  onEdit,
  onAppointment,
  onKva,
  onOpenCustomer,
  onMoveToInquiry,
  onSpam,
}: {
  call: CallDetailData
  inquiry: Inquiry | undefined
  employees: Employee[]
  busy: boolean
  emergency: boolean
  tab: 'actions' | 'details' | 'course'
  setTab: (t: 'actions' | 'details' | 'course') => void
  timeline: TimelineEvent[]
  timelineLoading: boolean
  appointmentSlot?: ReactNode
  candidates: MoveCandidate[]
  onStatus: (s: string) => void
  onDelete: () => void
  onAssign: (id: string | null) => void
  onEdit: () => void
  onAppointment: () => void
  onKva?: () => void
  onOpenCustomer: () => void
  onMoveToInquiry: (inquiryId: string) => void
  onSpam: () => void
}) {
  const status = inquiry?.status ?? 'open'
  const navigate = useNavigate()
  const vgNumber = inquiry?.number ?? call.inquiry_number ?? null
  const vgSubject = inquiry?.subject ?? call.inquiry_subject ?? null
  // The grouping = the Fall (Case), now on case_id. An ungrouped call shows its
  // own Anfrage (inquiry). project_id is the optional top-layer Projekt (PR-).
  const caseId = call.case_id
  const projectId = call.project_id
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col bg-surface">
      <div className="px-[18px] pt-4">
        <div className="mb-2.5 flex items-start gap-2.5">
          {emergency && <span className="mt-0.5"><NotdienstBadge small /></span>}
          <h2 className="text-[15.5px] font-extrabold leading-snug text-text">
            {inquiry?.title ?? call.summary_title ?? 'Anruf'}
          </h2>
        </div>
        <div className="mb-2.5 flex flex-wrap gap-1.5">
          <StatusPill status={status} />
          {inquiry?.type && <Tag variant="green">{inquiry.type}</Tag>}
        </div>
        {caseId ? (
          <div className="mb-3.5 flex flex-wrap items-center gap-1.5">
            <button
              onClick={() => navigate(`/fall/${caseId}`)}
              title="Zum Vorgang (alle Anfragen, Termine, Angebot, Rechnungen, Techniker)"
              className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-ai-bg bg-ai-bg px-2.5 py-1.5 text-xs font-bold text-ai transition hover:brightness-95"
            >
              <Layers size={13} className="flex-shrink-0" />
              <span className="truncate">
                Vorgang {call.case_number ?? ''}
                {call.case_label ? ` · ${call.case_label}` : ''}
              </span>
              <ChevronRight size={13} className="flex-shrink-0" />
            </button>
            {projectId && (
              <button
                onClick={() => navigate(`/projects/${projectId}`)}
                title="Zum Projekt (übergeordnet)"
                className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-border bg-alt px-2.5 py-1.5 text-xs font-bold text-muted transition-colors hover:border-green-primary hover:text-green-deep"
              >
                <Layers size={13} className="flex-shrink-0" />
                <span className="truncate">Projekt {call.project_number ?? ''}</span>
              </button>
            )}
          </div>
        ) : call.inquiry_id ? (
          <button
            onClick={() => navigate(`/vorgang/${call.inquiry_id}`)}
            title="Zur Anfrage"
            className="mb-3.5 inline-flex max-w-full items-center gap-1.5 rounded-lg border border-border bg-alt px-2.5 py-1.5 text-xs font-bold text-muted transition-colors hover:border-green-primary hover:text-green-deep"
          >
            <ListChecks size={13} className="flex-shrink-0" />
            <span className="truncate">
              Anfrage {vgNumber ?? ''}
              {vgSubject ? ` · ${vgSubject}` : ''}
            </span>
            <ChevronRight size={13} className="flex-shrink-0" />
          </button>
        ) : null}
      </div>

      <div className="flex gap-1 border-b border-border px-3.5">
        {([['actions', 'Aktionen', ListChecks], ['details', 'Details', Info], ['course', 'Verlauf', History]] as const).map(
          ([v, label, Ic]) => {
            const active = tab === v
            return (
              <button
                key={v}
                onClick={() => setTab(v)}
                className={cn(
                  '-mb-px inline-flex items-center gap-1.5 border-b-[2.5px] px-3 py-2.5 text-[13px] font-bold transition-colors',
                  active ? 'border-green-primary text-green-deep' : 'border-transparent text-muted hover:text-body',
                )}
              >
                <Ic size={15} />
                {label}
              </button>
            )
          },
        )}
      </div>

      <div className="scroll flex-1 overflow-y-auto p-[18px]">
        {tab === 'actions' && (
          <ActionsTab
            call={call}
            inquiry={inquiry}
            employees={employees}
            status={status}
            busy={busy}
            appointmentSlot={appointmentSlot}
            candidates={candidates}
            onStatus={onStatus}
            onDelete={onDelete}
            onAssign={onAssign}
            onEdit={onEdit}
            onAppointment={onAppointment}
            onKva={onKva}
            onMoveToInquiry={onMoveToInquiry}
            onSpam={onSpam}
          />
        )}
        {tab === 'details' && <DetailsTab call={call} onOpenCustomer={onOpenCustomer} />}
        {tab === 'course' && <VerlaufTab events={timeline} isLoading={timelineLoading} />}
      </div>
    </div>
  )
}
