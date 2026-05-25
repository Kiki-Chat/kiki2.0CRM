import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  Bell,
  Bot,
  Calendar,
  Check,
  ChevronDown,
  ClipboardList,
  Clock,
  CreditCard,
  Eye,
  EyeOff,
  FileText,
  Info,
  Mail,
  Palette,
  Plug,
  Receipt,
  Star,
  Trash2,
  Upload,
  UploadCloud,
  Users,
  Wrench,
  type LucideIcon,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'

import { KpiCard } from '../components/ui/KpiCard'
import { Modal } from '../components/ui/Modal'
import { applyAccent, isHexColor } from '../lib/accent'
import { apiFetch, apiUpload } from '../lib/api'
import { supabase } from '../lib/supabase'
import { cn } from '../lib/utils'

const STALE = 5 * 60 * 1000

interface Org {
  id: string
  name: string | null
  trade: string | null
  phone_number: string | null
  fax: string | null
  email: string | null
  website: string | null
  address: Record<string, string> | null
  bank_details: Record<string, string> | null
  tax_info: Record<string, string> | null
  management: Record<string, string> | null
  chamber_of_crafts: string | null
  logo_url: string | null
  accent_color: string | null
  font_preference: string | null
  google_reviews_enabled: boolean
}
interface EmailConfig {
  provider?: string
  smtp_host?: string | null
  smtp_port?: number | null
  smtp_username?: string | null
  smtp_sender_name?: string | null
  smtp_sender_email?: string | null
  use_ssl?: boolean
  invoice_email_subject?: string | null
  invoice_email_body?: string | null
  kva_email_subject?: string | null
  kva_email_body?: string | null
  has_password?: boolean
}
interface PdsConfig {
  api_url?: string | null
  api_user?: string | null
  auto_sync_enabled?: boolean
  sync_interval?: string | null
  sync_entities?: Record<string, string>
  has_api_key?: boolean
}
interface AiSuggestions {
  ai_suggestions_enabled: boolean
  kva_followup_days: number
  payment_reminder_days: number
  appointment_reminder_days: number
  maintenance_reminder_days: number
}
interface Usage {
  ai_minutes_used: number
  ai_minutes_quota: number | null
  active_employees: number
  document_count: number
  document_size_bytes: number
}
interface SettingsResponse {
  organization: Org
  email_config: EmailConfig | null
  pds_config: PdsConfig | null
  ai_suggestions: AiSuggestions
  usage: Usage
}

interface NavItem { slug: string; label: string; icon: LucideIcon }
const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  { label: 'Unternehmen', items: [
    { slug: 'stammdaten', label: 'Stammdaten', icon: ClipboardList },
    { slug: 'design', label: 'Design', icon: Palette },
    { slug: 'abrechnung', label: 'Abrechnung', icon: CreditCard },
  ] },
  { label: 'Operatives', items: [
    { slug: 'ki-vorschlaege', label: 'KI-Vorschläge', icon: Bot },
    { slug: 'benachrichtigungen', label: 'Benachrichtigungen', icon: Bell },
  ] },
  { label: 'Kommunikation', items: [
    { slug: 'email-versand', label: 'E-Mail-Versand', icon: Mail },
    { slug: 'email-vorlagen', label: 'E-Mail-Vorlagen', icon: FileText },
    { slug: 'kalender-sync', label: 'Kalender-Sync', icon: Calendar },
    { slug: 'google-reviews', label: 'Google Reviews', icon: Star },
  ] },
  { label: 'Integrationen', items: [
    { slug: 'pds-software', label: 'PDS-Software', icon: Plug },
  ] },
]
const DANGER: NavItem = { slug: 'gefahrenzone', label: 'Gefahrenzone', icon: AlertTriangle }
const ALL_SLUGS = new Set([...NAV_GROUPS.flatMap((g) => g.items.map((i) => i.slug)), DANGER.slug])

export function SettingsPage() {
  const { section = 'stammdaten' } = useParams()
  const navigate = useNavigate()
  const { data, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiFetch<SettingsResponse>('/api/settings'),
    staleTime: STALE,
  })

  const [toast, setToast] = useState<string | null>(null)
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(null), 4000) }

  if (!ALL_SLUGS.has(section)) return <Navigate to="/settings/stammdaten" replace />

  return (
    <div className="p-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-text">Einstellungen</h1>
        <p className="mt-0.5 text-sm text-muted">Verwalten Sie Ihr Unternehmen, Ihre Integrationen und Ihre Benachrichtigungen.</p>
      </div>

      {toast && <div className="mb-4 rounded-md bg-green-tint-50 px-3 py-2 text-sm font-medium text-green-deep">{toast}</div>}

      <div className="flex flex-col gap-6 lg:flex-row">
        {/* Sub-nav */}
        <aside className="w-full shrink-0 lg:w-60">
          <nav className="space-y-4">
            {NAV_GROUPS.map((group) => (
              <div key={group.label}>
                <div className="mb-1 px-3 text-xs font-semibold uppercase tracking-wide text-muted">{group.label}</div>
                {group.items.map((it) => <NavLink key={it.slug} item={it} active={section === it.slug} onClick={() => navigate(`/settings/${it.slug}`)} />)}
              </div>
            ))}
            <div className="border-t border-border pt-3">
              <NavLink item={DANGER} active={section === DANGER.slug} danger onClick={() => navigate(`/settings/${DANGER.slug}`)} />
            </div>
          </nav>
        </aside>

        {/* Active section */}
        <div className="min-w-0 flex-1">
          {isLoading || !data ? (
            <div className="rounded-xl border border-border bg-surface p-12 text-center text-muted">Lädt…</div>
          ) : (
            <SectionContent section={section} data={data} flash={flash} />
          )}
        </div>
      </div>
    </div>
  )
}

function NavLink({ item, active, danger, onClick }: { item: NavItem; active: boolean; danger?: boolean; onClick: () => void }) {
  const Icon = item.icon
  return (
    <button
      onClick={onClick}
      className={cn(
        'mb-0.5 flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm transition',
        active
          ? 'bg-green-tint-100 font-semibold text-green-deep'
          : danger
            ? 'text-error hover:bg-error-bg'
            : 'text-body hover:bg-alt',
      )}
    >
      <Icon size={16} className={cn(active && danger && 'text-error')} /> {item.label}
    </button>
  )
}

// ─── Shared bits ──────────────────────────────────────────────────────────────
const inputCls = 'w-full rounded-md border border-border bg-alt px-3 py-2 text-sm text-text outline-none focus:border-green-primary'
const labelCls = 'mb-1 block text-xs font-semibold text-body'

function Card({ children }: { children: React.ReactNode }) {
  return <div className="rounded-xl border border-border bg-surface p-6">{children}</div>
}
function GroupLabel({ children }: { children: React.ReactNode }) {
  return <div className="mb-3 text-xs font-bold uppercase tracking-wide text-muted">{children}</div>
}
function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return <div><div className={labelCls}>{label}{required && ' *'}</div>{children}</div>
}
function SaveBar({ onReset, onSave, saving, resetLabel = 'Zurücksetzen', disabled }: { onReset: () => void; onSave: () => void; saving: boolean; resetLabel?: string; disabled?: boolean }) {
  return (
    <div className="mt-6 flex items-center justify-between border-t border-border pt-4">
      <button onClick={onReset} className="text-sm font-medium text-muted hover:text-body">{resetLabel}</button>
      <button onClick={onSave} disabled={saving || disabled} className="rounded-md bg-green-primary px-6 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">{saving ? 'Speichert…' : 'Speichern'}</button>
    </div>
  )
}
function Toggle({ on, onChange, disabled }: { on: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={cn('relative h-6 w-11 shrink-0 rounded-full transition disabled:opacity-50', on ? 'bg-green-primary' : 'bg-border')}
    >
      <span className={cn('absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all', on ? 'left-[22px]' : 'left-0.5')} />
    </button>
  )
}

function SectionContent({ section, data, flash }: { section: string; data: SettingsResponse; flash: (m: string) => void }) {
  switch (section) {
    case 'stammdaten': return <StammdatenSection org={data.organization} />
    case 'design': return <DesignSection org={data.organization} />
    case 'abrechnung': return <AbrechnungSection usage={data.usage} />
    case 'ki-vorschlaege': return <KiVorschlaegeSection ai={data.ai_suggestions} flash={flash} />
    case 'benachrichtigungen': return <BenachrichtigungenSection />
    case 'email-versand': return <EmailVersandSection config={data.email_config} flash={flash} />
    case 'email-vorlagen': return <EmailVorlagenSection config={data.email_config} flash={flash} />
    case 'kalender-sync': return <KalenderSyncSection flash={flash} />
    case 'google-reviews': return <GoogleReviewsSection org={data.organization} />
    case 'pds-software': return <PdsSection config={data.pds_config} flash={flash} />
    case 'gefahrenzone': return <GefahrenzoneSection org={data.organization} flash={flash} />
    default: return null
  }
}

// ─── Stammdaten ───────────────────────────────────────────────────────────────
const formatIban = (v: string) => v.replace(/\s+/g, '').replace(/(.{4})/g, '$1 ').trim()

function stammFromOrg(org: Org) {
  const a = org.address || {}
  const b = org.bank_details || {}
  const m = org.management || {}
  const t = org.tax_info || {}
  return {
    name: org.name ?? '',
    trade: org.trade ?? '',
    street: a.street || a.raw || '',
    plz: a.postal_code || a.zip || '',
    ort: a.city || '',
    phone: org.phone_number ?? '',
    fax: org.fax ?? '',
    email: org.email ?? '',
    website: org.website ?? '',
    bankName: b.bank_name ?? '',
    iban: b.iban ?? '',
    bic: b.bic ?? '',
    mgmtName: m.name ?? '',
    mgmtTitle: m.title ?? '',
    chamber: org.chamber_of_crafts ?? '',
    vatId: t.vat_id ?? '',
    taxNumber: t.tax_number ?? '',
  }
}

function StammdatenSection({ org }: { org: Org }) {
  const qc = useQueryClient()
  const [f, setF] = useState(() => stammFromOrg(org))
  const set = (k: keyof typeof f, v: string) => setF((p) => ({ ...p, [k]: v }))

  const save = useMutation({
    mutationFn: () => {
      const bank_details = { ...(org.bank_details || {}), bank_name: f.bankName, iban: f.iban, bic: f.bic }
      if (f.mgmtName) { bank_details.account_holder = f.mgmtName; bank_details.managing_director = f.mgmtName }
      return apiFetch('/api/settings/general', {
        method: 'PATCH',
        body: JSON.stringify({
          name: f.name, trade: f.trade,
          phone_number: f.phone, fax: f.fax, email: f.email, website: f.website,
          address: { street: f.street, postal_code: f.plz, city: f.ort },
          bank_details,
          management: { name: f.mgmtName, title: f.mgmtTitle },
          chamber_of_crafts: f.chamber,
          tax_info: { vat_id: f.vatId, tax_number: f.taxNumber },
        }),
      })
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }),
  })

  return (
    <Card>
      {/* Grunddaten */}
      <GroupLabel>Grunddaten</GroupLabel>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Unternehmensname" required><input value={f.name} onChange={(e) => set('name', e.target.value)} className={inputCls} /></Field>
        <Field label="Gewerk / Branche"><input value={f.trade} onChange={(e) => set('trade', e.target.value)} className={inputCls} /></Field>
      </div>

      {/* Adresse */}
      <div className="my-6 border-t border-border" />
      <GroupLabel>Adresse</GroupLabel>
      <div className="space-y-4">
        <Field label="Straße + Hausnummer" required><input value={f.street} onChange={(e) => set('street', e.target.value)} className={inputCls} /></Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="PLZ" required><input value={f.plz} onChange={(e) => set('plz', e.target.value)} className={inputCls} /></Field>
          <Field label="Ort" required><input value={f.ort} onChange={(e) => set('ort', e.target.value)} className={inputCls} /></Field>
        </div>
      </div>

      {/* Kontakt */}
      <div className="my-6 border-t border-border" />
      <GroupLabel>Kontakt</GroupLabel>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Telefon" required><input value={f.phone} onChange={(e) => set('phone', e.target.value)} className={inputCls} /></Field>
        <Field label="Fax"><input value={f.fax} onChange={(e) => set('fax', e.target.value)} className={inputCls} /></Field>
        <Field label="E-Mail" required><input value={f.email} onChange={(e) => set('email', e.target.value)} className={inputCls} /></Field>
        <Field label="Website"><input value={f.website} onChange={(e) => set('website', e.target.value)} className={inputCls} /></Field>
      </div>

      {/* Bankverbindung */}
      <div className="my-6 border-t border-border" />
      <GroupLabel>Bankverbindung</GroupLabel>
      <div className="space-y-4">
        <Field label="Bankname" required><input value={f.bankName} onChange={(e) => set('bankName', e.target.value)} className={inputCls} /></Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="IBAN" required><input value={f.iban} onChange={(e) => set('iban', formatIban(e.target.value))} className={inputCls} /></Field>
          <Field label="BIC" required><input value={f.bic} onChange={(e) => set('bic', e.target.value)} className={inputCls} /></Field>
        </div>
      </div>

      {/* Geschäftsführung */}
      <div className="my-6 border-t border-border" />
      <GroupLabel>Geschäftsführung</GroupLabel>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Name"><input value={f.mgmtName} onChange={(e) => set('mgmtName', e.target.value)} className={inputCls} /></Field>
        <Field label="Titel / Position"><input value={f.mgmtTitle} onChange={(e) => set('mgmtTitle', e.target.value)} className={inputCls} /></Field>
      </div>

      {/* Steuer & Rechtliches */}
      <div className="my-6 border-t border-border" />
      <GroupLabel>Steuer & Rechtliches</GroupLabel>
      <div className="space-y-4">
        <Field label="Handwerkskammer"><input value={f.chamber} onChange={(e) => set('chamber', e.target.value)} className={inputCls} /></Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="USt-IdNr." required><input value={f.vatId} onChange={(e) => set('vatId', e.target.value)} className={inputCls} /></Field>
          <Field label="Steuernummer"><input value={f.taxNumber} onChange={(e) => set('taxNumber', e.target.value)} className={inputCls} /></Field>
        </div>
      </div>

      <SaveBar onReset={() => setF(stammFromOrg(org))} onSave={() => save.mutate()} saving={save.isPending} disabled={!f.name.trim()} />
    </Card>
  )
}

// ─── Design ───────────────────────────────────────────────────────────────────
const SWATCHES: [string, string][] = [
  ['#2563EB', 'Blau'], ['#16A34A', 'Grün'], ['#7C3AED', 'Lila'], ['#9333EA', 'Violett'],
  ['#DB2777', 'Pink'], ['#DC2626', 'Rot'], ['#EA580C', 'Orange'], ['#D97706', 'Amber'],
]
const FONTS: [string, string][] = [
  ['Montserrat', 'Montserrat (Standard)'], ['Inter', 'Inter'],
  ['Playfair Display', 'Playfair Display'], ['System-UI', 'System-UI'],
]
const fontStack = (f: string) => (f === 'System-UI' ? 'system-ui, sans-serif' : `'${f}', sans-serif`)

function DesignSection({ org }: { org: Org }) {
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [accent, setAccent] = useState(org.accent_color || '#16A34A')
  const [font, setFont] = useState(org.font_preference || 'Montserrat')
  const [uploading, setUploading] = useState(false)
  const savedAccent = useRef(org.accent_color)

  // Live-preview the accent across the app; restore the saved value on unmount.
  const pickAccent = (hex: string) => { setAccent(hex); applyAccent(hex) }
  useEffect(() => () => { applyAccent(savedAccent.current) }, [])

  const save = useMutation({
    mutationFn: () => apiFetch('/api/settings/design', { method: 'PATCH', body: JSON.stringify({ accent_color: accent, font_preference: font }) }),
    onSuccess: () => { savedAccent.current = accent; applyAccent(accent); qc.invalidateQueries({ queryKey: ['settings'] }) },
  })
  const reset = () => { setAccent(org.accent_color || '#16A34A'); setFont(org.font_preference || 'Montserrat'); applyAccent(org.accent_color) }

  async function uploadLogo(files: FileList | null) {
    if (!files?.length) return
    setUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', files[0])
      await apiUpload('/api/settings/logo', fd)
      qc.invalidateQueries({ queryKey: ['settings'] })
    } finally { setUploading(false) }
  }
  const removeLogo = useMutation({
    mutationFn: () => apiFetch('/api/settings/logo', { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }),
  })

  return (
    <Card>
      {/* Logo */}
      <GroupLabel>Unternehmenslogo</GroupLabel>
      <div className="flex flex-wrap items-start gap-5">
        <div className="flex h-[120px] w-[200px] items-center justify-center rounded-lg border border-border bg-alt">
          {org.logo_url ? (
            <img src={org.logo_url} alt="Logo" className="max-h-[104px] max-w-[184px] object-contain" />
          ) : (
            <div className="flex flex-col items-center gap-1 text-faint"><UploadCloud size={22} /><span className="text-xs">Kein Logo</span></div>
          )}
        </div>
        <div className="flex flex-col gap-2">
          <button onClick={() => fileRef.current?.click()} className="inline-flex items-center gap-2 rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-body hover:bg-alt">
            <Upload size={15} /> {uploading ? 'Lädt hoch…' : 'Logo ändern'}
          </button>
          {org.logo_url && <button onClick={() => removeLogo.mutate()} className="text-left text-sm font-medium text-error hover:underline">Logo entfernen</button>}
          <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/svg+xml,image/webp" className="hidden" onChange={(e) => uploadLogo(e.target.files)} />
        </div>
      </div>
      <p className="mt-2 text-xs text-muted">PNG, JPG oder SVG, max. 2 MB. Erscheint in Seitenleiste, Login und Rechnungen/PDFs.</p>

      {/* Accent */}
      <div className="my-6 border-t border-border" />
      <GroupLabel>Akzentfarbe</GroupLabel>
      <div className="flex flex-wrap gap-2">
        {SWATCHES.map(([hex, name]) => (
          <button key={hex} title={name} onClick={() => pickAccent(hex)} className="flex h-8 w-8 items-center justify-center rounded-md border border-border" style={{ background: hex }}>
            {accent.toLowerCase() === hex.toLowerCase() && <span className="text-sm font-bold text-white">✓</span>}
          </button>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-2">
        <span className="h-7 w-7 rounded-md border border-border" style={{ background: isHexColor(accent) ? accent : 'transparent' }} />
        <input value={accent} onChange={(e) => pickAccent(e.target.value)} placeholder="#16A34A" className={cn(inputCls, 'w-40')} />
      </div>
      <div className="mt-4 rounded-lg bg-alt p-4">
        <div className="mb-2 text-xs font-semibold text-muted">Vorschau</div>
        <div className="flex flex-wrap items-center gap-3">
          <button className="rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white">Primärer Button</button>
          <button className="rounded-md border border-green-primary px-4 py-2 text-sm font-semibold text-green-deep">Sekundärer Button</button>
          <span className="rounded-full bg-green-tint-100 px-2.5 py-0.5 text-xs font-medium text-green-deep">Badge</span>
        </div>
      </div>

      {/* Font */}
      <div className="my-6 border-t border-border" />
      <GroupLabel>Schrift für Überschriften</GroupLabel>
      <select value={font} onChange={(e) => setFont(e.target.value)} className={cn(inputCls, 'max-w-xs')}>
        {FONTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
      <div className="mt-4 rounded-lg bg-alt p-4" style={{ fontFamily: fontStack(font) }}>
        <div className="mb-2 text-xs font-semibold text-muted" style={{ fontFamily: 'Inter, sans-serif' }}>Vorschau</div>
        <div className="text-2xl font-bold text-text">Dashboard</div>
        <div className="text-base font-semibold text-body">Rechnungen & Kostenvoranschläge</div>
      </div>

      <SaveBar onReset={reset} onSave={() => save.mutate()} saving={save.isPending} />
    </Card>
  )
}

// ─── Abrechnung ───────────────────────────────────────────────────────────────
function AbrechnungSection({ usage }: { usage: Usage }) {
  const quota = usage.ai_minutes_quota ?? 0
  const pct = quota ? Math.round((usage.ai_minutes_used / quota) * 100) : 0
  const over = quota > 0 && usage.ai_minutes_used > quota
  const size = usage.document_size_bytes > 1e6 ? `${(usage.document_size_bytes / 1e6).toFixed(1)} MB` : `${Math.round(usage.document_size_bytes / 1024)} KB`
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card>
          <div className="flex items-center gap-4">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-green-tint-100"><Clock size={18} className="text-green-deep" /></div>
            <div className="min-w-0">
              <div className="text-xs font-bold uppercase tracking-wide text-muted">KI-Minuten (Monat)</div>
              <div className="text-2xl font-bold leading-tight text-text">{usage.ai_minutes_used} / {quota || '∞'}</div>
            </div>
          </div>
          <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-alt">
            <div className={cn('h-full rounded-full', over ? 'bg-error' : 'bg-green-primary')} style={{ width: `${Math.min(pct, 100)}%` }} />
          </div>
        </Card>
        <KpiCard label="Aktive Mitarbeiter" value={usage.active_employees} icon={Users} />
        <KpiCard label="Gespeicherte Dokumente" value={usage.document_count} sub={size} icon={FileText} />
      </div>
      <div className="flex items-start gap-3 rounded-xl border border-info/30 bg-info-bg/40 p-4 text-sm text-body">
        <Info size={16} className="mt-0.5 shrink-0 text-info" />
        <span>Für Änderungen an Ihrem Abonnement oder Kontingent wenden Sie sich bitte an <a href="mailto:support@heykiki.de" className="font-medium text-green-deep hover:underline">support@heykiki.de</a>.</span>
      </div>
    </div>
  )
}

// ─── KI-Vorschläge ────────────────────────────────────────────────────────────
function KiVorschlaegeSection({ ai, flash }: { ai: AiSuggestions; flash: (m: string) => void }) {
  const qc = useQueryClient()
  const [enabled, setEnabled] = useState(ai.ai_suggestions_enabled)
  const [kva, setKva] = useState(ai.kva_followup_days)
  const [pay, setPay] = useState(ai.payment_reminder_days)
  const [appt, setAppt] = useState(ai.appointment_reminder_days)
  const [maint, setMaint] = useState(ai.maintenance_reminder_days)
  const save = useMutation({
    mutationFn: () => apiFetch('/api/settings/ai-suggestions', { method: 'PATCH', body: JSON.stringify({ ai_suggestions_enabled: enabled, kva_followup_days: kva, payment_reminder_days: pay, appointment_reminder_days: appt, maintenance_reminder_days: maint }) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['settings'] }); flash('Gespeichert.') },
  })
  const gen = useMutation({ mutationFn: () => apiFetch<{ message?: string }>('/api/settings/generate-suggestions', { method: 'POST' }), onSuccess: (r) => flash(r?.message || 'Vorschläge werden generiert.') })
  const cards = [
    { icon: FileText, title: 'KVA-Nachfassen', sub: 'Vorschlag wenn ein gesendeter KVA nicht beantwortet wurde', value: kva, set: setKva, unit: 'Tage ohne Antwort' },
    { icon: Receipt, title: 'Zahlungserinnerung', sub: 'Vorschlag für Zahlungserinnerung bei überfälligen Rechnungen', value: pay, set: setPay, unit: 'Tage Zahlungsverzug' },
    { icon: Calendar, title: 'Terminerinnerung', sub: 'Tägliche Übersicht über anstehende Termine', value: appt, set: setAppt, unit: 'Tag(e) vorher' },
    { icon: Wrench, title: 'Wartungserinnerung', sub: 'Erscheint wenn Wartung laut Wartungsvertrag bald fällig ist', value: maint, set: setMaint, unit: 'Tage vor Fälligkeit' },
  ]
  return (
    <Card>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-bold text-text">KI-Vorschläge</h2>
          <p className="text-sm text-muted">Automatische Aktionsempfehlungen im Dashboard</p>
        </div>
        <Toggle on={enabled} onChange={setEnabled} />
      </div>
      {enabled && <p className="mt-2 text-sm text-muted">Die KI analysiert Ihre Daten täglich um 06:00 Uhr und generiert Aktionsempfehlungen, die im Dashboard-Widget erscheinen.</p>}
      <div className={cn('mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2', !enabled && 'pointer-events-none opacity-50')}>
        {cards.map((c) => (
          <div key={c.title} className="rounded-lg border border-border bg-alt p-4">
            <div className="flex items-center gap-2"><c.icon size={16} className="text-green-deep" /><span className="text-sm font-bold text-text">{c.title}</span></div>
            <p className="mt-1 text-xs text-muted">{c.sub}</p>
            <div className="mt-3 flex items-center gap-2">
              <input type="number" value={c.value} onChange={(e) => c.set(Number(e.target.value))} className="w-20 rounded-md border border-border bg-surface px-2 py-1.5 text-sm text-text outline-none focus:border-green-primary" />
              <span className="text-xs text-muted">{c.unit}</span>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-6 flex items-center justify-between border-t border-border pt-4">
        <button onClick={() => gen.mutate()} className="rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-body hover:bg-alt">Vorschläge jetzt generieren</button>
        <button onClick={() => save.mutate()} disabled={save.isPending} className="rounded-md bg-green-primary px-6 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">{save.isPending ? 'Speichert…' : 'Speichern'}</button>
      </div>
    </Card>
  )
}

// ─── Benachrichtigungen ───────────────────────────────────────────────────────
function NoteDetailRow({ label, ok }: { label: string; ok: boolean }) {
  return <div className="flex justify-between"><span className="text-muted">{label}</span><span className={ok ? 'text-success' : 'text-error'}>{ok ? '✓ Ja' : '✗ Nein'}</span></div>
}
function BenachrichtigungenSection() {
  const supported = typeof Notification !== 'undefined'
  const [perm, setPerm] = useState<string>(supported ? Notification.permission : 'unsupported')
  const [open, setOpen] = useState(false)
  const granted = perm === 'granted'
  const secure = window.location.protocol === 'https:' || window.location.hostname === 'localhost'
  const pushSupported = 'PushManager' in window
  const permLabel = perm === 'granted' ? 'Erlaubt' : perm === 'denied' ? 'Abgelehnt' : perm === 'unsupported' ? 'Nicht unterstützt' : 'Nicht angefragt'
  const request = async () => { if (supported) setPerm(await Notification.requestPermission()) }
  return (
    <div className="space-y-4">
      {/* TODO: full ServiceWorker push subscription is out of scope this sprint. */}
      <Card>
        <div className="flex items-start gap-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-green-tint-100"><Bell size={22} className="text-green-deep" /></div>
          <div className="flex-1">
            <h2 className="text-lg font-bold text-text">Push-Benachrichtigungen aktivieren</h2>
            <p className="mt-1 text-sm text-muted">Erhalten Sie auf diesem Gerät sofort eine Benachrichtigung bei neuen Anrufen, Anfragen und überfälligen Rechnungen.</p>
            <div className="mt-4">
              {granted ? (
                <button disabled className="inline-flex items-center gap-2 rounded-md border border-success/40 bg-success-bg px-4 py-2 text-sm font-semibold text-success"><Check size={15} /> Aktiv</button>
              ) : (
                <button onClick={request} className="rounded-md bg-green-primary px-5 py-2 text-sm font-semibold text-white hover:brightness-110">Aktivieren</button>
              )}
            </div>
          </div>
        </div>
      </Card>
      <Card>
        <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center justify-between text-sm font-semibold text-body">
          Technische Details <ChevronDown size={16} className={cn('transition-transform', open && 'rotate-180')} />
        </button>
        {open && (
          <div className="mt-3 space-y-2 border-t border-border pt-3 text-sm">
            <NoteDetailRow label="HTTPS / Sicher" ok={secure} />
            <NoteDetailRow label="Push-Unterstützung" ok={pushSupported} />
            <div className="flex justify-between"><span className="text-muted">Berechtigung</span><span className="text-text">{permLabel}</span></div>
            <div className="flex justify-between"><span className="text-muted">Status</span><span className={granted ? 'text-success' : 'text-muted'}>{granted ? 'Aktiv' : 'Inaktiv'}</span></div>
          </div>
        )}
      </Card>
    </div>
  )
}

// ─── E-Mail-Versand ───────────────────────────────────────────────────────────
function Banner({ children }: { children: React.ReactNode }) {
  return <div className="rounded-md bg-info-bg/50 px-3 py-2 text-xs text-info">{children}</div>
}
function EmailVersandSection({ config, flash }: { config: EmailConfig | null; flash: (m: string) => void }) {
  const qc = useQueryClient()
  const [provider, setProvider] = useState(config?.provider || 'smtp')
  const [host, setHost] = useState(config?.smtp_host || '')
  const [port, setPort] = useState(config?.smtp_port ?? 465)
  const [username, setUsername] = useState(config?.smtp_username || '')
  const [senderName, setSenderName] = useState(config?.smtp_sender_name || '')
  const [senderEmail, setSenderEmail] = useState(config?.smtp_sender_email || '')
  const [password, setPassword] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [useSsl, setUseSsl] = useState(config?.use_ssl ?? true)
  const save = useMutation({
    mutationFn: () => apiFetch('/api/settings/email-config', { method: 'PATCH', body: JSON.stringify({ provider, smtp_host: host, smtp_port: port, smtp_username: username, smtp_sender_name: senderName, smtp_sender_email: senderEmail, use_ssl: useSsl, ...(password ? { smtp_password: password } : {}) }) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['settings'] }); setPassword(''); flash('Gespeichert.') },
  })
  const test = useMutation({ mutationFn: () => apiFetch<{ message?: string }>('/api/settings/email-test', { method: 'POST' }), onSuccess: (r) => flash(r?.message || 'Test gesendet.'), onError: () => flash('Test fehlgeschlagen.') })
  const providers: [string, string][] = [['gmail', 'Gmail'], ['outlook', 'Outlook'], ['smtp', 'SMTP']]
  return (
    <Card>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {providers.map(([v, l]) => (
          <button key={v} onClick={() => setProvider(v)} className={cn('rounded-lg border p-4 text-left transition', provider === v ? 'border-green-primary bg-green-tint-50' : 'border-border hover:bg-alt')}>
            <div className="flex items-center justify-between"><span className="font-semibold text-text">{l}</span>{provider === v && <Check size={16} className="text-green-deep" />}</div>
            <div className="mt-1 text-xs text-muted">{v === 'smtp' ? 'HeyKiki Standard' : 'Nicht verbunden'}</div>
          </button>
        ))}
      </div>
      <div className="mt-5">
        {provider === 'gmail' && (
          <div>
            <Banner>Verbindung über Google OAuth. Höhere Zustellrate als SMTP.</Banner>
            {/* TODO: Gmail OAuth flow out of scope this sprint. */}
            <button onClick={() => flash('OAuth-Integration in Kürze verfügbar.')} className="mt-3 rounded-md bg-green-primary px-5 py-2 text-sm font-semibold text-white hover:brightness-110">Mit Gmail verbinden</button>
          </div>
        )}
        {provider === 'outlook' && (
          <div>
            <Banner>Verbindung über Microsoft OAuth. Höhere Zustellrate als SMTP.</Banner>
            {/* TODO: Outlook OAuth flow out of scope this sprint. */}
            <button onClick={() => flash('OAuth-Integration in Kürze verfügbar.')} className="mt-3 rounded-md bg-green-primary px-5 py-2 text-sm font-semibold text-white hover:brightness-110">Mit Outlook verbinden</button>
          </div>
        )}
        {provider === 'smtp' && (
          <div className="space-y-4">
            <Banner>Standardversand über info@kiki-zusammenfassung.de bis eigener SMTP eingetragen.</Banner>
            <div className="grid grid-cols-2 gap-4">
              <Field label="SMTP-Server"><input value={host} onChange={(e) => setHost(e.target.value)} className={inputCls} /></Field>
              <Field label="Port"><input type="number" value={port} onChange={(e) => setPort(Number(e.target.value))} className={inputCls} /></Field>
              <Field label="E-Mail / Benutzername"><input value={username} onChange={(e) => setUsername(e.target.value)} className={inputCls} /></Field>
              <Field label="Absendername"><input value={senderName} onChange={(e) => setSenderName(e.target.value)} className={inputCls} /></Field>
            </div>
            <Field label="Passwort / App-Passwort">
              <div className="relative">
                <input type={showPw ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)} placeholder={config?.has_password ? 'Leer = bestehendes behalten' : 'Passwort eingeben'} className={cn(inputCls, 'pr-10')} />
                <button onClick={() => setShowPw((s) => !s)} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted">{showPw ? <EyeOff size={15} /> : <Eye size={15} />}</button>
              </div>
            </Field>
            <Field label="Absender-E-Mail (optional)"><input value={senderEmail} onChange={(e) => setSenderEmail(e.target.value)} className={inputCls} /></Field>
            <label className="flex items-center gap-2 text-sm text-text"><Toggle on={useSsl} onChange={setUseSsl} /> SSL/TLS verwenden <span className="text-xs text-muted">(Port 465 = SSL, Port 587 = TLS/STARTTLS)</span></label>
          </div>
        )}
      </div>
      <div className="mt-6 flex items-center justify-between border-t border-border pt-4">
        <button onClick={() => test.mutate()} disabled={test.isPending} className="rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-body hover:bg-alt disabled:opacity-50">Test-E-Mail senden</button>
        <button onClick={() => save.mutate()} disabled={save.isPending} className="rounded-md bg-green-primary px-6 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">{save.isPending ? 'Speichert…' : 'Speichern'}</button>
      </div>
    </Card>
  )
}

// ─── E-Mail-Vorlagen ──────────────────────────────────────────────────────────
function EmailVorlagenSection({ config, flash }: { config: EmailConfig | null; flash: (m: string) => void }) {
  const qc = useQueryClient()
  const [invSub, setInvSub] = useState(config?.invoice_email_subject || '')
  const [invBody, setInvBody] = useState(config?.invoice_email_body || '')
  const [kvaSub, setKvaSub] = useState(config?.kva_email_subject || '')
  const [kvaBody, setKvaBody] = useState(config?.kva_email_body || '')
  const lastFocused = useRef<HTMLTextAreaElement | null>(null)
  const insert = (ph: string) => {
    const el = lastFocused.current
    if (!el) return
    const start = el.selectionStart ?? el.value.length
    const end = el.selectionEnd ?? el.value.length
    const next = el.value.slice(0, start) + ph + el.value.slice(end)
    if (el.dataset.field === 'invBody') setInvBody(next)
    else if (el.dataset.field === 'kvaBody') setKvaBody(next)
    requestAnimationFrame(() => { el.focus(); const pos = start + ph.length; el.setSelectionRange(pos, pos) })
  }
  const save = useMutation({
    mutationFn: () => apiFetch('/api/settings/email-config', { method: 'PATCH', body: JSON.stringify({ invoice_email_subject: invSub, invoice_email_body: invBody, kva_email_subject: kvaSub, kva_email_body: kvaBody }) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['settings'] }); flash('Gespeichert.') },
  })
  const reset = () => { setInvSub(config?.invoice_email_subject || ''); setInvBody(config?.invoice_email_body || ''); setKvaSub(config?.kva_email_subject || ''); setKvaBody(config?.kva_email_body || '') }
  const general = ['{kundename}', '{firmenname}', '{strasse}', '{plz}', '{ort}', '{telefon}', '{firmenemail}']
  const inv = ['{rechnungsnummer}', '{datum}', '{betrag}', '{faelligDatum}']
  const kva = ['{kvanummer}', '{datum}', '{betrag}', '{gueltigBis}', '{anfrage}']
  const Chip = ({ t }: { t: string }) => <button onMouseDown={(e) => e.preventDefault()} onClick={() => insert(t)} className="rounded-md border border-border bg-surface px-2 py-1 text-xs font-medium text-body hover:bg-alt">{t}</button>
  const ta = cn(inputCls, 'min-h-[240px]')
  return (
    <div className="space-y-4">
      <Card>
        <p className="mb-2 text-sm text-body">Verfügbare Platzhalter — klicken Sie auf einen Platzhalter, um ihn in das aktive Feld einzufügen.</p>
        <div className="flex flex-wrap gap-1.5">{general.map((t) => <Chip key={t} t={t} />)}</div>
        <div className="mt-2 text-xs text-muted">Rechnungs-Platzhalter:</div>
        <div className="mt-1 flex flex-wrap gap-1.5">{inv.map((t) => <Chip key={t} t={t} />)}</div>
        <div className="mt-2 text-xs text-muted">KVA-Platzhalter:</div>
        <div className="mt-1 flex flex-wrap gap-1.5">{kva.map((t) => <Chip key={t} t={t} />)}</div>
      </Card>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <h3 className="mb-3 text-sm font-bold text-text">Rechnungs-E-Mail</h3>
          <Field label="Betreff"><input value={invSub} onChange={(e) => setInvSub(e.target.value)} className={inputCls} /></Field>
          <div className="mt-3"><div className={labelCls}>Nachricht</div>
            <textarea data-field="invBody" onFocus={(e) => (lastFocused.current = e.currentTarget)} value={invBody} onChange={(e) => setInvBody(e.target.value)} placeholder="Sehr geehrte/r {kundename}, anbei erhalten Sie Ihre Rechnung {rechnungsnummer}…" className={ta} />
          </div>
        </Card>
        <Card>
          <h3 className="mb-3 text-sm font-bold text-text">KVA-E-Mail</h3>
          <Field label="Betreff"><input value={kvaSub} onChange={(e) => setKvaSub(e.target.value)} className={inputCls} /></Field>
          <div className="mt-3"><div className={labelCls}>Nachricht</div>
            <textarea data-field="kvaBody" onFocus={(e) => (lastFocused.current = e.currentTarget)} value={kvaBody} onChange={(e) => setKvaBody(e.target.value)} placeholder="Sehr geehrte/r {kundename}, anbei erhalten Sie unseren Kostenvoranschlag {kvanummer}…" className={ta} />
          </div>
        </Card>
      </div>
      <SaveBar onReset={reset} onSave={() => save.mutate()} saving={save.isPending} resetLabel="Beide zurücksetzen" />
    </div>
  )
}

// ─── Kalender-Sync ────────────────────────────────────────────────────────────
function KalenderSyncSection({ flash }: { flash: (m: string) => void }) {
  const providers = [
    { key: 'google', name: 'Google Kalender', summary: 'Termine werden automatisch zwischen CRM und Google Kalender synchronisiert.', token: false },
    { key: 'outlook', name: 'Outlook Kalender', summary: 'Termine werden automatisch zwischen CRM und Outlook synchronisiert.', token: false },
    { key: 'calendly', name: 'Calendly', summary: 'Eingehende Calendly-Buchungen erscheinen automatisch im CRM-Kalender.', token: true },
  ]
  return <div className="space-y-3">{providers.map((p) => <CalendarProviderCard key={p.key} p={p} flash={flash} />)}</div>
}
function CalendarProviderCard({ p, flash }: { p: { name: string; summary: string; token: boolean }; flash: (m: string) => void }) {
  const [more, setMore] = useState(false)
  const [showToken, setShowToken] = useState(false)
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2"><Calendar size={18} className="text-green-deep" /><span className="font-bold text-text">{p.name}</span></div>
        <span className="rounded-full bg-alt px-2.5 py-0.5 text-xs font-medium text-muted">Nicht verbunden</span>
      </div>
      <p className="mt-1 text-sm text-muted">{p.summary}</p>
      <div className="mt-3 flex items-center gap-3">
        <button onClick={() => (p.token ? setShowToken(true) : flash('OAuth-Integration in Kürze verfügbar.'))} className="rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110">Verbinden</button>
        <button onClick={() => setMore((m) => !m)} className="text-sm font-medium text-green-deep hover:underline">Mehr erfahren</button>
      </div>
      {p.token && showToken && (
        <div className="mt-3">
          <Field label="Calendly API-Token"><input className={inputCls} placeholder="cal_…" /></Field>
          {/* TODO: Calendly token integration out of scope this sprint. */}
          <button onClick={() => flash('OAuth-Integration in Kürze verfügbar.')} className="mt-2 rounded-md border border-border bg-surface px-3 py-1.5 text-sm font-medium text-body hover:bg-alt">Token speichern</button>
        </div>
      )}
      {more && <ul className="mt-3 list-disc space-y-1 border-t border-border pt-3 pl-5 text-sm text-muted"><li>Zwei-Wege-Synchronisierung von Terminen</li><li>Automatische Aktualisierung bei Änderungen</li><li>Konfliktvermeidung bei Doppelbuchungen</li></ul>}
    </Card>
  )
}

// ─── Google Reviews ───────────────────────────────────────────────────────────
function GoogleReviewsSection({ org }: { org: Org }) {
  const qc = useQueryClient()
  const [on, setOn] = useState(org.google_reviews_enabled)
  const timer = useRef<number | undefined>(undefined)
  const toggle = (v: boolean) => {
    setOn(v)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      apiFetch('/api/settings/google-reviews', { method: 'PATCH', body: JSON.stringify({ google_reviews_enabled: v }) }).then(() => qc.invalidateQueries({ queryKey: ['settings'] }))
    }, 500)
  }
  return (
    <Card>
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-warning-bg"><Star size={18} className="text-warning" /></div>
          <div>
            <h2 className="text-lg font-bold text-text">Google Reviews</h2>
            <p className="mt-1 text-sm text-muted">{on ? 'Bewertungsanfrage 3 Tage nach Auftragsabschluss versendet.' : 'Kunden nach Auftragsabschluss automatisch um Bewertung bitten — aktuell deaktiviert.'}</p>
          </div>
        </div>
        <Toggle on={on} onChange={toggle} />
      </div>
    </Card>
  )
}

// ─── PDS-Software ─────────────────────────────────────────────────────────────
const PDS_ENTITIES: [string, string][] = [['customers', 'Kunden'], ['inquiries', 'Anfragen/Aufträge'], ['appointments', 'Termine'], ['projects', 'Projekte'], ['invoices', 'Rechnungen'], ['cost_estimates', 'KVAs'], ['time_entries', 'Zeiterfassung'], ['catalog', 'Katalog'], ['assets', 'Anlagen']]
const SYNC_INTERVALS: [string, string][] = [['every_15_min', '15 Minuten'], ['every_30_min', '30 Minuten'], ['hourly', 'Stündlich'], ['daily', 'Täglich']]
const DIRECTIONS: [string, string][] = [['bidirectional', 'Bidirektional'], ['import', 'Nur Import'], ['export', 'Nur Export']]
function PdsSection({ config, flash }: { config: PdsConfig | null; flash: (m: string) => void }) {
  const qc = useQueryClient()
  const [apiUrl, setApiUrl] = useState(config?.api_url || '')
  const [apiUser, setApiUser] = useState(config?.api_user || '')
  const [apiKey, setApiKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [autoSync, setAutoSync] = useState(config?.auto_sync_enabled ?? false)
  const [syncInterval, setSyncInterval] = useState(config?.sync_interval || 'every_30_min')
  const [entities, setEntities] = useState<Record<string, string>>(config?.sync_entities || {})
  const toggleEntity = (k: string) => setEntities((e) => { const n = { ...e }; if (n[k]) delete n[k]; else n[k] = 'bidirectional'; return n })
  const setDir = (k: string, d: string) => setEntities((e) => ({ ...e, [k]: d }))
  const save = useMutation({
    mutationFn: () => apiFetch('/api/settings/pds-config', { method: 'PATCH', body: JSON.stringify({ api_url: apiUrl, api_user: apiUser, auto_sync_enabled: autoSync, sync_interval: syncInterval, sync_entities: entities, ...(apiKey ? { api_key: apiKey } : {}) }) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['settings'] }); setApiKey(''); flash('Gespeichert.') },
  })
  const testConn = useMutation({ mutationFn: () => apiFetch<{ message?: string }>('/api/settings/pds-test', { method: 'POST' }), onSuccess: (r) => flash(r?.message || 'Test') })
  const syncNow = useMutation({ mutationFn: () => apiFetch<{ message?: string }>('/api/settings/pds-sync', { method: 'POST' }), onSuccess: (r) => flash(r?.message || 'Sync') })
  return (
    <Card>
      <GroupLabel>API-Konfiguration</GroupLabel>
      <div className="grid grid-cols-2 gap-4">
        <Field label="PDS API URL"><input value={apiUrl} onChange={(e) => setApiUrl(e.target.value)} className={inputCls} /></Field>
        <Field label="API-Benutzer (optional)"><input value={apiUser} onChange={(e) => setApiUser(e.target.value)} className={inputCls} /></Field>
      </div>
      <div className="mt-4"><Field label="API-Key">
        <div className="relative">
          <input type={showKey ? 'text' : 'password'} value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder={config?.has_api_key ? 'Leer = bestehenden behalten' : 'API-Key eingeben'} className={cn(inputCls, 'pr-10')} />
          <button onClick={() => setShowKey((s) => !s)} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted">{showKey ? <EyeOff size={15} /> : <Eye size={15} />}</button>
        </div>
      </Field></div>
      <button onClick={() => testConn.mutate()} className="mt-3 rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-body hover:bg-alt">Verbindung testen</button>

      <div className="my-6 border-t border-border" />
      <GroupLabel>Synchronisierung</GroupLabel>
      <label className="flex items-center gap-2 text-sm text-text"><Toggle on={autoSync} onChange={setAutoSync} /> Automatische Synchronisierung aktivieren</label>
      <div className="mt-3"><Field label="Sync-Intervall"><select value={syncInterval} disabled={!autoSync} onChange={(e) => setSyncInterval(e.target.value)} className={cn(inputCls, 'max-w-xs', !autoSync && 'opacity-50')}>{SYNC_INTERVALS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field></div>

      <div className="my-6 border-t border-border" />
      <GroupLabel>Daten</GroupLabel>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {PDS_ENTITIES.map(([k, l]) => (
          <div key={k} className="flex items-center gap-2 rounded-md border border-border p-2">
            <label className="flex flex-1 items-center gap-2 text-sm text-text"><input type="checkbox" checked={!!entities[k]} onChange={() => toggleEntity(k)} className="h-4 w-4 accent-green-primary" /> {l}</label>
            {entities[k] && <select value={entities[k]} onChange={(e) => setDir(k, e.target.value)} className="rounded-md border border-border bg-alt px-1.5 py-1 text-xs text-text outline-none">{DIRECTIONS.map(([v, dl]) => <option key={v} value={v}>{dl}</option>)}</select>}
          </div>
        ))}
      </div>

      <div className="mt-6 flex items-center justify-between border-t border-border pt-4">
        <button onClick={() => syncNow.mutate()} className="rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-body hover:bg-alt">Jetzt synchronisieren</button>
        <button onClick={() => save.mutate()} disabled={save.isPending} className="rounded-md bg-green-primary px-6 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">{save.isPending ? 'Speichert…' : 'Speichern'}</button>
      </div>
    </Card>
  )
}

// ─── Gefahrenzone ─────────────────────────────────────────────────────────────
function GefahrenzoneSection({ org, flash }: { org: Org; flash: (m: string) => void }) {
  const navigate = useNavigate()
  const [resetOpen, setResetOpen] = useState(false)
  const [delOpen, setDelOpen] = useState(false)
  const [confirmName, setConfirmName] = useState('')
  const del = useMutation({
    mutationFn: () => apiFetch('/api/settings/organization', { method: 'DELETE', headers: { 'X-Confirm-Delete': org.name || '' } }),
    onSuccess: async () => { await supabase?.auth.signOut(); navigate('/login') },
    onError: () => flash('Löschen fehlgeschlagen.'),
  })
  return (
    <div className="rounded-xl border-2 border-dashed border-error/50 p-5">
      <div className="mb-4 flex items-center gap-2 text-sm font-bold text-error"><AlertTriangle size={16} /> Gefahrenzone — Diese Aktionen können nicht rückgängig gemacht werden.</div>
      <div className="space-y-3">
        <div className="rounded-lg border border-border bg-surface p-4">
          <h3 className="text-sm font-bold text-text">Onboarding zurücksetzen</h3>
          <p className="mt-1 text-sm text-muted">Branche, Öffnungszeiten und KI-Konfiguration werden zurückgesetzt. Kunden, Rechnungen und Termine bleiben erhalten.</p>
          <button onClick={() => setResetOpen(true)} className="mt-3 rounded-md border border-warning px-4 py-2 text-sm font-semibold text-warning hover:bg-warning-bg">Onboarding zurücksetzen</button>
        </div>
        <div className="rounded-lg border border-error/40 bg-error-bg/30 p-4">
          <h3 className="text-sm font-bold text-text">Organisation löschen</h3>
          <p className="mt-1 text-sm text-muted">Löscht unwiderruflich alle Daten: Kunden, Rechnungen, Termine, Mitarbeiter, Projekte.</p>
          <button onClick={() => { setConfirmName(''); setDelOpen(true) }} className="mt-3 rounded-md bg-error px-4 py-2 text-sm font-semibold text-white hover:brightness-110">Organisation löschen</button>
        </div>
      </div>

      {/* TODO: onboarding-reset endpoint out of scope this sprint. */}
      <Modal open={resetOpen} onOpenChange={setResetOpen} title="Onboarding zurücksetzen" footer={
        <div className="flex gap-3">
          <button onClick={() => setResetOpen(false)} className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body">Abbrechen</button>
          <button onClick={() => { setResetOpen(false); flash('Wird in Kürze verfügbar.') }} className="flex-1 rounded-md bg-warning py-2.5 text-sm font-semibold text-white">Zurücksetzen</button>
        </div>
      }><p className="text-sm text-body">Möchten Sie das Onboarding wirklich zurücksetzen? Branche, Öffnungszeiten und KI-Konfiguration gehen verloren.</p></Modal>

      <Modal open={delOpen} onOpenChange={setDelOpen} title="Organisation löschen" footer={
        <div className="flex gap-3">
          <button onClick={() => setDelOpen(false)} className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body">Abbrechen</button>
          <button disabled={confirmName !== (org.name || '') || del.isPending} onClick={() => del.mutate()} className="flex-1 rounded-md bg-error py-2.5 text-sm font-semibold text-white disabled:opacity-50">Endgültig löschen</button>
        </div>
      }>
        <p className="text-sm text-body">Geben Sie zur Bestätigung den Organisationsnamen <span className="font-bold text-text">{org.name}</span> ein:</p>
        <input value={confirmName} onChange={(e) => setConfirmName(e.target.value)} className={cn(inputCls, 'mt-3')} placeholder={org.name || ''} />
      </Modal>
    </div>
  )
}
