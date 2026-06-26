import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity, BadgeEuro, BookOpen, Bot, CalendarClock, Clock, GitBranch,
  History, Lock, Phone, PhoneOutgoing, RotateCcw, Siren, SlidersHorizontal, Sparkles, Tags, Wrench,
  type LucideIcon,
} from 'lucide-react'
import { useState } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'

import { AusgehendeSection, BrancheKontextSection, LeistungsangebotSection, NotdienstSection, PflichtfelderSection, PreisauskunftSection, TelefonSection, TerminkategorienSection, TerminregelnSection } from '../components/kiki/ConfigSections'
import { AgentDriftBanner, AgentSyncBanner } from '../components/kiki/AgentSyncBanner'
import { AutonomieSection } from '../components/kiki/AutonomieSection'
import { GespraechslogikSection } from '../components/kiki/GespraechslogikSection'
import { ConfirmDialog } from '../components/kiki/shared'
import { GeschaeftszeitenSection } from '../components/kiki/GeschaeftszeitenSection'
import { VerhaltenSection } from '../components/kiki/VerhaltenSection'
import { VerlaufSection } from '../components/kiki/VerlaufSection'
import { Modal } from '../components/ui/Modal'
import { apiFetch } from '../lib/api'
import { KZ, KZ_STALE, minutesAgo, SECTION_ENDPOINT_LABEL, type KzAudit, type KzHealth, type KzOverview } from '../lib/kikiApi'
import { useMe } from '../lib/useMe'
import { useToast } from '../lib/useToast'
import { cn } from '../lib/utils'

interface NavItem { slug: string; label: string; icon: LucideIcon }
const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  { label: 'Konfiguration', items: [
    { slug: 'verhalten', label: 'Verhalten', icon: Sparkles },
    { slug: 'autonomie', label: 'Autonomie', icon: SlidersHorizontal },
    { slug: 'gespraechsablauf', label: 'Gesprächsablauf', icon: GitBranch },
    { slug: 'branche-kontext', label: 'Gewerk & Wissensbasis', icon: BookOpen },
  ] },
  { label: 'Terminplanung', items: [
    { slug: 'geschaeftszeiten', label: 'Geschäftszeiten', icon: Clock },
    { slug: 'terminregeln', label: 'Terminregeln', icon: CalendarClock },
    { slug: 'terminkategorien', label: 'Terminkategorien', icon: Tags },
  ] },
  { label: 'Automatisierung', items: [
    { slug: 'preisauskunft', label: 'Preisauskunft', icon: BadgeEuro },
    { slug: 'leistungsangebot', label: 'Leistungsangebot', icon: Wrench },
  ] },
  { label: 'Notdienst', items: [{ slug: 'notdienst', label: 'Notdienst', icon: Siren }] },
  { label: 'Telefon & Anrufe', items: [
    { slug: 'telefon', label: 'Telefon-Einstellungen', icon: Phone },
    { slug: 'ausgehende-anrufe', label: 'Ausgehende Anrufe', icon: PhoneOutgoing },
  ] },
  { label: 'Versionsverlauf', items: [{ slug: 'verlauf', label: 'Verlauf & Rückgängig', icon: History }] },
]
const ALL_SLUGS = new Set(NAV_GROUPS.flatMap((g) => g.items.map((i) => i.slug)))

export function KikiZentralePage() {
  const { section = 'verhalten' } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { isAdmin, isLoading: meLoading } = useMe()
  const { toast, flash } = useToast()
  const [healthOpen, setHealthOpen] = useState(false)
  const [rollbackSnap, setRollbackSnap] = useState<string | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['kiki-zentrale'],
    queryFn: () => apiFetch<KzOverview>(KZ),
    staleTime: KZ_STALE,
  })

  const rollback = useMutation({
    mutationFn: (snapId: string) => apiFetch(`${KZ}/rollback/${snapId}`, { method: 'POST' }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['kiki-zentrale'] }); setRollbackSnap(null); flash('Wiederhergestellt.') },
    onError: (e: Error) => { setRollbackSnap(null); flash(e.message || 'Wiederherstellen fehlgeschlagen.') },
  })

  // Old bookmark/link compatibility: Pflichtfelder → Leitfaden → and now both
  // Leitfaden + Gesprächslogik live on the combined Gesprächsablauf page.
  if (section === 'pflichtfelder' || section === 'leitfaden' || section === 'gespraechslogik')
    return <Navigate to="/kiki-zentrale/gespraechsablauf" replace />
  if (!ALL_SLUGS.has(section)) return <Navigate to="/kiki-zentrale/verhalten" replace />

  // Kiki-Zentrale is the AI control surface — every mutation is admin-only on the
  // backend. Non-admins get a restricted panel instead of forms that 403.
  if (!meLoading && !isAdmin) {
    return (
      <div className="p-8">
        <div className="mb-6 flex items-center gap-3">
          <Bot size={26} className="text-ai" />
          <h1 className="text-2xl font-bold text-text">Kiki-Zentrale</h1>
        </div>
        <div className="mx-auto mt-6 max-w-md rounded-xl border border-border bg-surface p-8 text-center">
          <div className="mb-3 flex justify-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-alt">
              <Lock size={22} className="text-muted" />
            </div>
          </div>
          <h2 className="text-lg font-bold text-text">Nur für Administratoren</h2>
          <p className="mt-1.5 text-sm text-muted">
            Die Kiki-Zentrale (KI-Konfiguration) ist nur für Administratoren
            zugänglich. Bitte wende dich an deinen Administrator.
          </p>
        </div>
      </div>
    )
  }

  const agent = data?.agent
  const healthy = !!agent?.reachable && !!agent?.audio_event_present

  // Per-section rollback strip: latest snapshot for this section within 60 min.
  const sectionLabel = SECTION_ENDPOINT_LABEL[section]
  const recentSnap = sectionLabel
    ? (data?.recent_snapshots ?? []).find((s) => s.endpoint_label === sectionLabel && minutesAgo(s.created_at) <= 60)
    : undefined

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-ai-bg"><Bot size={24} className="text-ai" /></div>
          <div>
            <h1 className="text-2xl font-bold text-text">Kiki-Zentrale</h1>
            <p className="mt-0.5 text-sm text-muted">Volle Kontrolle über deine KI — Verhalten, Sprache, Wissen und mehr.</p>
          </div>
        </div>
        <button
          onClick={() => setHealthOpen(true)}
          className={cn('flex shrink-0 items-center gap-2 rounded-full px-3 py-1.5 text-sm font-semibold', healthy ? 'bg-success-bg text-success' : 'bg-error-bg text-error')}
        >
          <Activity size={15} /> {healthy ? 'Kiki OK' : 'Kiki-Problem'}
        </button>
      </div>

      <AgentSyncBanner />
      <AgentDriftBanner />

      {toast && <div className="mb-4 rounded-md bg-green-tint-50 px-3 py-2 text-sm font-medium text-green-deep">{toast}</div>}

      <div className="flex flex-col gap-6 md:flex-row">
        {/* Sub-nav — side-by-side from md (768px), so narrowing the window/sidebar
            lets the content CONTRACT next to the menu instead of dropping below it
            (it only stacks on true mobile, where the app nav is a drawer anyway). */}
        <aside className="w-full shrink-0 md:w-52 lg:w-60">
          <nav className="space-y-4">
            {NAV_GROUPS.map((group) => (
              <div key={group.label}>
                <div className="mb-1 px-3 text-xs font-semibold uppercase tracking-wide text-muted">{group.label}</div>
                {group.items.map((it) => {
                  const Icon = it.icon
                  const active = section === it.slug
                  return (
                    <button
                      key={it.slug}
                      onClick={() => navigate(`/kiki-zentrale/${it.slug}`)}
                      className={cn('mb-0.5 flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm transition', active ? 'bg-green-tint-100 font-semibold text-green-deep' : 'text-body hover:bg-alt')}
                    >
                      <Icon size={16} /> {it.label}
                    </button>
                  )
                })}
              </div>
            ))}
          </nav>
        </aside>

        {/* Content */}
        <div className="min-w-0 flex-1">
          {recentSnap && (
            <div className="mb-4 flex items-center justify-between rounded-lg border border-ai/30 bg-ai-bg/40 px-4 py-2.5 text-sm">
              <span className="flex items-center gap-2 text-body"><RotateCcw size={15} className="text-ai" /> Letzte Änderung an dieser Sektion: vor {minutesAgo(recentSnap.created_at)} Min.</span>
              <button onClick={() => setRollbackSnap(recentSnap.id)} className="font-medium text-ai hover:underline">Rückgängig machen</button>
            </div>
          )}

          {isLoading || !data ? (
            <div className="rounded-xl border border-border bg-surface p-12 text-center text-muted">Wird geladen…</div>
          ) : (
            <SectionContent section={section} data={data} flash={flash} />
          )}
        </div>
      </div>

      <HealthDrawer open={healthOpen} onOpenChange={setHealthOpen} onFullLog={() => { setHealthOpen(false); navigate('/kiki-zentrale/verlauf') }} />

      <ConfirmDialog
        open={!!rollbackSnap}
        onOpenChange={(v) => !v && setRollbackSnap(null)}
        title="Änderung rückgängig machen?"
        message="Kiki wird auf den gespeicherten Snapshot vor dieser Änderung zurückgesetzt. Der aktuelle Stand wird zuvor gesichert."
        confirmLabel="Rückgängig machen"
        busy={rollback.isPending}
        onConfirm={() => rollbackSnap && rollback.mutate(rollbackSnap)}
      />
    </div>
  )
}

// ONE page for the whole call flow: the Standard-Ablauf first (the default path),
// the Sonderfälle (decision trees) below — Amber 2026-06-12. The two are
// EITHER/OR per field: a field may be ON in the Standard OR used in a
// Sonderfall, never both (Kiki would ask twice). Not auto-toggled — each side
// WARNS and tells the user to switch it off on the other side.
function GespraechsablaufSection({ data, flash }: { data: KzOverview; flash: (m: string) => void }) {
  const [usedFieldKeys, setUsedFieldKeys] = useState<string[]>([])
  return (
    <div className="space-y-8">
      <div>
        <h2 className="mb-1 text-lg font-bold text-text">Standard-Ablauf</h2>
        <p className="mb-3 text-sm text-muted">
          Diese Punkte fragt Kiki in jedem normalen Gespräch der Reihe nach ab.
        </p>
        <PflichtfelderSection data={data} flash={flash} specialCaseFieldKeys={usedFieldKeys} />
      </div>
      <div>
        <h2 className="mb-1 text-lg font-bold text-text">Ausnahmen & Sonderfälle</h2>
        <p className="mb-3 text-sm text-muted">
          Wenn/Dann-Regeln, die VOR dem Standard-Ablauf greifen. Ein Feld gehört entweder hierher
          oder in den Standard-Ablauf — nie in beide (sonst fragt Kiki doppelt).
        </p>
        <GespraechslogikSection flash={flash} onUsedFieldsChange={setUsedFieldKeys} />
      </div>
    </div>
  )
}

function SectionContent({ section, data, flash }: { section: string; data: KzOverview; flash: (m: string) => void }) {
  switch (section) {
    case 'verhalten': return <VerhaltenSection data={data} flash={flash} />
    case 'autonomie': return <AutonomieSection data={data} flash={flash} />
    case 'gespraechsablauf': return <GespraechsablaufSection data={data} flash={flash} />
    case 'branche-kontext': return <BrancheKontextSection data={data} flash={flash} />
    case 'geschaeftszeiten': return <GeschaeftszeitenSection />
    case 'terminregeln': return <TerminregelnSection data={data} flash={flash} />
    case 'terminkategorien': return <TerminkategorienSection data={data} flash={flash} />
    case 'preisauskunft': return <PreisauskunftSection data={data} flash={flash} />
    case 'leistungsangebot': return <LeistungsangebotSection data={data} flash={flash} />
    case 'notdienst': return <NotdienstSection data={data} flash={flash} />
    case 'telefon': return <TelefonSection data={data} flash={flash} />
    case 'ausgehende-anrufe': return <AusgehendeSection data={data} flash={flash} />
    case 'verlauf': return <VerlaufSection flash={flash} />
    default: return null
  }
}

function HealthDrawer({ open, onOpenChange, onFullLog }: { open: boolean; onOpenChange: (v: boolean) => void; onFullLog: () => void }) {
  const { data: health } = useQuery({
    queryKey: ['kiki-zentrale', 'health'],
    queryFn: () => apiFetch<KzHealth>(`${KZ}/agent-health`),
    enabled: open,
  })
  const { data: audit } = useQuery({
    queryKey: ['kiki-zentrale', 'audit'],
    queryFn: () => apiFetch<{ entries: KzAudit[] }>(`${KZ}/audit`),
    enabled: open,
  })
  const checks: [string, boolean | undefined][] = [
    ['Kiki erreichbar', health?.reachable],
    ['Audio-Event vorhanden', health?.audio_event_present],
    ['System-Prompt gesetzt', health?.prompt_non_empty],
    ['Begrüßung gesetzt', health?.first_message_non_empty],
    ['Stimme gesetzt', health?.voice_set],
  ]
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Kiki-Status" widthClass="max-w-md">
      <div className="space-y-1.5">
        {checks.map(([label, ok]) => (
          <div key={label} className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm">
            <span className="text-body">{label}</span>
            <span className={cn('font-semibold', ok ? 'text-success' : 'text-error')}>{ok ? '✓ OK' : '✗ Fehlt'}</span>
          </div>
        ))}
        <div className="flex items-center justify-between px-3 py-1 text-xs text-muted"><span>Sprache</span><span>{health?.language ?? '—'}</span></div>
      </div>
      <div className="mt-4 border-t border-border pt-3">
        <div className="mb-2 text-xs font-bold uppercase tracking-wide text-muted">Letzte Änderungen</div>
        <div className="space-y-1">
          {(audit?.entries ?? []).slice(0, 5).map((e) => (
            <div key={e.id} className="flex items-center justify-between text-xs">
              <span className="text-body">{e.endpoint_label}</span>
              <span className="text-muted">{new Date(e.created_at).toLocaleString('de-DE', { timeZone: 'Europe/Berlin' })}</span>
            </div>
          ))}
          {(audit?.entries ?? []).length === 0 && <div className="text-xs text-faint">Noch keine Änderungen.</div>}
        </div>
        <button onClick={onFullLog} className="mt-3 text-sm font-medium text-green-deep hover:underline">Vollständiger Verlauf →</button>
      </div>
    </Modal>
  )
}
