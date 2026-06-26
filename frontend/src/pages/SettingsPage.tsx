import { type QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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
  ExternalLink,
  Eye,
  EyeOff,
  FileText,
  Info,
  Lock,
  Mail,
  Minus,
  Palette,
  Plug,
  Receipt,
  Star,
  TrendingUp,
  Upload,
  UploadCloud,
  Users,
  Wrench,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'

import { KpiCard } from '../components/ui/KpiCard'
import { Modal } from '../components/ui/Modal'
import { applyAccent, isHexColor } from '../lib/accent'
import { apiFetch, apiUpload } from '../lib/api'
import {
  type BillingInvoice,
  type BillingSummary,
  type ChangePlanPreview,
  type PlanOption,
  billingStatusLabel,
  fmtCents,
  stripeInvoiceStatusLabel,
} from '../lib/dashApi'
import { supabase } from '../lib/supabase'
import { useTheme } from '../lib/theme'
import { useToast } from '../lib/useToast'
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
    { slug: 'kalender-sync', label: 'Kalender-Abgleich', icon: Calendar },
    { slug: 'google-reviews', label: 'Google-Bewertungen', icon: Star },
  ] },
  { label: 'Integrationen', items: [
    { slug: 'pds-software', label: 'PDS-Software', icon: Plug },
  ] },
  // Konto sits LAST, immediately before the Danger Zone. The admin = the company
  // login; password lives here (Company Settings) now that the personal-settings
  // surface is employee-only.
  { label: 'Konto', items: [
    { slug: 'passwort', label: 'Passwort', icon: Lock },
  ] },
]
const DANGER: NavItem = { slug: 'gefahrenzone', label: 'Gefahrenzone', icon: AlertTriangle }
const ALL_SLUGS = new Set([...NAV_GROUPS.flatMap((g) => g.items.map((i) => i.slug)), DANGER.slug])

export function SettingsPage() {
  const { section = 'stammdaten' } = useParams()
  const navigate = useNavigate()
  const me = useQuery({
    queryKey: ['me'],
    queryFn: () => apiFetch<{ role: string | null }>('/api/me'),
    staleTime: 5 * 60 * 1000,
  })
  const isAdmin = me.data?.role === 'org_admin' || me.data?.role === 'super_admin'
  const { data, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiFetch<SettingsResponse>('/api/settings'),
    staleTime: STALE,
    enabled: isAdmin,
  })

  const { toast, flash } = useToast()

  if (!ALL_SLUGS.has(section)) return <Navigate to="/settings/stammdaten" replace />

  // Employees (non-admins) get an explicit RESTRICTED message — not a perpetual
  // loader (GET /api/settings is admin-only). Wait for the role to resolve first.
  if (!me.isLoading && !isAdmin) {
    return (
      <div className="p-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-text">Einstellungen</h1>
        </div>
        <div className="mx-auto mt-6 max-w-md rounded-xl border border-border bg-surface p-8 text-center">
          <div className="mb-3 flex justify-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-alt">
              <Lock size={22} className="text-muted" />
            </div>
          </div>
          <h2 className="text-lg font-bold text-text">Nur für Administratoren</h2>
          <p className="mt-1.5 text-sm text-muted">
            Die Unternehmenseinstellungen sind nur für Administratoren zugänglich. Bitte
            wende dich an deinen Administrator, wenn du Änderungen benötigst.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="p-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-text">Einstellungen</h1>
        <p className="mt-0.5 text-sm text-muted">Verwalte dein Unternehmen, deine Integrationen und deine Benachrichtigungen.</p>
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
            <div className="rounded-xl border border-border bg-surface p-12 text-center text-muted">Wird geladen…</div>
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
    case 'abrechnung': return <AbrechnungSection usage={data.usage} flash={flash} />
    case 'ki-vorschlaege': return <KiVorschlaegeSection ai={data.ai_suggestions} flash={flash} />
    case 'benachrichtigungen': return <BenachrichtigungenSection />
    case 'email-versand': return <EmailVersandSection config={data.email_config} flash={flash} />
    case 'email-vorlagen': return <EmailVorlagenSection config={data.email_config} flash={flash} />
    case 'kalender-sync': return <KalenderSyncSection flash={flash} />
    case 'google-reviews': return <GoogleReviewsSection org={data.organization} />
    case 'pds-software': return <PdsSection config={data.pds_config} flash={flash} />
    case 'passwort': return <PasswortSection flash={flash} />
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
      const bank_details: Record<string, string> = { ...(org.bank_details || {}), bank_name: f.bankName, iban: f.iban, bic: f.bic }
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
  const { theme, toggle } = useTheme()
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
      <p className="mt-2 text-xs text-muted">PNG, JPG oder SVG, max. 2 MB. Erscheint in Seitenleiste, Anmeldung und Rechnungen/PDFs.</p>

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
          <button className="rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white">Hauptschaltfläche</button>
          <button className="rounded-md border border-green-primary px-4 py-2 text-sm font-semibold text-green-deep">Zweite Schaltfläche</button>
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
        <div className="text-2xl font-bold text-text">Übersicht</div>
        <div className="text-base font-semibold text-body">Rechnungen & Angebote</div>
      </div>

      {/* Darstellung — per-device preference (localStorage), applies live, no save
          needed. Lives here so the company login keeps the dark-mode control now
          that the personal-settings surface is employee-only. */}
      <div className="my-6 border-t border-border" />
      <GroupLabel>Darstellung</GroupLabel>
      <label className="flex items-center justify-between rounded-lg bg-alt p-4">
        <span className="text-sm font-medium text-text">Dunkles Design</span>
        <Toggle on={theme === 'dark'} onChange={() => toggle()} />
      </label>

      <SaveBar onReset={reset} onSave={() => save.mutate()} saving={save.isPending} />
    </Card>
  )
}

// ─── Plan features (mirrors the catalog packaging — Amber 2026-06-26) ─────────
const PLAN_FEATURE_BULLETS: Record<string, string[]> = {
  'Kiki Basis': ['Kiki – Anrufe qualifizieren', 'Kontakte', 'Geschäftszeiten', 'Begrüßungen'],
  'Kiki Pro': ['Alles aus Basis', 'Vorgänge & Aufträge', 'Planungstafel', 'Kalender & Terminverwaltung', 'Automatische Notizen (KI)'],
  'Kiki Enterprise': ['Alles aus Pro', 'Projekte', 'Finanzen (Rechnungen, Angebote)', 'Artikel/Katalog', 'ERP-Integrationen', 'API & Custom'],
  'Kiki Legacy': ['Alles aus Basis', 'Vorgänge & Aufträge', 'Basic Notizen (manuell)'],
}

const COMPARE_COLUMNS = ['Kiki Basis', 'Kiki Pro', 'Kiki Enterprise']
const COMPARE_GROUPS: { group: string; rows: { label: string; in: string[] }[] }[] = [
  { group: 'Kommunikation', rows: [
    { label: 'Kiki – Anrufe qualifizieren', in: ['Kiki Basis', 'Kiki Pro', 'Kiki Enterprise'] },
    { label: 'Kontakte', in: ['Kiki Basis', 'Kiki Pro', 'Kiki Enterprise'] },
    { label: 'Geschäftszeiten', in: ['Kiki Basis', 'Kiki Pro', 'Kiki Enterprise'] },
    { label: 'Begrüßungen', in: ['Kiki Basis', 'Kiki Pro', 'Kiki Enterprise'] },
  ] },
  { group: 'Workflow & Termine', rows: [
    { label: 'Vorgänge & Aufträge', in: ['Kiki Pro', 'Kiki Enterprise'] },
    { label: 'Planungstafel', in: ['Kiki Pro', 'Kiki Enterprise'] },
    { label: 'Kalender & Terminverwaltung', in: ['Kiki Pro', 'Kiki Enterprise'] },
    { label: 'Automatische Notizen (KI)', in: ['Kiki Pro', 'Kiki Enterprise'] },
  ] },
  { group: 'Enterprise', rows: [
    { label: 'Projekte', in: ['Kiki Enterprise'] },
    { label: 'Finanzen (Rechnungen, Angebote)', in: ['Kiki Enterprise'] },
    { label: 'Artikel/Katalog', in: ['Kiki Enterprise'] },
    { label: 'ERP-Integrationen', in: ['Kiki Enterprise'] },
    { label: 'API & Custom', in: ['Kiki Enterprise'] },
  ] },
]

const shortPlan = (title: string) => title.replace(/^Kiki\s+/, '')

function PlanFeatureList({ plan }: { plan: string }) {
  const bullets = PLAN_FEATURE_BULLETS[plan] ?? []
  if (!bullets.length) return null
  return (
    <ul className="mt-3 space-y-1.5">
      {bullets.map((b) => (
        <li key={b} className="flex items-start gap-2 text-xs text-body">
          <Check size={13} className="mt-0.5 shrink-0 text-green-deep" />
          <span>{b}</span>
        </li>
      ))}
    </ul>
  )
}

function PlanComparison() {
  return (
    <div className="mt-5">
      <div className="mb-2 text-sm font-bold text-text">Alle Funktionen im Vergleich</div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[440px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-border">
              <th className="sticky left-0 z-10 bg-surface py-2 pr-3 text-left text-xs font-bold uppercase tracking-wide text-muted">Funktion</th>
              {COMPARE_COLUMNS.map((c) => (
                <th key={c} className="px-3 py-2 text-center text-sm font-bold text-text">{shortPlan(c)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {COMPARE_GROUPS.flatMap((g) => [
              <tr key={`${g.group}-head`} className="bg-alt/60">
                <td colSpan={COMPARE_COLUMNS.length + 1} className="sticky left-0 px-0 py-1.5 text-xs font-bold uppercase tracking-wide text-muted">{g.group}</td>
              </tr>,
              ...g.rows.map((row) => (
                <tr key={row.label} className="border-t border-border">
                  <td className="sticky left-0 z-10 bg-surface py-2 pr-3 text-left text-body">{row.label}</td>
                  {COMPARE_COLUMNS.map((c) => (
                    <td key={c} className="px-3 py-2 text-center">
                      {row.in.includes(c)
                        ? <Check size={16} className="mx-auto text-green-deep" />
                        : <Minus size={16} className="mx-auto text-muted/40" />}
                    </td>
                  ))}
                </tr>
              )),
            ])}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ─── Abrechnung ───────────────────────────────────────────────────────────────
function AbrechnungSection({ usage, flash }: { usage: Usage; flash: (m: string) => void }) {
  const qc = useQueryClient()
  // Billing endpoints exist only when STRIPE_BILLING_ENABLED on the backend; on
  // 404 (module off) the queries error and we fall back to the usage-only view.
  const summaryQ = useQuery({
    queryKey: ['billing', 'summary'],
    queryFn: () => apiFetch<BillingSummary>('/api/billing/summary'),
    retry: false,
    staleTime: STALE,
  })
  const s = summaryQ.data
  // 'Subscribed' = an actual Stripe subscription exists (any live state) — NOT merely
  // 'has a Stripe customer'. A failed checkout can create a customer without a
  // subscription; keying the whole billing view off status (not 'configured') is what
  // keeps usage/plan/invoices hidden until the customer has really subscribed.
  const subscribed =
    !!s && ['active', 'trialing', 'past_due', 'unpaid'].includes(s.status ?? '')
  const invoicesQ = useQuery({
    queryKey: ['billing', 'invoices'],
    queryFn: () => apiFetch<BillingInvoice[]>('/api/billing/invoices?limit=12'),
    retry: false,
    enabled: subscribed,
    staleTime: STALE,
  })
  const portal = useMutation({
    mutationFn: () => apiFetch<{ url: string }>('/api/billing/portal-session', { method: 'POST' }),
    onSuccess: (r) => { window.location.href = r.url },
  })
  const plansQ = useQuery({
    queryKey: ['billing', 'plans'],
    queryFn: () => apiFetch<PlanOption[]>('/api/billing/plans'),
    retry: false,
    staleTime: STALE,
  })
  const [planInterval, setPlanInterval] = useState<'month' | 'year'>('month')
  const [showUpgrade, setShowUpgrade] = useState(false)
  // The plan the user has selected to switch to but not yet confirmed — drives the
  // "confirm the change + prorated cost" step so a tier change is never silent.
  const [pendingPlan, setPendingPlan] = useState<PlanOption | null>(null)
  const subscribe = useMutation({
    mutationFn: (vars: { plan_title: string; interval: string }) =>
      apiFetch<{ url: string }>('/api/billing/checkout-session', {
        method: 'POST',
        // Send our own origin so Stripe returns the user to THIS app (logged in),
        // not a baked PUBLIC_URL that may differ and bounce them to /login.
        body: JSON.stringify({ ...vars, return_origin: window.location.origin }),
      }),
    onSuccess: (r) => { window.location.href = r.url },
  })
  // In-CRM plan switch: swap the live subscription up OR down (no Stripe redirect);
  // Stripe prorates the difference onto the next invoice. Reflect the synced summary.
  const changePlan = useMutation({
    mutationFn: (vars: { plan_title: string }) =>
      apiFetch<BillingSummary>('/api/billing/change-plan', { method: 'POST', body: JSON.stringify(vars) }),
    onSuccess: (next) => {
      qc.setQueryData(['billing', 'summary'], next)
      qc.invalidateQueries({ queryKey: ['billing'] })
      setShowUpgrade(false)
      setPendingPlan(null)
      flash(`Tarif geändert: ${next.plan_title ?? 'aktualisiert'}.`)
    },
  })
  // Prorated cost of the selected switch — fetched when a target is picked, shown in
  // the confirm step so the customer sees the adjusted amount before applying.
  const previewQ = useQuery({
    queryKey: ['billing', 'change-preview', pendingPlan?.plan_title],
    queryFn: () => apiFetch<ChangePlanPreview>('/api/billing/change-plan/preview', {
      method: 'POST', body: JSON.stringify({ plan_title: pendingPlan!.plan_title }),
    }),
    enabled: !!pendingPlan,
    retry: false,
    staleTime: 0,
  })

  // Webhook fallback: Stripe redirects back to ?checkout=success after a self-serve
  // Checkout, but its webhook can't reach localhost — so pull the new subscription
  // once and refresh the billing views. (?checkout=cancel → just clean the URL.)
  const checkoutHandled = useRef(false)
  useEffect(() => {
    if (checkoutHandled.current) return
    const checkout = new URLSearchParams(window.location.search).get('checkout')
    if (!checkout) return
    checkoutHandled.current = true
    window.history.replaceState({}, '', window.location.pathname) // don't re-trigger on refresh
    if (checkout !== 'success') {
      if (checkout === 'cancel') flash('Vorgang abgebrochen.')
      return
    }
    apiFetch<BillingSummary>('/api/billing/sync', { method: 'POST' })
      .then((s) => {
        qc.setQueryData(['billing', 'summary'], s) // instant, before the refetch lands
        qc.invalidateQueries({ queryKey: ['billing'] })
        flash(s.status === 'trialing' ? 'Testphase gestartet.' : 'Abonnement aktiviert.')
      })
      .catch(() => {
        qc.invalidateQueries({ queryKey: ['billing'] })
        flash('Status konnte nicht aktualisiert werden. Bitte Seite neu laden.')
      })
  }, [qc, flash])

  // Prefer the Stripe-derived summary; fall back to the settings usage payload.
  const used = s ? s.used_minutes : usage.ai_minutes_used
  const quota = s ? s.quota_minutes : usage.ai_minutes_quota ?? 0
  const over = s ? s.over_quota : quota > 0 && usage.ai_minutes_used > quota
  const pct = quota ? Math.round((used / quota) * 100) : 0
  const size = usage.document_size_bytes > 1e6 ? `${(usage.document_size_bytes / 1e6).toFixed(1)} MB` : `${Math.round(usage.document_size_bytes / 1024)} KB`
  const invoices = invoicesQ.data ?? []
  const plans = plansQ.data ?? []
  // Switch targets = every other self-serve plan (up AND down) except the current one.
  // Stripe prorates the difference (credit on downgrade, charge on upgrade).
  const otherPlans = plans.filter((p) => p.plan_title !== s?.plan_title)
  const trialing = s?.status === 'trialing'
  const paymentDue = s?.status === 'past_due' || s?.status === 'unpaid'

  return (
    <div className="space-y-4">
      {paymentDue && (
        <div className="flex items-start gap-3 rounded-xl border border-error/40 bg-error-bg/40 p-4 text-sm text-body">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-error" />
          <span><strong>Zahlung erforderlich.</strong> Deine letzte Zahlung ist fehlgeschlagen. Bitte aktualisiere deine Zahlungsdetails, um eine Unterbrechung zu vermeiden.{' '}
            <button onClick={() => portal.mutate()} className="font-semibold text-green-deep underline">Jetzt aktualisieren</button>
          </span>
        </div>
      )}
      {trialing && (
        <div className="flex items-start gap-3 rounded-xl border border-info/30 bg-info-bg/40 p-4 text-sm text-body">
          <Info size={16} className="mt-0.5 shrink-0 text-info" />
          <span><strong>Testphase aktiv</strong>{s?.period_end ? ` – endet am ${new Date(s.period_end).toLocaleDateString('de-DE', { timeZone: 'Europe/Berlin' })}` : ''}. Hinterlege eine Zahlungsmethode, damit deine KI nahtlos weiterläuft.</span>
        </div>
      )}
      {subscribed && s && (
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-green-tint-100"><CreditCard size={18} className="text-green-deep" /></div>
              <div>
                <div className="text-xs font-bold uppercase tracking-wide text-muted">Aktueller Tarif</div>
                <div className="text-lg font-bold leading-tight text-text">{s.plan_title ?? 'Individueller Tarif'}</div>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
              <div>
                <div className="text-xs font-bold uppercase tracking-wide text-muted">Status</div>
                <div className={cn('text-sm font-semibold', s.status === 'past_due' || s.status === 'unpaid' ? 'text-error' : 'text-text')}>{billingStatusLabel(s.status)}</div>
              </div>
              {s.next_invoice_amount_cents != null && (
                <div>
                  <div className="text-xs font-bold uppercase tracking-wide text-muted">Nächste Rechnung</div>
                  <div className="text-sm font-semibold text-text">{fmtCents(s.next_invoice_amount_cents, s.currency)}</div>
                </div>
              )}
              {otherPlans.length > 0 && (
                <button
                  onClick={() => { setShowUpgrade((v) => !v); setPendingPlan(null) }}
                  className="flex items-center gap-2 rounded-md border border-green-primary px-4 py-2 text-sm font-semibold text-green-deep hover:bg-green-tint-100"
                >
                  <TrendingUp size={15} /> {showUpgrade ? 'Schließen' : 'Tarif wechseln'}
                </button>
              )}
              <button
                onClick={() => portal.mutate()}
                disabled={portal.isPending}
                className="flex items-center gap-2 rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
              >
                <ExternalLink size={15} /> {portal.isPending ? 'Öffnet…' : 'Zahlungsdetails verwalten'}
              </button>
            </div>
          </div>
          {portal.isError && <div className="mt-3 text-sm text-error">{(portal.error as Error).message}</div>}

          {showUpgrade && otherPlans.length > 0 && (
            <div className="mt-4 border-t border-border pt-4">
              <div className="mb-3 text-sm font-bold text-text">Tarif wechseln</div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                {otherPlans.map((p) => {
                  const isDown = p.included_minutes < quota
                  const selected = pendingPlan?.plan_title === p.plan_title
                  return (
                    <div key={p.plan_title} className={cn('flex flex-col rounded-xl border p-4', selected ? 'border-green-primary ring-1 ring-green-primary' : 'border-border')}>
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-sm font-bold text-text">{shortPlan(p.plan_title)}</div>
                        <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide', isDown ? 'bg-alt text-muted' : 'bg-green-tint-100 text-green-deep')}>{isDown ? 'Downgrade' : 'Upgrade'}</span>
                      </div>
                      <div className="mt-1 text-2xl font-bold text-text">{fmtCents(p.monthly_cents)}<span className="text-xs font-normal text-muted">/Mon.</span></div>
                      <div className="mt-1 text-xs text-muted">{p.included_minutes} Min. inkl. · dann {fmtCents(p.overage_cents_per_min)}/Min.</div>
                      <PlanFeatureList plan={p.plan_title} />
                      <button
                        onClick={() => setPendingPlan(selected ? null : p)}
                        disabled={changePlan.isPending}
                        className={cn('mt-4 rounded-md px-4 py-2 text-sm font-semibold disabled:opacity-50', selected ? 'border border-border text-muted hover:bg-alt' : 'bg-green-primary text-white hover:brightness-110')}
                      >
                        {selected ? 'Abbrechen' : `Zu ${shortPlan(p.plan_title)} wechseln`}
                      </button>
                    </div>
                  )
                })}
              </div>
              {pendingPlan && (
                <div className="mt-4 rounded-xl border border-green-primary bg-green-tint-100/40 p-4">
                  <div className="text-sm font-semibold text-text">{shortPlan(s?.plan_title ?? 'Aktuell')} → {shortPlan(pendingPlan.plan_title)} — Wechsel bestätigen</div>
                  {previewQ.isLoading && <div className="mt-2 text-xs text-muted">Anteilige Kosten werden berechnet…</div>}
                  {previewQ.isError && <div className="mt-2 text-xs text-error">Vorschau konnte nicht geladen werden — der Wechsel ist trotzdem möglich.</div>}
                  {previewQ.data && (
                    <div className="mt-2 space-y-1.5 rounded-lg bg-surface/80 p-3 text-sm">
                      <div className="flex items-center justify-between text-muted">
                        <span>Gutschrift für ungenutzte Zeit ({shortPlan(previewQ.data.current_plan_title ?? 'aktuell')})</span>
                        <span>−{fmtCents(previewQ.data.prorated_credit_cents)}</span>
                      </div>
                      <div className="flex items-center justify-between text-muted">
                        <span>Anteilig {shortPlan(previewQ.data.target_plan_title)} (Rest der Periode)</span>
                        <span>+{fmtCents(previewQ.data.prorated_charge_cents)}</span>
                      </div>
                      <div className="flex items-center justify-between border-t border-border pt-1.5 font-bold text-text">
                        <span>{previewQ.data.net_due_cents >= 0 ? 'Differenz (auf nächster Rechnung)' : 'Dein Guthaben'}</span>
                        <span>{fmtCents(Math.abs(previewQ.data.net_due_cents))}</span>
                      </div>
                      <div className="flex items-center justify-between text-xs text-muted">
                        <span>danach</span>
                        <span>
                          {fmtCents(previewQ.data.next_recurring_cents)}/{previewQ.data.interval === 'year' ? 'Jahr' : 'Mon.'}
                          {previewQ.data.billed_on ? ` · ab ${new Date(previewQ.data.billed_on).toLocaleDateString('de-DE', { timeZone: 'Europe/Berlin' })}` : ''}
                        </span>
                      </div>
                    </div>
                  )}
                  <div className="mt-2 text-xs text-muted">Alle Beträge zzgl. 19 % MwSt.; aktive Rabatte werden bei der Abrechnung berücksichtigt.</div>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <button
                      onClick={() => changePlan.mutate({ plan_title: pendingPlan.plan_title })}
                      disabled={changePlan.isPending}
                      className="rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
                    >
                      {changePlan.isPending ? 'Wird gewechselt…' : 'Bestätigen & wechseln'}
                    </button>
                    <button
                      onClick={() => setPendingPlan(null)}
                      disabled={changePlan.isPending}
                      className="rounded-md border border-border px-4 py-2 text-sm font-semibold text-muted hover:bg-alt disabled:opacity-50"
                    >
                      Abbrechen
                    </button>
                  </div>
                  {changePlan.isError && <div className="mt-2 text-sm text-error">{(changePlan.error as Error).message}</div>}
                </div>
              )}
            </div>
          )}
        </Card>
      )}

      {subscribed && (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card>
          <div className="flex items-center gap-4">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-green-tint-100"><Clock size={18} className="text-green-deep" /></div>
            <div className="min-w-0">
              <div className="text-xs font-bold uppercase tracking-wide text-muted">KI-Minuten (Abrechnungsperiode)</div>
              <div className="text-2xl font-bold leading-tight text-text">{used} / {quota || '∞'}</div>
            </div>
          </div>
          <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-alt">
            <div className={cn('h-full rounded-full', over ? 'bg-error' : 'bg-green-primary')} style={{ width: `${Math.min(pct, 100)}%` }} />
          </div>
        </Card>
        <KpiCard label="Aktive Mitarbeiter" value={usage.active_employees} icon={Users} />
        <KpiCard label="Gespeicherte Dokumente" value={usage.document_count} sub={size} icon={FileText} />
      </div>
      )}

      {/* Two pre-overage warnings (80 % → first, 95 % → final), mirroring the two
          warning e-mails the backend sends before any extra usage is charged. */}
      {subscribed && !over && quota > 0 && pct >= 80 && pct < 95 && (
        <div className="flex items-start gap-3 rounded-xl border border-warning/30 bg-warning-bg/40 p-4 text-sm text-body">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-warning" />
          <span><strong>{Math.round(pct)} % deines Minutenkontingents verbraucht.</strong> Ab {quota} Min. wird jede weitere Minute nach Tarif berechnet.</span>
        </div>
      )}
      {subscribed && !over && quota > 0 && pct >= 95 && (
        <div className="flex items-start gap-3 rounded-xl border border-warning/50 bg-warning-bg/60 p-4 text-sm text-body">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-warning" />
          <span><strong>Letzte Warnung: {Math.round(pct)} % verbraucht.</strong> Dein Kontingent ist fast aufgebraucht. Ab {quota} Min. wird jede weitere Minute{s?.overage_cents_per_min != null ? ` mit ${fmtCents(s.overage_cents_per_min)}/Min.` : ''} berechnet.</span>
        </div>
      )}
      {subscribed && over && (
        <div className="flex items-start gap-3 rounded-xl border border-warning/30 bg-warning-bg/40 p-4 text-sm text-body">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-warning" />
          <span>Dein Minutenkontingent ist aufgebraucht. Deine KI bleibt erreichbar — der <strong>Mehrverbrauch wird nach Tarif berechnet</strong>.</span>
        </div>
      )}

      {/* Explicit extra-usage breakdown — included vs used, minutes over, the
          per-minute tariff, and the running projected extra charge for the period. */}
      {subscribed && over && s && s.minutes_over > 0 && (
        <Card>
          <div className="mb-3 flex items-center gap-2 text-sm font-bold text-text"><Zap size={16} className="text-warning" /> Mehrverbrauch (Extra-Nutzung)</div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div>
              <div className="text-xs font-bold uppercase tracking-wide text-muted">Inklusive</div>
              <div className="text-lg font-bold leading-tight text-text">{s.quota_minutes} Min.</div>
            </div>
            <div>
              <div className="text-xs font-bold uppercase tracking-wide text-muted">Verbraucht</div>
              <div className="text-lg font-bold leading-tight text-text">{s.used_minutes} Min.</div>
            </div>
            <div>
              <div className="text-xs font-bold uppercase tracking-wide text-muted">Mehr als das</div>
              <div className="text-lg font-bold leading-tight text-warning">+{s.minutes_over} Min.</div>
            </div>
            <div>
              <div className="text-xs font-bold uppercase tracking-wide text-muted">Tarif</div>
              <div className="text-lg font-bold leading-tight text-text">{s.overage_cents_per_min != null ? `${fmtCents(s.overage_cents_per_min)}/Min.` : '—'}</div>
            </div>
          </div>
          {s.projected_overage_cents != null && (
            <div className="mt-3 flex items-center justify-between rounded-lg bg-warning-bg/40 px-4 py-3">
              <span className="text-sm font-semibold text-text">Voraussichtlicher Mehrverbrauch (zzgl. 19 % MwSt.)</span>
              <span className="text-lg font-bold text-text">{fmtCents(s.projected_overage_cents)}</span>
            </div>
          )}
          <div className="mt-2 text-xs text-muted">Der Mehrverbrauch wird zusätzlich zur Grundgebühr über deine nächste Rechnung abgerechnet.</div>
        </Card>
      )}

      {subscribed && invoices.length > 0 && (
        <Card>
          <div className="mb-3 flex items-center gap-2 text-sm font-bold text-text"><Receipt size={16} className="text-green-deep" /> Rechnungen</div>
          <div className="divide-y divide-border">
            {invoices.map((inv) => (
              <div key={inv.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                <div className="min-w-0">
                  <div className="truncate font-medium text-text">{inv.number ?? inv.id}</div>
                  <div className="text-xs text-muted">
                    {inv.created ? new Date(inv.created * 1000).toLocaleDateString('de-DE', { timeZone: 'Europe/Berlin' }) : '—'} · {stripeInvoiceStatusLabel(inv.status)}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  <span className="font-semibold text-text">{fmtCents(inv.amount_paid_cents ?? inv.amount_due_cents, inv.currency ?? 'EUR')}</span>
                  {inv.hosted_invoice_url && (
                    <a href={inv.hosted_invoice_url} target="_blank" rel="noreferrer" className="font-medium text-green-deep hover:underline">Ansehen</a>
                  )}
                  {inv.invoice_pdf && (
                    <a href={inv.invoice_pdf} target="_blank" rel="noreferrer" className="font-medium text-green-deep hover:underline">PDF</a>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {!subscribed && plans.length > 0 && (
        <Card>
          <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-base font-bold text-text">Tarif wählen</div>
              <div className="text-xs text-muted">Jederzeit wechselbar. Alle Preise zzgl. 19 % MwSt.</div>
            </div>
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1 rounded-lg bg-alt p-1 text-xs font-semibold">
                <button onClick={() => setPlanInterval('month')} className={cn('rounded-md px-3 py-1 transition', planInterval === 'month' ? 'bg-surface text-text shadow' : 'text-muted')}>Monatlich</button>
                <button onClick={() => setPlanInterval('year')} className={cn('rounded-md px-3 py-1 transition', planInterval === 'year' ? 'bg-surface text-text shadow' : 'text-muted')}>Jährlich</button>
              </div>
              <span className="rounded-full bg-green-tint-100 px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-green-deep">2 Monate gratis</span>
            </div>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {plans.map((p) => {
              const annual = planInterval === 'year'
              const monthlyEquiv = Math.round(p.annual_cents / 12)
              const savings = p.monthly_cents * 12 - p.annual_cents
              const recommended = p.plan_title === 'Kiki Pro'
              return (
                <div key={p.plan_title} className={cn('relative flex flex-col rounded-2xl border p-5', recommended ? 'border-green-primary ring-1 ring-green-primary shadow-sm' : 'border-border')}>
                  {recommended && <span className="absolute -top-2.5 left-5 rounded-full bg-green-primary px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white shadow">Beliebt</span>}
                  <div className="text-sm font-bold text-text">{shortPlan(p.plan_title)}</div>
                  <div className="mt-2 flex items-baseline gap-1">
                    <span className="text-3xl font-bold leading-none text-text">{fmtCents(annual ? monthlyEquiv : p.monthly_cents)}</span>
                    <span className="text-sm font-normal text-muted">/Mon.</span>
                  </div>
                  {annual ? (
                    <div className="mt-1.5 text-xs font-semibold text-green-deep">{fmtCents(p.annual_cents)} / Jahr · spare {fmtCents(savings)}</div>
                  ) : (
                    <div className="mt-1.5 text-xs text-muted">inkl. MwSt. {fmtCents(Math.round(p.monthly_cents * 1.19))}/Mon.</div>
                  )}
                  <div className="mt-3 border-t border-border pt-3 text-xs font-semibold text-text">{p.included_minutes} Min. inkl. <span className="font-normal text-muted">· dann {fmtCents(p.overage_cents_per_min)}/Min.</span></div>
                  <PlanFeatureList plan={p.plan_title} />
                  <button
                    onClick={() => subscribe.mutate({ plan_title: p.plan_title, interval: planInterval })}
                    disabled={subscribe.isPending}
                    className={cn('mt-5 rounded-lg px-4 py-2.5 text-sm font-semibold transition disabled:opacity-50', recommended ? 'bg-green-primary text-white hover:brightness-110' : 'border border-green-primary text-green-deep hover:bg-green-tint-100')}
                  >
                    {subscribe.isPending ? 'Weiterleitung…' : 'Jetzt abonnieren'}
                  </button>
                </div>
              )
            })}
          </div>
          {subscribe.isError && <div className="mt-3 text-sm text-error">{(subscribe.error as Error).message}</div>}
          <PlanComparison />
        </Card>
      )}

      {!subscribed && (
        <div className="flex items-start gap-3 rounded-xl border border-info/30 bg-info-bg/40 p-4 text-sm text-body">
          <Info size={16} className="mt-0.5 shrink-0 text-info" />
          <span>Für Fragen zu deinem Abonnement wende dich an <a href="mailto:info@kikichat.de" className="font-medium text-green-deep hover:underline">info@kikichat.de</a>.</span>
        </div>
      )}
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
    { icon: FileText, title: 'Angebot nachfassen', sub: 'Vorschlag, wenn ein gesendetes Angebot nicht beantwortet wurde', value: kva, set: setKva, unit: 'Tage ohne Antwort' },
    { icon: Receipt, title: 'Zahlungserinnerung', sub: 'Vorschlag für eine Zahlungserinnerung bei überfälligen Rechnungen', value: pay, set: setPay, unit: 'Tage Zahlungsverzug' },
    { icon: Calendar, title: 'Terminerinnerung', sub: 'Tägliche Übersicht über anstehende Termine', value: appt, set: setAppt, unit: 'Tag(e) vorher' },
    { icon: Wrench, title: 'Wartungserinnerung', sub: 'Erscheint, wenn die Wartung laut Wartungsvertrag bald fällig ist.', value: maint, set: setMaint, unit: 'Tage vor Fälligkeit' },
  ]
  return (
    <Card>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-bold text-text">KI-Vorschläge</h2>
          <p className="text-sm text-muted">Automatische Empfehlungen in der Übersicht</p>
        </div>
        <Toggle on={enabled} onChange={setEnabled} />
      </div>
      {enabled && <p className="mt-2 text-sm text-muted">Kiki wertet deine Daten täglich um 06:00 Uhr aus und erstellt Empfehlungen, die in der Übersicht erscheinen.</p>}
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
            <p className="mt-1 text-sm text-muted">Erhalte auf diesem Gerät sofort eine Benachrichtigung bei neuen Anrufen, Anfragen und überfälligen Rechnungen.</p>
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

// ─── OAuth connect (Google / Microsoft / Calendly) ────────────────────────────
type Purpose = 'email' | 'calendar'

interface OAuthConnection {
  provider: string
  connected: boolean
  account_email: string | null
  token_expires_at: string | null
}
interface PurposeLink {
  provider: string
  account_email: string | null
}
interface OAuthState {
  connections: OAuthConnection[]
  purposes: Partial<Record<Purpose, PurposeLink>>
}

function useOAuthConnections() {
  return useQuery({
    queryKey: ['oauth-connections'],
    queryFn: () => apiFetch<OAuthState>('/api/settings/oauth/connections'),
    staleTime: STALE,
  })
}

/** Open the provider consent in a popup for a given PURPOSE (email|calendar) and
 *  refresh connection state on success. The popup is opened synchronously
 *  (preserves the click gesture), then pointed at the authed authorize URL. The
 *  callback posts {source:'heykiki-oauth', success, message} back here. */
function startOAuthConnect(
  provider: string,
  purpose: Purpose,
  qc: QueryClient,
  flash: (m: string) => void,
) {
  const popup = window.open('', 'heykiki-oauth', 'width=520,height=680')
  if (!popup) {
    flash('Bitte Popups für diese Seite erlauben und erneut versuchen.')
    return
  }
  // Guaranteed, idempotent teardown — the message listener must never leak,
  // even if the user closes the popup early or no callback ever arrives.
  let cleaned = false
  let safetyTimer: ReturnType<typeof setTimeout> | undefined
  const cleanup = () => {
    if (cleaned) return
    cleaned = true
    window.removeEventListener('message', onMessage)
    if (safetyTimer) clearTimeout(safetyTimer)
  }
  const onMessage = (e: MessageEvent) => {
    if (!e.data || e.data.source !== 'heykiki-oauth') return
    cleanup()
    flash(e.data.message || (e.data.success ? 'Verbunden.' : 'Verbindung fehlgeschlagen.'))
    if (e.data.success) qc.invalidateQueries({ queryKey: ['oauth-connections'] })
  }
  window.addEventListener('message', onMessage)
  // Safety net: drop the listener after 30s if no callback ever posts back.
  safetyTimer = setTimeout(cleanup, 30000)
  apiFetch<{ url: string }>(`/api/settings/oauth/${provider}/authorize?purpose=${purpose}`)
    .then(({ url }) => {
      popup.location.href = url
    })
    .catch((err: Error) => {
      cleanup()
      popup.close()
      flash(err.message || 'OAuth nicht verfügbar.')
    })
}

/** "Use the same account": link an already-connected provider grant to another
 *  purpose without a fresh consent (no popup). */
async function linkPurpose(
  provider: string,
  purpose: Purpose,
  qc: QueryClient,
  flash: (m: string) => void,
) {
  try {
    await apiFetch(`/api/settings/oauth/${provider}/link?purpose=${purpose}`, { method: 'POST' })
    qc.invalidateQueries({ queryKey: ['oauth-connections'] })
    flash('Verbunden — vorhandenes Konto wiederverwendet.')
  } catch (e) {
    flash((e as Error).message)
  }
}

/** Purpose-scoped disconnect. The backend drops only this purpose's link and
 *  revokes the underlying grant ONLY if no purpose still uses it. */
async function disconnectPurpose(purpose: Purpose, qc: QueryClient, flash: (m: string) => void) {
  try {
    await apiFetch(`/api/settings/oauth/disconnect?purpose=${purpose}`, { method: 'POST' })
    qc.invalidateQueries({ queryKey: ['oauth-connections'] })
    qc.invalidateQueries({ queryKey: ['calendar-sync-status'] })
    flash('Verbindung getrennt.')
  } catch (e) {
    flash((e as Error).message)
  }
}
function EmailVersandSection({ config, flash }: { config: EmailConfig | null; flash: (m: string) => void }) {
  const qc = useQueryClient()
  const conns = useOAuthConnections()
  const emailLink = conns.data?.purposes?.email // {provider, account_email} | undefined
  // Which tile ('gmail'|'outlook'|'smtp') currently serves email — the basis for
  // exclusivity (exactly one active; the other two go to disabled mode).
  const activeEmail: string | null =
    emailLink?.provider === 'google'
      ? 'gmail'
      : emailLink?.provider === 'microsoft'
        ? 'outlook'
        : config?.smtp_host
          ? 'smtp'
          : null
  const accountOf = (v: string): string | null =>
    (v === 'gmail' && emailLink?.provider === 'google') ||
    (v === 'outlook' && emailLink?.provider === 'microsoft')
      ? emailLink?.account_email ?? null
      : null
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
        {providers.map(([v, l]) => {
          // Exclusivity: when one email provider is active, the others are shown
          // disabled ("disconnect to switch").
          const locked = activeEmail !== null && activeEmail !== v
          return (
            <button
              key={v}
              disabled={locked}
              onClick={() => !locked && setProvider(v)}
              className={cn(
                'rounded-lg border p-4 text-left transition',
                provider === v ? 'border-green-primary bg-green-tint-50' : 'border-border hover:bg-alt',
                locked && 'cursor-not-allowed opacity-50 hover:bg-transparent',
              )}
            >
              <div className="flex items-center justify-between"><span className="font-semibold text-text">{l}</span>{provider === v && <Check size={16} className="text-green-deep" />}</div>
              <div className="mt-1 text-xs text-muted">
                {activeEmail === v
                  ? 'Aktiv'
                  : locked
                    ? 'Zum Wechseln andere Verbindung trennen'
                    : v === 'smtp'
                      ? 'HeyKiki Standard'
                      : 'Nicht verbunden'}
              </div>
            </button>
          )
        })}
      </div>
      <div className="mt-5">
        {provider === 'gmail' && (
          <div>
            <Banner>Verbindung über Google OAuth. Höhere Zustellrate als SMTP.</Banner>
            {activeEmail === 'gmail' ? (
              <div className="mt-3 flex items-center gap-3">
                <span className="text-sm font-medium text-success">✓ Verbunden{accountOf('gmail') ? ` als ${accountOf('gmail')}` : ''}</span>
                <button onClick={() => disconnectPurpose('email', qc, flash)} className="rounded-md border border-border bg-surface px-3 py-1.5 text-sm font-medium text-body hover:bg-alt">Trennen</button>
              </div>
            ) : (
              <button onClick={() => startOAuthConnect('google', 'email', qc, flash)} className="mt-3 rounded-md bg-green-primary px-5 py-2 text-sm font-semibold text-white hover:brightness-110">Mit Gmail verbinden</button>
            )}
          </div>
        )}
        {provider === 'outlook' && (
          <div>
            <Banner>Verbindung über Microsoft OAuth. Höhere Zustellrate als SMTP.</Banner>
            {activeEmail === 'outlook' ? (
              <div className="mt-3 flex items-center gap-3">
                <span className="text-sm font-medium text-success">✓ Verbunden{accountOf('outlook') ? ` als ${accountOf('outlook')}` : ''}</span>
                <button onClick={() => disconnectPurpose('email', qc, flash)} className="rounded-md border border-border bg-surface px-3 py-1.5 text-sm font-medium text-body hover:bg-alt">Trennen</button>
              </div>
            ) : (
              // Outlook OAuth has no credentials yet → shown but disabled.
              <button disabled title="Microsoft-Zugangsdaten noch nicht hinterlegt" className="mt-3 cursor-not-allowed rounded-md bg-green-primary px-5 py-2 text-sm font-semibold text-white opacity-50">Mit Outlook verbinden (demnächst)</button>
            )}
          </div>
        )}
        {provider === 'smtp' && (
          <div className="space-y-4">
            <Banner>Standardversand über info@kiki-zusammenfassung.de, bis eine eigene SMTP-Adresse eingetragen ist.</Banner>
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
        <p className="mb-2 text-sm text-body">Verfügbare Platzhalter — klicke auf einen Platzhalter, um ihn in das aktive Feld einzufügen.</p>
        <div className="flex flex-wrap gap-1.5">{general.map((t) => <Chip key={t} t={t} />)}</div>
        <div className="mt-2 text-xs text-muted">Rechnungs-Platzhalter:</div>
        <div className="mt-1 flex flex-wrap gap-1.5">{inv.map((t) => <Chip key={t} t={t} />)}</div>
        <div className="mt-2 text-xs text-muted">Angebot-Platzhalter:</div>
        <div className="mt-1 flex flex-wrap gap-1.5">{kva.map((t) => <Chip key={t} t={t} />)}</div>
      </Card>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <h3 className="mb-3 text-sm font-bold text-text">Rechnungs-E-Mail</h3>
          <Field label="Betreff"><input value={invSub} onChange={(e) => setInvSub(e.target.value)} className={inputCls} /></Field>
          <div className="mt-3"><div className={labelCls}>Nachricht</div>
            <textarea data-field="invBody" onFocus={(e) => (lastFocused.current = e.currentTarget)} value={invBody} onChange={(e) => setInvBody(e.target.value)} placeholder="Hallo {kundename}, anbei erhältst du deine Rechnung {rechnungsnummer}…" className={ta} />
          </div>
        </Card>
        <Card>
          <h3 className="mb-3 text-sm font-bold text-text">Angebot-E-Mail</h3>
          <Field label="Betreff"><input value={kvaSub} onChange={(e) => setKvaSub(e.target.value)} className={inputCls} /></Field>
          <div className="mt-3"><div className={labelCls}>Nachricht</div>
            <textarea data-field="kvaBody" onFocus={(e) => (lastFocused.current = e.currentTarget)} value={kvaBody} onChange={(e) => setKvaBody(e.target.value)} placeholder="Hallo {kundename}, anbei erhältst du unser Angebot {kvanummer}…" className={ta} />
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
    { provider: 'google', name: 'Google Kalender', summary: 'Google-Termine werden als belegte Zeit ins CRM übernommen (Lesen). Eine Übertragung CRM → Google erfolgt nur nach manueller Freigabe je Termin.' },
    { provider: 'microsoft', name: 'Outlook Kalender', summary: 'Termine werden automatisch zwischen CRM und Outlook synchronisiert.' },
    { provider: 'calendly', name: 'Calendly', summary: 'Eingehende Calendly-Buchungen erscheinen automatisch im Kalender.' },
  ]
  return <div className="space-y-3">{providers.map((p) => <CalendarProviderCard key={p.provider} p={p} flash={flash} />)}</div>
}
function CalendarProviderCard({ p, flash }: { p: { provider: string; name: string; summary: string }; flash: (m: string) => void }) {
  const qc = useQueryClient()
  const conns = useOAuthConnections()
  const calLink = conns.data?.purposes?.calendar        // provider serving the calendar axis
  const grants = conns.data?.connections ?? []
  const isConnected = calLink?.provider === p.provider
  const activeProvider = calLink?.provider ?? null
  // Exclusivity: another provider already serves calendar → this card is locked.
  const locked = activeProvider !== null && activeProvider !== p.provider
  // "Use the same account?": this provider already has a grant (e.g. connected
  // for email) → offer to reuse it for calendar without a fresh consent.
  const existingGrant = grants.find((c) => c.provider === p.provider)
  const noCreds = p.provider === 'microsoft' // Outlook calendar: no credentials yet
  const [more, setMore] = useState(false)
  const isGoogle = p.provider === 'google'
  // Only Google has a working read-sync today; status + manual sync are Google-only.
  const syncStatus = useQuery({
    queryKey: ['calendar-sync-status'],
    queryFn: () => apiFetch<{ last_synced_at: string | null; event_count: number }>('/api/calendar/sync-status'),
    enabled: isGoogle && isConnected,
  })
  // B3: no manual sync button at the connection point — connecting auto-syncs
  // (backend OAuth callback). Manual re-sync lives on the Kalender page.
  const lastSynced = syncStatus.data?.last_synced_at

  const connect = () => {
    // Reuse an existing google/microsoft grant for calendar if one exists.
    if (existingGrant && (p.provider === 'google' || p.provider === 'microsoft')) {
      const ok = window.confirm(
        `Dasselbe Konto${existingGrant.account_email ? ` (${existingGrant.account_email})` : ''} auch für den Kalender verwenden?`,
      )
      if (ok) {
        linkPurpose(p.provider, 'calendar', qc, flash)
        return
      }
    }
    startOAuthConnect(p.provider, 'calendar', qc, flash)
  }

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2"><Calendar size={18} className="text-green-deep" /><span className="font-bold text-text">{p.name}</span></div>
        <span className={cn('rounded-full px-2.5 py-0.5 text-xs font-medium', isConnected ? 'bg-success-bg text-success' : 'bg-alt text-muted')}>{isConnected ? 'Verbunden' : locked ? 'Andere Verbindung aktiv' : 'Nicht verbunden'}</span>
      </div>
      <p className="mt-1 text-sm text-muted">{p.summary}</p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        {isConnected ? (
          <>
            {calLink?.account_email && <span className="text-sm font-medium text-success">✓ {calLink.account_email}</span>}
            <button onClick={() => disconnectPurpose('calendar', qc, flash)} className="rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-body hover:bg-alt">Trennen</button>
          </>
        ) : locked ? (
          <span className="text-sm text-muted">Zum Wechseln zuerst die aktive Kalender-Verbindung trennen.</span>
        ) : noCreds ? (
          <button disabled title="Microsoft-Zugangsdaten noch nicht hinterlegt" className="cursor-not-allowed rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white opacity-50">Verbinden (demnächst)</button>
        ) : (
          <button onClick={connect} className="rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110">{existingGrant ? 'Verbinden (Konto wiederverwenden)' : 'Verbinden'}</button>
        )}
        <button onClick={() => setMore((m) => !m)} className="text-sm font-medium text-green-deep hover:underline">Mehr erfahren</button>
      </div>
      {isGoogle && isConnected && (
        <p className="mt-2 text-xs text-muted">
          {lastSynced
            ? `Zuletzt synchronisiert: ${new Date(lastSynced).toLocaleString('de-DE', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Europe/Berlin' })} · ${syncStatus.data?.event_count ?? 0} Termine als belegte Zeit im CRM.`
            : 'Wird beim Verbinden automatisch synchronisiert — Google-Termine erscheinen als belegte Zeit im CRM. Manuelle Synchronisierung auf der Kalender-Seite.'}
        </p>
      )}
      {more && <ul className="mt-3 list-disc space-y-1 border-t border-border pt-3 pl-5 text-sm text-muted"><li>Google-Termine erscheinen als belegte Zeit im CRM (Lesen)</li><li>Übertragung CRM → Google nur nach manueller Freigabe je Termin</li><li>Keine automatische Zwei-Wege-Synchronisierung</li></ul>}
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
            <h2 className="text-lg font-bold text-text">Google-Bewertungen</h2>
            <p className="mt-1 text-sm text-muted">{on ? 'Bewertungsanfrage 3 Tage nach Auftragsabschluss versendet.' : 'Kunden nach Auftragsabschluss automatisch um Bewertung bitten — aktuell deaktiviert.'}</p>
          </div>
        </div>
        <Toggle on={on} onChange={toggle} />
      </div>
    </Card>
  )
}

// ─── PDS-Software ─────────────────────────────────────────────────────────────
function PdsSection({ config, flash }: { config: PdsConfig | null; flash: (m: string) => void }) {
  const qc = useQueryClient()
  const [apiUrl, setApiUrl] = useState(config?.api_url || '')
  const [apiKey, setApiKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [autoSync, setAutoSync] = useState(config?.auto_sync_enabled ?? false)
  const save = useMutation({
    mutationFn: () => apiFetch('/api/settings/pds-config', { method: 'PATCH', body: JSON.stringify({ api_url: apiUrl, auto_sync_enabled: autoSync, ...(apiKey ? { api_key: apiKey } : {}) }) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['settings'] }); setApiKey(''); flash('Gespeichert.') },
  })
  // Persistent inline test result (not just a transient toast) — the demo shows
  // the live PDS answer (reachability + Personen count) right under the button.
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)
  const testConn = useMutation({
    mutationFn: () => apiFetch<{ success: boolean; message: string }>('/api/settings/pds-test', { method: 'POST' }),
    onSuccess: (r) => setTestResult(r),
    onError: (e: Error) => setTestResult({ success: false, message: e.message || 'Test fehlgeschlagen.' }),
  })
  const syncNow = useMutation({
    mutationFn: () => apiFetch<{ message?: string }>('/api/settings/pds-sync', { method: 'POST' }),
    onSuccess: (r) => flash(r?.message || 'Synchronisiert.'),
    onError: (e: Error) => flash(e.message || 'Synchronisierung fehlgeschlagen.'),
  })
  return (
    <Card>
      <GroupLabel>API-Konfiguration</GroupLabel>
      <Field label="PDS API URL"><input value={apiUrl} onChange={(e) => setApiUrl(e.target.value)} placeholder="https://41309.pdscloud.de" className={inputCls} /></Field>
      <div className="mt-4"><Field label="API-Key">
        <div className="relative">
          <input type={showKey ? 'text' : 'password'} value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder={config?.has_api_key ? 'Leer = bestehenden behalten' : 'API-Key eingeben'} className={cn(inputCls, 'pr-10')} />
          <button onClick={() => setShowKey((s) => !s)} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted">{showKey ? <EyeOff size={15} /> : <Eye size={15} />}</button>
        </div>
      </Field></div>
      <button onClick={() => { setTestResult(null); testConn.mutate() }} disabled={testConn.isPending} className="mt-3 rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-body hover:bg-alt disabled:opacity-50">
        {testConn.isPending ? 'Teste Verbindung…' : 'Verbindung testen'}
      </button>
      {testResult && (
        <div className={cn(
          'mt-2 rounded-md px-3 py-2 text-sm font-medium',
          testResult.success ? 'bg-green-tint-50 text-green-deep' : 'bg-error-bg text-error',
        )}>
          {testResult.success ? '✓ ' : '✗ '}{testResult.message}
        </div>
      )}

      <div className="my-6 border-t border-border" />
      <GroupLabel>Synchronisierung</GroupLabel>
      <label className="flex items-center gap-2 text-sm text-text"><Toggle on={autoSync} onChange={setAutoSync} /> Automatische Synchronisierung aktivieren</label>
      <p className="mt-1 text-xs text-muted">
        Ist die Synchronisierung aktiv, wird jeder eingehende KI-Anruf direkt nach Gesprächsende
        automatisch als Aufgabe in PDS protokolliert (Anrufer-Zuordnung per Telefonnummer).
      </p>

      <div className="mt-6 flex items-center justify-between border-t border-border pt-4">
        <button onClick={() => syncNow.mutate()} disabled={syncNow.isPending} className="rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-body hover:bg-alt disabled:opacity-50">
          {syncNow.isPending ? 'Synchronisiert…' : 'Jetzt synchronisieren'}
        </button>
        <button onClick={() => save.mutate()} disabled={save.isPending} className="rounded-md bg-green-primary px-6 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">{save.isPending ? 'Speichert…' : 'Speichern'}</button>
      </div>
    </Card>
  )
}

// ─── Passwort ─────────────────────────────────────────────────────────────────
function PwField({ label, value, onChange, show, onToggle }: { label: string; value: string; onChange: (v: string) => void; show: boolean; onToggle: () => void }) {
  return (
    <Field label={label}>
      <div className="relative">
        <input type={show ? 'text' : 'password'} value={value} onChange={(e) => onChange(e.target.value)} className={cn(inputCls, 'pr-10')} />
        <button type="button" onClick={onToggle} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted">{show ? <EyeOff size={15} /> : <Eye size={15} />}</button>
      </div>
    </Field>
  )
}
function PasswortSection({ flash }: { flash: (m: string) => void }) {
  const [cur, setCur] = useState('')
  const [nw, setNw] = useState('')
  const [conf, setConf] = useState('')
  const [showCur, setShowCur] = useState(false)
  const [showNew, setShowNew] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const changePw = useMutation({
    mutationFn: () => apiFetch('/api/users/me/change-password', { method: 'POST', body: JSON.stringify({ current_password: cur, new_password: nw }) }),
    onSuccess: () => { setCur(''); setNw(''); setConf(''); setError(null); flash('Passwort geändert.') },
    onError: (e: Error) => setError(e.message || 'Passwort konnte nicht geändert werden.'),
  })
  const submit = () => {
    setError(null)
    if (nw.length < 8) { setError('Neues Passwort muss mindestens 8 Zeichen haben.'); return }
    if (nw !== conf) { setError('Die neuen Passwörter stimmen nicht überein.'); return }
    changePw.mutate()
  }
  return (
    <Card>
      <GroupLabel>Passwort ändern</GroupLabel>
      <p className="mb-4 text-sm text-muted">Ändere das Passwort für deinen Firmen-Zugang.</p>
      <div className="max-w-md space-y-4">
        <PwField label="Aktuelles Passwort" value={cur} onChange={setCur} show={showCur} onToggle={() => setShowCur((s) => !s)} />
        <PwField label="Neues Passwort" value={nw} onChange={setNw} show={showNew} onToggle={() => setShowNew((s) => !s)} />
        <PwField label="Neues Passwort bestätigen" value={conf} onChange={setConf} show={showNew} onToggle={() => setShowNew((s) => !s)} />
        {error && <p className="text-sm font-medium text-error">{error}</p>}
      </div>
      <div className="mt-6 flex items-center justify-end border-t border-border pt-4">
        <button onClick={submit} disabled={changePw.isPending || !cur || !nw || !conf} className="rounded-md bg-green-primary px-6 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">{changePw.isPending ? 'Wird geändert…' : 'Passwort ändern'}</button>
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
      <div className="mb-4 flex items-center gap-2 text-sm font-bold text-error"><AlertTriangle size={16} /> Gefahrenzone — diese Aufgaben lassen sich nicht rückgängig machen.</div>
      <div className="space-y-3">
        <div className="rounded-lg border border-border bg-surface p-4">
          <h3 className="text-sm font-bold text-text">Onboarding zurücksetzen</h3>
          <p className="mt-1 text-sm text-muted">Branche, Öffnungszeiten und KI-Konfiguration werden zurückgesetzt. Kunden, Rechnungen und Termine bleiben erhalten.</p>
          <button onClick={() => setResetOpen(true)} className="mt-3 rounded-md border border-warning px-4 py-2 text-sm font-semibold text-warning hover:bg-warning-bg">Onboarding zurücksetzen</button>
        </div>
        <div className="rounded-lg border border-error/40 bg-error-bg/30 p-4">
          <h3 className="text-sm font-bold text-text">Organisation löschen</h3>
          <p className="mt-1 text-sm text-muted">Löscht unwiderruflich alle Daten: Kunden, Rechnungen, Termine, Mitarbeiter, Vorgänge.</p>
          <button onClick={() => { setConfirmName(''); setDelOpen(true) }} className="mt-3 rounded-md bg-error px-4 py-2 text-sm font-semibold text-white hover:brightness-110">Organisation löschen</button>
        </div>
      </div>

      {/* TODO: onboarding-reset endpoint out of scope this sprint. */}
      <Modal open={resetOpen} onOpenChange={setResetOpen} title="Onboarding zurücksetzen" footer={
        <div className="flex gap-3">
          <button onClick={() => setResetOpen(false)} className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body">Abbrechen</button>
          <button onClick={() => { setResetOpen(false); flash('Wird in Kürze verfügbar.') }} className="flex-1 rounded-md bg-warning py-2.5 text-sm font-semibold text-white">Zurücksetzen</button>
        </div>
      }><p className="text-sm text-body">Möchtest du die Einrichtung wirklich zurücksetzen? Branche, Öffnungszeiten und KI-Konfiguration gehen verloren.</p></Modal>

      <Modal open={delOpen} onOpenChange={setDelOpen} title="Organisation löschen" footer={
        <div className="flex gap-3">
          <button onClick={() => setDelOpen(false)} className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body">Abbrechen</button>
          <button disabled={confirmName !== (org.name || '') || del.isPending} onClick={() => del.mutate()} className="flex-1 rounded-md bg-error py-2.5 text-sm font-semibold text-white disabled:opacity-50">Endgültig löschen</button>
        </div>
      }>
        <p className="text-sm text-body">Gib zur Bestätigung den Organisationsnamen ein <span className="font-bold text-text">{org.name}</span> ein:</p>
        <input value={confirmName} onChange={(e) => setConfirmName(e.target.value)} className={cn(inputCls, 'mt-3')} placeholder={org.name || ''} />
      </Modal>
    </div>
  )
}
