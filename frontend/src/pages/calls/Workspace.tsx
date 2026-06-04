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
  History,
  Info,
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
  { value: 'in_progress', label: 'In Arbeit', Icon: Clock, border: 'border-warning', bg: 'bg-warning-bg', text: 'text-warning', chipOn: 'bg-warning text-white', chipOff: 'bg-warning-bg text-warning' },
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
function PrimaryAction({ icon: Icon, label, tone, onClick, disabled }: { icon: LucideIcon; label: string; tone: 'green' | 'money'; onClick?: () => void; disabled?: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="flex flex-1 flex-col items-start gap-2.5 rounded-2xl border border-border bg-surface p-3.5 text-left transition hover:shadow-e2 disabled:opacity-50 disabled:hover:shadow-none"
    >
      <span className={cn('flex h-[38px] w-[38px] items-center justify-center rounded-xl', tone === 'money' ? 'bg-ai-bg text-ai' : 'bg-green-tint-100 text-green-deep')}>
        <Icon size={19} />
      </span>
      <span className="text-[13px] font-extrabold leading-tight text-text">{label}</span>
    </button>
  )
}

// ─── Overflow kebab (Bearbeiten / Wieder öffnen / Anfrage löschen) ─────────
function MoreMenu({ onEdit, onReopen, onDelete, disabled }: { onEdit: () => void; onReopen: () => void; onDelete: () => void; disabled: boolean }) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild disabled={disabled}>
        <button className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl border border-border bg-surface text-muted disabled:opacity-50">
          <MoreVertical size={18} />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={6} className="z-[60] w-52 rounded-xl border border-border bg-surface p-1.5 shadow-e3">
          <DropdownMenu.Item onSelect={onEdit} className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm font-bold text-body outline-none data-[highlighted]:bg-alt">
            <Pencil size={15} /> Bearbeiten
          </DropdownMenu.Item>
          <DropdownMenu.Item onSelect={onReopen} className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm font-bold text-body outline-none data-[highlighted]:bg-alt">
            <RotateCcw size={15} /> Wieder öffnen
          </DropdownMenu.Item>
          <DropdownMenu.Separator className="my-1 h-px bg-border" />
          <DropdownMenu.Item onSelect={onDelete} className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm font-bold text-error outline-none data-[highlighted]:bg-error-bg">
            <Trash2 size={15} /> Anruf löschen
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}

// ─── Aktionen tab ──────────────────────────────────────────────────────────
function ActionsTab({
  inquiry,
  employees,
  status,
  busy,
  appointmentSlot,
  onStatus,
  onDelete,
  onAssign,
  onEdit,
  onAppointment,
  onKva,
}: {
  inquiry: Inquiry | undefined
  employees: Employee[]
  status: string
  busy: boolean
  appointmentSlot?: ReactNode
  onStatus: (s: string) => void
  onDelete: () => void
  onAssign: (id: string | null) => void
  onEdit: () => void
  onAppointment: () => void
  onKva?: () => void
}) {
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
      {appointmentSlot && (
        <div>
          <SectionLabel>Offene Aktion</SectionLabel>
          {appointmentSlot}
        </div>
      )}
      <div>
        <SectionLabel>Aktion erstellen</SectionLabel>
        <div className="flex gap-2.5">
          <PrimaryAction icon={CalendarPlus} label="Termin erstellen" tone="green" onClick={onAppointment} />
          <PrimaryAction icon={Receipt} label="Kostenvoranschlag" tone="money" onClick={onKva} disabled={!onKva} />
        </div>
      </div>
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
          <MoreMenu onEdit={onEdit} onReopen={() => onStatus('open')} onDelete={onDelete} disabled={busy} />
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
  appointment_confirmed: { Icon: CheckCircle2, tile: 'bg-success-bg text-success' },
  appointment_rejected: { Icon: X, tile: 'bg-error-bg text-error' },
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
  onStatus,
  onDelete,
  onAssign,
  onEdit,
  onAppointment,
  onKva,
  onOpenCustomer,
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
  onStatus: (s: string) => void
  onDelete: () => void
  onAssign: (id: string | null) => void
  onEdit: () => void
  onAppointment: () => void
  onKva?: () => void
  onOpenCustomer: () => void
}) {
  const status = inquiry?.status ?? 'open'
  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <div className="px-[18px] pt-4">
        <div className="mb-2.5 flex items-start gap-2.5">
          {emergency && <span className="mt-0.5"><NotdienstBadge small /></span>}
          <h2 className="text-[15.5px] font-extrabold leading-snug text-text">
            {inquiry?.title ?? call.summary_title ?? 'Anruf'}
          </h2>
        </div>
        <div className="mb-3.5 flex flex-wrap gap-1.5">
          <StatusPill status={status} />
          {inquiry?.type && <Tag variant="green">{inquiry.type}</Tag>}
        </div>
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
            inquiry={inquiry}
            employees={employees}
            status={status}
            busy={busy}
            appointmentSlot={appointmentSlot}
            onStatus={onStatus}
            onDelete={onDelete}
            onAssign={onAssign}
            onEdit={onEdit}
            onAppointment={onAppointment}
            onKva={onKva}
          />
        )}
        {tab === 'details' && <DetailsTab call={call} onOpenCustomer={onOpenCustomer} />}
        {tab === 'course' && <VerlaufTab events={timeline} isLoading={timelineLoading} />}
      </div>
    </div>
  )
}
