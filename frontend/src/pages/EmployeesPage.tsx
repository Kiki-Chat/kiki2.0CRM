import deLocale from '@fullcalendar/core/locales/de'
import dayGridPlugin from '@fullcalendar/daygrid'
import interactionPlugin from '@fullcalendar/interaction'
import listPlugin from '@fullcalendar/list'
import FullCalendar from '@fullcalendar/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BarChart3,
  CalendarDays,
  CircleCheck,
  ClipboardList,
  KeyRound,
  Link2,
  Mail,
  Pencil,
  Plus,
  RefreshCw,
  RotateCw,
  Search,
  Shield,
  Trash2,
  Upload,
  Users,
} from 'lucide-react'
import { useMemo, useState } from 'react'

import { CsvImportModal } from '../components/CsvImportModal'
import { Modal } from '../components/ui/Modal'
import { apiFetch } from '../lib/api'
import { cn } from '../lib/utils'

// ─── Types ───────────────────────────────────────────────────────────────────
interface Employee {
  id: string
  display_name: string | null
  email: string | null
  has_login: boolean
  access_role: 'admin' | 'employee'
  is_active: boolean
  is_org_owner: boolean
  calendar_color: string | null
  vacation_days_per_year: number
  remaining_vacation_days: number | null
  hourly_rate: number | null
  activity_area: string | null
  auto_assign: boolean
  present: boolean
  absence_type: string | null
}

type Tab = 'employees' | 'overview' | 'calendar' | 'applications'

const TABS: { id: Tab; label: string; icon: typeof Users; disabled?: boolean }[] = [
  { id: 'employees', label: 'Mitarbeiter', icon: Users },
  { id: 'overview', label: 'Übersicht', icon: BarChart3 },
  { id: 'calendar', label: 'Kalender', icon: CalendarDays },
  { id: 'applications', label: 'Anträge', icon: ClipboardList },
]

const COLOR_SWATCHES = [
  '#2D6B3D', '#4A9B3F', '#1E4D2B', '#0891B2', '#2563EB', '#1E3A8A',
  '#7C3AED', '#DB2777', '#DC2626', '#D97706', '#64748B',
]

// Absence types — single source of truth for labels + colours.
const ABSENCE_META: Record<string, { label: string; color: string }> = {
  vacation: { label: 'Urlaub', color: '#2D9D5C' },
  illness: { label: 'Krankheit', color: '#DC2626' },
  training: { label: 'Weiterbildung', color: '#2563EB' },
  home_office: { label: 'Homeoffice', color: '#D97706' },
  other: { label: 'Sonstiges', color: '#64748B' },
}
const ABSENCE_TYPES = Object.entries(ABSENCE_META).map(([key, v]) => ({ key, label: v.label }))

interface Absence {
  id: string
  employee_id: string
  employee_name: string | null
  calendar_color: string | null
  type: string
  starts_at: string
  ends_at: string
  all_day: boolean
  reason: string | null
}

function AbsenceLegend() {
  return (
    <div className="flex flex-wrap items-center gap-4 text-xs text-body">
      {Object.values(ABSENCE_META).map((m) => (
        <span key={m.label} className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: m.color }} />
          {m.label}
        </span>
      ))}
    </div>
  )
}

export function EmployeesPage() {
  const qc = useQueryClient()
  const [tab, setTab] = useState<Tab>('employees')
  const [newOpen, setNewOpen] = useState(false)
  const [csvOpen, setCsvOpen] = useState(false)
  const [newAbsenceOpen, setNewAbsenceOpen] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const flash = (m: string) => {
    setToast(m)
    setTimeout(() => setToast(null), 6000)
  }

  const isAbsenceTab = tab === 'calendar' || tab === 'applications'

  return (
    <div className="p-8">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <Users size={26} className="text-green-primary" />
          <div>
            <h1 className="text-2xl font-bold text-text">Mitarbeiter</h1>
            <p className="mt-0.5 text-sm text-muted">
              {isAbsenceTab
                ? 'Abwesenheiten und Urlaubsplanung'
                : 'Mitarbeiterkonten und Zugriffsrechte verwalten'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {isAbsenceTab ? (
            <>
              <button
                onClick={() => {
                  qc.invalidateQueries({ queryKey: ['absences'] })
                  qc.invalidateQueries({ queryKey: ['employees-full'] })
                  flash('Aktualisiert.')
                }}
                title="Aktualisieren"
                className="rounded-md border border-border bg-surface p-2 text-body hover:bg-alt"
              >
                <RotateCw size={16} />
              </button>
              <button
                onClick={() => setNewAbsenceOpen(true)}
                className="inline-flex items-center gap-2 rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110"
              >
                <Plus size={16} /> Neue Abwesenheit
              </button>
            </>
          ) : (
            <div className="flex items-center gap-2">
              <button
                onClick={() => setCsvOpen(true)}
                className="inline-flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-2 text-sm font-medium text-body hover:bg-alt"
              >
                <Upload size={15} /> CSV Import
              </button>
              <button
                onClick={() => setNewOpen(true)}
                className="inline-flex items-center gap-2 rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110"
              >
                <Plus size={16} /> Neuer Mitarbeiter
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="mb-6 flex gap-1 border-b border-border">
        {TABS.map((t) => (
          <button
            key={t.id}
            disabled={t.disabled}
            onClick={() => !t.disabled && setTab(t.id)}
            className={cn(
              'flex items-center gap-1.5 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors',
              tab === t.id
                ? 'border-green-primary text-green-deep'
                : 'border-transparent text-muted hover:text-body',
              t.disabled && 'cursor-not-allowed opacity-40',
            )}
          >
            <t.icon size={15} />
            {t.label}
            {t.disabled && <span className="ml-1 text-[10px]">(bald)</span>}
          </button>
        ))}
      </div>

      {toast && (
        <div className="mb-3 rounded-md bg-green-tint-50 px-3 py-2 text-sm font-medium text-green-deep">
          {toast}
        </div>
      )}

      {tab === 'employees' && <EmployeesTab flash={flash} />}
      {tab === 'overview' && <OverviewTab />}
      {tab === 'calendar' && <AbsenceCalendarTab />}
      {tab === 'applications' && <AntraegeTab />}

      {newOpen && <NewEmployeeModal flash={flash} onClose={() => setNewOpen(false)} />}
      {csvOpen && (
        <CsvImportModal
          entity="employees"
          onClose={() => setCsvOpen(false)}
          onDone={() => qc.invalidateQueries({ queryKey: ['employees-full'] })}
        />
      )}
      {newAbsenceOpen && (
        <NewAbsenceModal
          flash={flash}
          onClose={() => setNewAbsenceOpen(false)}
          onSaved={() => {
            qc.invalidateQueries({ queryKey: ['absences'] })
            qc.invalidateQueries({ queryKey: ['employees-full'] })
            setNewAbsenceOpen(false)
          }}
        />
      )}
    </div>
  )
}

// ─── Mitarbeiter tab (list) ──────────────────────────────────────────────────
function EmployeesTab({ flash }: { flash: (m: string) => void }) {
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [editing, setEditing] = useState<Employee | null>(null)
  const [absenceFor, setAbsenceFor] = useState<Employee | null>(null)
  const [permsFor, setPermsFor] = useState<Employee | null>(null)
  const [passwordFor, setPasswordFor] = useState<Employee | null>(null)

  const { data: employees = [], isLoading, error } = useQuery({
    queryKey: ['employees-full'],
    queryFn: () => apiFetch<Employee[]>('/api/employees'),
  })

  const del = useMutation({
    mutationFn: (id: string) => apiFetch(`/api/employees/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['employees-full'] })
      flash('Mitarbeiter entfernt.')
    },
    onError: (e: Error) => flash(e.message),
  })
  const resend = useMutation({
    mutationFn: (id: string) => apiFetch(`/api/employees/${id}/resend-invite`, { method: 'POST' }),
    onSuccess: (_d, id) => {
      const e = employees.find((x) => x.id === id)
      flash(`Einladung erneut an ${e?.email ?? 'den Mitarbeiter'} versendet`)
    },
    onError: (e: Error) => flash(e.message),
  })

  const filtered = employees.filter(
    (e) =>
      !q ||
      e.display_name?.toLowerCase().includes(q.toLowerCase()) ||
      e.email?.toLowerCase().includes(q.toLowerCase()),
  )

  return (
    <div>
      <div className="relative mb-4">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Mitarbeiter suchen…"
          className="w-full rounded-md border border-border bg-surface py-2.5 pl-9 pr-3 text-sm text-text outline-none focus:border-green-primary"
        />
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs font-semibold uppercase tracking-wide text-muted">
              <th className="px-5 py-3">Name</th>
              <th className="px-5 py-3">E-Mail</th>
              <th className="px-5 py-3">Zugang</th>
              <th className="px-5 py-3">Rolle</th>
              <th className="px-5 py-3">Anwesenheit</th>
              <th className="px-5 py-3">Urlaub</th>
              <th className="px-5 py-3 text-right">Aktionen</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((e) => (
              <tr key={e.id} className="border-b border-border-faint last:border-0">
                <td className="px-5 py-3.5">
                  <div className="flex items-center gap-2">
                    {e.calendar_color && (
                      <span className="h-2.5 w-2.5 rounded-full" style={{ background: e.calendar_color }} />
                    )}
                    <span className="font-semibold text-text">{e.display_name ?? '—'}</span>
                  </div>
                </td>
                <td className="px-5 py-3.5 text-body">{e.email ?? '—'}</td>
                <td className="px-5 py-3.5">
                  {e.has_login ? (
                    <span className="inline-flex items-center gap-1 text-green-deep">
                      <Link2 size={13} /> Login
                    </span>
                  ) : (
                    <span className="text-muted">Kein Login</span>
                  )}
                </td>
                <td className="px-5 py-3.5">
                  <span
                    className={cn(
                      'rounded-full px-2.5 py-0.5 text-xs font-medium',
                      e.access_role === 'admin' ? 'bg-ai-bg text-ai' : 'bg-alt text-muted',
                    )}
                  >
                    {e.access_role === 'admin' ? 'Admin' : 'Mitarbeiter'}
                  </span>
                </td>
                <td className="px-5 py-3.5">
                  <span
                    className={cn(
                      'rounded-full px-2.5 py-0.5 text-xs font-medium',
                      e.present ? 'bg-success-bg text-success' : 'bg-error-bg text-error',
                    )}
                  >
                    {e.present ? 'Anwesend' : 'Abwesend'}
                  </span>
                </td>
                <td className="px-5 py-3.5 text-body">
                  <span className="font-semibold text-text">{e.vacation_days_per_year}</span> Tage
                </td>
                <td className="px-5 py-3.5">
                  <div className="flex items-center justify-end gap-1 text-muted">
                    <IconBtn title="Abwesenheit" onClick={() => setAbsenceFor(e)}>
                      <CalendarDays size={16} />
                    </IconBtn>
                    <IconBtn title="Berechtigungen" onClick={() => setPermsFor(e)}>
                      <Shield size={16} />
                    </IconBtn>
                    <IconBtn title="Bearbeiten" onClick={() => setEditing(e)}>
                      <Pencil size={16} />
                    </IconBtn>
                    {e.has_login && (
                      <IconBtn title="Passwort zurücksetzen" onClick={() => setPasswordFor(e)}>
                        <KeyRound size={16} />
                      </IconBtn>
                    )}
                    {e.has_login && !e.is_org_owner && (
                      <IconBtn title="Einladung erneut senden" onClick={() => resend.mutate(e.id)}>
                        <RefreshCw size={16} />
                      </IconBtn>
                    )}
                    {!e.is_org_owner && (
                      <IconBtn
                        title="Löschen"
                        onClick={() => {
                          if (confirm(`${e.display_name} wirklich entfernen?`)) del.mutate(e.id)
                        }}
                      >
                        <Trash2 size={16} />
                      </IconBtn>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {!filtered.length && (
              <tr>
                <td colSpan={7} className="px-5 py-10 text-center text-muted">
                  {isLoading ? 'Lädt…' : error ? `Fehler: ${(error as Error).message}` : 'Keine Mitarbeiter.'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {editing && <EditEmployeeModal employee={editing} onClose={() => setEditing(null)} />}
      {absenceFor && <AbsenceModal employee={absenceFor} onClose={() => setAbsenceFor(null)} />}
      {permsFor && <PermissionsModal employee={permsFor} onClose={() => setPermsFor(null)} />}
      {passwordFor && (
        <PasswordResetModal employee={passwordFor} flash={flash} onClose={() => setPasswordFor(null)} />
      )}
    </div>
  )
}

// ─── Permissions modal ───────────────────────────────────────────────────────
function PermissionsModal({ employee, onClose }: { employee: Employee; onClose: () => void }) {
  const isAdmin = employee.access_role === 'admin'
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title={`Berechtigungen: ${employee.display_name}`}
      footer={
        <button onClick={onClose} className="w-full rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body">
          Schließen
        </button>
      }
    >
      {isAdmin ? (
        <div className="flex gap-3 rounded-md border border-ai/30 bg-ai-bg px-4 py-3 text-sm text-ai">
          <Shield size={18} className="mt-0.5 shrink-0" />
          <div>
            <span className="font-bold">Admin-Konto:</span> Administratoren haben automatisch Vollzugriff
            auf alle Module. Die Berechtigungen können nicht eingeschränkt werden.
          </div>
        </div>
      ) : (
        <div className="space-y-3 text-sm text-body">
          <p>
            Dieser Mitarbeiter hat Standard-Zugriff. Modul-Berechtigungen pro Mitarbeiter werden in
            Kürze konfigurierbar.
          </p>
          <div className="rounded-md border border-border bg-alt px-3 py-2 text-muted">
            Aktuell sehen Mitarbeiter Anrufe, Kunden, Kalender und ihre eigenen Aufgaben.
          </div>
        </div>
      )}
    </Modal>
  )
}

// ─── Password reset modal ────────────────────────────────────────────────────
function PasswordResetModal({
  employee,
  flash,
  onClose,
}: {
  employee: Employee
  flash: (m: string) => void
  onClose: () => void
}) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: () =>
      apiFetch(`/api/employees/${employee.id}/set-password`, {
        method: 'POST',
        body: JSON.stringify({ password }),
      }),
    onSuccess: () => {
      flash(`Passwort für ${employee.display_name} gesetzt.`)
      onClose()
    },
    onError: (e: Error) => setError(e.message),
  })

  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title="Passwort zurücksetzen"
      footer={
        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body">
            Abbrechen
          </button>
          <button
            disabled={password.length < 6 || save.isPending}
            onClick={() => save.mutate()}
            className="flex-1 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
          >
            {save.isPending ? 'Speichert…' : 'Passwort setzen'}
          </button>
        </div>
      }
    >
      <div className="space-y-3">
        {error && <div className="rounded-md bg-error-bg px-3 py-2 text-sm text-error">{error}</div>}
        <p className="text-sm text-body">
          Neues Passwort für <span className="font-bold text-text">{employee.display_name}</span> festlegen:
        </p>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Neues Passwort (min. 6 Zeichen)"
          className={inputCls}
        />
      </div>
    </Modal>
  )
}

function IconBtn({
  children,
  title,
  onClick,
  disabled,
}: {
  children: React.ReactNode
  title: string
  onClick?: () => void
  disabled?: boolean
}) {
  return (
    <button
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'rounded-md p-1.5 hover:bg-alt hover:text-body',
        disabled && 'cursor-not-allowed opacity-40 hover:bg-transparent',
      )}
    >
      {children}
    </button>
  )
}

// ─── Shared bits ─────────────────────────────────────────────────────────────
const inputCls =
  'w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary'
const labelCls = 'mb-1.5 block text-xs font-semibold text-body'

function ColorPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <div className={labelCls}>Kalenderfarbe (optional)</div>
      <div className="mb-2 flex flex-wrap gap-2">
        {COLOR_SWATCHES.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => onChange(c)}
            className={cn(
              'h-7 w-7 rounded-full ring-offset-2 ring-offset-surface transition',
              value === c && 'ring-2 ring-green-primary',
            )}
            style={{ background: c }}
          />
        ))}
      </div>
      <div className="flex items-center gap-2">
        <span className="h-8 w-8 rounded-md border border-border" style={{ background: value || '#ffffff' }} />
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="#057867"
          className={cn(inputCls, 'max-w-40 font-mono')}
        />
      </div>
      <p className="mt-1 text-xs text-muted">
        Wird als Rahmen um die Termine dieses Mitarbeiters angezeigt.
      </p>
    </div>
  )
}

function Radio({
  checked,
  onChange,
  label,
}: {
  checked: boolean
  onChange: () => void
  label: string
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-sm text-text">
      <span
        onClick={onChange}
        className={cn(
          'flex h-4 w-4 items-center justify-center rounded-full border',
          checked ? 'border-green-primary' : 'border-border',
        )}
      >
        {checked && <span className="h-2 w-2 rounded-full bg-green-primary" />}
      </span>
      {label}
    </label>
  )
}

function Check({
  checked,
  onChange,
  label,
  sub,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
  sub?: string
}) {
  return (
    <label className="flex cursor-pointer items-start gap-2">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 accent-green-primary"
      />
      <span>
        <span className="text-sm font-medium text-text">{label}</span>
        {sub && <span className="block text-xs text-muted">{sub}</span>}
      </span>
    </label>
  )
}

// ─── New employee modal ──────────────────────────────────────────────────────
function NewEmployeeModal({ flash, onClose }: { flash: (m: string) => void; onClose: () => void }) {
  const qc = useQueryClient()
  const [loginAccess, setLoginAccess] = useState(true)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<'employee' | 'admin'>('employee')
  const [active, setActive] = useState(true)
  const [color, setColor] = useState('')
  const [activity, setActivity] = useState('')
  const [autoAssign, setAutoAssign] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const create = useMutation({
    mutationFn: () =>
      apiFetch('/api/employees', {
        method: 'POST',
        body: JSON.stringify({
          display_name: name,
          email: email || null,
          login_access: loginAccess,
          access_role: role,
          is_active: active,
          calendar_color: color || null,
          activity_area: activity || null,
          auto_assign: autoAssign,
        }),
      }) as Promise<{ warning?: string }>,
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['employees-full'] })
      flash(data?.warning || `${name} wurde angelegt.`)
      onClose()
    },
    onError: (e: Error) => setError(e.message),
  })

  const valid = name.trim() && (!loginAccess || email.trim())

  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title="Neuer Mitarbeiter"
      widthClass="max-w-lg"
      footer={
        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body">
            Abbrechen
          </button>
          <button
            disabled={!valid || create.isPending}
            onClick={() => create.mutate()}
            className="flex-1 inline-flex items-center justify-center gap-2 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
          >
            <Mail size={15} /> {create.isPending ? 'Sendet…' : 'Einladen'}
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        {error && <div className="rounded-md bg-error-bg px-3 py-2 text-sm text-error">{error}</div>}
        <div className="rounded-md border border-border bg-alt p-3">
          <Check
            checked={loginAccess}
            onChange={setLoginAccess}
            label="Login-Zugang zu HeyKiki"
            sub="Der Mitarbeiter erhält eine E-Mail-Einladung und kann sich einloggen. Zählt zum Plan-Limit."
          />
        </div>
        <div>
          <div className={labelCls}>Name *</div>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Vor- und Nachname" className={inputCls} />
        </div>
        <div>
          <div className={labelCls}>E-Mail {loginAccess && '*'}</div>
          <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="email@example.de" className={inputCls} />
        </div>
        {loginAccess && (
          <div className="flex gap-2 rounded-md border border-info/30 bg-info-bg px-3 py-2.5 text-sm text-info">
            <Mail size={16} className="mt-0.5 shrink-0" />
            <div>
              <span className="font-medium">Einladung per E-Mail</span> — Der neue Mitarbeiter erhält
              eine E-Mail mit einem Link, um ein eigenes Passwort zu setzen. Gültig für 7 Tage.
            </div>
          </div>
        )}
        <div>
          <div className={labelCls}>Rolle</div>
          <div className="flex gap-6">
            <Radio checked={role === 'employee'} onChange={() => setRole('employee')} label="Mitarbeiter" />
            <Radio checked={role === 'admin'} onChange={() => setRole('admin')} label="Admin" />
          </div>
          <p className="mt-1 text-xs text-muted">Admins haben automatisch vollen Zugriff auf alle Module.</p>
        </div>
        <Check checked={active} onChange={setActive} label="Konto aktiv" sub="Inaktive Konten können sich nicht einloggen." />
        <ColorPicker value={color} onChange={setColor} />
        <div className="border-t border-border pt-4">
          <div className="mb-3 text-sm font-bold text-text">Automatische Anfragezuweisung</div>
          <div className={labelCls}>Tätigkeitsbereich</div>
          <textarea
            value={activity}
            onChange={(e) => setActivity(e.target.value)}
            placeholder="z.B. Heizung, Sanitär, Solar"
            rows={2}
            className={inputCls}
          />
          <p className="mb-3 mt-1 text-xs text-muted">
            Wird vom KI-Telefonassistenten nach jedem Anruf genutzt, um die passende Anfrage automatisch zuzuweisen.
          </p>
          <Check checked={autoAssign} onChange={setAutoAssign} label="Automatische Zuweisung aktivieren" />
        </div>
      </div>
    </Modal>
  )
}

// ─── Edit employee modal ─────────────────────────────────────────────────────
function EditEmployeeModal({ employee, onClose }: { employee: Employee; onClose: () => void }) {
  const qc = useQueryClient()
  const [name, setName] = useState(employee.display_name ?? '')
  const [email, setEmail] = useState(employee.email ?? '')
  const [role, setRole] = useState<'employee' | 'admin'>(employee.access_role)
  const [active, setActive] = useState(employee.is_active)
  const [color, setColor] = useState(employee.calendar_color ?? '')
  const [vacationPerYear, setVacationPerYear] = useState(employee.vacation_days_per_year ?? 28)
  const [remaining, setRemaining] = useState(employee.remaining_vacation_days ?? 0)
  const [rate, setRate] = useState(employee.hourly_rate ?? 0)
  const [activity, setActivity] = useState(employee.activity_area ?? '')
  const [autoAssign, setAutoAssign] = useState(employee.auto_assign)
  const [error, setError] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: () =>
      apiFetch(`/api/employees/${employee.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          display_name: name,
          email: email || null,
          access_role: role,
          is_active: active,
          calendar_color: color || null,
          vacation_days_per_year: vacationPerYear,
          remaining_vacation_days: remaining,
          hourly_rate: rate,
          activity_area: activity || null,
          auto_assign: autoAssign,
        }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['employees-full'] })
      onClose()
    },
    onError: (e: Error) => setError(e.message),
  })

  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title="Mitarbeiter bearbeiten"
      widthClass="max-w-lg"
      footer={
        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body">
            Abbrechen
          </button>
          <button
            disabled={save.isPending}
            onClick={() => save.mutate()}
            className="flex-1 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
          >
            {save.isPending ? 'Speichert…' : 'Aktualisieren'}
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        {employee.is_org_owner && (
          <div className="rounded-md bg-warning-bg px-3 py-2 text-sm text-warning">
            Der Organisationsinhaber muss den Login-Zugang behalten.
          </div>
        )}
        {error && <div className="rounded-md bg-error-bg px-3 py-2 text-sm text-error">{error}</div>}
        <div>
          <div className={labelCls}>Name</div>
          <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} />
        </div>
        <div>
          <div className={labelCls}>E-Mail</div>
          <input value={email} onChange={(e) => setEmail(e.target.value)} className={inputCls} />
        </div>
        <div>
          <div className={labelCls}>Rolle</div>
          <div className="flex gap-6">
            <Radio checked={role === 'employee'} onChange={() => setRole('employee')} label="Mitarbeiter" />
            <Radio checked={role === 'admin'} onChange={() => setRole('admin')} label="Admin" />
          </div>
        </div>
        <Check checked={active} onChange={setActive} label="Konto aktiv" sub="Inaktive Konten können sich nicht einloggen." />
        <ColorPicker value={color} onChange={setColor} />

        <div className="border-t border-border pt-4">
          <div className="mb-3 text-sm font-bold text-text">Arbeitszeiten & Urlaub</div>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <div className={labelCls}>Urlaubstage/Jahr</div>
              <input type="number" value={vacationPerYear} onChange={(e) => setVacationPerYear(Number(e.target.value))} className={inputCls} />
            </div>
            <div>
              <div className={labelCls}>Verbleibend</div>
              <input type="number" value={remaining} onChange={(e) => setRemaining(Number(e.target.value))} className={inputCls} />
            </div>
            <div>
              <div className={labelCls}>Stundensatz</div>
              <div className="relative">
                <input type="number" value={rate} onChange={(e) => setRate(Number(e.target.value))} className={cn(inputCls, 'pr-7')} />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted">€</span>
              </div>
            </div>
          </div>
        </div>

        <div className="border-t border-border pt-4">
          <div className="mb-3 text-sm font-bold text-text">Automatische Anfragezuweisung</div>
          <div className={labelCls}>Tätigkeitsbereich</div>
          <textarea
            value={activity}
            onChange={(e) => setActivity(e.target.value)}
            placeholder="z.B. Heizung, Sanitär, Solar"
            rows={2}
            className={inputCls}
          />
          <p className="mb-3 mt-1 text-xs text-muted">
            Wird vom KI-Telefonassistenten nach jedem Anruf genutzt, um die passende Anfrage automatisch zuzuweisen.
          </p>
          <Check checked={autoAssign} onChange={setAutoAssign} label="Automatische Zuweisung aktivieren" />
        </div>
      </div>
    </Modal>
  )
}

// ─── Absence modal ───────────────────────────────────────────────────────────
function todayYmd() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function AbsenceModal({ employee, onClose }: { employee: Employee; onClose: () => void }) {
  const qc = useQueryClient()
  const [type, setType] = useState('vacation')
  const [from, setFrom] = useState(todayYmd())
  const [until, setUntil] = useState(todayYmd())
  const [allDay, setAllDay] = useState(true)
  const [reason, setReason] = useState('')
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: () =>
      apiFetch(`/api/employees/${employee.id}/absences`, {
        method: 'POST',
        body: JSON.stringify({
          type,
          starts_at: new Date(`${from}T00:00:00`).toISOString(),
          ends_at: new Date(`${until}T23:59:59`).toISOString(),
          all_day: allDay,
          reason: reason || null,
          internal_note: note || null,
        }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['employees-full'] })
      qc.invalidateQueries({ queryKey: ['absences'] })
      onClose()
    },
    onError: (e: Error) => setError(e.message),
  })

  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title={`${employee.display_name}s Abwesenheit`}
      widthClass="max-w-lg"
      footer={
        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body">
            Abbrechen
          </button>
          <button
            disabled={!from || !until || save.isPending}
            onClick={() => save.mutate()}
            className="flex-1 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
          >
            {save.isPending ? 'Speichert…' : 'Eintragen'}
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        {error && <div className="rounded-md bg-error-bg px-3 py-2 text-sm text-error">{error}</div>}
        <div>
          <div className={labelCls}>Typ *</div>
          <div className="flex flex-wrap gap-2">
            {ABSENCE_TYPES.map((t) => (
              <button
                key={t.key}
                onClick={() => setType(t.key)}
                className={cn(
                  'rounded-md border px-3 py-2 text-sm font-medium transition-colors',
                  type === t.key
                    ? 'border-green-primary bg-green-primary text-white'
                    : 'border-border text-body hover:bg-alt',
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <div className={labelCls}>Von *</div>
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className={inputCls} />
          </div>
          <div>
            <div className={labelCls}>Bis *</div>
            <input type="date" value={until} onChange={(e) => setUntil(e.target.value)} className={inputCls} />
          </div>
        </div>
        <Check checked={allDay} onChange={setAllDay} label="Ganztägig" />
        <div>
          <div className={labelCls}>Grund (optional)</div>
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="z.B. Familienurlaub, Arzttermin…" rows={2} className={inputCls} />
        </div>
        <div>
          <div className={labelCls}>Interne Notiz (optional)</div>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Interne Notizen…" rows={2} className={inputCls} />
        </div>
      </div>
    </Modal>
  )
}

// ─── Overview tab ────────────────────────────────────────────────────────────
const DAY_MS = 86400000
const pad2 = (n: number) => String(n).padStart(2, '0')
const ymdLocal = (iso: string | Date) => {
  const d = new Date(iso)
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
}
const absenceDays = (a: Absence) =>
  Math.max(1, Math.round((new Date(a.ends_at).getTime() - new Date(a.starts_at).getTime()) / DAY_MS))

function OverviewTab() {
  const year = new Date().getFullYear()
  const { data: employees = [] } = useQuery({
    queryKey: ['employees-full'],
    queryFn: () => apiFetch<Employee[]>('/api/employees'),
  })
  const { data: absences = [] } = useQuery({
    queryKey: ['absences', `${year}-01-01`, `${year}-12-31`],
    queryFn: () =>
      apiFetch<Absence[]>(
        `/api/employees/absences?from=${year}-01-01T00:00:00.000Z&to=${year}-12-31T23:59:59.000Z`,
      ),
  })

  const now = Date.now()
  const covers = (a: Absence, t: number) =>
    new Date(a.starts_at).getTime() <= t && new Date(a.ends_at).getTime() >= t
  const overlaps = (a: Absence, s: number, e: number) =>
    new Date(a.starts_at).getTime() <= e && new Date(a.ends_at).getTime() >= s

  const today = absences.filter((a) => covers(a, now))
  const day = new Date().getDay()
  const monday = new Date()
  monday.setHours(0, 0, 0, 0)
  monday.setDate(monday.getDate() - ((day + 6) % 7))
  const sunday = new Date(monday.getTime() + 6 * DAY_MS + (DAY_MS - 1))
  const week = absences.filter((a) => overlaps(a, monday.getTime(), sunday.getTime()))

  const vacationRows = employees.map((e) => {
    const mine = absences.filter((a) => a.employee_id === e.id)
    const taken = mine
      .filter((a) => a.type === 'vacation' && new Date(a.starts_at).getTime() <= now)
      .reduce((s, a) => s + absenceDays(a), 0)
    const requested = mine
      .filter((a) => a.type === 'vacation' && new Date(a.starts_at).getTime() > now)
      .reduce((s, a) => s + absenceDays(a), 0)
    const sick = mine.filter((a) => a.type === 'illness').reduce((s, a) => s + absenceDays(a), 0)
    const total = e.vacation_days_per_year || 28
    return { e, total, taken, requested, available: total - taken - requested, sick }
  })

  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface p-5">
          <div className="mb-3 text-sm font-bold text-text">Abwesend heute</div>
          {today.length ? (
            <div className="space-y-2">
              {today.map((a) => (
                <div key={a.id} className="flex items-center gap-2 text-sm">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: ABSENCE_META[a.type]?.color }} />
                  <span className="font-medium text-text">{a.employee_name}</span>
                  <span className="text-muted">· {ABSENCE_META[a.type]?.label}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted">Alle Mitarbeiter anwesend.</p>
          )}
        </div>
        <div className="rounded-xl border border-border bg-surface p-5">
          <div className="mb-3 text-sm font-bold text-text">Diese Woche</div>
          {week.length ? (
            <div className="space-y-2">
              {week.map((a) => (
                <div key={a.id} className="flex items-center gap-2 text-sm">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: ABSENCE_META[a.type]?.color }} />
                  <span className="font-medium text-text">{a.employee_name}</span>
                  <span className="text-muted">
                    · {ABSENCE_META[a.type]?.label} ({ymdLocal(a.starts_at).slice(5)}–{ymdLocal(a.ends_at).slice(5)})
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted">Keine Abwesenheiten diese Woche.</p>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-border bg-surface p-5">
        <AbsenceLegend />
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        <div className="border-b border-border px-5 py-3 text-sm font-bold text-text">Urlaubstage {year}</div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs font-semibold uppercase tracking-wide text-muted">
              <th className="px-5 py-3">Mitarbeiter</th>
              <th className="px-5 py-3">Gesamt</th>
              <th className="px-5 py-3">Genommen</th>
              <th className="px-5 py-3">Beantragt</th>
              <th className="px-5 py-3">Verfügbar</th>
              <th className="px-5 py-3">Krank</th>
            </tr>
          </thead>
          <tbody>
            {vacationRows.map(({ e, total, taken, requested, available, sick }) => (
              <tr key={e.id} className="border-b border-border-faint last:border-0">
                <td className="px-5 py-3 font-semibold text-text">{e.display_name}</td>
                <td className="px-5 py-3 text-body">{total}</td>
                <td className={cn('px-5 py-3', taken ? 'font-semibold text-success' : 'text-muted')}>{taken}</td>
                <td className="px-5 py-3 text-body">{requested}</td>
                <td className="px-5 py-3 font-semibold text-text">{available}</td>
                <td className={cn('px-5 py-3', sick ? 'font-semibold text-error' : 'text-muted')}>{sick}</td>
              </tr>
            ))}
            {!vacationRows.length && (
              <tr>
                <td colSpan={6} className="px-5 py-10 text-center text-muted">Keine Mitarbeiter.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ─── Anträge tab (absence requests) ──────────────────────────────────────────
function AntraegeTab() {
  return (
    <div className="rounded-xl border border-border bg-surface py-20 text-center">
      <CircleCheck size={48} className="mx-auto mb-4 text-success" strokeWidth={1.5} />
      <div className="text-lg font-bold text-text">Keine offenen Anträge</div>
      <p className="mt-1 text-sm text-muted">Alle Abwesenheitsanträge wurden bearbeitet.</p>
    </div>
  )
}

// ─── Absence calendar tab ────────────────────────────────────────────────────
function AbsenceCalendarTab() {
  const [range, setRange] = useState<{ from: string; to: string } | null>(null)

  const { data: absences = [] } = useQuery({
    queryKey: ['absences', range?.from, range?.to],
    queryFn: () =>
      apiFetch<Absence[]>(`/api/employees/absences?from=${range!.from}&to=${range!.to}`),
    enabled: !!range,
  })

  const events = useMemo(
    () =>
      absences.map((a) => {
        const meta = ABSENCE_META[a.type]
        return {
          id: a.id,
          title: `${a.employee_name ?? ''} – ${meta?.label ?? a.type}`,
          start: ymdLocal(a.starts_at),
          end: ymdLocal(new Date(new Date(a.ends_at).getTime() + DAY_MS)),
          allDay: true,
          backgroundColor: meta?.color,
          borderColor: meta?.color,
        }
      }),
    [absences],
  )

  return (
    <div>
      <div className="rounded-xl border border-border bg-surface p-4" style={{ height: 640 }}>
        <FullCalendar
          plugins={[dayGridPlugin, listPlugin, interactionPlugin]}
          initialView="dayGridMonth"
          locale={deLocale}
          firstDay={1}
          height="100%"
          headerToolbar={{ left: 'prev,next today', center: 'title', right: 'dayGridMonth,listMonth' }}
          events={events}
          datesSet={(info) =>
            setRange({ from: info.start.toISOString(), to: info.end.toISOString() })
          }
        />
      </div>
      <div className="mt-4 rounded-xl border border-border bg-surface p-4">
        <AbsenceLegend />
      </div>
    </div>
  )
}

// ─── New absence modal (with employee picker) ────────────────────────────────
function NewAbsenceModal({
  flash,
  onClose,
  onSaved,
}: {
  flash: (m: string) => void
  onClose: () => void
  onSaved: () => void
}) {
  const { data: employees = [] } = useQuery({
    queryKey: ['employees-full'],
    queryFn: () => apiFetch<Employee[]>('/api/employees'),
  })
  const [employeeId, setEmployeeId] = useState('')
  const [type, setType] = useState('vacation')
  const [from, setFrom] = useState(todayYmd())
  const [until, setUntil] = useState(todayYmd())
  const [allDay, setAllDay] = useState(true)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: () =>
      apiFetch(`/api/employees/${employeeId}/absences`, {
        method: 'POST',
        body: JSON.stringify({
          type,
          starts_at: new Date(`${from}T00:00:00`).toISOString(),
          ends_at: new Date(`${until}T23:59:59`).toISOString(),
          all_day: allDay,
          reason: reason || null,
        }),
      }),
    onSuccess: () => {
      flash('Abwesenheit eingetragen.')
      onSaved()
    },
    onError: (e: Error) => setError(e.message),
  })

  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title="Neue Abwesenheit"
      widthClass="max-w-lg"
      footer={
        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body">
            Abbrechen
          </button>
          <button
            disabled={!employeeId || !from || !until || save.isPending}
            onClick={() => save.mutate()}
            className="flex-1 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
          >
            {save.isPending ? 'Speichert…' : 'Eintragen'}
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        {error && <div className="rounded-md bg-error-bg px-3 py-2 text-sm text-error">{error}</div>}
        <div>
          <div className={labelCls}>Mitarbeiter *</div>
          <select value={employeeId} onChange={(e) => setEmployeeId(e.target.value)} className={inputCls}>
            <option value="">— auswählen —</option>
            {employees.map((e) => (
              <option key={e.id} value={e.id}>{e.display_name}</option>
            ))}
          </select>
        </div>
        <div>
          <div className={labelCls}>Typ *</div>
          <div className="flex flex-wrap gap-2">
            {ABSENCE_TYPES.map((t) => (
              <button
                key={t.key}
                onClick={() => setType(t.key)}
                className={cn(
                  'rounded-md border px-3 py-2 text-sm font-medium transition-colors',
                  type === t.key ? 'border-green-primary bg-green-primary text-white' : 'border-border text-body hover:bg-alt',
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <div className={labelCls}>Von *</div>
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className={inputCls} />
          </div>
          <div>
            <div className={labelCls}>Bis *</div>
            <input type="date" value={until} onChange={(e) => setUntil(e.target.value)} className={inputCls} />
          </div>
        </div>
        <Check checked={allDay} onChange={setAllDay} label="Ganztägig" />
        <div>
          <div className={labelCls}>Grund (optional)</div>
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="z.B. Familienurlaub…" rows={2} className={inputCls} />
        </div>
      </div>
    </Modal>
  )
}
